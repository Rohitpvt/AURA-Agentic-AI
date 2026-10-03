"""Tests for AURA-104: FastEmbed + pgvector Memory Foundation and Recall."""

import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models.workspace import Workspace
from app.services.embedding_service import embedding_service
from app.services.memory_service import memory_service


@pytest.mark.asyncio
async def test_embedding_service_dimensions_and_batching():
    """Verify local embedding service generates 768-dimensional normalized vectors."""
    text = "AURA is a local-first agentic operating system."
    vec = embedding_service.embed_text(text)
    assert len(vec) == 768
    assert embedding_service.get_dimension() == 768

    # Batch test
    batch = ["First statement", "Second statement", "Third statement"]
    vectors = embedding_service.embed_batch(batch)
    assert len(vectors) == 3
    for v in vectors:
        assert len(v) == 768


@pytest.mark.asyncio
async def test_memory_ingestion_and_semantic_recall(db_session: AsyncSession):
    """Test full memory write and semantic vector similarity recall."""
    ws = Workspace(name="WS Memory Test", slug=f"ws-mem-{uuid.uuid4().hex[:6]}")
    db_session.add(ws)
    await db_session.flush()

    # 1. Ingest distinct memories
    rec1 = await memory_service.ingest_memory(
        db=db_session,
        workspace_id=ws.id,
        fact_statement="PostgreSQL 16 uses HNSW index for fast approximate nearest neighbor vector search.",
        category="project_context",
    )
    rec2 = await memory_service.ingest_memory(
        db=db_session,
        workspace_id=ws.id,
        fact_statement="User prefers concise Python code formatted with black and ruff.",
        category="preference",
    )
    rec3 = await memory_service.ingest_memory(
        db=db_session,
        workspace_id=ws.id,
        fact_statement="The server is hosted on an AMD Ryzen 7 4800H machine with 24GB RAM.",
        category="personal_fact",
    )

    # 2. Query for database performance -> should rank rec1 highest
    results = await memory_service.recall_memories(
        db=db_session,
        workspace_id=ws.id,
        query="PostgreSQL vector indexing HNSW",
        top_k=2,
    )
    assert len(results) > 0
    top_hit = results[0]
    assert top_hit.record.id == rec1.id
    assert top_hit.similarity_score > 0.3


@pytest.mark.asyncio
async def test_memory_governance_and_tombstoning(db_session: AsyncSession):
    """Test memory tombstoning (soft delete) excludes record from active recall."""
    ws = Workspace(name="WS Tombstone Test", slug=f"ws-tomb-{uuid.uuid4().hex[:6]}")
    db_session.add(ws)
    await db_session.flush()

    rec = await memory_service.ingest_memory(
        db=db_session,
        workspace_id=ws.id,
        fact_statement="The legacy backend port was 9000.",
        category="project_context",
    )

    # Initial query finds it
    results_before = await memory_service.recall_memories(
        db=db_session,
        workspace_id=ws.id,
        query="legacy backend port",
    )
    assert len(results_before) == 1

    # Tombstone record
    tombstoned = await memory_service.tombstone_memory(
        db=db_session,
        memory_id=rec.id,
        workspace_id=ws.id,
        reason="Port changed to 8000 in Phase 1",
    )
    assert tombstoned.is_tombstoned is True

    # Subsequent recall excludes tombstoned memory by default
    results_after = await memory_service.recall_memories(
        db=db_session,
        workspace_id=ws.id,
        query="legacy backend port",
        include_tombstoned=False,
    )
    assert len(results_after) == 0

    # Explicit request includes it
    results_with_tombstoned = await memory_service.recall_memories(
        db=db_session,
        workspace_id=ws.id,
        query="legacy backend port",
        include_tombstoned=True,
    )
    assert len(results_with_tombstoned) == 1


@pytest.mark.asyncio
async def test_memory_multi_tenant_workspace_isolation(db_session: AsyncSession):
    """Test memories in Workspace A are never returned when searching Workspace B."""
    ws_a = Workspace(name="WS Alpha", slug=f"ws-alpha-{uuid.uuid4().hex[:6]}")
    ws_b = Workspace(name="WS Beta", slug=f"ws-beta-{uuid.uuid4().hex[:6]}")
    db_session.add_all([ws_a, ws_b])
    await db_session.flush()

    # Ingest secret project fact in Workspace A
    await memory_service.ingest_memory(
        db=db_session,
        workspace_id=ws_a.id,
        fact_statement="Project Alpha secret codename is Horizon 2026.",
        category="project_context",
    )

    # Query from Workspace B -> must return empty
    results_b = await memory_service.recall_memories(
        db=db_session,
        workspace_id=ws_b.id,
        query="Project Alpha secret codename Horizon",
    )
    assert len(results_b) == 0


@pytest.mark.asyncio
async def test_promote_chunk_to_memory_provenance(db_session: AsyncSession):
    """Verify promote_chunk_to_memory creates file_intelligence record with full structured provenance."""
    ws = Workspace(name="WS Provenance Test", slug=f"ws-prov-{uuid.uuid4().hex[:6]}")
    db_session.add(ws)
    await db_session.flush()

    file_id = uuid.uuid4()
    chunk_id = uuid.uuid4()

    rec = await memory_service.promote_chunk_to_memory(
        db=db_session,
        workspace_id=ws.id,
        file_id=file_id,
        chunk_id=chunk_id,
        chunk_index=2,
        fact_statement="Microservice auth timeout configured to 3000ms.",
        category="file_insight",
        confidence_score=0.95,
        source_location={"section": "Authentication", "line_start": 42, "line_end": 50},
        file_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        retrieval_score=0.88,
    )

    assert rec.source_type == "file_intelligence"
    assert rec.category == "file_insight"
    assert float(rec.confidence_score) == 0.95
    assert rec.is_tombstoned is False

    # Check exact structured provenance fields
    prov = rec.provenance
    assert prov["workspace_id"] == str(ws.id)
    assert prov["file_id"] == str(file_id)
    assert prov["chunk_id"] == str(chunk_id)
    assert prov["chunk_index"] == 2
    assert prov["source_location"]["section"] == "Authentication"
    assert prov["file_sha256"] == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert prov["parser_version"] == "1.0.0"
    assert prov["chunking_version"] == "1.0.0"
    assert prov["embedding_model"] == "BAAI/bge-base-en-v1.5"
    assert prov["retrieval_score"] == 0.88
    assert "timestamp" in prov

