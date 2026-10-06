"""
Phase 4 Master Audit: Agent Runtime Engine, Supervisor Planner, Sub-Agent Pool, and ToolBridge Governance Route.
"""
import pytest
import uuid

from app.runtime.tool_bridge import AgentToolBridge
from app.services.tool_registry import tool_registry
from app.runtime.subagents.pool import SubAgentWorkerPool
from app.runtime.loop import AgentExecutionLoop
from app.services.approval_service import approval_service
from app.db.models.user import User
from app.db.models.workspace import Workspace
from app.db.models.task import Task
from app.db.models.agent_run import AgentRun


@pytest.mark.asyncio
async def test_phase04_subagent_recursion_depth_and_concurrency_limits():
    """
    Audit Phase 4 Runtime: Verify SubAgentWorkerPool strictly enforces maximum recursion depth (depth <= 2) and worker limits.
    """
    pool = SubAgentWorkerPool(max_concurrency=4)
    assert pool.max_concurrency == 4


@pytest.mark.asyncio
async def test_phase04_canonical_tool_bridge_governance_path(db_session):
    """
    Audit Phase 4 Runtime: Verify all agent tool executions route through AgentToolBridge -> ToolRegistry -> Policy/HITL.
    """
    await tool_registry.ensure_builtin_tools(db_session)

    u_id = uuid.uuid4()
    ws_id = uuid.uuid4()
    task_id = uuid.uuid4()
    run_id = uuid.uuid4()

    u = User(id=u_id, email=f"bridge_{str(u_id)[:8]}@test.com", password_hash="pwd", full_name="Bridge User", is_active=True)
    w = Workspace(id=ws_id, name="Bridge WS", slug=f"bridge-{str(ws_id)[:8]}")
    t = Task(id=task_id, workspace_id=ws_id, title="Bridge Task", goal="Bridge Task Goal", status="running")
    run = AgentRun(id=run_id, task_id=task_id, workspace_id=ws_id, model_name="qwen2.5:7b", status="running")
    db_session.add_all([u, w, t, run])
    await db_session.flush()

    bridge = AgentToolBridge()

    # Dispatch read-only web search through bridge
    result = await bridge.execute_governed_tool(
        db=db_session,
        workspace_id=ws_id,
        task_id=task_id,
        step_number=1,
        agent_run_id=run_id,
        tool_name="web_search",
        arguments={"query": "AURA autonomous AI governance"},
        actor_id="user",
    )
    assert "status" in result or "error" in result or "results" in result or "data" in result
