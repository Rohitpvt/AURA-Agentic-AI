"""
Cross-Phase Failure Injection Master Audit: Dependency Fault Injection and Fail-Closed Validation.
"""
import pytest
from app.services.os_guard import (
    OSGuardService,
    OSActionRequest,
    OSActionType,
    OSActionLifecycleState,
)
from app.services.kill_switch import kill_switch


@pytest.mark.asyncio
async def test_failure_injection_kill_switch_active_halts_all_actions():
    """
    Failure Injection: Simulate active emergency kill switch across multiple subsystems.
    """
    guard = OSGuardService()
    req = OSActionRequest(
        action_type=OSActionType.READ_ONLY,
        parameters={},
        workspace_id="ws_inject",
        user_id="user_inject",
    )

    kill_switch.set_active(True)
    try:
        resp = await guard.execute_os_action(req)
        assert resp.state == OSActionLifecycleState.KILL_SWITCHED
    finally:
        kill_switch.set_active(False)
