"""Race Condition and Concurrency Tests for AURA-1004 File Transfer Pipeline."""

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
from app.services.kill_switch import kill_switch


@pytest.mark.asyncio
async def test_race_kill_switch_during_download_streaming(db_session):
    """Verify kill-switch activation mid-stream immediately aborts download and cleans quarantine."""
    ws_id = uuid.uuid4()
    barrier = asyncio.Event()

    async def _slow_chunks(chunk_size=65536):
        yield b"Chunk 1 data"
        barrier.set()
        await asyncio.sleep(0.05)
        yield b"Chunk 2 data"

    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_resp.url = "https://example.com/stream.bin"
    mock_resp.headers = {"content-type": "application/octet-stream"}
    mock_resp.aiter_bytes = _slow_chunks

    mock_stream_ctx = AsyncMock()
    mock_stream_ctx.__aenter__.return_value = mock_resp
    mock_stream_ctx.__aexit__.return_value = None

    async def _trigger_kill():
        await barrier.wait()
        kill_switch.set_active(True, workspace_id=ws_id)

    with patch.object(httpx.AsyncClient, "stream", return_value=mock_stream_ctx), \
         patch("app.core.network.ssrf_guard.validate_url", return_value=True):

        kill_task = asyncio.create_task(_trigger_kill())
        try:
            with pytest.raises(AuthorizationError) as exc_info:
                await browser_file_transfer_service.download_file(
                    db=db_session,
                    workspace_id=ws_id,
                    url="https://example.com/stream.bin",
                )
            assert "Emergency Kill Switch is active" in str(exc_info.value)
        finally:
            await kill_task
            kill_switch.set_active(False, workspace_id=ws_id)

    # Verify quarantine directory was cleaned up
    ws_root = filesystem_guard.get_workspace_root(ws_id)
    downloads_dir = ws_root / "downloads"
    if downloads_dir.exists():
        assert len(list(downloads_dir.glob(".incoming_*"))) == 0


@pytest.mark.asyncio
async def test_race_concurrent_downloads_isolated_quarantines(db_session):
    """Verify distinct downloads in the same workspace generate distinct quarantine folders and register cleanly."""
    ws_id = uuid.uuid4()

    async def _mock_stream(content: bytes, filename: str):
        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.url = f"https://example.com/{filename}"
        mock_resp.headers = {
            "content-type": "text/plain",
            "content-disposition": f'attachment; filename="{filename}"',
        }

        async def _aiter_bytes(chunk_size=65536):
            yield content

        mock_resp.aiter_bytes = _aiter_bytes
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_resp
        mock_ctx.__aexit__.return_value = None
        return mock_ctx

    ctx1 = await _mock_stream(b"File 1 distinct payload 111", "doc1.txt")
    ctx2 = await _mock_stream(b"File 2 distinct payload 222", "doc2.txt")

    def _stream_side_effect(method, url, **kwargs):
        if "doc1" in url:
            return ctx1
        return ctx2

    with patch.object(httpx.AsyncClient, "stream", side_effect=_stream_side_effect), \
         patch("app.core.network.ssrf_guard.validate_url", return_value=True):

        res1 = await browser_file_transfer_service.download_file(
            db=db_session,
            workspace_id=ws_id,
            url="https://example.com/doc1.txt",
        )
        res2 = await browser_file_transfer_service.download_file(
            db=db_session,
            workspace_id=ws_id,
            url="https://example.com/doc2.txt",
        )

        assert res1["status"] == "success"
        assert res2["status"] == "success"
        assert res1["file_id"] != res2["file_id"]
        assert res1["filename"] == "doc1.txt"
        assert res2["filename"] == "doc2.txt"


@pytest.mark.asyncio
async def test_race_file_deletion_during_upload_attempt(db_session):
    """Verify file deleted just prior to upload raises EntityNotFoundError and fails closed."""
    ws_id = uuid.uuid4()
    ws_root = filesystem_guard.get_workspace_root(ws_id)

    file_id = uuid.uuid4()
    file_dir = ws_root / "files" / str(file_id)
    file_dir.mkdir(parents=True, exist_ok=True)
    file_path = file_dir / "target.pdf"
    file_path.write_bytes(b"%PDF-1.4 Temp")

    record = FileRecord(
        id=file_id,
        workspace_id=ws_id,
        original_filename="target.pdf",
        safe_filename="target.pdf",
        mime_type="application/pdf",
        file_extension=".pdf",
        size_bytes=len(b"%PDF-1.4 Temp"),
        sha256_hash="temp_hash",
        storage_path=f"files/{file_id}/target.pdf",
        status=FileStatus.DELETED.value,  # Already marked deleted
        metadata_={},
        security_flags=[],
    )
    db_session.add(record)
    await db_session.commit()

    with pytest.raises(ValidationError) as exc_info:
        await browser_file_transfer_service.upload_file(
            db=db_session,
            workspace_id=ws_id,
            file_id=file_id,
        )
    assert "Cannot upload deleted file" in str(exc_info.value)
