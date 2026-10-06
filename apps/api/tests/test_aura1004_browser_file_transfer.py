"""Unit and Functional Tests for AURA-1004 Governed Browser Download & Upload Pipeline."""

import asyncio
from pathlib import Path
import shutil
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
    is_sensitive_file,
    sanitize_url_provenance,
)
from app.services.file_service import FileService


@pytest.mark.asyncio
async def test_sanitize_url_provenance_redacts_secrets():
    """Verify sensitive query parameters are redacted from provenance URLs."""
    raw_url = "https://example.corp/download?report=Q3&token=secret_jwt_token_123&auth=bearer99&user=alice"
    sanitized = sanitize_url_provenance(raw_url)
    assert "token=%5BREDACTED%5D" in sanitized or "token=[REDACTED]" in sanitized
    assert "auth=%5BREDACTED%5D" in sanitized or "auth=[REDACTED]" in sanitized
    assert "secret_jwt_token_123" not in sanitized
    assert "user=alice" in sanitized
    assert "report=Q3" in sanitized


@pytest.mark.asyncio
async def test_sensitive_file_denylist_detection():
    """Verify sensitive files matching secrets/vault patterns are detected."""
    assert is_sensitive_file(".env") is True
    assert is_sensitive_file(".env.production") is True
    assert is_sensitive_file("master_key.txt") is True
    assert is_sensitive_file("credential_vault.sqlite") is True
    assert is_sensitive_file("id_rsa") is True
    assert is_sensitive_file("id_ed25519") is True
    assert is_sensitive_file("private.key") is True
    assert is_sensitive_file("certificate.pem") is True
    assert is_sensitive_file("app.db") is True

    # Benign files
    assert is_sensitive_file("annual_report.pdf") is False
    assert is_sensitive_file("dataset.csv") is False
    assert is_sensitive_file("logo.png") is False
    assert is_sensitive_file("notes.md") is False


@pytest.mark.asyncio
async def test_download_file_direct_url_success(db_session):
    """Verify downloading a harmless file via URL stages in quarantine and registers in Phase 6."""
    ws_id = uuid.uuid4()
    file_content = b"Harmless downloaded document content for Phase 10 verification."

    # Mock httpx streaming response
    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_resp.url = "https://example.com/files/quarterly_report.pdf?token=secret123"
    mock_resp.headers = {
        "content-type": "application/pdf",
        "content-disposition": 'attachment; filename="quarterly_report.pdf"',
    }

    async def _aiter_bytes(chunk_size=65536):
        yield file_content

    mock_resp.aiter_bytes = _aiter_bytes
    mock_stream_ctx = AsyncMock()
    mock_stream_ctx.__aenter__.return_value = mock_resp
    mock_stream_ctx.__aexit__.return_value = None

    with patch.object(httpx.AsyncClient, "stream", return_value=mock_stream_ctx), \
         patch("app.core.network.ssrf_guard.validate_url", return_value=True):

        res = await browser_file_transfer_service.download_file(
            db=db_session,
            workspace_id=ws_id,
            url="https://example.com/files/quarterly_report.pdf?token=secret123",
        )

        assert res["status"] == "success"
        assert res["action"] == "download_file"
        assert res["filename"] == "quarterly_report.pdf"
        assert res["size_bytes"] == len(file_content)
        assert res["is_untrusted_content"] is True
        assert "secret123" not in res["source_url"]

        # Verify DB record creation in Phase 6 Universal File Registry
        file_id = uuid.UUID(res["file_id"])
        record = await db_session.get(FileRecord, file_id)
        assert record is not None
        assert record.workspace_id == ws_id
        assert record.safe_filename == "quarterly_report.pdf"
        assert record.status == FileStatus.UPLOADED.value
        assert record.metadata_["source_type"] == "browser_download"

        # Verify quarantine directory was cleaned up
        ws_root = filesystem_guard.get_workspace_root(ws_id)
        downloads_dir = ws_root / "downloads"
        incoming_dirs = list(downloads_dir.glob(".incoming_*"))
        assert len(incoming_dirs) == 0


@pytest.mark.asyncio
async def test_download_file_size_limit_rejection(db_session):
    """Verify downloads exceeding 50 MB are rejected and quarantine is cleaned up."""
    ws_id = uuid.uuid4()
    oversized_chunk = b"X" * (51 * 1024 * 1024)  # 51 MB

    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_resp.url = "https://example.com/files/huge_blob.bin"
    mock_resp.headers = {"content-type": "application/octet-stream"}

    async def _aiter_bytes(chunk_size=65536):
        yield oversized_chunk

    mock_resp.aiter_bytes = _aiter_bytes
    mock_stream_ctx = AsyncMock()
    mock_stream_ctx.__aenter__.return_value = mock_resp
    mock_stream_ctx.__aexit__.return_value = None

    with patch.object(httpx.AsyncClient, "stream", return_value=mock_stream_ctx), \
         patch("app.core.network.ssrf_guard.validate_url", return_value=True):

        with pytest.raises(ValidationError) as exc_info:
            await browser_file_transfer_service.download_file(
                db=db_session,
                workspace_id=ws_id,
                url="https://example.com/files/huge_blob.bin",
            )
        assert "50 MB" in str(exc_info.value)

        # Ensure quarantine directory cleaned up
        ws_root = filesystem_guard.get_workspace_root(ws_id)
        downloads_dir = ws_root / "downloads"
        if downloads_dir.exists():
            assert len(list(downloads_dir.glob(".incoming_*"))) == 0


@pytest.mark.asyncio
async def test_download_file_empty_rejection(db_session):
    """Verify 0-byte downloads are rejected."""
    ws_id = uuid.uuid4()

    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_resp.url = "https://example.com/files/empty.txt"
    mock_resp.headers = {"content-type": "text/plain"}

    async def _aiter_bytes(chunk_size=65536):
        if False:
            yield b""

    mock_resp.aiter_bytes = _aiter_bytes
    mock_stream_ctx = AsyncMock()
    mock_stream_ctx.__aenter__.return_value = mock_resp
    mock_stream_ctx.__aexit__.return_value = None

    with patch.object(httpx.AsyncClient, "stream", return_value=mock_stream_ctx), \
         patch("app.core.network.ssrf_guard.validate_url", return_value=True):

        with pytest.raises(ValidationError) as exc_info:
            await browser_file_transfer_service.download_file(
                db=db_session,
                workspace_id=ws_id,
                url="https://example.com/files/empty.txt",
            )
        assert "empty (0 bytes)" in str(exc_info.value)


@pytest.mark.asyncio
async def test_download_file_duplicate_deduplication(db_session):
    """Verify downloading identical content deduplicates inside the workspace registry."""
    ws_id = uuid.uuid4()
    content = b"Unique content for duplicate deduplication testing 12345."

    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_resp.url = "https://example.com/files/doc.txt"
    mock_resp.headers = {"content-type": "text/plain"}

    async def _aiter_bytes(chunk_size=65536):
        yield content

    mock_resp.aiter_bytes = _aiter_bytes
    mock_stream_ctx = AsyncMock()
    mock_stream_ctx.__aenter__.return_value = mock_resp
    mock_stream_ctx.__aexit__.return_value = None

    with patch.object(httpx.AsyncClient, "stream", return_value=mock_stream_ctx), \
         patch("app.core.network.ssrf_guard.validate_url", return_value=True):

        # First download
        res1 = await browser_file_transfer_service.download_file(
            db=db_session,
            workspace_id=ws_id,
            url="https://example.com/files/doc.txt",
        )
        assert res1["is_duplicate"] is False

        # Second download with same content
        res2 = await browser_file_transfer_service.download_file(
            db=db_session,
            workspace_id=ws_id,
            url="https://example.com/files/doc_copy.txt",
        )
        assert res2["is_duplicate"] is True
        assert res2["file_id"] == res1["file_id"]


@pytest.mark.asyncio
async def test_upload_file_workspace_isolation_and_success(db_session):
    """Verify uploading an authorized workspace file succeeds and binds to active browser tab."""
    ws_id = uuid.uuid4()
    ws_root = filesystem_guard.get_workspace_root(ws_id)

    # 1. Register a harmless workspace file
    file_id = uuid.uuid4()
    file_dir = ws_root / "files" / str(file_id)
    file_dir.mkdir(parents=True, exist_ok=True)
    file_path = file_dir / "sample_upload.pdf"
    file_path.write_bytes(b"%PDF-1.4 Mock PDF Content")

    record = FileRecord(
        id=file_id,
        workspace_id=ws_id,
        original_filename="sample_upload.pdf",
        safe_filename="sample_upload.pdf",
        mime_type="application/pdf",
        file_extension=".pdf",
        size_bytes=len(b"%PDF-1.4 Mock PDF Content"),
        sha256_hash="mock_hash_123",
        storage_path=f"files/{file_id}/sample_upload.pdf",
        status=FileStatus.UPLOADED.value,
        metadata_={"test": True},
        security_flags=[],
    )
    db_session.add(record)
    await db_session.commit()

    # 2. Mock browser context and page
    mock_locator = AsyncMock()
    mock_page = MagicMock()
    mock_page.url = "https://portal.example.com/upload"
    mock_page.locator.return_value.first = mock_locator

    mock_ws_ctx = MagicMock()
    mock_ws_ctx.active_tab_id = "tab_upload_1"
    mock_ws_ctx.get_page.return_value = mock_page

    with patch("app.services.browser.file_transfer.browser_engine.get_or_create_workspace_context", return_value=mock_ws_ctx):
        res = await browser_file_transfer_service.upload_file(
            db=db_session,
            workspace_id=ws_id,
            file_id=file_id,
            tab_id="tab_upload_1",
        )

        assert res["status"] == "success"
        assert res["action"] == "upload_file"
        assert res["file_id"] == str(file_id)
        assert res["filename"] == "sample_upload.pdf"
        assert res["destination_origin"] == "https://portal.example.com"
        mock_locator.set_input_files.assert_awaited_once_with(str(file_path))


@pytest.mark.asyncio
async def test_upload_file_cross_workspace_blocked(db_session):
    """Verify attempting to upload a file belonging to another workspace fails closed."""
    ws_owner = uuid.uuid4()
    ws_attacker = uuid.uuid4()

    ws_root = filesystem_guard.get_workspace_root(ws_owner)
    file_id = uuid.uuid4()
    file_dir = ws_root / "files" / str(file_id)
    file_dir.mkdir(parents=True, exist_ok=True)
    file_path = file_dir / "private_doc.pdf"
    file_path.write_bytes(b"%PDF-1.4 Private Doc")

    record = FileRecord(
        id=file_id,
        workspace_id=ws_owner,
        original_filename="private_doc.pdf",
        safe_filename="private_doc.pdf",
        mime_type="application/pdf",
        file_extension=".pdf",
        size_bytes=len(b"%PDF-1.4 Private Doc"),
        sha256_hash="mock_hash_owner",
        storage_path=f"files/{file_id}/private_doc.pdf",
        status=FileStatus.UPLOADED.value,
        metadata_={},
        security_flags=[],
    )
    db_session.add(record)
    await db_session.commit()

    with pytest.raises(EntityNotFoundError):
        await browser_file_transfer_service.upload_file(
            db=db_session,
            workspace_id=ws_attacker,  # Attacker attempts to use owner's file_id
            file_id=file_id,
        )


@pytest.mark.asyncio
async def test_upload_file_sensitive_denylist_blocked(db_session):
    """Verify uploading sensitive files (.env, vault, keys) is strictly blocked."""
    ws_id = uuid.uuid4()
    ws_root = filesystem_guard.get_workspace_root(ws_id)

    file_id = uuid.uuid4()
    file_dir = ws_root / "files" / str(file_id)
    file_dir.mkdir(parents=True, exist_ok=True)
    file_path = file_dir / ".env.production"
    file_path.write_bytes(b"SECRET_KEY=12345")

    record = FileRecord(
        id=file_id,
        workspace_id=ws_id,
        original_filename=".env.production",
        safe_filename=".env.production",
        mime_type="text/plain",
        file_extension=".production",
        size_bytes=len(b"SECRET_KEY=12345"),
        sha256_hash="env_hash",
        storage_path=f"files/{file_id}/.env.production",
        status=FileStatus.UPLOADED.value,
        metadata_={},
        security_flags=[],
    )
    db_session.add(record)
    await db_session.commit()

    with pytest.raises(AuthorizationError) as exc_info:
        await browser_file_transfer_service.upload_file(
            db=db_session,
            workspace_id=ws_id,
            file_id=file_id,
        )
    assert "strictly blocked by security policy" in str(exc_info.value)
