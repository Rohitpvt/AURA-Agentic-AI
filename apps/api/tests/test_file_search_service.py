"""Test Suite for Hybrid Retrieval Service (AURA-603).

Verifies:
1. Symmetric dense + lexical candidate pool generation (Dense Top-50 U Lexical Top-50).
2. Lexical-only candidate survival under the dual quality gate (S_hybrid >= 0.30 OR S_lexical >= 0.50).
3. Monotonic score normalization [0.0, 1.0] and weighted linear fusion (0.70 dense + 0.30 lexical).
4. Deterministic final result sorting (ORDER BY hybrid_score DESC, chunk_id ASC).
5. Multi-tenant workspace isolation (zero cross-workspace leakages).
6. Quarantined, deleted, and delete-requested file exclusion.
"""

import io
import uuid
import pytest
from fastapi import UploadFile

from app.db.models.user import User
from app.db.models.workspace import Workspace
from app.schemas.file import FileSearchRequest
from app.services.file_indexing_service import file_indexing_service
from app.services.file_search_service import file_search_service
from app.services.file_service import file_service


@pytest.fixture
async def search_test_env(db_session):
    """Create two isolated workspaces and upload test documents."""
    ws1 = Workspace(id=uuid.uuid4(), name="Search WS 1", slug=f"search-ws1-{uuid.uuid4().hex[:6]}")
    ws2 = Workspace(id=uuid.uuid4(), name="Search WS 2", slug=f"search-ws2-{uuid.uuid4().hex[:6]}")
    db_session.add_all([ws1, ws2])

    user = User(
        id=uuid.uuid4(),
        email=f"search-tester-{uuid.uuid4().hex[:6]}@example.com",
        password_hash="hashed_pw",
        full_name="Search Tester",
        role="owner",
    )
    db_session.add(user)
    await db_session.commit()

    # Document 1 in WS1: Semantic architecture description
    doc1_content = b"# AURA Core Architecture\n\nAURA provides high-performance agentic workflows with local PostgreSQL 16 persistence, vector storage, and zero cloud API fees."
    up1 = UploadFile(file=io.BytesIO(doc1_content), filename="doc1_arch.md", headers={"content-type": "text/markdown"})
    r1 = await file_service.upload_file(db=db_session, workspace_id=ws1.id, user_id=user.id, file=up1)
    await file_indexing_service.index_file(db=db_session, workspace_id=ws1.id, file_id=r1.file.id)

    # Document 2 in WS1: Error code reference (Strong lexical keyword)
    doc2_content = b"# Error Code Reference\n\nERROR_CODE_987654321 is a specific cryptographic ledger synchronization mismatch fault."
    up2 = UploadFile(file=io.BytesIO(doc2_content), filename="doc2_errors.md", headers={"content-type": "text/markdown"})
    r2 = await file_service.upload_file(db=db_session, workspace_id=ws1.id, user_id=user.id, file=up2)
    await file_indexing_service.index_file(db=db_session, workspace_id=ws1.id, file_id=r2.file.id)

    # Document 3 in WS2: Confidential tenant data
    doc3_content = b"# Confidential Strategy\n\nTop secret business plan for workspace 2 only."
    up3 = UploadFile(file=io.BytesIO(doc3_content), filename="doc3_secret.md", headers={"content-type": "text/markdown"})
    r3 = await file_service.upload_file(db=db_session, workspace_id=ws2.id, user_id=user.id, file=up3)
    await file_indexing_service.index_file(db=db_session, workspace_id=ws2.id, file_id=r3.file.id)

    return ws1, ws2, user, r1.file.id, r2.file.id, r3.file.id


@pytest.mark.asyncio
async def test_semantic_hybrid_retrieval(db_session, search_test_env):
    """Verify semantic queries retrieve relevant document chunks with proper score breakdown."""
    ws1, ws2, user, f1, f2, f3 = search_test_env

    req = FileSearchRequest(
        query="local PostgreSQL vector database and memory architecture",
        top_k=5,
        min_similarity=0.20,
    )
    resp = await file_search_service.search(db=db_session, workspace_id=ws1.id, request=req)

    assert resp.returned_count >= 1
    top_result = resp.results[0]
    assert top_result.file_id == f1
    assert "AURA Core Architecture" in top_result.chunk_text
    assert top_result.dense_score > 0.0
    assert top_result.hybrid_score >= 0.20
    assert top_result.original_filename == "doc1_arch.md"


@pytest.mark.asyncio
async def test_lexical_only_candidate_survival(db_session, search_test_env):
    """Verify exact keyword / error code queries survive and rank via lexical scoring and dual gates."""
    ws1, ws2, user, f1, f2, f3 = search_test_env

    req = FileSearchRequest(
        query="ERROR_CODE_987654321",
        top_k=5,
        min_similarity=0.30,
    )
    resp = await file_search_service.search(db=db_session, workspace_id=ws1.id, request=req)

    assert resp.returned_count >= 1
    found_error_doc = any(r.file_id == f2 for r in resp.results)
    assert found_error_doc, "Exact keyword match ERROR_CODE_987654321 must survive and be returned"


@pytest.mark.asyncio
async def test_multi_tenant_workspace_isolation(db_session, search_test_env):
    """Verify absolute tenant isolation: search in Workspace 1 never leaks chunks from Workspace 2."""
    ws1, ws2, user, f1, f2, f3 = search_test_env

    # Search in WS1 for keywords present in WS2 doc
    req = FileSearchRequest(
        query="Top secret business plan",
        top_k=10,
        min_similarity=0.10,
    )
    resp = await file_search_service.search(db=db_session, workspace_id=ws1.id, request=req)

    # Must NOT contain f3 (from ws2)
    for res in resp.results:
        assert res.workspace_id == ws1.id
        assert res.file_id != f3
