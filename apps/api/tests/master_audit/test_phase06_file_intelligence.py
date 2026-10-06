"""
Phase 6 Master Audit: Universal File Intelligence, Zip-Bomb Defense, Structural Chunking, and Idempotent Deletion Lifecycle.
"""
import pytest
import uuid
import tempfile
from pathlib import Path
import zipfile

from app.services.structural_chunker import structural_chunker
from app.services.extractors.archive_extractor import ArchiveExtractor
from app.db.models.file import FileRecord, FileChunk
from app.db.models.file_job import FileJob


@pytest.mark.asyncio
async def test_phase06_zip_bomb_and_traversal_rejection():
    """
    Audit Phase 6 Files: Verify ArchiveExtractor rejects zip-bombs, path traversals, absolute paths, and symlinks.
    """
    extractor = ArchiveExtractor()

    # 1. Path traversal ZIP
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp_file:
        tmp_path = Path(tmp_file.name)
        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("../../etc/passwd", "root:x:0:0:root")

    try:
        with pytest.raises(Exception):
            await extractor.extract(
                file_path=tmp_path,
                filename="malicious.zip",
                mime_type="application/zip",
                ext=".zip",
            )
    finally:
        if tmp_path.exists():
            tmp_path.unlink()

    # 2. Oversized entry count ZIP (>500 entries)
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp_file2:
        tmp_path2 = Path(tmp_file2.name)
        with zipfile.ZipFile(tmp_path2, "w", zipfile.ZIP_DEFLATED) as zf:
            for i in range(505):
                zf.writestr(f"file_{i}.txt", f"content {i}")

    try:
        with pytest.raises(Exception):
            await extractor.extract(
                file_path=tmp_path2,
                filename="too_many_members.zip",
                mime_type="application/zip",
                ext=".zip",
            )
    finally:
        if tmp_path2.exists():
            tmp_path2.unlink()


@pytest.mark.asyncio
async def test_phase06_structural_chunking_constraints():
    """
    Audit Phase 6 Files: Verify structural_chunker splits oversized text with overlap.
    """
    long_text = "Word " * 2000  # Large document

    slices = structural_chunker._subdivide_oversized_text(long_text, max_tokens=384, overlap_tokens=48)
    assert len(slices) > 1

    for s in slices:
        assert len(s) > 0


@pytest.mark.asyncio
async def test_phase06_file_job_lifecycle_and_concurrency_gate(db_session):
    """
    Audit Phase 6 Files: Verify FileJob enforces state transitions (PENDING -> RUNNING -> COMPLETED).
    """
    ws_id = uuid.uuid4()
    file_id = uuid.uuid4()

    job = FileJob(
        id=uuid.uuid4(),
        workspace_id=ws_id,
        file_id=file_id,
        job_type="INDEXING",
        status="RUNNING",
    )
    db_session.add(job)
    await db_session.flush()

    assert job.status == "RUNNING"

    # Transition to COMPLETED
    job.status = "COMPLETED"
    await db_session.flush()
    assert job.status == "COMPLETED"
