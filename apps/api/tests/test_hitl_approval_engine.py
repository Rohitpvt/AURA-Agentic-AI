"""Unit and integration tests for AURA-204: Deterministic HITL Suspension & Resumption Engine."""

import json
import uuid
from datetime import datetime, timedelta, timezone
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.security import compute_sha256_hash, sign_approval_payload
from app.db.models.agent_run import AgentRun
from app.db.models.approval import ApprovalRequest
from app.db.models.task import Task, TaskStep
from app.db.models.tool import Tool, ToolPermission
from app.schemas.approval import ApprovalResolveRequest
from app.schemas.tool import ToolExecutionRequest
from app.services.approval_service import approval_service
from app.services.tool_registry import tool_registry


@pytest.mark.asyncio
async def test_hitl_high_risk_tool_suspension_flow(db_session: AsyncSession, client: AsyncClient):
    """Verify that requesting a high-risk tool creates ApprovalRequest and suspends Task."""
    # 1. Setup User & Workspace
    email = f"hitl_user_{uuid.uuid4().hex[:6]}@example.com"
    reg = await client.post("/api/v1/auth/register", json={"email": email, "password": "Password123!", "full_name": "HITL Tester"})
    token = reg.json()["access_token"]
    me_res = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    user_id = uuid.UUID(me_res.json()["id"])
    ws_id = uuid.UUID(me_res.json()["workspaces"][0]["id"])

    headers = {"Authorization": f"Bearer {token}"}

    # 2. Register high-risk tool in DB
    high_risk_tool = Tool(
        workspace_id=ws_id,
        name="deploy_production_service",
        display_name="Deploy Production Service",
        description="Deploys container image to production cluster",
        category="devops",
        risk_level="high",
        input_schema={"type": "object", "properties": {"cluster": {"type": "string"}}, "required": ["cluster"]},
        output_schema={"type": "object"},
        timeout_seconds=30,
        rate_limit_per_minute=10,
        requires_approval=True,
        is_active=True,
    )
    db_session.add(high_risk_tool)

    # Register handler in tool registry
    async def mock_deploy(cluster: str):
        return {"status": "deployed", "cluster": cluster}
    tool_registry.register_handler("deploy_production_service", mock_deploy)

    # 3. Create Task & TaskStep
    task = Task(
        workspace_id=ws_id,
        created_by=user_id,
        title="Production Deployment",
        goal="Deploy new release to production",
        status="running",
    )
    db_session.add(task)
    await db_session.flush()

    step = TaskStep(
        task_id=task.id,
        step_number=1,
        title="Deploy to prod",
        description="Execute deployment tool",
        dependencies=[],
        status="running",
    )
    db_session.add(step)

    agent_run = AgentRun(
        task_id=task.id,
        workspace_id=ws_id,
        agent_type="master_supervisor",
        model_name="qwen2.5:7b-instruct-q4_K_M",
        model_tier="general",
        status="running",
    )
    db_session.add(agent_run)
    await db_session.commit()

    # 4. Request Tool Execution (High Risk -> Suspended)
    approval_rec, signed_token = await approval_service.create_approval_request(
        db=db_session,
        workspace_id=ws_id,
        task_id=task.id,
        agent_run_id=agent_run.id,
        step_number=1,
        tool_name="deploy_production_service",
        tool_params={"cluster": "us-east-1"},
        risk_level="high",
        reason_requested="Production deployment requires approval",
    )

    # Verify Task & Step transitioned to waiting_approval
    await db_session.refresh(task)
    await db_session.refresh(step)
    assert task.status == "waiting_approval"
    assert step.status == "waiting_approval"
    assert approval_rec.status == "pending"

    # 5. List Pending Approvals via API
    list_resp = await client.get(f"/api/v1/approvals?workspace_id={ws_id}", headers=headers)
    assert list_resp.status_code == 200
    approvals_list = list_resp.json()
    assert len(approvals_list) >= 1
    target_approval = [a for a in approvals_list if a["id"] == str(approval_rec.id)][0]
    assert target_approval["tool_name"] == "deploy_production_service"

    # 6. Resolve Approval (Approve)
    resolve_resp = await client.post(
        f"/api/v1/approvals/{approval_rec.id}/resolve?workspace_id={ws_id}",
        headers=headers,
        json={
            "decision": "approve",
            "token": signed_token,
            "resolution_notes": "Deployment verified and approved by lead architect",
        },
    )
    assert resolve_resp.status_code == 200
    resolve_data = resolve_resp.json()
    assert resolve_data["status"] == "approved"
    assert resolve_data["resumed"] is True
    assert resolve_data["execution_result"]["status"] == "deployed"

    # 7. Verify Task Step is Completed in Database
    await db_session.refresh(step)
    assert step.status == "completed"
    assert step.tool_output["status"] == "deployed"


@pytest.mark.asyncio
async def test_hitl_tampered_token_rejection(db_session: AsyncSession, client: AsyncClient):
    """Verify that an altered parameter token is rejected."""
    ws_id = uuid.uuid4()
    task_id = uuid.uuid4()
    run_id = uuid.uuid4()

    approval_rec, signed_token = await approval_service.create_approval_request(
        db=db_session,
        workspace_id=ws_id,
        task_id=task_id,
        agent_run_id=run_id,
        step_number=1,
        tool_name="delete_database",
        tool_params={"target": "staging"},
        risk_level="critical",
    )

    # Attempt to resolve with tampered token
    tampered_token = signed_token[:-4] + "dead"
    with pytest.raises(Exception):
        await approval_service.resolve_approval(
            db=db_session,
            approval_id=approval_rec.id,
            workspace_id=ws_id,
            user_id=uuid.uuid4(),
            payload=ApprovalResolveRequest(decision="approve", token=tampered_token),
        )


@pytest.mark.asyncio
async def test_hitl_single_use_replay_protection(db_session: AsyncSession):
    """Verify that an approval token cannot be replayed once resolved."""
    ws_id = uuid.uuid4()
    task_id = uuid.uuid4()
    run_id = uuid.uuid4()

    # Register tool & mock handler
    db_session.add(Tool(
        workspace_id=ws_id,
        name="restart_worker",
        display_name="Restart Worker",
        description="Restart background worker",
        category="ops",
        risk_level="high",
        input_schema={"type": "object", "properties": {}},
        is_active=True,
    ))
    tool_registry.register_handler("restart_worker", lambda: {"restarted": True})

    approval_rec, signed_token = await approval_service.create_approval_request(
        db=db_session,
        workspace_id=ws_id,
        task_id=task_id,
        agent_run_id=run_id,
        step_number=1,
        tool_name="restart_worker",
        tool_params={},
        risk_level="high",
    )

    # First approval succeeds
    res1 = await approval_service.resolve_approval(
        db=db_session,
        approval_id=approval_rec.id,
        workspace_id=ws_id,
        user_id=uuid.uuid4(),
        payload=ApprovalResolveRequest(decision="approve", token=signed_token),
    )
    assert res1.status == "approved"

    # Second approval attempt on the same token must fail (replay protection)
    with pytest.raises(Exception) as exc_info:
        await approval_service.resolve_approval(
            db=db_session,
            approval_id=approval_rec.id,
            workspace_id=ws_id,
            user_id=uuid.uuid4(),
            payload=ApprovalResolveRequest(decision="approve", token=signed_token),
        )
    assert "already been resolved" in str(exc_info.value)

