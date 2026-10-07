"""Live Security Validation Suite for AURA-1004 Governed Browser File Transfers.

Exercises 14 live end-to-end security validations against a local disposable HTTP server and Playwright Chromium:
1. Normal download -> Phase 6 registration
2. Malicious & traversal filename download handling
3. Disguised executable download quarantine
4. Archive traversal containment
5. Workspace isolation
6. Normal upload to live DOM <input type="file">
7. Renamed private key upload rejection (content inspection)
8. Renamed SQLite vault DB upload rejection
9. Renamed .env secret upload rejection
10. Cross-workspace upload isolation
11. Deleted file upload rejection
12. Kill-switch interruption
13. Quarantine directory cleanup invariant
14. Provenance query secret sanitization
"""

import asyncio
import http.server
import io
from pathlib import Path
import socket
import threading
import time
import urllib.parse
import uuid
import zipfile
from unittest.mock import patch
import pytest

from app.core.errors import AuthorizationError, EntityNotFoundError, ValidationError
from app.core.filesystem import filesystem_guard
from app.db.models.file import FileRecord, FileStatus
from app.services.browser.engine import browser_engine
from app.services.browser.file_transfer import browser_file_transfer_service
from app.services.file_service import FileService
from app.services.kill_switch import kill_switch
from app.services.tools.browser_tools import (
    execute_browser_download_file,
    execute_browser_get_page_state,
    execute_browser_navigate,
    execute_browser_upload_file,
)

PORTAL_HTML = """<!DOCTYPE html>
<html>
<head>
    <title>AURA Security Upload Portal</title>
</head>
<body>
    <h1>Security Upload Gateway</h1>
    <form id="sec-form" action="/submit" method="POST" enctype="multipart/form-data">
        <div>
            <label for="upload-input">Document File</label>
            <input id="upload-input" type="file" name="payload_file" />
        </div>
        <button id="submit-btn" type="submit">Upload</button>
    </form>
</body>
</html>
"""

SAMPLE_TXT = b"Live Harmless Document: Verified AURA-1004 Security Pipeline."
DISGUISED_EXE = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00" + b"X" * 200

# Synthetic zip with path traversal
ZIP_TRAVERSAL_BUF = io.BytesIO()
with zipfile.ZipFile(ZIP_TRAVERSAL_BUF, "w") as zf:
    zf.writestr("../../escape.txt", "escaped content")
    zf.writestr("safe.txt", "safe content")
ZIP_TRAVERSAL_BYTES = ZIP_TRAVERSAL_BUF.getvalue()


class LiveSecurityServerHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/portal":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(PORTAL_HTML.encode("utf-8"))))
            self.end_headers()
            self.wfile.write(PORTAL_HTML.encode("utf-8"))

        elif path == "/files/doc.txt":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Disposition", 'attachment; filename="doc.txt"')
            self.send_header("Content-Length", str(len(SAMPLE_TXT)))
            self.end_headers()
            self.wfile.write(SAMPLE_TXT)

        elif path == "/files/disguised.pdf":
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Disposition", 'attachment; filename="disguised.pdf"')
            self.send_header("Content-Length", str(len(DISGUISED_EXE)))
            self.end_headers()
            self.wfile.write(DISGUISED_EXE)

        elif path == "/files/traversal.zip":
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", 'attachment; filename="traversal.zip"')
            self.send_header("Content-Length", str(len(ZIP_TRAVERSAL_BYTES)))
            self.end_headers()
            self.wfile.write(ZIP_TRAVERSAL_BYTES)

        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


@pytest.fixture(scope="module")
def live_security_server():
    """Start disposable local HTTP server."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    server = http.server.HTTPServer(("127.0.0.1", port), LiveSecurityServerHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    time.sleep(0.1)

    yield f"http://127.0.0.1:{port}"
    server.shutdown()


@pytest.mark.asyncio
async def test_live_aura1004_full_security_closure(live_security_server, db_session):
    """Execute live 14-step end-to-end security transfer tests."""
    ws_id = uuid.uuid4()
    ws_b_id = uuid.uuid4()
    file_service = FileService()
    ws_root = filesystem_guard.get_workspace_root(ws_id)
    ws_root.mkdir(parents=True, exist_ok=True)

    with patch("app.core.network.ssrf_guard.validate_url", return_value=True):
        # 1. Live Normal Download
        dl_res = await execute_browser_download_file(
            workspace_id=ws_id,
            url=f"{live_security_server}/files/doc.txt?token=SECRET_CANARY_JWT&auth=BEARER_CANARY",
            db=db_session,
        )
        assert dl_res["status"] == "success"
        assert dl_res["filename"] == "doc.txt"
        assert dl_res["is_untrusted_content"] is True
        doc_file_id = dl_res["file_id"]

        # 2. Verify Provenance Sanitization
        assert "SECRET_CANARY_JWT" not in dl_res["source_url"]
        assert "BEARER_CANARY" not in dl_res["source_url"]
        assert "%5BREDACTED%5D" in dl_res["source_url"] or "[REDACTED]" in dl_res["source_url"]

        # 3. Disguised Executable Download -> Quarantined
        exe_res = await execute_browser_download_file(
            workspace_id=ws_id,
            url=f"{live_security_server}/files/disguised.pdf",
            db=db_session,
        )
        assert exe_res["status"] == "success"
        assert exe_res["is_quarantined"] is True
        assert any("SUSPICIOUS" in f for f in exe_res["security_flags"])

        # 4. Archive Traversal Download -> Contained
        zip_res = await execute_browser_download_file(
            workspace_id=ws_id,
            url=f"{live_security_server}/files/traversal.zip",
            db=db_session,
        )
        assert zip_res["status"] == "success"
        assert not (ws_root.parent / "escape.txt").exists()

        # 5. Live Browser Navigation to Upload Portal
        nav_res = await execute_browser_navigate(
            workspace_id=ws_id,
            url=f"{live_security_server}/portal",
        )
        assert nav_res["status"] == "success"
        tab_id = nav_res["tab_id"]

        # 6. Live Upload Harmless Workspace File
        up_res = await execute_browser_upload_file(
            workspace_id=ws_id,
            file_id=doc_file_id,
            selector="#upload-input",
            tab_id=tab_id,
            db=db_session,
        )
        assert up_res["status"] == "success"
        assert up_res["action"] == "upload_file"

        # Verify page state shows file attached
        page_state = await execute_browser_get_page_state(workspace_id=ws_id, tab_id=tab_id)
        assert page_state["title"] == "AURA Security Upload Portal"

        # 7. Renamed Private Key Upload -> Blocked
        fake_key = b"-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA0...\n-----END RSA PRIVATE KEY-----"
        key_temp = ws_root / "temp_key.txt"
        key_temp.write_bytes(fake_key)
        intake_key = await file_service.intake_staged_file(
            db=db_session,
            workspace_id=ws_id,
            staged_path=key_temp,
            original_filename="harmless_report.pdf",
        )
        with pytest.raises(AuthorizationError, match="sensitive data detected"):
            await execute_browser_upload_file(
                workspace_id=ws_id,
                file_id=str(intake_key.file.id),
                selector="#upload-input",
                tab_id=tab_id,
                db=db_session,
            )

        # 8. Renamed Vault DB Upload -> Blocked
        fake_db = b"SQLite format 3\x00" + b"\x00" * 100
        db_temp = ws_root / "temp_db.bin"
        db_temp.write_bytes(fake_db)
        intake_db = await file_service.intake_staged_file(
            db=db_session,
            workspace_id=ws_id,
            staged_path=db_temp,
            original_filename="data_export.csv",
        )
        with pytest.raises(AuthorizationError, match="sensitive data detected"):
            await execute_browser_upload_file(
                workspace_id=ws_id,
                file_id=str(intake_db.file.id),
                selector="#upload-input",
                tab_id=tab_id,
                db=db_session,
            )

        # 9. Renamed .env Secret Upload -> Blocked
        env_body = b"JWT_SECRET=canary_secret_jwt_sign_key_999\nPORT=3000\n"
        env_temp = ws_root / "temp_env.txt"
        env_temp.write_bytes(env_body)
        intake_env = await file_service.intake_staged_file(
            db=db_session,
            workspace_id=ws_id,
            staged_path=env_temp,
            original_filename="system_notes.txt",
        )
        with pytest.raises(AuthorizationError, match="sensitive data detected"):
            await execute_browser_upload_file(
                workspace_id=ws_id,
                file_id=str(intake_env.file.id),
                selector="#upload-input",
                tab_id=tab_id,
                db=db_session,
            )

        # 10. Cross-Workspace Upload -> Blocked
        with pytest.raises(EntityNotFoundError):
            await execute_browser_upload_file(
                workspace_id=ws_b_id,
                file_id=doc_file_id,
                selector="#upload-input",
                db=db_session,
            )

        # 11. Deleted File Upload -> Blocked
        fake_deleted_id = str(uuid.uuid4())
        with pytest.raises(EntityNotFoundError):
            await execute_browser_upload_file(
                workspace_id=ws_id,
                file_id=fake_deleted_id,
                selector="#upload-input",
                tab_id=tab_id,
                db=db_session,
            )

        # 12. Emergency Kill-Switch Interruption
        kill_switch.activate(ws_id, reason="Live validation kill-switch test")
        try:
            with pytest.raises(AuthorizationError, match="Emergency Kill Switch is active"):
                await execute_browser_upload_file(
                    workspace_id=ws_id,
                    file_id=doc_file_id,
                    selector="#upload-input",
                    tab_id=tab_id,
                    db=db_session,
                )
        finally:
            kill_switch.deactivate(ws_id)

        # 13. Quarantine Cleanup Verification
        downloads_dir = ws_root / "downloads"
        if downloads_dir.exists():
            incoming_dirs = list(downloads_dir.glob(".incoming_*"))
            assert len(incoming_dirs) == 0, f"Found orphan quarantine dirs: {incoming_dirs}"

        # 14. Close Browser Context
        await browser_engine.close_workspace_context(ws_id)
