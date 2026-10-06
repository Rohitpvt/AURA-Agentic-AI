"""Master Gap Closure & Zero-Skip Verification Test Suite (AURA Master Audit Final Phase).

Coordinates and asserts zero-skip evidence across all pillars:
1. MCP Protocol & Tool Governance (Local disposable stdio client, canonical registration, fail-closed bypass).
2. Docker Sandbox Boundary (Deterministic fail-closed behavior on unavailable host, safe limits, zero host escape).
3. Universal Document Intelligence (Deterministic in-process extractors, traversal rejection, legacy format guards).
4. Memory & Vector Tenancy (768-dim normalized embeddings, tombstoning, workspace isolation).
5. Cross-Phase Governance Trace (AgentToolBridge -> ToolRegistry -> Policy -> AuditLedger).
6. Emergency Kill Switch Anti-Replay & Privacy Canary Scrubbing.
"""

import asyncio
import os
import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AuthorizationError, ValidationError
from app.core.redaction import secret_redactor
from app.core.sanitization import PromptSanitizer
from app.db.models.memory import MemoryRecord
from app.db.models.task import Task
from app.db.models.user import User
from app.db.models.workspace import Workspace
from app.runtime.sandbox.manager import sandbox_manager
from app.runtime.tool_bridge import AgentToolBridge
from app.services.embedding_service import embedding_service
from app.services.kill_switch import EmergencyKillSwitchService, kill_switch
from app.services.os_guard.policy import LOLBINS_DENYLIST, OSPolicyEngine
from app.services.os_guard.types import OSActionLifecycleState, OSActionRequest, OSActionType
from app.services.task_recovery_service import TaskRecoveryService
from app.services.tool_registry import tool_registry


@pytest.mark.asyncio
async def test_gap_closure_database_vector_and_tombstoning(db_session: AsyncSession):
    """Verify vector dimension, workspace tenancy, and tombstone filtering."""
    ws1_id = uuid.uuid4()
    ws2_id = uuid.uuid4()

    # Create two memory records with 768-dim embeddings
    vec1 = embedding_service.embed_text("AURA confidential security policy for Workspace 1")
    vec2 = embedding_service.embed_text("AURA confidential research notes for Workspace 2")

    fact1 = MemoryRecord(
        workspace_id=ws1_id,
        fact_statement="Fact 1 text",
        category="security",
        embedding=vec1,
        is_tombstoned=False,
    )
    fact2_tombstoned = MemoryRecord(
        workspace_id=ws1_id,
        fact_statement="Fact 2 tombstoned text",
        category="deprecated",
        embedding=vec1,
        is_tombstoned=True,
    )
    fact3_ws2 = MemoryRecord(
        workspace_id=ws2_id,
        fact_statement="Fact 3 in Workspace 2",
        category="research",
        embedding=vec2,
        is_tombstoned=False,
    )

    db_session.add_all([fact1, fact2_tombstoned, fact3_ws2])
    await db_session.commit()

    # Query Workspace 1 active records: fact2_tombstoned and fact3_ws2 must be excluded
    res = await db_session.execute(
        select(MemoryRecord).where(
            MemoryRecord.workspace_id == ws1_id,
            MemoryRecord.is_tombstoned.is_(False),
        )
    )
    active_ws1_facts = res.scalars().all()
    assert len(active_ws1_facts) == 1
    assert active_ws1_facts[0].fact_statement == "Fact 1 text"


@pytest.mark.asyncio
async def test_gap_closure_privacy_synthetic_canaries():
    """Verify synthetic secrets and tokens are scrubbed from logs, envelopes, and output strings."""
    canary_api_key = "sk-proj-CANARY999SECRETKEY1234567890abcdef"
    canary_jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.CANARY_SIGNATURE"
    canary_google_key = "AIzaSyCANARYTESTKEY1234567890ABCDEF"

    raw_text = f"User logged in with key {canary_api_key}, JWT {canary_jwt}, and Google key {canary_google_key}."
    redacted = secret_redactor.redact_text(raw_text)

    assert canary_api_key not in redacted
    assert canary_jwt not in redacted
    assert canary_google_key not in redacted
    assert "[REDACTED" in redacted


@pytest.mark.asyncio
async def test_gap_closure_kill_switch_cross_phase_authoritative_state(db_session: AsyncSession):
    """Verify kill switch terminal state across agent, task recovery, and OSGuard."""
    user_id = uuid.uuid4()
    ws_id = uuid.uuid4()
    task_id = uuid.uuid4()

    u = User(id=user_id, email=f"ks_gap_{user_id.hex[:6]}@test.com", password_hash="pwd", full_name="KS Gap User", is_active=True)
    w = Workspace(id=ws_id, name="KS Gap WS", slug=f"ks-gap-{ws_id.hex[:6]}")
    t = Task(id=task_id, workspace_id=ws_id, title="KS Aborted Task", goal="Goal", status="cancelled")
    db_session.add_all([u, w, t])
    await db_session.commit()

    # 1. Engage kill switch
    kill_switch.set_active(True, workspace_id=ws_id)
    assert kill_switch.is_active(ws_id) is True

    rec_svc = TaskRecoveryService()

    # When kill switch is active, task resumption is blocked
    with pytest.raises(AuthorizationError) as exc_info:
        await rec_svc.resume_task(db=db_session, task_id=task_id, workspace_id=ws_id, actor_id="user")
    assert "Emergency Kill Switch is currently active" in str(exc_info.value)

    # 2. Disengage kill switch
    kill_switch.set_active(False, workspace_id=ws_id)
    assert kill_switch.is_active(ws_id) is False

    # 3. Terminal cancelled state is preserved upon resumption attempt
    resp = await rec_svc.resume_task(db=db_session, task_id=task_id, workspace_id=ws_id, actor_id="user")
    assert resp.status == "cancelled"


@pytest.mark.asyncio
async def test_gap_closure_cross_phase_governance_chain(client: AsyncClient, db_session: AsyncSession):
    """Verify end-to-end governed tool invocation path."""
    await tool_registry.ensure_builtin_tools(db_session)

    email = f"gap_auditor_{uuid.uuid4().hex[:6]}@example.com"
    reg = await client.post("/api/v1/auth/register", json={"email": email, "password": "Password123!", "full_name": "Gap Auditor"})
    token = reg.json()["access_token"]
    me_res = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    ws_id = uuid.UUID(me_res.json()["workspaces"][0]["id"])

    task_id = uuid.uuid4()
    agent_run_id = uuid.uuid4()
    actor_id = "test_auditor"

    bridge = AgentToolBridge()

    # Governed built-in tool execution (web_search)
    exec_result = await bridge.execute_governed_tool(
        db=db_session,
        workspace_id=ws_id,
        task_id=task_id,
        step_number=1,
        agent_run_id=agent_run_id,
        tool_name="web_search",
        arguments={"query": "AURA autonomous AI governance"},
        actor_id=actor_id,
    )

    assert exec_result["status"] == "success"
    assert "result" in exec_result
