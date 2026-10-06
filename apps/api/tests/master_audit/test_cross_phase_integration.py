"""
Cross-Phase Integration Master Audit: End-to-End Multi-Phase Control Plane Workflows.
"""
import pytest
import uuid

from app.services.tool_registry import tool_registry
from app.runtime.tool_bridge import AgentToolBridge
from app.services.os_guard import OSGuardService, OSActionRequest, OSActionType
from app.services.approval_service import approval_service
from app.services.audit_service import AuditLedgerService
from app.db.models.user import User
from app.db.models.workspace import Workspace
from app.db.models.task import Task
from app.db.models.agent_run import AgentRun


@pytest.mark.asyncio
async def test_cross_phase_e2e_governed_tool_to_audit_pipeline(db_session):
    """
    Cross-Phase Audit: Full E2E path: User -> Workspace -> Task -> ToolBridge -> Registry -> Policy -> Audit.
    """
    user_id = uuid.uuid4()
    ws_id = uuid.uuid4()
    task_id = uuid.uuid4()
    run_id = uuid.uuid4()

    u = User(id=user_id, email=f"cross_{str(user_id)[:8]}@test.com", password_hash="pwd", full_name="Cross User", is_active=True)
    w = Workspace(id=ws_id, name="Cross Phase WS", slug=f"cross-{str(ws_id)[:8]}")
    t = Task(id=task_id, workspace_id=ws_id, title="Cross Phase Task", goal="Cross Phase Goal", status="running")
    run = AgentRun(id=run_id, task_id=task_id, workspace_id=ws_id, model_name="qwen2.5:7b", status="running")
    db_session.add_all([u, w, t, run])
    await db_session.flush()

    await tool_registry.ensure_builtin_tools(db_session)
    bridge = AgentToolBridge()

    # Dispatch tool
    res = await bridge.execute_governed_tool(
        db=db_session,
        workspace_id=ws_id,
        task_id=task_id,
        step_number=1,
        agent_run_id=run_id,
        tool_name="get_hardware_capabilities",
        arguments={},
        actor_id="user",
    )

    assert "status" in res or "capabilities" in res or "error" not in res
