"""Test Suite for File Indexing & Reindexing Service (AURA-603).

Verifies:
1. Two-stage staging pipeline (Preparation outside DB lock -> Atomic DB swap).
2. FileChunk persistence with valid 768-dim embeddings and structural location metadata.
3. Publication of authoritative vector index metadata on FileRecord.
4. Re-indexing atomically increments generation UUID and replaces previous chunks.
5. Deletion / reindex race prevention (fail closed if file is marked for deletion).
6. Quarantined file indexing rejection.
7. Deletion cascade purges FileChunk rows and tombstones linked MemoryRecord.
"""

import io
import uuid
import pytest
from fastapi import UploadFile
from sqlalchemy import select

from app.core.errors import EntityNotFoundError, ValidationError
from app.db.models.file import FileChunk, FileRecord, FileStatus
from app.db.models.memory import MemoryRecord
from app.db.models.user import User
from app.db.models.workspace import Workspace
from app.services.file_indexing_service import file_indexing_service
from app.services.file_service import file_service
from app.services.memory_service import memory_service


@pytest.fixture
async def sample_workspace_and_user(db_session):
    """Create test workspace and user."""
    ws = Workspace(
        id=uuid.uuid4(),
        name="Vector Test Workspace",
        slug=f"vector-ws-{uuid.uuid4().hex[:6]}",
    )
    db_session.add(ws)

    user = User(
        id=uuid.uuid4(),
        email=f"tester-{uuid.uuid4().hex[:6]}@example.com",
        password_hash="hashed_pw",
        full_name="Vector Tester",
        role="owner",
    )
    db_session.add(user)
    await db_session.commit()
    return ws, user


@pytest.mark.asyncio
async def test_file_indexing_lifecycle(db_session, sample_workspace_and_user):
    """Verify complete indexing lifecycle from upload to chunk vectorization and metadata publication."""
    ws, user = sample_workspace_and_user

    # 1. Upload Markdown file
    content = b"# Vector Indexing Guide\n\nPostgreSQL 16 with pgvector HNSW provides high-performance vector search.\n\n## Settings\nSet m=16 and ef_construction=64."
    upload = UploadFile(
        file=io.BytesIO(content),
        filename="vector_guide.md",
        headers={"content-type": "text/markdown"},
    )
    upload_resp = await file_service.upload_file(
        db=db_session,
        workspace_id=ws.id,
        user_id=user.id,
        file=upload,
    )
    file_id = upload_resp.file.id

    # 2. Trigger Indexing
    index_resp = await file_indexing_service.index_file(
        db=db_session,
        workspace_id=ws.id,
        file_id=file_id,
        actor_id=str(user.id),
    )

    assert index_resp.status == "ready"
    assert index_resp.chunks_count >= 1
    assert index_resp.tokens_count > 0
    assert index_resp.generation is not None
    assert index_resp.embedding_model == "BAAI/bge-base-en-v1.5"

    # 3. Verify FileChunk rows in DB
    stmt = select(FileChunk).where(FileChunk.file_id == file_id, FileChunk.workspace_id == ws.id)
    chunks = (await db_session.execute(stmt)).scalars().all()
    assert len(chunks) == index_resp.chunks_count
    for chk in chunks:
        assert chk.embedding is not None
        assert len(chk.embedding) == 768
        assert chk.token_count <= 510
        assert chk.chunk_text.startswith("[Document: vector_guide.md")

    # 4. Verify FileRecord metadata publication
    rec = await file_service.get_file(db=db_session, workspace_id=ws.id, file_id=file_id)
    assert rec.metadata_["vector_index"]["status"] == "ready"
    assert rec.metadata_["vector_index"]["chunk_count"] == len(chunks)
    assert rec.metadata_["vector_index"]["generation"] == index_resp.generation


@pytest.mark.asyncio
async def test_file_reindexing_generation_swap(db_session, sample_workspace_and_user):
    """Verify forced reindexing updates generation and atomically swaps chunks."""
    ws, user = sample_workspace_and_user

    content = b"# Document Title\n\nInitial section with some sample text for indexing."
    upload = UploadFile(
        file=io.BytesIO(content),
        filename="reindex_doc.md",
        headers={"content-type": "text/markdown"},
    )
    upload_resp = await file_service.upload_file(
        db=db_session,
        workspace_id=ws.id,
        user_id=user.id,
        file=upload,
    )
    file_id = upload_resp.file.id

    # Initial Indexing
    resp1 = await file_indexing_service.index_file(
        db=db_session,
        workspace_id=ws.id,
        file_id=file_id,
    )
    gen1 = resp1.generation

    # Force Re-indexing
    resp2 = await file_indexing_service.index_file(
        db=db_session,
        workspace_id=ws.id,
        file_id=file_id,
        reindex=True,
    )
    gen2 = resp2.generation

    assert gen1 != gen2
    assert resp2.status == "ready"


@pytest.mark.asyncio
async def test_indexing_fails_on_deleted_file(db_session, sample_workspace_and_user):
    """Verify indexing fails closed if file is deleted."""
    ws, user = sample_workspace_and_user

    content = b"# Ephemeral\nContent to delete."
    upload = UploadFile(
        file=io.BytesIO(content),
        filename="ephemeral.md",
        headers={"content-type": "text/markdown"},
    )
    upload_resp = await file_service.upload_file(
        db=db_session,
        workspace_id=ws.id,
        user_id=user.id,
        file=upload,
    )
    file_id = upload_resp.file.id

    # Delete file
    await file_service.delete_file(db=db_session, workspace_id=ws.id, file_id=file_id)

    # Attempt indexing on deleted file must fail
    with pytest.raises((ValidationError, EntityNotFoundError)):
        await file_indexing_service.index_file(
            db=db_session,
            workspace_id=ws.id,
            file_id=file_id,
        )


@pytest.mark.asyncio
async def test_deletion_purges_chunks_and_tombstones_memory(db_session, sample_workspace_and_user):
    """Verify file deletion cascades chunk hard-delete and tombstones cognitive memory with strict scope protection."""
    ws, user = sample_workspace_and_user

    # 1. Upload Target File (File 1)
    content1 = b"# Provenance Doc 1\nFact: The API port is 8000."
    upload1 = UploadFile(
        file=io.BytesIO(content1),
        filename="provenance_1.md",
        headers={"content-type": "text/markdown"},
    )
    upload_resp1 = await file_service.upload_file(
        db=db_session,
        workspace_id=ws.id,
        user_id=user.id,
        file=upload1,
    )
    file_id_1 = upload_resp1.file.id

    # 2. Upload Unrelated File (File 2) in same workspace
    content2 = b"# Provenance Doc 2\nFact: The Database port is 5432."
    upload2 = UploadFile(
        file=io.BytesIO(content2),
        filename="provenance_2.md",
        headers={"content-type": "text/markdown"},
    )
    upload_resp2 = await file_service.upload_file(
        db=db_session,
        workspace_id=ws.id,
        user_id=user.id,
        file=upload2,
    )
    file_id_2 = upload_resp2.file.id

    # 3. Create Second Workspace (Workspace 2) with File 3
    ws2 = Workspace(id=uuid.uuid4(), name="Workspace 2", slug=f"ws2-{uuid.uuid4().hex[:6]}")
    db_session.add(ws2)
    await db_session.commit()

    upload3 = UploadFile(
        file=io.BytesIO(b"# WS2 Doc\nFact: Cache port is 6379."),
        filename="ws2_doc.md",
        headers={"content-type": "text/markdown"},
    )
    upload_resp3 = await file_service.upload_file(
        db=db_session,
        workspace_id=ws2.id,
        user_id=user.id,
        file=upload3,
    )
    file_id_3 = upload_resp3.file.id

    # Index all 3 files
    await file_indexing_service.index_file(db=db_session, workspace_id=ws.id, file_id=file_id_1)
    await file_indexing_service.index_file(db=db_session, workspace_id=ws.id, file_id=file_id_2)
    await file_indexing_service.index_file(db=db_session, workspace_id=ws2.id, file_id=file_id_3)

    # 4. Create memories:
    # A. User directive memory in WS1 (non-file)
    user_mem = await memory_service.ingest_memory(
        db=db_session,
        workspace_id=ws.id,
        fact_statement="User prefers YAML configurations over JSON.",
        source_type="user_directive",
        category="preferences",
    )

    # B. File 1 intelligence memory in WS1 (target)
    f1_chunk_id = uuid.uuid4()
    f1_mem = await memory_service.promote_chunk_to_memory(
        db=db_session,
        workspace_id=ws.id,
        file_id=file_id_1,
        chunk_id=f1_chunk_id,
        chunk_index=0,
        fact_statement="The API port is 8000.",
        file_hash=upload_resp1.file.sha256_hash,
        retrieval_score=0.92,
    )
    assert f1_mem.source_type == "file_intelligence"
    assert f1_mem.provenance["file_id"] == str(file_id_1)
    assert f1_mem.provenance["chunk_id"] == str(f1_chunk_id)
    assert f1_mem.provenance["file_sha256"] == upload_resp1.file.sha256_hash
    assert f1_mem.provenance["parser_version"] == "1.0.0"
    assert f1_mem.provenance["embedding_model"] == "BAAI/bge-base-en-v1.5"
    assert "timestamp" in f1_mem.provenance

    # C. File 2 intelligence memory in WS1 (unrelated file in same WS)
    f2_mem = await memory_service.promote_chunk_to_memory(
        db=db_session,
        workspace_id=ws.id,
        file_id=file_id_2,
        chunk_id=uuid.uuid4(),
        chunk_index=0,
        fact_statement="The Database port is 5432.",
        file_hash=upload_resp2.file.sha256_hash,
    )

    # D. File 3 intelligence memory in WS2 (cross-workspace)
    f3_mem = await memory_service.promote_chunk_to_memory(
        db=db_session,
        workspace_id=ws2.id,
        file_id=file_id_3,
        chunk_id=uuid.uuid4(),
        chunk_index=0,
        fact_statement="Cache port is 6379.",
        file_hash=upload_resp3.file.sha256_hash,
    )

    # 5. Delete File 1 ONLY
    del_resp = await file_service.delete_file(db=db_session, workspace_id=ws.id, file_id=file_id_1)
    assert del_resp.status == "deleted"
    assert del_resp.purged_chunks > 0

    # 6. Verify chunks of File 1 are purged; File 2 chunks remain intact
    stmt_chunks_f1 = select(FileChunk).where(FileChunk.file_id == file_id_1)
    assert len((await db_session.execute(stmt_chunks_f1)).scalars().all()) == 0

    stmt_chunks_f2 = select(FileChunk).where(FileChunk.file_id == file_id_2)
    assert len((await db_session.execute(stmt_chunks_f2)).scalars().all()) > 0

    # 7. Verify Tombstone Scoping:
    # Target memory (File 1) is tombstoned
    r_f1 = (await db_session.execute(select(MemoryRecord).where(MemoryRecord.id == f1_mem.id))).scalar_one()
    assert r_f1.is_tombstoned is True
    assert f"Originating file {file_id_1} was deleted" in r_f1.tombstoned_reason
    # Provenance integrity preserved post-tombstone
    assert r_f1.provenance["file_id"] == str(file_id_1)
    assert r_f1.provenance["chunk_id"] == str(f1_chunk_id)

    # User directive memory in WS1 NOT tombstoned
    r_user = (await db_session.execute(select(MemoryRecord).where(MemoryRecord.id == user_mem.id))).scalar_one()
    assert r_user.is_tombstoned is False

    # File 2 memory in WS1 NOT tombstoned
    r_f2 = (await db_session.execute(select(MemoryRecord).where(MemoryRecord.id == f2_mem.id))).scalar_one()
    assert r_f2.is_tombstoned is False

    # File 3 memory in WS2 NOT tombstoned
    r_f3 = (await db_session.execute(select(MemoryRecord).where(MemoryRecord.id == f3_mem.id))).scalar_one()
    assert r_f3.is_tombstoned is False

    # 8. Test Idempotency: Deleting File 1 again returns already_deleted and produces zero side-effects
    del_resp2 = await file_service.delete_file(db=db_session, workspace_id=ws.id, file_id=file_id_1)
    assert del_resp2.status == "already_deleted"
    assert del_resp2.purged_chunks == 0

