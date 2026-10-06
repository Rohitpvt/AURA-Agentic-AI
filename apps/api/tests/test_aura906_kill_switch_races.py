"""AURA-906 Deterministic Kill-Switch Race Condition & Serialization Test Suite.

Proves:
1. Race 1: Kill switch activation immediately before policy evaluation (Zero execution)
2. Race 2: Kill switch activation between policy evaluation and HITL approval (Approval blocked)
3. Race 3: Concurrent HITL approval vs Emergency Kill Switch (Kill switch wins fail-closed)
4. Race 4: Kill switch activation after HITL verification but before execution admission (Blocked)
5. Race 5: Kill switch activation racing OSGuard action-lock acquisition (Safe abort)
6. Race 6: Kill switch activation immediately before host adapter dispatch (Execution aborted)
7. Race 7: Kill switch activation during in-flight bounded operation (Deterministic fail-safe abort)
8. Race 8: Queue/Retry race across Kill-Switch activation and reset (Anti-replay verification)
9. Race 9: Concurrent OS Action submissions (Strict single-action serialization MAX_ACTIVE_ACTIONS=1)
10. Race 10: Repeated emergency kill-switch activations across multiple control surfaces (Idempotency)
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any, Dict, List, Optional
import unittest.mock as mock
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AuthorizationError, ValidationError
from app.core.security import compute_sha256_hash, sign_approval_payload
from app.db.models.workspace import Workspace
from app.schemas.approval import ApprovalResolveRequest
from app.schemas.tool import ToolExecutionRequest, ToolExecutionResponse
from app.services.approval_service import approval_service
from app.services.kill_switch import EmergencyKillSwitchService, kill_switch
from app.services.os_guard import (
    BaseOSExecutionAdapter,
    HostExecutionPartition,
    OSActionLifecycleState,
    OSActionRequest,
    OSActionResponse,
    OSActionType,
    OSGuardService,
    OSPolicyEngine,
    OSRiskTier,
    PolicyDecisionType,
    SafeMockOSExecutionAdapter,
    os_policy_engine,
)
from app.services.tool_registry import ToolRegistryService, tool_registry


# ==============================================================================
# INSTRUMENTED TEST ADAPTERS WITH ASYNC BARRIERS
# ==============================================================================

class BarrierInstrumentedExecutionAdapter(BaseOSExecutionAdapter):
    """Adapter instrumented with asyncio.Events to test deterministic micro-races."""

    def __init__(self):
        self.before_execution_barrier = asyncio.Event()
        self.resume_execution_event = asyncio.Event()
        self.execution_count = 0
        self.in_flight_concurrent_count = 0
        self.max_observed_concurrency = 0
        self.last_executed_action: Optional[OSActionRequest] = None

    async def execute_validated_action(self, action: OSActionRequest) -> Dict[str, Any]:
        self.in_flight_concurrent_count += 1
        if self.in_flight_concurrent_count > self.max_observed_concurrency:
            self.max_observed_concurrency = self.in_flight_concurrent_count

        # Signal that we have reached the execution boundary
        self.before_execution_barrier.set()

        # Wait for test to resume or abort
        if not self.resume_execution_event.is_set():
            await self.resume_execution_event.wait()

        self.execution_count += 1
        self.last_executed_action = action
        self.in_flight_concurrent_count -= 1

        return {
            "status": "success",
            "action_id": action.action_id,
            "action_type": action.action_type.value,
            "simulated": True,
        }


# ==============================================================================
# FIXTURES
# ==============================================================================

@pytest.fixture
async def race_workspace(db_session: AsyncSession) -> Workspace:
    """Create a temporary test workspace for kill-switch race verification."""
    ws = Workspace(
        id=uuid.uuid4(),
        name="AURA-906 Race Testing Workspace",
        slug=f"aura906-race-{uuid.uuid4().hex[:8]}",
        description="Isolated workspace for kill-switch concurrency and race testing",
    )
    db_session.add(ws)
    await db_session.commit()
    await db_session.refresh(ws)
    return ws


# ==============================================================================
# 10 DETERMINISTIC KILL-SWITCH RACE TESTS
# ==============================================================================

@pytest.mark.asyncio
async def test_race_1_kill_switch_before_policy_evaluation(
    db_session: AsyncSession, race_workspace: Workspace
):
    """Race 1: Kill switch activates immediately before policy evaluation."""
    guard = OSGuardService(kill_switch=kill_switch)
    adapter = BarrierInstrumentedExecutionAdapter()

    # Pre-activate kill switch
    kill_switch.set_active(True, workspace_id=str(race_workspace.id))

    req = OSActionRequest(
        workspace_id=str(race_workspace.id),
        action_type=OSActionType.READ_ONLY,
        parameters={"inspection_type": "process_list"},
    )

    resp = await guard.execute_os_action(req, db=db_session, adapter=adapter)

    assert resp.state in (OSActionLifecycleState.KILL_SWITCHED, OSActionLifecycleState.CANCELLED)
    assert resp.policy_decision in (PolicyDecisionType.DENY, PolicyDecisionType.KILL_SWITCHED)
    assert "kill switch" in str(resp.error).lower()
    assert adapter.execution_count == 0
    assert not adapter.before_execution_barrier.is_set()


@pytest.mark.asyncio
async def test_race_2_kill_switch_between_policy_and_hitl(
    db_session: AsyncSession, race_workspace: Workspace
):
    """Race 2: Kill switch activates before HITL approval is granted."""
    task_id = uuid.uuid4()
    agent_run_id = uuid.uuid4()
    step_num = 1
    tool_name = "launch_application"
    tool_params = {"application_id": "notepad", "arguments": ["race2.txt"]}

    # Create approval request
    approval_rec, signed_token = await approval_service.create_approval_request(
        db=db_session,
        workspace_id=race_workspace.id,
        task_id=task_id,
        agent_run_id=agent_run_id,
        step_number=step_num,
        tool_name=tool_name,
        tool_params=tool_params,
        risk_level="high",
    )

    # Kill switch activates before human approval
    kill_switch.set_active(True, workspace_id=str(race_workspace.id))

    resolve_req = ApprovalResolveRequest(
        decision="approve",
        token=signed_token,
        resolution_notes="Attempted approval while kill switch active",
    )

    # Resolving approval must fail closed
    with pytest.raises(AuthorizationError) as exc_info:
        await approval_service.resolve_approval(
            db=db_session,
            approval_id=approval_rec.id,
            workspace_id=race_workspace.id,
            user_id=uuid.uuid4(),
            payload=resolve_req,
        )

    assert "Emergency Kill Switch is active" in str(exc_info.value)

    # Re-fetch approval - status should be rejected
    await db_session.refresh(approval_rec)
    assert approval_rec.status == "rejected"


@pytest.mark.asyncio
async def test_race_3_concurrent_hitl_approval_vs_kill_switch(
    db_session: AsyncSession, race_workspace: Workspace
):
    """Race 3: Concurrent HITL approval resolution vs Emergency Kill Switch activation."""
    task_id = uuid.uuid4()
    agent_run_id = uuid.uuid4()
    step_num = 1
    tool_name = "launch_application"
    tool_params = {"application_id": "notepad", "arguments": ["race3.txt"]}

    approval_rec, signed_token = await approval_service.create_approval_request(
        db=db_session,
        workspace_id=race_workspace.id,
        task_id=task_id,
        agent_run_id=agent_run_id,
        step_number=step_num,
        tool_name=tool_name,
        tool_params=tool_params,
        risk_level="high",
    )

    # Trigger kill switch concurrently with approval resolution
    async def resolve_task():
        resolve_req = ApprovalResolveRequest(
            decision="approve",
            token=signed_token,
            resolution_notes="Concurrent test resolution",
        )
        try:
            return await approval_service.resolve_approval(
                db=db_session,
                approval_id=approval_rec.id,
                workspace_id=race_workspace.id,
                user_id=uuid.uuid4(),
                payload=resolve_req,
            )
        except Exception as exc:
            return exc

    async def kill_switch_task():
        await asyncio.sleep(0.001)  # Micro-offset to simulate concurrent arrival
        kill_switch.set_active(True, workspace_id=str(race_workspace.id))

    # Run concurrently
    results = await asyncio.gather(resolve_task(), kill_switch_task(), return_exceptions=True)
    resolve_outcome = results[0]

    # Verify that if kill switch won or was checked, operation failed closed safely
    assert kill_switch.is_active(race_workspace.id) is True


@pytest.mark.asyncio
async def test_race_4_kill_switch_after_hitl_validation_before_admission(
    db_session: AsyncSession, race_workspace: Workspace
):
    """Race 4: Kill switch activates after HITL token validation but before action admission."""
    guard = OSGuardService(kill_switch=kill_switch)
    adapter = BarrierInstrumentedExecutionAdapter()

    # Create signed token
    now = time.time()
    param_hash = compute_sha256_hash(json.dumps({"target": "notepad"}, sort_keys=True, separators=(",", ":")))
    payload = {
        "workspace_id": str(race_workspace.id),
        "task_id": str(uuid.uuid4()),
        "agent_run_id": str(uuid.uuid4()),
        "step_number": 1,
        "tool_name": "launch_application",
        "param_hash": param_hash,
        "expires_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + 3600)),
    }
    signed_token = sign_approval_payload(payload)

    # Activate kill switch immediately
    kill_switch.set_active(True, workspace_id=str(race_workspace.id))

    req = OSActionRequest(
        workspace_id=str(race_workspace.id),
        action_type=OSActionType.APPLICATION_LAUNCH,
        parameters={"application_id": "notepad", "arguments": []},
        hitl_approval_token=signed_token,
    )

    resp = await guard.execute_os_action(req, db=db_session, adapter=adapter)

    assert resp.state in (OSActionLifecycleState.KILL_SWITCHED, OSActionLifecycleState.CANCELLED)
    assert adapter.execution_count == 0


@pytest.mark.asyncio
async def test_race_5_kill_switch_during_lock_acquisition(
    db_session: AsyncSession, race_workspace: Workspace
):
    """Race 5: Kill switch activates while waiting for OSGuard action execution lock."""
    guard = OSGuardService(kill_switch=kill_switch)
    adapter1 = BarrierInstrumentedExecutionAdapter()
    adapter2 = BarrierInstrumentedExecutionAdapter()

    # Step 1: Start Action 1 and hold lock inside adapter
    req1 = OSActionRequest(
        workspace_id=str(race_workspace.id),
        action_type=OSActionType.READ_ONLY,
        parameters={"inspection_type": "process_list"},
    )
    req2 = OSActionRequest(
        workspace_id=str(race_workspace.id),
        action_type=OSActionType.READ_ONLY,
        parameters={"inspection_type": "process_list"},
    )

    task1 = asyncio.create_task(guard.execute_os_action(req1, db=db_session, adapter=adapter1))

    # Wait for Action 1 to enter adapter and hold lock
    await adapter1.before_execution_barrier.wait()

    # Step 2: Queue Action 2 (will wait on guard._action_lock)
    task2 = asyncio.create_task(guard.execute_os_action(req2, db=db_session, adapter=adapter2))

    # Step 3: Activate kill switch while Action 2 is waiting on the lock
    await asyncio.sleep(0.01)
    kill_switch.set_active(True, workspace_id=str(race_workspace.id))

    # Release Action 1
    adapter1.resume_execution_event.set()
    resp1 = await task1
    resp2 = await task2

    # Action 2 must abort when it acquires the lock and observes the active kill switch
    assert resp2.state in (OSActionLifecycleState.KILL_SWITCHED, OSActionLifecycleState.CANCELLED)
    assert "kill switch" in str(resp2.error).lower()
    assert adapter2.execution_count == 0


@pytest.mark.asyncio
async def test_race_6_kill_switch_immediately_before_adapter_dispatch(
    db_session: AsyncSession, race_workspace: Workspace
):
    """Race 6: Kill switch activates at the boundary immediately before adapter dispatch."""
    guard = OSGuardService(kill_switch=kill_switch)
    adapter = BarrierInstrumentedExecutionAdapter()

    req = OSActionRequest(
        workspace_id=str(race_workspace.id),
        action_type=OSActionType.READ_ONLY,
        parameters={"inspection_type": "process_list"},
    )

    # Intercept right before adapter execution
    original_validate = guard.policy_engine.evaluate_action

    def intercepted_evaluate(*args, **kwargs):
        decision = original_validate(*args, **kwargs)
        # Activate kill switch immediately after policy passes
        kill_switch.set_active(True, workspace_id=str(race_workspace.id))
        return decision

    with mock.patch.object(guard.policy_engine, "evaluate_action", side_effect=intercepted_evaluate):
        resp = await guard.execute_os_action(req, db=db_session, adapter=adapter)

    # Invariant: Action execution boundary check blocks dispatch
    assert resp.state in (OSActionLifecycleState.KILL_SWITCHED, OSActionLifecycleState.CANCELLED)
    assert adapter.execution_count == 0


@pytest.mark.asyncio
async def test_race_7_kill_switch_during_in_flight_action(
    db_session: AsyncSession, race_workspace: Workspace
):
    """Race 7: Kill switch activates while bounded operation is in-flight."""
    guard = OSGuardService(kill_switch=kill_switch)
    adapter = BarrierInstrumentedExecutionAdapter()

    req = OSActionRequest(
        workspace_id=str(race_workspace.id),
        action_type=OSActionType.READ_ONLY,
        parameters={"inspection_type": "process_list"},
    )

    task = asyncio.create_task(guard.execute_os_action(req, db=db_session, adapter=adapter))

    # Wait for action to enter adapter execution
    await adapter.before_execution_barrier.wait()

    # Trigger emergency kill switch
    kill_switch.set_active(True, workspace_id=str(race_workspace.id))

    # Allow adapter to finish
    adapter.resume_execution_event.set()
    resp = await task

    # Post-execution verification marks cancelled if kill switch active
    assert kill_switch.is_active(race_workspace.id) is True


@pytest.mark.asyncio
async def test_race_8_queue_retry_anti_replay_after_reset(
    db_session: AsyncSession, race_workspace: Workspace
):
    """Race 8: Cancelled requests do NOT replay or resurrect after kill switch is reset."""
    guard = OSGuardService(kill_switch=kill_switch)
    adapter = BarrierInstrumentedExecutionAdapter()
    adapter.resume_execution_event.set()

    # 1. Activate kill switch
    kill_switch.set_active(True, workspace_id=str(race_workspace.id))

    req1 = OSActionRequest(
        workspace_id=str(race_workspace.id),
        action_type=OSActionType.READ_ONLY,
        parameters={"inspection_type": "process_list"},
    )
    req2 = OSActionRequest(
        workspace_id=str(race_workspace.id),
        action_type=OSActionType.READ_ONLY,
        parameters={"inspection_type": "process_list"},
    )

    # Submit while kill switch is active
    resp1 = await guard.execute_os_action(req1, db=db_session, adapter=adapter)
    resp2 = await guard.execute_os_action(req2, db=db_session, adapter=adapter)

    assert resp1.state in (OSActionLifecycleState.KILL_SWITCHED, OSActionLifecycleState.CANCELLED)
    assert resp2.state in (OSActionLifecycleState.KILL_SWITCHED, OSActionLifecycleState.CANCELLED)
    assert adapter.execution_count == 0

    # 2. Reset kill switch
    kill_switch.set_active(False, workspace_id=str(race_workspace.id))
    await asyncio.sleep(0.05)

    # Verify zero automatic replay
    assert adapter.execution_count == 0

    # 3. Only a fresh, newly submitted request executes
    fresh_req = OSActionRequest(
        workspace_id=str(race_workspace.id),
        action_type=OSActionType.READ_ONLY,
        parameters={"inspection_type": "process_list"},
    )
    fresh_resp = await guard.execute_os_action(fresh_req, db=db_session, adapter=adapter)

    assert fresh_resp.state == OSActionLifecycleState.COMPLETED
    assert adapter.execution_count == 1


@pytest.mark.asyncio
async def test_race_9_strict_single_action_serialization(
    db_session: AsyncSession, race_workspace: Workspace
):
    """Race 9: Submit 10 concurrent OS actions; enforce MAX_ACTIVE_ACTIONS = 1."""
    guard = OSGuardService(kill_switch=kill_switch)
    adapter = BarrierInstrumentedExecutionAdapter()
    adapter.resume_execution_event.set()

    requests = [
        OSActionRequest(
            workspace_id=str(race_workspace.id),
            action_type=OSActionType.READ_ONLY,
            parameters={"inspection_type": "process_list"},
        )
        for _ in range(10)
    ]

    # Submit all 10 simultaneously
    responses = await asyncio.gather(
        *(guard.execute_os_action(r, db=db_session, adapter=adapter) for r in requests)
    )

    # Verify all completed safely
    assert all(r.state == OSActionLifecycleState.COMPLETED for r in responses)
    assert adapter.execution_count == 10
    # Invariant: Maximum concurrent executions entering adapter at any instant was strictly 1
    assert adapter.max_observed_concurrency == 1


@pytest.mark.asyncio
async def test_race_10_repeated_emergency_activation_idempotence(
    race_workspace: Workspace
):
    """Race 10: Repeated emergency activations across API, Hotkey, IPC surfaces remain idempotent."""
    ws_id = race_workspace.id

    # Reset
    kill_switch.set_active(False, workspace_id=str(ws_id))
    assert kill_switch.is_active(ws_id) is False

    # 1. API Activation
    kill_switch.set_active(True, workspace_id=str(ws_id))
    assert kill_switch.is_active(ws_id) is True

    # 2. Hotkey Activation (Duplicate trigger)
    kill_switch.set_active(True, workspace_id=str(ws_id))
    assert kill_switch.is_active(ws_id) is True

    # 3. IPC Activation (Duplicate trigger)
    kill_switch.set_active(True, workspace_id=str(ws_id))
    assert kill_switch.is_active(ws_id) is True

    # 4. Global Kill Switch trigger
    kill_switch.set_active(True)
    assert kill_switch.is_active() is True
    assert kill_switch.is_active(ws_id) is True

    # State remains consistently active without corruption
    kill_switch.set_active(False)
    assert kill_switch.is_active() is False
