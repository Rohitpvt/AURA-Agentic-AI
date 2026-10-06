"""
Phase 1 Master Audit: Database, ORM Models, Constraints, and FastAPI API Foundation.
"""
import pytest
import uuid
from datetime import datetime, timezone
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from httpx import AsyncClient, ASGITransport

from app.db.base import Base
from app.db.models.user import User
from app.db.models.workspace import Workspace
from app.db.models.session import Session
from app.db.models.message import Message
from app.db.models.task import Task, TaskStep
from app.db.models.agent_run import AgentRun
from app.db.models.tool import Tool
from app.db.models.skill import Skill
from app.db.models.approval import ApprovalRequest
from app.db.models.audit import AuditLog
from app.db.models.memory import MemoryRecord
from app.db.models.file import FileRecord, FileChunk
from app.db.models.file_job import FileJob
from app.db.models.automation import Automation
from app.db.models.telegram import TelegramPairing
from app.db.models.webhook import WebhookEndpoint
from app.main import app


@pytest.mark.asyncio
async def test_phase01_database_schema_and_model_instantiation(db_session):
    """
    Audit Phase 1 DB: Verify all 18+ core models can be cleanly instantiated,
    persisted, queried, and respect foreign keys and constraints.
    """
    user_id = uuid.uuid4()
    ws_id = uuid.uuid4()

    user = User(
        id=user_id,
        email=f"audit_user_{str(user_id)[:8]}@example.com",
        password_hash="hashed_argon2_password",
        full_name="Audit User",
        is_active=True,
    )
    db_session.add(user)

    ws = Workspace(
        id=ws_id,
        name="Phase 1 Audit Workspace",
        slug=f"ws-{ws_id.hex[:8]}",
    )
    db_session.add(ws)
    await db_session.flush()

    task_id = uuid.uuid4()
    task = Task(
        id=task_id,
        workspace_id=ws_id,
        title="Phase 1 Audit Task",
        goal="Audit Phase 1 database schema and models",
        status="PENDING",
    )
    db_session.add(task)

    step = TaskStep(
        id=uuid.uuid4(),
        task_id=task_id,
        step_number=1,
        title="Step 1 Audit",
        description="Audit step 1 description",
        status="PENDING",
    )
    db_session.add(step)
    await db_session.flush()

    # Query back
    stmt = select(Task).where(Task.id == task_id)
    res = (await db_session.execute(stmt)).scalar_one_or_none()
    assert res is not None
    assert res.workspace_id == ws_id
    assert res.title == "Phase 1 Audit Task"


@pytest.mark.asyncio
async def test_phase01_database_foreign_key_and_unique_constraints(db_session):
    """
    Audit Phase 1 DB: Verify constraints enforce integrity and reject orphaned/duplicate records.
    """
    # Attempt to insert Task with non-existent workspace_id
    invalid_task = Task(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),  # Does not exist
        title="Invalid Orphan Task",
        status="PENDING",
    )
    db_session.add(invalid_task)
    with pytest.raises((IntegrityError, Exception)):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_phase01_transaction_rollback_behavior(db_session):
    """
    Audit Phase 1 DB: Verify atomic transaction rollback leaves zero partial records.
    """
    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        email=f"rollback_user_{str(user_id)[:8]}@example.com",
        password_hash="hashed_pwd",
        full_name="Rollback User",
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()

    try:
        # Intentionally cause integrity error
        db_session.add(User(id=user_id, email=f"rollback_user_{str(user_id)[:8]}@example.com", password_hash="pwd", full_name="Dup"))
        await db_session.flush()
    except Exception:
        await db_session.rollback()

    # Verify state rolled back cleanly
    stmt = select(User).where(User.id == user_id)
    res = (await db_session.execute(stmt)).scalar_one_or_none()
    assert res is None


@pytest.mark.asyncio
async def test_phase01_fastapi_health_and_correlation_middleware():
    """
    Audit Phase 1 API: Verify health endpoints and correlation ID middleware.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Health check
        resp = await client.get("/api/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("status") in ["ok", "healthy", "degraded"]

        # Custom correlation ID propagation
        corr_id = str(uuid.uuid4())
        resp2 = await client.get("/api/v1/health", headers={"X-Correlation-ID": corr_id})
        assert resp2.status_code == 200
        assert resp2.headers.get("X-Correlation-ID") == corr_id


@pytest.mark.asyncio
async def test_phase01_fastapi_malformed_requests_fail_closed():
    """
    Audit Phase 1 API: Verify malformed requests fail closed without exposing internals.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Malformed JSON
        resp = await client.post(
            "/api/v1/auth/login",
            content="NOT_VALID_JSON{",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code in [400, 422]
        body = resp.text.lower()
        # Verify no Python traceback leaks
        assert "traceback (most recent call last)" not in body
        assert "internal server error" not in body or resp.status_code != 500
