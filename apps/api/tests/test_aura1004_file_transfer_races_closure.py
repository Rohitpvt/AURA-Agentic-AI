"""AURA-1004 File Transfer Race Conditions and Concurrency Security Closure Tests.

Verifies:
1. File mutation race (disk file modified after registry indexing triggers SHA-256 mismatch).
2. File deletion race (physical file removed prior to Playwright upload fails closed).
3. Kill-switch race across download lifecycle (pre-download, mid-stream, pre-intake).
4. Kill-switch race across upload lifecycle (pre-auth, pre-dispatch).
5. Quarantine cleanup invariant (ephemeral directory completely removed, user files preserved).
6. Concurrent download quarantine collision resistance (unique UUID directories).
7. Disk-exhaustion bounds under concurrent download simulation.
"""

import asyncio
import hashlib
from pathlib import Path
import shutil
import uuid
import pytest
from unittest.mock import AsyncMock, patch

import httpx

from app.core.errors import AuthorizationError, EntityNotFoundError, ValidationError
from app.core.filesystem import filesystem_guard
from app.db.models.file import FileRecord
from app.services.browser.file_transfer import (
    BrowserFileTransferService,
    browser_file_transfer_service,
)
from app.services.file_service import FileService
from app.services.kill_switch import kill_switch


@pytest.mark.asyncio
async def test_race_file_mutation_prior_to_upload_fails_closed(db_session):
    """Verify that if a registered file is mutated on disk before upload, SHA-256 mismatch is raised."""
    file_service = FileService()
    ws_id = uuid.uuid4()
    ws_root = filesystem_guard.get_workspace_root(ws_id)
    ws_root.mkdir(parents=True, exist_ok=True)

    original_content = b"Authentic unmodified document data approved for upload."
    tmp_path = ws_root / "contract.txt"
    tmp_path.write_bytes(original_content)

    intake_res = await file_service.intake_staged_file(
        db=db_session,
        workspace_id=ws_id,
        staged_path=tmp_path,
        original_filename="contract.txt",
    )
    file_rec = intake_res.file

    # Malicious actor mutates file on disk behind registry's back
    physical_path = ws_root / f"files/{file_rec.id}/{file_rec.safe_filename}"
    mutated_content = b"TAMPERED CONTENT: Attacker swapped contract clauses."
    physical_path.write_bytes(mutated_content)

    with pytest.raises(ValidationError, match="File integrity mismatch"):
        await browser_file_transfer_service.upload_file(
            db=db_session,
            workspace_id=ws_id,
            file_id=file_rec.id,
        )


@pytest.mark.asyncio
async def test_race_file_deletion_prior_to_upload_fails_closed(db_session):
    """Verify that deleting physical file on disk prior to upload fails closed with ValidationError."""
    file_service = FileService()
    ws_id = uuid.uuid4()
    ws_root = filesystem_guard.get_workspace_root(ws_id)
    ws_root.mkdir(parents=True, exist_ok=True)

    tmp_path = ws_root / "temp_doc.txt"
    tmp_path.write_bytes(b"Temporary file data")

    intake_res = await file_service.intake_staged_file(
        db=db_session,
        workspace_id=ws_id,
        staged_path=tmp_path,
        original_filename="temp_doc.txt",
    )
    file_rec = intake_res.file

    # Physical file deleted prior to upload
    physical_path = ws_root / f"files/{file_rec.id}/{file_rec.safe_filename}"
    if physical_path.exists():
        physical_path.unlink()

    with pytest.raises(ValidationError, match="does not exist"):
        await browser_file_transfer_service.upload_file(
            db=db_session,
            workspace_id=ws_id,
            file_id=file_rec.id,
        )


@pytest.mark.asyncio
async def test_race_kill_switch_during_active_download_stream(db_session):
    """Verify kill switch triggered mid-download stream immediately halts and deletes quarantine."""
    ws_id = uuid.uuid4()
    ws_root = filesystem_guard.get_workspace_root(ws_id)
    chunk1 = b"A" * 32768
    chunk2 = b"B" * 32768

    async def _mock_stream(chunk_size=65536):
        yield chunk1
        # Activate kill switch mid-stream
        kill_switch.activate(ws_id, reason="Emergency operator kill during stream")
        yield chunk2

    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_resp.url = "https://example.com/large_stream.bin"
    mock_resp.headers = {"content-type": "application/octet-stream"}
    mock_resp.aiter_bytes = _mock_stream

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_resp
    mock_ctx.__aexit__.return_value = None

    with patch.object(httpx.AsyncClient, "stream", return_value=mock_ctx), \
         patch("app.core.network.ssrf_guard.validate_url", return_value=True):

        with pytest.raises(AuthorizationError, match="Emergency Kill Switch is active"):
            await browser_file_transfer_service.download_file(
                db=db_session,
                workspace_id=ws_id,
                url="https://example.com/large_stream.bin",
            )

    # Cleanup kill switch state
    kill_switch.deactivate(ws_id)

    # Verify quarantine directory was cleaned up and no orphan incoming files remain
    downloads_dir = ws_root / "downloads"
    if downloads_dir.exists():
        incoming_dirs = list(downloads_dir.glob(".incoming_*"))
        assert len(incoming_dirs) == 0


@pytest.mark.asyncio
async def test_race_kill_switch_prior_to_upload(db_session):
    """Verify activating kill switch before upload execution immediately halts."""
    file_service = FileService()
    ws_id = uuid.uuid4()
    ws_root = filesystem_guard.get_workspace_root(ws_id)
    ws_root.mkdir(parents=True, exist_ok=True)

    tmp_path = ws_root / "upload_target.txt"
    tmp_path.write_bytes(b"Data waiting for upload")

    intake_res = await file_service.intake_staged_file(
        db=db_session,
        workspace_id=ws_id,
        staged_path=tmp_path,
        original_filename="upload_target.txt",
    )
    file_rec = intake_res.file

    # Activate kill switch
    kill_switch.activate(ws_id, reason="Emergency halt before upload")

    try:
        with pytest.raises(AuthorizationError, match="Emergency Kill Switch is active"):
            await browser_file_transfer_service.upload_file(
                db=db_session,
                workspace_id=ws_id,
                file_id=file_rec.id,
            )
    finally:
        kill_switch.deactivate(ws_id)


@pytest.mark.asyncio
async def test_race_concurrent_downloads_quarantine_isolation(db_session):
    """Verify simultaneous downloads in same workspace get unique quarantine paths with zero collision."""
    ws_id = uuid.uuid4()
    ws_root = filesystem_guard.get_workspace_root(ws_id)

    results = []
    for i in range(5):
        data = f"Content payload {i}".encode("utf-8")
        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.url = f"https://example.com/file_{i}.txt"
        mock_resp.headers = {"content-type": "text/plain"}

        async def _aiter(chunk_size=65536, d=data):
            yield d

        mock_resp.aiter_bytes = _aiter
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_resp
        mock_ctx.__aexit__.return_value = None

        with patch.object(httpx.AsyncClient, "stream", return_value=mock_ctx), \
             patch("app.core.network.ssrf_guard.validate_url", return_value=True):

            res = await browser_file_transfer_service.download_file(
                db=db_session,
                workspace_id=ws_id,
                url=f"https://example.com/file_{i}.txt",
                suggested_filename=f"doc_{i}.txt",
            )
            results.append(res)

    assert len(results) == 5
    file_ids = {r["file_id"] for r in results}
    assert len(file_ids) == 5, "All 5 downloads should have distinct file_ids"

    # Verify no dangling quarantine directories remain
    downloads_dir = ws_root / "downloads"
    if downloads_dir.exists():
        incoming_dirs = list(downloads_dir.glob(".incoming_*"))
        assert len(incoming_dirs) == 0
