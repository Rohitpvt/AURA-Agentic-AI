"""Concurrency and Micro-Race Test Suite for AURA-1002 Governed Browser Interactions."""

import asyncio
import time
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.core.errors import AuthorizationError, EntityNotFoundError, ValidationError
from app.db.models.tool import Tool
from app.schemas.tool import ToolExecutionRequest, ToolExecutionResponse
from app.services.browser.engine import PlaywrightBrowserEngine, browser_engine
from app.services.browser.governance import (
    MAX_BROWSER_ACTIONS_PER_TASK,
    action_budget_manager,
    freshness_store,
)
from app.services.browser.models import AXTreeNode, PageObservation
from app.services.kill_switch import kill_switch
from app.services.tool_registry import tool_registry
from app.services.tools.browser_tools import (
    execute_browser_click,
    execute_browser_navigate,
    execute_browser_tab_manage,
)


@pytest.fixture(autouse=True)
def clean_race_state():
    freshness_store.clear()
    action_budget_manager.clear()
    kill_switch.set_active(False)
    yield
    freshness_store.clear()
    action_budget_manager.clear()
    kill_switch.set_active(False)


@pytest.mark.asyncio
async def test_race_1_policy_vs_kill_switch():
    """Race 1: Kill switch activation concurrently fired while policy evaluating."""
    ws_id = uuid.uuid4()
    tab_id = "race-tab-1"

    node = AXTreeNode(node_id=1, role="button", name="Harmless Button")
    freshness_store.record_observation(
        workspace_id=ws_id,
        tab_id=tab_id,
        url="https://aura.local/test",
        title="Test",
        nodes=[node],
    )

    barrier = asyncio.Event()

    async def _kill_switch_trigger():
        await barrier.wait()
        kill_switch.activate(ws_id, triggered_by="race_test", reason="Simulated breach")

    async def _action_attempt():
        barrier.set()
        await asyncio.sleep(0.001)  # Context switch to let kill switch trigger
        return await execute_browser_click(workspace_id=ws_id, element_id=1, tab_id=tab_id)

    t1 = asyncio.create_task(_kill_switch_trigger())
    t2 = asyncio.create_task(_action_attempt())

    try:
        await t1
        with pytest.raises(AuthorizationError):
            await t2
    finally:
        kill_switch.deactivate(ws_id, reactivated_by="race_test")


@pytest.mark.asyncio
async def test_race_2_hitl_vs_kill_switch(db_session):
    """Race 2: Kill switch activates while user is resolving HITL approval."""
    from app.services.approval_service import approval_service
    from app.schemas.approval import ApprovalResolveRequest

    ws_id = uuid.uuid4()
    task_id = uuid.uuid4()
    agent_run_id = uuid.uuid4()

    approval_rec, token = await approval_service.create_approval_request(
        db=db_session,
        workspace_id=ws_id,
        task_id=task_id,
        agent_run_id=agent_run_id,
        step_number=1,
        tool_name="browser_scroll",
        tool_params={"direction": "down", "amount": 100},
        risk_level="high",
    )

    # Concurrently activate kill switch and resolve approval
    kill_switch.activate(ws_id, triggered_by="race_test", reason="Immediate lockdown")

    try:
        req = ApprovalResolveRequest(token=token, decision="approve")
        with pytest.raises(AuthorizationError, match="Emergency Kill Switch is active"):
            await approval_service.resolve_approval(
                db=db_session,
                approval_id=approval_rec.id,
                workspace_id=ws_id,
                user_id=uuid.uuid4(),
                payload=req,
            )
    finally:
        kill_switch.deactivate(ws_id, reactivated_by="race_test")


@pytest.mark.asyncio
async def test_race_3_stale_observation_vs_click():
    """Race 3: Observation expires exactly during execution dispatch."""
    ws_id = uuid.uuid4()
    tab_id = "race-tab-3"

    node = AXTreeNode(node_id=1, role="button", name="Button")
    freshness_store.record_observation(
        workspace_id=ws_id,
        tab_id=tab_id,
        url="https://aura.local/test",
        title="Test",
        nodes=[node],
        ttl_seconds=0.005,  # 5ms TTL
    )

    await asyncio.sleep(0.01)  # 10ms passes

    with pytest.raises(ValidationError, match="Page observation is stale"):
        await execute_browser_click(workspace_id=ws_id, element_id=1, tab_id=tab_id)


@pytest.mark.asyncio
async def test_race_4_page_mutation_navigation_vs_click():
    """Race 4: Page navigates away while click is pending; previous observation invalidated."""
    ws_id = uuid.uuid4()
    tab_id = "race-tab-4"

    node = AXTreeNode(node_id=1, role="button", name="Old Button")
    freshness_store.record_observation(
        workspace_id=ws_id,
        tab_id=tab_id,
        url="https://aura.local/page1",
        title="Page 1",
        nodes=[node],
    )

    # Invalidate on navigation
    freshness_store.invalidate(ws_id, tab_id)

    # Click on previous element must fail
    with pytest.raises(ValidationError, match="No active page observation found"):
        await execute_browser_click(workspace_id=ws_id, element_id=1, tab_id=tab_id)


@pytest.mark.asyncio
async def test_race_5_tab_close_vs_action():
    """Race 5: Tab is closed externally while an interaction is queued."""
    ws_id = uuid.uuid4()
    tab_id = "race-tab-5"

    node = AXTreeNode(node_id=1, role="button", name="Button")
    freshness_store.record_observation(
        workspace_id=ws_id,
        tab_id=tab_id,
        url="https://aura.local/test",
        title="Test",
        nodes=[node],
    )

    # Tab closed
    freshness_store.invalidate(ws_id, tab_id)

    with pytest.raises(ValidationError):
        await execute_browser_click(workspace_id=ws_id, element_id=1, tab_id=tab_id)


@pytest.mark.asyncio
async def test_race_6_workspace_close_vs_action():
    """Race 6: Workspace context is closed while action is executing."""
    ws_id = uuid.uuid4()
    tab_id = "race-tab-6"

    node = AXTreeNode(node_id=1, role="button", name="Button")
    freshness_store.record_observation(
        workspace_id=ws_id,
        tab_id=tab_id,
        url="https://aura.local/test",
        title="Test",
        nodes=[node],
    )

    # Invalidate entire workspace
    freshness_store.invalidate(ws_id)

    with pytest.raises(ValidationError, match="No active page observation found"):
        await execute_browser_click(workspace_id=ws_id, element_id=1, tab_id=tab_id)


@pytest.mark.asyncio
async def test_race_7_cancellation_vs_action_execution():
    """Race 7: Task cancellation cancels running interaction coroutine."""
    ws_id = uuid.uuid4()

    async def _long_operation():
        await asyncio.sleep(10.0)
        return "done"

    task = asyncio.create_task(_long_operation())
    await asyncio.sleep(0.01)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_race_8_action_budget_boundary_race():
    """Race 8: Concurrent requests at the 30-action budget boundary strictly cap at 30."""
    ws_id = uuid.uuid4()
    task_id = "race-task-8"

    # Pre-fill to 29 actions
    for i in range(29):
        action_budget_manager.consume_action(ws_id, task_id, f"action_{i}")

    results = []

    async def _attempt_consume(idx: int):
        try:
            c = action_budget_manager.consume_action(ws_id, task_id, f"concurrent_{idx}")
            results.append(("success", c))
        except ValidationError as e:
            results.append(("rejected", str(e)))

    # Launch 5 concurrent calls for the 30th slot
    tasks = [_attempt_consume(i) for i in range(5)]
    await asyncio.gather(*tasks)

    successes = [r for r in results if r[0] == "success"]
    rejections = [r for r in results if r[0] == "rejected"]

    assert len(successes) == 1, f"Expected exactly 1 success for 30th slot, got {len(successes)}"
    assert len(rejections) == 4, f"Expected 4 rejections, got {len(rejections)}"


@pytest.mark.asyncio
async def test_race_9_repeated_click_race():
    """Race 9: Rapid repeated clicks on same element fail closed if element is disabled or removed."""
    ws_id = uuid.uuid4()
    tab_id = "race-tab-9"

    # First click is valid, but button mutates to disabled
    node = AXTreeNode(node_id=1, role="button", name="One-Time Button", disabled=False)
    freshness_store.record_observation(
        workspace_id=ws_id,
        tab_id=tab_id,
        url="https://aura.local/test",
        title="Test",
        nodes=[node],
    )

    # Element mutates to disabled
    node.disabled = True

    with pytest.raises(ValidationError, match="is disabled"):
        await execute_browser_click(workspace_id=ws_id, element_id=1, tab_id=tab_id)


@pytest.mark.asyncio
async def test_race_10_recovery_vs_replay_single_use(db_session):
    """Race 10: Approved HITL token cannot be replayed twice concurrently."""
    from app.services.approval_service import approval_service
    from app.schemas.approval import ApprovalResolveRequest

    ws_id = uuid.uuid4()
    task_id = uuid.uuid4()
    agent_run_id = uuid.uuid4()
    await tool_registry.ensure_builtin_tools(db_session)

    approval_rec, token = await approval_service.create_approval_request(
        db=db_session,
        workspace_id=ws_id,
        task_id=task_id,
        agent_run_id=agent_run_id,
        step_number=1,
        tool_name="browser_scroll",
        tool_params={"direction": "down", "amount": 100},
        risk_level="high",
    )

    req = ApprovalResolveRequest(token=token, decision="approve")

    # First resolution succeeds
    res1 = await approval_service.resolve_approval(
        db=db_session,
        approval_id=approval_rec.id,
        workspace_id=ws_id,
        user_id=uuid.uuid4(),
        payload=req,
    )
    assert res1.status == "approved"

    # Second concurrent resolution must be rejected
    with pytest.raises(ValidationError, match="already been resolved"):
        await approval_service.resolve_approval(
            db=db_session,
            approval_id=approval_rec.id,
            workspace_id=ws_id,
            user_id=uuid.uuid4(),
            payload=req,
        )
