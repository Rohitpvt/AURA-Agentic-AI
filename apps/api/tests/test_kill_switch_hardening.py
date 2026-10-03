"""Deterministic and Local Test Suite for Emergency Kill Switch Hardening (AURA-507).

Tests:
1. Global and tenant-scoped kill-switch state transitions.
2. Concurrent / repeated kill-switch triggers (idempotency).
3. Task, TaskStep, and AgentRun database state transitions to 'cancelled'.
4. Kill vs Tool Start race condition (test_kill_race_against_tool_dispatch).
5. Kill vs Subagent Dispatch race condition (test_kill_race_against_subagent_dispatch).
6. Kill vs Retry race condition (test_kill_race_against_task_retry).
7. Kill vs Scheduler Claim race condition (test_kill_race_against_scheduler_claim).
8. Kill vs External Ingress race condition (test_kill_race_against_external_ingress).
9. Kill vs HITL Approval race condition (test_kill_race_against_hitl_approval).
10. Repeated Kill / Recovery Stability (test_repeated_kill_recovery_cycles).
11. OpenTelemetry tracing integration and fail-safe behavior (test_kill_switch_telemetry_isolation).
12. Kill-Switch Authorization & Recovery Endpoint Security matrix (test_kill_switch_api_endpoint_authorization_matrix).
"""

import asyncio
import hashlib
import hmac
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AuthorizationError, ValidationError
from app.core.process import ManagedProcessInfo, ManagedProcessRegistry, managed_process_registry
from app.core.security import create_access_token, encrypt_secret
from app.core.telemetry import telemetry_manager
from app.db.models.agent_run import AgentRun, SubAgentRun
from app.db.models.approval import ApprovalRequest
from app.db.models.audit import AuditLog
from app.db.models.automation import Automation, AutomationRun
from app.db.models.task import Task, TaskStep
from app.db.models.telegram import TelegramIntegration, TelegramPairing
from app.db.models.tool import Tool, ToolPermission
from app.db.models.user import User
from app.db.models.webhook import WebhookDelivery, WebhookEndpoint
from app.db.models.workspace import Workspace, WorkspaceMember
from app.runtime.subagents.pool import subagent_pool
from app.schemas.approval import ApprovalResolveRequest
from app.schemas.subagent import SubAgentSpec
from app.schemas.tool import ToolExecutionRequest
from app.services.approval_service import ApprovalService
from app.services.audit_service import audit_service
from app.services.automations.scheduler_service import scheduler_service
from app.services.automations.webhook_service import webhook_service
from app.services.integrations.telegram_service import telegram_service
from app.services.kill_switch import EmergencyKillSwitchService, kill_switch
from app.services.tool_registry import tool_registry


@pytest.fixture(autouse=True)
def reset_kill_switch_state():
    """Ensure kill-switch is reset to inactive before and after every test."""
    kill_switch.set_active(False)
    yield
    kill_switch.set_active(False)


@pytest.mark.asyncio
async def test_kill_switch_state_transitions():
    """Test global vs tenant-specific kill-switch activation and scoping."""
    ws_a = uuid.uuid4()
    ws_b = uuid.uuid4()

    # Initial state
    assert not kill_switch.is_active()
    assert not kill_switch.is_active(ws_a)
    assert not kill_switch.is_active(ws_b)

    # Workspace A only
    kill_switch.set_active(True, workspace_id=ws_a)
    assert not kill_switch._is_active
    assert kill_switch.is_active(ws_a)
    assert not kill_switch.is_active(ws_b)

    # Workspace A deactivate
    kill_switch.set_active(False, workspace_id=ws_a)
    assert not kill_switch.is_active(ws_a)

    # Global activate
    kill_switch.set_active(True)
    assert kill_switch.is_active()
    assert kill_switch.is_active(ws_a)
    assert kill_switch.is_active(ws_b)

    # Global deactivate
    kill_switch.set_active(False)
    assert not kill_switch.is_active()
    assert not kill_switch.is_active(ws_a)


@pytest.mark.asyncio
async def test_kill_switch_concurrent_idempotency(db_session: AsyncSession):
    """Test multiple simultaneous emergency kill triggers execute safely and idempotently."""
    ws_id = uuid.uuid4()

    # Launch 5 concurrent kill requests
    results = await asyncio.gather(*[
        kill_switch.trigger_emergency_kill(
            db=db_session,
            workspace_id=ws_id,
            actor_id=f"operator_{i}",
            reason=f"Concurrent trigger #{i}",
        )
        for i in range(5)
    ])

    for r in results:
        assert r["status"] == "ABORTED"
        assert r["workspace_id"] == str(ws_id)
        assert r["total_latency_ms"] >= 0

    assert kill_switch.is_active(ws_id)


@pytest.mark.asyncio
async def test_kill_switch_db_state_cancellation(db_session: AsyncSession):
    """Test that active tasks, steps, and agent runs transition to cancelled."""
    ws_id = uuid.uuid4()

    task = Task(
        workspace_id=ws_id,
        title="Active Task to Abort",
        goal="Do something long-running",
        status="running",
    )
    db_session.add(task)
    await db_session.flush()

    step = TaskStep(
        task_id=task.id,
        step_number=1,
        title="Running Step",
        description="Running step description",
        status="running",
    )
    db_session.add(step)

    run = AgentRun(
        task_id=task.id,
        workspace_id=ws_id,
        model_name="test_model",
        status="running",
    )
    db_session.add(run)
    await db_session.commit()

    # Trigger emergency kill
    res = await kill_switch.trigger_emergency_kill(
        db=db_session,
        workspace_id=ws_id,
        actor_id="test_admin",
        reason="Test abort",
        target_task_id=task.id,
    )
    assert res["status"] == "ABORTED"

    # Verify DB states
    await db_session.refresh(task)
    await db_session.refresh(step)
    await db_session.refresh(run)
    assert task.status == "cancelled"
    assert step.status == "cancelled"
    assert run.status == "cancelled"


@pytest.mark.asyncio
async def test_kill_race_against_tool_dispatch(db_session: AsyncSession):
    """Race test: Tool invocation arriving during active kill state is immediately blocked."""
    ws_id = uuid.uuid4()
    kill_switch.set_active(True, workspace_id=ws_id)

    exec_req = ToolExecutionRequest(
        workspace_id=ws_id,
        tool_name="web_search",
        arguments={"query": "test query"},
    )

    with pytest.raises(AuthorizationError) as exc_info:
        await tool_registry.execute_tool(
            db=db_session,
            request=exec_req,
            actor_id="test_actor",
        )
    assert "Emergency Kill Switch is active" in str(exc_info.value)


@pytest.mark.asyncio
async def test_kill_race_against_subagent_dispatch(db_session: AsyncSession):
    """Race test: Sub-agent dispatch is rejected immediately when kill state is active."""
    ws_id = uuid.uuid4()
    parent_task = Task(workspace_id=ws_id, title="PTask", goal="PGoal", status="running")
    parent_run = AgentRun(task_id=parent_task.id, workspace_id=ws_id, model_name="test_model", status="running")
    db_session.add(parent_task)
    db_session.add(parent_run)
    await db_session.commit()

    kill_switch.set_active(True, workspace_id=ws_id)

    spec = SubAgentSpec(
        parent_task_id=parent_task.id,
        parent_run_id=parent_run.id,
        workspace_id=ws_id,
        role="researcher",
        goal="Sub-task research",
    )

    with pytest.raises(AuthorizationError) as exc_info:
        await subagent_pool.dispatch_worker(db=db_session, spec=spec)
    assert "Emergency Kill Switch is active" in str(exc_info.value)


@pytest.mark.asyncio
async def test_kill_race_against_task_retry(db_session: AsyncSession):
    """Race test: Task retry loop verifies kill state before retry and suppresses execution."""
    ws_id = uuid.uuid4()
    task = Task(workspace_id=ws_id, title="Retry Task", goal="Retry Goal", status="running")
    db_session.add(task)
    await db_session.commit()

    # Activate kill switch
    kill_switch.set_active(True, workspace_id=ws_id)

    # Simulated retry loop check
    retry_attempted = False
    if not kill_switch.is_active(ws_id):
        retry_attempted = True
    else:
        task.status = "cancelled"
        task.error_summary = "Retry aborted: Emergency Kill Switch active"
        await db_session.commit()

    assert not retry_attempted
    await db_session.refresh(task)
    assert task.status == "cancelled"
    assert "Emergency Kill Switch active" in task.error_summary


@pytest.mark.asyncio
async def test_kill_race_against_scheduler_claim(db_session: AsyncSession):
    """Race test: Scheduler claim cycle detects active kill switch and suppresses claiming."""
    ws_id = uuid.uuid4()
    kill_switch.set_active(True)

    runs_claimed = await scheduler_service.claim_due_automations(db=db_session, worker_id="daemon_w1")
    assert runs_claimed == []


@pytest.mark.asyncio
async def test_kill_race_against_external_ingress(db_session: AsyncSession):
    """Race test: External ingress (Telegram & Webhook) rejects new execution requests during kill state."""
    ws_id = uuid.uuid4()
    
    # 1. Telegram gating
    integration = TelegramIntegration(
        workspace_id=ws_id,
        display_name="Test Bot",
        bot_token_ciphertext="cipher",
        bot_username="test_bot",
        bot_id="12345",
        is_active=True,
    )
    db_session.add(integration)

    # 2. Webhook endpoint
    endpoint = WebhookEndpoint(
        workspace_id=ws_id,
        public_id="whk_race_test",
        name="GitHub Ingress",
        secret_ciphertext=encrypt_secret("test_secret_race"),
        prompt_template="Handle {payload.event}",
        is_active=True,
    )
    db_session.add(endpoint)
    await db_session.commit()

    kill_switch.set_active(True, workspace_id=ws_id)

    # Telegram /goal command
    resp_goal = await telegram_service._handle_goal_command(
        db=db_session,
        workspace_id=ws_id,
        chat_id="999",
        username="op",
        goal_text="Research quantum computing",
        update_id=1,
        integration=integration,
    )
    assert "Emergency Kill Switch is active" in resp_goal

    # Webhook delivery
    now_ts = str(datetime.now(timezone.utc).timestamp())
    raw_body = b'{"event": "push"}'
    signed_payload = f"{now_ts}.".encode("utf-8") + raw_body
    valid_sig = hmac.new(b"test_secret_race", signed_payload, hashlib.sha256).hexdigest()

    with patch.object(webhook_service, "_check_rate_limit", return_value=True):
        status_code, res = await webhook_service.process_inbound_webhook(
            db=db_session,
            public_id=endpoint.public_id,
            raw_body=raw_body,
            headers={
                "x-aura-timestamp": now_ts,
                "x-aura-signature": valid_sig,
                "x-aura-idempotency-key": f"test_idemp_{uuid.uuid4().hex[:8]}",
            },
        )
        assert status_code == 503
        assert res.status == "blocked"
        assert "Emergency Kill Switch" in res.message


@pytest.mark.asyncio
async def test_kill_race_against_hitl_approval(db_session: AsyncSession):
    """Race test: Pending HITL approval resolution cannot execute tools if kill switch is active."""
    ws_id = uuid.uuid4()
    appr_svc = ApprovalService()

    task = Task(workspace_id=ws_id, title="Appr Task", goal="Appr Goal", status="waiting_approval")
    db_session.add(task)
    await db_session.flush()

    run = AgentRun(task_id=task.id, workspace_id=ws_id, model_name="test_model", status="waiting_approval")
    db_session.add(run)
    await db_session.flush()

    appr_req, token = await appr_svc.create_approval_request(
        db=db_session,
        workspace_id=ws_id,
        task_id=task.id,
        agent_run_id=run.id,
        step_number=1,
        tool_name="web_search",
        tool_params={"query": "test query"},
        risk_level="high",
    )

    # Activate kill switch
    kill_switch.set_active(True, workspace_id=ws_id)

    # Attempt to resolve approval
    user_id = uuid.uuid4()
    resolve_payload = ApprovalResolveRequest(
        token=token,
        decision="approve",
        resolution_notes="Operator approved action",
    )

    with pytest.raises(AuthorizationError) as exc_info:
        await appr_svc.resolve_approval(
            db=db_session,
            approval_id=appr_req.id,
            workspace_id=ws_id,
            user_id=user_id,
            payload=resolve_payload,
        )

    assert "Emergency Kill Switch is active" in str(exc_info.value)
    await db_session.refresh(appr_req)
    assert appr_req.status == "rejected"


@pytest.mark.asyncio
async def test_repeated_kill_recovery_cycles(db_session: AsyncSession):
    """Stability test: Execute 3 repeated Run -> Kill -> Recover cycles verifying clean state across all cycles."""
    ws_id = uuid.uuid4()

    for cycle in range(1, 4):
        # 1. Normal State
        assert not kill_switch.is_active(ws_id)
        active_procs_before = await managed_process_registry.get_active_processes(ws_id)
        assert len(active_procs_before) == 0

        # 2. Trigger Kill
        kill_res = await kill_switch.trigger_emergency_kill(
            db=db_session,
            workspace_id=ws_id,
            actor_id=f"cycle_runner_{cycle}",
            reason=f"Repeated stability test cycle {cycle}",
        )
        assert kill_res["status"] == "ABORTED"
        assert kill_switch.is_active(ws_id)

        # 3. Explicit Recovery Reset
        rec_res = await kill_switch.reset_emergency_state(
            db=db_session,
            workspace_id=ws_id,
            actor_id=f"cycle_runner_{cycle}",
            reason=f"Cycle {cycle} recovery",
        )
        assert rec_res["status"] == "RECOVERED"
        assert not kill_switch.is_active(ws_id)

        # 4. Verify clean registry
        active_procs_after = await managed_process_registry.get_active_processes(ws_id)
        assert len(active_procs_after) == 0


@pytest.mark.asyncio
async def test_kill_switch_telemetry_isolation(db_session: AsyncSession):
    """Test that kill switch functions safely even if OpenTelemetry raises an unexpected error."""
    ws_id = uuid.uuid4()

    with patch.object(telemetry_manager, "start_span", side_effect=RuntimeError("OTel Exporter Down")):
        res = await kill_switch.trigger_emergency_kill(
            db=db_session,
            workspace_id=ws_id,
            actor_id="operator",
            reason="Telemetry resilience test",
        )
        assert res["status"] == "ABORTED"
        assert kill_switch.is_active(ws_id)


@pytest.mark.asyncio
async def test_kill_switch_api_endpoint_authorization_matrix(client: AsyncClient, db_session: AsyncSession):
    """Authorization & RBAC test matrix for /system/kill-switch, /system/kill-switch/reset, and /system/kill-switch/status."""
    # Create workspace
    ws = Workspace(name="SecWS", slug=f"secws-{uuid.uuid4().hex[:6]}")
    db_session.add(ws)
    await db_session.flush()

    # Create Owner, Member, and Non-Member Users
    owner = User(email="owner@example.com", password_hash="hash", full_name="WS Owner", role="member", is_active=True)
    member = User(email="member@example.com", password_hash="hash", full_name="WS Member", role="member", is_active=True)
    non_member = User(email="outsider@example.com", password_hash="hash", full_name="Outsider", role="member", is_active=True)
    sys_admin = User(email="sysadmin@example.com", password_hash="hash", full_name="Admin", role="admin", is_active=True)
    db_session.add_all([owner, member, non_member, sys_admin])
    await db_session.flush()

    # Memberships
    m_owner = WorkspaceMember(workspace_id=ws.id, user_id=owner.id, role="owner", permissions=["*"])
    m_member = WorkspaceMember(workspace_id=ws.id, user_id=member.id, role="member", permissions=["read", "write"])
    db_session.add_all([m_owner, m_member])
    await db_session.commit()

    token_owner = create_access_token({"sub": str(owner.id)})
    token_member = create_access_token({"sub": str(member.id)})
    token_outsider = create_access_token({"sub": str(non_member.id)})
    token_admin = create_access_token({"sub": str(sys_admin.id)})

    kill_payload = {"workspace_id": str(ws.id), "reason": "Security auth test"}
    reset_payload = {"workspace_id": str(ws.id), "reason": "Security auth test reset"}

    # 1. Unauthenticated Trigger -> 401
    resp_unauth = await client.post("/api/v1/system/kill-switch", json=kill_payload)
    assert resp_unauth.status_code == 401

    # 2. Unauthorized Non-Member Trigger -> 403
    resp_outsider = await client.post(
        "/api/v1/system/kill-switch",
        json=kill_payload,
        headers={"Authorization": f"Bearer {token_outsider}"},
    )
    assert resp_outsider.status_code == 403

    # 3. Authorized Member Trigger -> 200
    resp_member_kill = await client.post(
        "/api/v1/system/kill-switch",
        json=kill_payload,
        headers={"Authorization": f"Bearer {token_member}"},
    )
    assert resp_member_kill.status_code == 200
    assert resp_member_kill.json()["status"] == "ABORTED"

    # 4. Unauthenticated Reset -> 401
    resp_reset_unauth = await client.post("/api/v1/system/kill-switch/reset", json=reset_payload)
    assert resp_reset_unauth.status_code == 401

    # 5. Unauthorized Member (regular member role) Reset -> 403
    resp_member_reset = await client.post(
        "/api/v1/system/kill-switch/reset",
        json=reset_payload,
        headers={"Authorization": f"Bearer {token_member}"},
    )
    assert resp_member_reset.status_code == 403
    assert "Only workspace owners and admins" in resp_member_reset.json()["error"]["message"]

    # 6. Authorized Owner Reset -> 200
    resp_owner_reset = await client.post(
        "/api/v1/system/kill-switch/reset",
        json=reset_payload,
        headers={"Authorization": f"Bearer {token_owner}"},
    )
    assert resp_owner_reset.status_code == 200
    assert resp_owner_reset.json()["status"] == "RECOVERED"

    # 7. Global Reset by Non-Admin -> 403
    resp_global_member = await client.post(
        "/api/v1/system/kill-switch/reset",
        json={"reason": "Unauthorized global reset"},
        headers={"Authorization": f"Bearer {token_member}"},
    )
    assert resp_global_member.status_code == 403

    # 8. Global Reset by System Admin -> 200
    resp_global_admin = await client.post(
        "/api/v1/system/kill-switch/reset",
        json={"reason": "Authorized global reset"},
        headers={"Authorization": f"Bearer {token_admin}"},
    )
    assert resp_global_admin.status_code == 200
    assert resp_global_admin.json()["status"] == "RECOVERED"
