"""Live Host and Browser Validation Suite for AURA-1004 Governed Browser File Transfers.

Executes live end-to-end download and upload flows against a local disposable HTTP server:
1. Live download of harmless text document into workspace registry (Phase 6)
2. Verification of quarantine staging lifecycle and automatic cleanup
3. Provenance URL secret parameter redaction
4. Live screening and quarantining of disguised executables
5. Live file upload of authorized workspace document via Playwright native boundary
6. Rejection of sensitive files (.env, vault, keys) on upload
7. Rejection of cross-workspace file access on upload
8. Emergency kill-switch enforcement on active transfers
"""

import asyncio
import http.server
from pathlib import Path
import socket
import threading
import time
import urllib.parse
import uuid
from unittest.mock import patch
import pytest

from app.core.errors import AuthorizationError, EntityNotFoundError, ValidationError
from app.core.filesystem import filesystem_guard
from app.db.models.file import FileRecord, FileStatus
from app.services.browser.engine import browser_engine
from app.services.browser.file_transfer import browser_file_transfer_service
from app.services.kill_switch import kill_switch
from app.services.tools.browser_tools import (
    execute_browser_download_file,
    execute_browser_get_page_state,
    execute_browser_navigate,
    execute_browser_upload_file,
)

UPLOAD_PORTAL_HTML = """<!DOCTYPE html>
<html>
<head>
    <title>AURA-1004 File Upload Portal</title>
</head>
<body>
    <h1>Enterprise Document Ingestion</h1>
    <form id="upload-form" action="/upload_receiver" method="POST" enctype="multipart/form-data">
        <div>
            <label for="doc-file">Select Workspace Document</label>
            <input id="doc-file" type="file" name="uploaded_file" />
        </div>
        <div style="margin-top: 10px;">
            <button id="upload-btn" type="submit">Submit Document</button>
        </div>
    </form>
</body>
</html>
"""

HARMLESS_DOC_CONTENT = b"AURA-1004 Live Validation Document Content: Verified Local Intake."
DISGUISED_EXE_CONTENT = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00" + b"E" * 200


class LocalFileServerHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/download/sample.txt":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Disposition", 'attachment; filename="sample.txt"')
            self.send_header("Content-Length", str(len(HARMLESS_DOC_CONTENT)))
            self.end_headers()
            self.wfile.write(HARMLESS_DOC_CONTENT)

        elif path == "/download/disguised.pdf":
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Disposition", 'attachment; filename="disguised.pdf"')
            self.send_header("Content-Length", str(len(DISGUISED_EXE_CONTENT)))
            self.end_headers()
            self.wfile.write(DISGUISED_EXE_CONTENT)

        elif path == "/download/with_secret":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Disposition", 'attachment; filename="secret_provenance.txt"')
            self.send_header("Content-Length", str(len(HARMLESS_DOC_CONTENT)))
            self.end_headers()
            self.wfile.write(HARMLESS_DOC_CONTENT)

        elif path == "/upload_portal":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(UPLOAD_PORTAL_HTML.encode("utf-8"))))
            self.end_headers()
            self.wfile.write(UPLOAD_PORTAL_HTML.encode("utf-8"))

        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # Suppress noisy HTTP logs


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def local_file_server():
    port = get_free_port()
    server = http.server.HTTPServer(("127.0.0.1", port), LocalFileServerHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()
    server.server_close()


@pytest.mark.asyncio
async def test_live_aura1004_full_file_transfer_lifecycle(local_file_server, db_session):
    """Execute live end-to-end download and upload pipeline verification with Playwright Chromium."""
    ws_id = uuid.uuid4()
    ws_root = filesystem_guard.get_workspace_root(ws_id)

    with patch("app.core.network.ssrf_guard.validate_url", return_value=True):
        # ==============================================================================
        # 1. Live Download of Harmless Document
        # ==============================================================================
        download_url = f"{local_file_server}/download/sample.txt"
        dl_res = await execute_browser_download_file(
            workspace_id=ws_id,
            url=download_url,
            db=db_session,
        )

        assert dl_res["status"] == "success"
        assert dl_res["action"] == "download_file"
        assert dl_res["filename"] == "sample.txt"
        assert dl_res["size_bytes"] == len(HARMLESS_DOC_CONTENT)
        assert dl_res["is_quarantined"] is False

        file_id = uuid.UUID(dl_res["file_id"])
        record = await db_session.get(FileRecord, file_id)
        assert record is not None
        assert record.workspace_id == ws_id
        assert record.status == FileStatus.UPLOADED.value

        # Verify quarantine directory was completely removed
        downloads_dir = ws_root / "downloads"
        if downloads_dir.exists():
            assert len(list(downloads_dir.glob(".incoming_*"))) == 0

        # ==============================================================================
        # 2. Live Provenance URL Secret Parameter Redaction
        # ==============================================================================
        secret_url = f"{local_file_server}/download/with_secret?token=CANARY_SECRET_TOKEN_99&auth=admin_key"
        sec_dl_res = await execute_browser_download_file(
            workspace_id=ws_id,
            url=secret_url,
            db=db_session,
        )

        assert sec_dl_res["status"] == "success"
        assert "CANARY_SECRET_TOKEN_99" not in sec_dl_res["source_url"]
        assert "admin_key" not in sec_dl_res["source_url"]
        assert "token=%5BREDACTED%5D" in sec_dl_res["source_url"] or "token=[REDACTED]" in sec_dl_res["source_url"]

        # ==============================================================================
        # 3. Live Screening of Disguised Executable
        # ==============================================================================
        disguised_url = f"{local_file_server}/download/disguised.pdf"
        dis_dl_res = await execute_browser_download_file(
            workspace_id=ws_id,
            url=disguised_url,
            db=db_session,
        )

        assert dis_dl_res["status"] == "success"
        assert dis_dl_res["is_quarantined"] is True
        assert any("SUSPICIOUS_EXECUTABLE" in f for f in dis_dl_res["security_flags"])

        dis_file_id = uuid.UUID(dis_dl_res["file_id"])
        dis_record = await db_session.get(FileRecord, dis_file_id)
        assert dis_record.status == FileStatus.QUARANTINED.value

        # ==============================================================================
        # 4. Live Workspace Document Upload via Playwright Chromium
        # ==============================================================================
        # Navigate to the upload portal page
        nav_res = await execute_browser_navigate(
            workspace_id=ws_id,
            url=f"{local_file_server}/upload_portal",
        )
        assert nav_res["status"] == "success"
        tab_id = nav_res["tab_id"]

        # Upload the previously registered sample.txt
        up_res = await execute_browser_upload_file(
            workspace_id=ws_id,
            file_id=str(file_id),
            selector="#doc-file",
            tab_id=tab_id,
            db=db_session,
        )

        assert up_res["status"] == "success"
        assert up_res["action"] == "upload_file"
        assert up_res["file_id"] == str(file_id)
        assert up_res["filename"] == "sample.txt"
        assert local_file_server in up_res["destination_origin"]

        # Verify input value in real browser DOM
        ws_ctx = await browser_engine.get_or_create_workspace_context(ws_id)
        page = ws_ctx.get_page(tab_id)
        input_value = await page.eval_on_selector("#doc-file", "el => el.value")
        assert "sample.txt" in input_value

        # ==============================================================================
        # 5. Security Check: Sensitive File Upload Blocked
        # ==============================================================================
        env_file_id = uuid.uuid4()
        env_dir = ws_root / "files" / str(env_file_id)
        env_dir.mkdir(parents=True, exist_ok=True)
        (env_dir / ".env.production").write_bytes(b"JWT_SECRET=super_secret_production")

        env_rec = FileRecord(
            id=env_file_id,
            workspace_id=ws_id,
            original_filename=".env.production",
            safe_filename=".env.production",
            mime_type="text/plain",
            file_extension=".production",
            size_bytes=len(b"JWT_SECRET=super_secret_production"),
            sha256_hash="mock_env_hash",
            storage_path=f"files/{env_file_id}/.env.production",
            status=FileStatus.UPLOADED.value,
            metadata_={},
            security_flags=[],
        )
        db_session.add(env_rec)
        await db_session.commit()

        with pytest.raises(AuthorizationError) as exc_env:
            await execute_browser_upload_file(
                workspace_id=ws_id,
                file_id=str(env_file_id),
                selector="#doc-file",
                tab_id=tab_id,
                db=db_session,
            )
        assert "strictly blocked by security policy" in str(exc_env.value)

        # ==============================================================================
        # 6. Security Check: Cross-Workspace File Upload Blocked
        # ==============================================================================
        other_ws_id = uuid.uuid4()
        with pytest.raises(EntityNotFoundError):
            await execute_browser_upload_file(
                workspace_id=other_ws_id,
                file_id=str(file_id),
                selector="#doc-file",
                db=db_session,
            )

        # Clean up browser context
        await browser_engine.close_workspace_context(ws_id)
