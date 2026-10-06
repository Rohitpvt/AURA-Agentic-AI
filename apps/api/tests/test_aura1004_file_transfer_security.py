"""Security Red Team and Adversarial Attack Suite for AURA-1004 File Transfer Pipeline."""

import asyncio
from pathlib import Path
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from app.core.errors import AuthorizationError, EntityNotFoundError, ValidationError
from app.core.filesystem import filesystem_guard
from app.db.models.file import FileRecord, FileStatus
from app.services.browser.file_transfer import (
    BrowserFileTransferService,
    browser_file_transfer_service,
)
from app.services.file_service import FileService
from app.services.kill_switch import kill_switch


@pytest.mark.asyncio
async def test_security_filename_traversal_sanitization(db_session):
    """Verify adversarial filename traversal payloads cannot escape quarantine namespace."""
    ws_id = uuid.uuid4()
    traversal_filenames = [
        "../../../../../../Windows/System32/calc.exe",
        "..\\..\\..\\..\\evil.ps1",
        "nested/../../../../etc/passwd",
        "/etc/shadow",
        "C:\\Windows\\System32\\cmd.exe",
        "\\\\attacker.server\\share\\malware.exe",
        "file.txt\x00.exe",
        "file.txt%00.exe",
        "test.txt:stream",
        "COM1",
        "NUL.txt",
    ]

    for malicious_name in traversal_filenames:
        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.url = f"https://example.com/{malicious_name}"
        mock_resp.headers = {
            "content-type": "text/plain",
            "content-disposition": f'attachment; filename="{malicious_name}"',
        }

        async def _aiter_bytes(chunk_size=65536):
            yield b"Trapped inside quarantine content"

        mock_resp.aiter_bytes = _aiter_bytes
        mock_stream_ctx = AsyncMock()
        mock_stream_ctx.__aenter__.return_value = mock_resp
        mock_stream_ctx.__aexit__.return_value = None

        with patch.object(httpx.AsyncClient, "stream", return_value=mock_stream_ctx), \
             patch("app.core.network.ssrf_guard.validate_url", return_value=True):

            res = await browser_file_transfer_service.download_file(
                db=db_session,
                workspace_id=ws_id,
                url=f"https://example.com/download",
                suggested_filename=malicious_name,
            )

            assert res["status"] == "success"
            safe_name = res["filename"]
            assert ".." not in safe_name
            assert "/" not in safe_name
            assert "\\" not in safe_name
            assert ":" not in safe_name
            assert "\x00" not in safe_name

            # Verify file exists inside canonical workspace storage, not arbitrary system locations
            file_id = uuid.UUID(res["file_id"])
            rec = await db_session.get(FileRecord, file_id)
            final_path = filesystem_guard.validate_and_resolve_path(ws_id, rec.storage_path)
            assert final_path.exists()
            assert ws_id.hex in str(final_path) or str(ws_id) in str(final_path)


@pytest.mark.asyncio
async def test_security_disguised_executable_quarantine_screening(db_session):
    """Verify disguised PE executables (MZ header) with .pdf extension are flagged and quarantined."""
    ws_id = uuid.uuid4()
    # DOS/PE MZ header signature disguised with .pdf extension
    pe_bytes = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00" + b"A" * 100

    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_resp.url = "https://example.com/trojan.pdf"
    mock_resp.headers = {"content-type": "application/pdf"}

    async def _aiter_bytes(chunk_size=65536):
        yield pe_bytes

    mock_resp.aiter_bytes = _aiter_bytes
    mock_stream_ctx = AsyncMock()
    mock_stream_ctx.__aenter__.return_value = mock_resp
    mock_stream_ctx.__aexit__.return_value = None

    with patch.object(httpx.AsyncClient, "stream", return_value=mock_stream_ctx), \
         patch("app.core.network.ssrf_guard.validate_url", return_value=True):

        res = await browser_file_transfer_service.download_file(
            db=db_session,
            workspace_id=ws_id,
            url="https://example.com/trojan.pdf",
        )

        assert res["status"] == "success"
        assert res["is_quarantined"] is True
        assert any("SUSPICIOUS_EXECUTABLE" in f for f in res["security_flags"])

        # Check DB status is QUARANTINED
        file_id = uuid.UUID(res["file_id"])
        rec = await db_session.get(FileRecord, file_id)
        assert rec.status == FileStatus.QUARANTINED.value


@pytest.mark.asyncio
async def test_security_download_ssrf_blocked(db_session):
    """Verify downloads targeting cloud metadata or loopback private IPs are blocked."""
    ws_id = uuid.uuid4()
    ssrf_targets = [
        "http://169.254.169.254/latest/meta-data/credentials",
        "http://127.0.0.1:5432/db",
        "http://localhost:8000/internal",
        "http://[::1]:8080/admin",
        "file:///C:/Windows/System32/cmd.exe",
        "javascript:alert(1)",
    ]

    for target in ssrf_targets:
        with pytest.raises((ValidationError, AuthorizationError)):
            await browser_file_transfer_service.download_file(
                db=db_session,
                workspace_id=ws_id,
                url=target,
            )


@pytest.mark.asyncio
async def test_security_sensitive_file_upload_blocked(db_session):
    """Verify attempting to upload sensitive workspace files is blocked."""
    ws_id = uuid.uuid4()
    ws_root = filesystem_guard.get_workspace_root(ws_id)

    sensitive_targets = [
        (".env", b"API_SECRET=super_secret"),
        ("id_rsa", b"-----BEGIN OPENSSH PRIVATE KEY-----"),
        ("server.key", b"-----BEGIN PRIVATE KEY-----"),
        ("vault.sqlite", b"SQLite format 3\x00"),
        ("master_key_backup.txt", b"AURA_MASTER_KEY_HEX"),
    ]

    for filename, content in sensitive_targets:
        file_id = uuid.uuid4()
        file_dir = ws_root / "files" / str(file_id)
        file_dir.mkdir(parents=True, exist_ok=True)
        file_path = file_dir / filename
        file_path.write_bytes(content)

        rec = FileRecord(
            id=file_id,
            workspace_id=ws_id,
            original_filename=filename,
            safe_filename=filename,
            mime_type="application/octet-stream",
            file_extension=Path(filename).suffix,
            size_bytes=len(content),
            sha256_hash="sec_hash",
            storage_path=f"files/{file_id}/{filename}",
            status=FileStatus.UPLOADED.value,
            metadata_={},
            security_flags=[],
        )
        db_session.add(rec)
        await db_session.commit()

        with pytest.raises(AuthorizationError) as exc_info:
            await browser_file_transfer_service.upload_file(
                db=db_session,
                workspace_id=ws_id,
                file_id=file_id,
            )
        assert "strictly blocked by security policy" in str(exc_info.value)


@pytest.mark.asyncio
async def test_security_emergency_kill_switch_blocks_transfers(db_session):
    """Verify emergency kill switch halts downloads and uploads immediately."""
    ws_id = uuid.uuid4()

    # Activate kill switch for workspace
    kill_switch.set_active(True, workspace_id=ws_id)

    try:
        # Download attempt blocked
        with pytest.raises(AuthorizationError) as exc_dl:
            await browser_file_transfer_service.download_file(
                db=db_session,
                workspace_id=ws_id,
                url="https://example.com/doc.pdf",
            )
        assert "Emergency Kill Switch is active" in str(exc_dl.value)

        # Upload attempt blocked
        with pytest.raises(AuthorizationError) as exc_ul:
            await browser_file_transfer_service.upload_file(
                db=db_session,
                workspace_id=ws_id,
                file_id=uuid.uuid4(),
            )
        assert "Emergency Kill Switch is active" in str(exc_ul.value)

    finally:
        # Reset kill switch
        kill_switch.set_active(False, workspace_id=ws_id)
