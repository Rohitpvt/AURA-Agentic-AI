"""Integration and Unit Tests for AURA-604 File Intelligence API Endpoints and Concurrency Gate.

Verifies:
1. Async job lifecycle: 202 Accepted + job_id, GET /jobs/{job_id} polling.
2. Database-enforced active job uniqueness: concurrent duplicate job submission produces 409 Conflict (OPERATION_ALREADY_IN_PROGRESS).
3. Document synthesis API with local Ollama / deterministic extractive fallback ($0.00 cost).
4. Inert file preview API with character bounding and security badge.
5. Spreadsheet schema and formula safety analysis API.
6. Governed user-driven memory promotion with source_type="file_intelligence".
7. Strict cross-workspace job and file isolation.
"""

import asyncio
import io
import uuid
from httpx import AsyncClient
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.db.models.file import FileRecord, FileStatus
from app.db.models.file_job import FileJob, FileJobStatus, FileJobType
from app.db.models.memory import MemoryRecord
from app.db.models.user import User
from app.db.models.workspace import Workspace, WorkspaceMember
from app.services.file_job_service import file_job_service
from app.services.file_service import file_service


@pytest_asyncio.fixture
async def api_test_env(db_session: AsyncSession):
    """Setup authenticated multi-tenant test environment."""
    user1 = User(
        id=uuid.uuid4(),
        email=f"owner1-{uuid.uuid4().hex[:6]}@aura.local",
        full_name="API Owner 1",
        password_hash="fake_hash",
        is_active=True,
    )
    user2 = User(
        id=uuid.uuid4(),
        email=f"owner2-{uuid.uuid4().hex[:6]}@aura.local",
        full_name="API Owner 2",
        password_hash="fake_hash",
        is_active=True,
    )
    db_session.add_all([user1, user2])

    ws1 = Workspace(id=uuid.uuid4(), name="API Workspace 1", slug=f"api-ws1-{uuid.uuid4().hex[:6]}")
    ws2 = Workspace(id=uuid.uuid4(), name="API Workspace 2", slug=f"api-ws2-{uuid.uuid4().hex[:6]}")
    db_session.add_all([ws1, ws2])

    m1 = WorkspaceMember(workspace_id=ws1.id, user_id=user1.id, role="owner")
    m2 = WorkspaceMember(workspace_id=ws2.id, user_id=user2.id, role="owner")
    db_session.add_all([m1, m2])
    await db_session.commit()

    token1 = create_access_token({"sub": str(user1.id), "email": user1.email})
    token2 = create_access_token({"sub": str(user2.id), "email": user2.email})

    headers1 = {"Authorization": f"Bearer {token1}"}
    headers2 = {"Authorization": f"Bearer {token2}"}

    return {
        "user1": user1,
        "user2": user2,
        "ws1": ws1,
        "ws2": ws2,
        "headers1": headers1,
        "headers2": headers2,
    }


@pytest.mark.asyncio
async def test_async_job_submission_and_status_polling(client: AsyncClient, api_test_env):
    """1. Test async 202 Accepted extraction dispatch and polling GET /jobs/{job_id}."""
    ws1 = api_test_env["ws1"]
    headers1 = api_test_env["headers1"]

    # Upload test document
    content = b"# Asynchronous Intelligence Guide\n\nThis document tests 202 Accepted background extraction."
    files = {"file": ("async_guide.md", io.BytesIO(content), "text/markdown")}
    upload_resp = await client.post(f"/api/v1/files/upload?workspace_id={ws1.id}", headers=headers1, files=files)
    assert upload_resp.status_code == 201
    file_id = upload_resp.json()["file"]["id"]

    # Trigger async extraction with async=true
    extract_resp = await client.post(f"/api/v1/files/{file_id}/extract?workspace_id={ws1.id}&async=true", headers=headers1)
    assert extract_resp.status_code == 202
    job_data = extract_resp.json()
    assert "job_id" in job_data
    job_id = job_data["job_id"]
    assert job_data["status"] in ["queued", "processing", "completed"]

    # Wait briefly for background task and poll job status
    await asyncio.sleep(0.5)
    poll_resp = await client.get(f"/api/v1/files/jobs/{job_id}?workspace_id={ws1.id}", headers=headers1)
    assert poll_resp.status_code == 200
    job_status = poll_resp.json()
    assert job_status["job_id"] == job_id
    assert job_status["job_type"] == "file_extract"
    assert job_status["status"] in ["queued", "processing", "completed"]


@pytest.mark.asyncio
async def test_concurrent_duplicate_job_rejection_409(client: AsyncClient, api_test_env, db_session: AsyncSession):
    """2. Test active job uniqueness: submitting two duplicate active jobs returns 409 OPERATION_ALREADY_IN_PROGRESS."""
    ws1 = api_test_env["ws1"]
    headers1 = api_test_env["headers1"]
    user1 = api_test_env["user1"]

    content = b"# Concurrency Gate Test\n\nTesting active job uniqueness."
    files = {"file": ("concurrency.md", io.BytesIO(content), "text/markdown")}
    upload_resp = await client.post(f"/api/v1/files/upload?workspace_id={ws1.id}", headers=headers1, files=files)
    file_id = uuid.UUID(upload_resp.json()["file"]["id"])

    # Directly create an active job in queued status
    job1 = await file_job_service.create_job(
        db=db_session,
        workspace_id=ws1.id,
        file_id=file_id,
        job_type=FileJobType.EXTRACT.value,
        user_id=user1.id,
    )
    assert job1.status == FileJobStatus.QUEUED.value

    # Attempting to submit another async extraction job for the same (ws, file, type) must receive 409 Conflict
    dup_resp = await client.post(f"/api/v1/files/{file_id}/extract?workspace_id={ws1.id}&async=true", headers=headers1)
    assert dup_resp.status_code == 409
    dup_json = dup_resp.json()
    assert "error" in dup_json
    assert dup_json["error"]["code"] == "OPERATION_ALREADY_IN_PROGRESS"


@pytest.mark.asyncio
async def test_document_summary_endpoint_with_extractive_fallback(client: AsyncClient, api_test_env):
    """3. Test POST /summary endpoint with local Ollama / deterministic extractive fallback."""
    ws1 = api_test_env["ws1"]
    headers1 = api_test_env["headers1"]

    content = b"# High-Speed Architecture\n\nAURA provides deterministic local-first agentic operating system capabilities.\n\n## Core Principles\n- Zero mandatory cloud cost ($0.00).\n- Strict workspace tenant isolation."
    files = {"file": ("architecture_doc.md", io.BytesIO(content), "text/markdown")}
    upload_resp = await client.post(f"/api/v1/files/upload?workspace_id={ws1.id}", headers=headers1, files=files)
    file_id = upload_resp.json()["file"]["id"]

    summary_resp = await client.post(
        f"/api/v1/files/{file_id}/summary?workspace_id={ws1.id}",
        headers=headers1,
        json={"max_tokens": 512, "focus_areas": ["Cost", "Tenant Isolation"]},
    )
    assert summary_resp.status_code == 200
    data = summary_resp.json()
    assert data["file_id"] == file_id
    assert len(data["executive_summary"]) > 0
    assert isinstance(data["key_takeaways"], list)
    assert data["status"] in ["completed", "extractive_fallback"]


@pytest.mark.asyncio
async def test_file_preview_endpoint_inert_bounded(client: AsyncClient, api_test_env):
    """4. Test GET /preview endpoint returns bounded inert content and security badge."""
    ws1 = api_test_env["ws1"]
    headers1 = api_test_env["headers1"]

    content = b"Line 1: System Config\nLine 2: Active Modules\nLine 3: Hardened Preview"
    files = {"file": ("preview_test.txt", io.BytesIO(content), "text/plain")}
    upload_resp = await client.post(f"/api/v1/files/upload?workspace_id={ws1.id}", headers=headers1, files=files)
    file_id = upload_resp.json()["file"]["id"]

    preview_resp = await client.get(f"/api/v1/files/{file_id}/preview?workspace_id={ws1.id}", headers=headers1)
    assert preview_resp.status_code == 200
    data = preview_resp.json()
    assert data["file_id"] == file_id
    assert data["preview_type"] == "text"
    assert "Line 1: System Config" in data["content"]
    assert data["security_badge"] == "Untrusted External File Content — Active Scripts Inactive"
    assert data["is_truncated"] is False


@pytest.mark.asyncio
async def test_spreadsheet_analysis_endpoint(client: AsyncClient, api_test_env):
    """5. Test POST /spreadsheet/analyze returns sheet structures, columns, and formula counts safely."""
    ws1 = api_test_env["ws1"]
    headers1 = api_test_env["headers1"]

    csv_content = b"Department,Headcount,Budget,Formula\nSecurity,12,1500000,=B2*125000\nEngineering,45,6000000,=B3*133333\n"
    files = {"file": ("dept_budget.csv", io.BytesIO(csv_content), "text/csv")}
    upload_resp = await client.post(f"/api/v1/files/upload?workspace_id={ws1.id}", headers=headers1, files=files)
    file_id = upload_resp.json()["file"]["id"]

    analyze_resp = await client.post(
        f"/api/v1/files/{file_id}/spreadsheet/analyze?workspace_id={ws1.id}",
        headers=headers1,
        json={"sample_row_limit": 10},
    )
    assert analyze_resp.status_code == 200
    data = analyze_resp.json()
    assert data["file_id"] == file_id
    assert data["total_sheets"] >= 1
    assert "sheets" in data
    assert len(data["sheets"][0]["columns"]) == 4
    assert data["summary"]["total_formulas_detected"] >= 2


@pytest.mark.asyncio
async def test_user_memory_promotion_provenance(client: AsyncClient, api_test_env, db_session: AsyncSession):
    """6. Test POST /promote-memory creates a MemoryRecord with source_type='file_intelligence' and verified provenance."""
    ws1 = api_test_env["ws1"]
    headers1 = api_test_env["headers1"]

    content = b"# Knowledge Retention\n\nAntigravity is designed by Google DeepMind."
    files = {"file": ("knowledge.md", io.BytesIO(content), "text/markdown")}
    upload_resp = await client.post(f"/api/v1/files/upload?workspace_id={ws1.id}", headers=headers1, files=files)
    file_id = upload_resp.json()["file"]["id"]

    promote_payload = {
        "fact_statement": "AURA is configured with $0.00 zero-cost local substrate.",
        "tags": ["architecture_insight", "zero_cost"],
    }

    promote_resp = await client.post(
        f"/api/v1/files/{file_id}/promote-memory?workspace_id={ws1.id}",
        headers=headers1,
        json=promote_payload,
    )
    assert promote_resp.status_code == 200
    promoted = promote_resp.json()
    assert promoted["source_type"] == "file_intelligence"
    assert promoted["provenance"]["file_id"] == str(file_id)
    assert "memory_id" in promoted

    # Verify directly in database
    memory_id = uuid.UUID(promoted["memory_id"])
    stmt = select(MemoryRecord).where(MemoryRecord.id == memory_id)
    mem_rec = (await db_session.execute(stmt)).scalar_one_or_none()
    assert mem_rec is not None
    assert mem_rec.source_type == "file_intelligence"
    assert mem_rec.provenance["file_id"] == str(file_id)
    assert mem_rec.workspace_id == ws1.id


@pytest.mark.asyncio
async def test_cross_workspace_job_isolation_and_security(client: AsyncClient, api_test_env):
    """7. Test User 2 from Workspace 2 cannot access jobs, files, or previews belonging to Workspace 1."""
    ws1 = api_test_env["ws1"]
    ws2 = api_test_env["ws2"]
    headers1 = api_test_env["headers1"]
    headers2 = api_test_env["headers2"]

    content = b"Confidential document in Workspace 1"
    files = {"file": ("classified.txt", io.BytesIO(content), "text/plain")}
    upload_resp = await client.post(f"/api/v1/files/upload?workspace_id={ws1.id}", headers=headers1, files=files)
    file_id = upload_resp.json()["file"]["id"]

    # 1. User 2 cannot access preview of ws1 file using ws2 context (404)
    resp_prev_ws2 = await client.get(f"/api/v1/files/{file_id}/preview?workspace_id={ws2.id}", headers=headers2)
    assert resp_prev_ws2.status_code == 404

    # 2. User 2 cannot access preview of ws1 file using ws1 context (403 forbidden)
    resp_prev_ws1 = await client.get(f"/api/v1/files/{file_id}/preview?workspace_id={ws1.id}", headers=headers2)
    assert resp_prev_ws1.status_code == 403

    # 3. User 2 cannot trigger extraction on ws1 file
    resp_ext = await client.post(f"/api/v1/files/{file_id}/extract?workspace_id={ws1.id}", headers=headers2)
    assert resp_ext.status_code == 403
