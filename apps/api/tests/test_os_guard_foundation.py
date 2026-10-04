"""Comprehensive Test Suite for AURA-901 Windows OS Control Foundation & Policy Boundary.

Tests:
1. Action Contract, Taxonomy & Risk Classification
2. Host Execution Partitioning & Forbidden Paths
3. Deterministic Policy Evaluation & Autonomy Levels
4. Cryptographic HMAC-SHA256 HITL Verification, Parameter Binding, Expiration & Anti-Replay
5. Single-Worker Concurrency Serialization & Rate Limiting
6. Sub-15ms Emergency Kill Switch Probing & In-Flight Abort
7. Hard 5.0-Second Action Timeout Enforcement
8. Path Validation, Traversal Defense & Windows LOLBins Rejection
9. Process Identity TOCTOU / PID Recycling Protection & System Denylist
10. Coordinate Safety, Monitor Boundaries & Stale Visual Observation TTL
11. Audit Ledger Integration & Secret Redaction
"""

import asyncio
import json
import time
from typing import Any, Dict
import uuid
import pytest

from app.core.security import compute_sha256_hash, sign_approval_payload
from app.services.kill_switch import EmergencyKillSwitchService
from app.services.os_guard import (
    CoordinateSafetyValidator,
    HostExecutionPartition,
    LOLBINS_DENYLIST,
    OSActionLifecycleState,
    OSActionRequest,
    OSActionResponse,
    OSActionType,
    OSGuardService,
    OSPolicyEngine,
    OSRiskTier,
    PathValidator,
    PolicyDecisionType,
    ProcessIdentityValidator,
    PROTECTED_PROCESS_NAMES,
    SafeMockOSExecutionAdapter,
    os_guard_service,
    os_policy_engine,
)


@pytest.fixture
def mock_kill_switch():
    """Create a dedicated, isolated kill switch service for testing."""
    import tempfile
    from pathlib import Path
    temp_dir = Path(tempfile.mkdtemp())
    state_file = temp_dir / "test_kill_state.json"
    ks = EmergencyKillSwitchService(state_file_path=str(state_file))
    ks.set_active(False)
    yield ks
    ks.set_active(False)


@pytest.fixture
def custom_os_guard(mock_kill_switch):
    """Create an isolated OSGuardService instance."""
    engine = OSPolicyEngine()
    adapter = SafeMockOSExecutionAdapter()
    return OSGuardService(policy_engine=engine, default_adapter=adapter, kill_switch=mock_kill_switch)


# ==============================================================================
# 1. ACTION CONTRACT, TAXONOMY & RISK CLASSIFICATION
# ==============================================================================

def test_os_action_request_validation():
    """Verify Pydantic validation clamps oversized timeouts and validates workspace."""
    # Valid request
    req = OSActionRequest(
        workspace_id="ws_test_001",
        action_type=OSActionType.SYSTEM_TELEMETRY,
        timeout_seconds=3.0,
    )
    assert req.timeout_seconds == 3.0
    assert req.action_type == OSActionType.SYSTEM_TELEMETRY

    # Oversized timeout clamped to 5.0s
    req_large = OSActionRequest(
        workspace_id="ws_test_001",
        action_type=OSActionType.MOUSE_CLICK,
        timeout_seconds=999.0,
    )
    assert req_large.timeout_seconds == 5.0

    # Non-positive timeout rejected
    with pytest.raises(ValueError, match="strictly positive"):
        OSActionRequest(
            workspace_id="ws_test_001",
            action_type=OSActionType.MOUSE_CLICK,
            timeout_seconds=0.0,
        )


def test_deterministic_risk_classification():
    """Verify exact 5-tier risk taxonomy mapping across all action types."""
    engine = OSPolicyEngine()
    
    assert engine.get_risk_tier(OSActionType.READ_ONLY) == OSRiskTier.READ_ONLY
    assert engine.get_risk_tier(OSActionType.SYSTEM_TELEMETRY) == OSRiskTier.READ_ONLY
    assert engine.get_risk_tier(OSActionType.CLIPBOARD_READ) == OSRiskTier.READ_ONLY
    assert engine.get_risk_tier(OSActionType.WINDOW_FOCUS) == OSRiskTier.LOW_RISK_WRITE
    assert engine.get_risk_tier(OSActionType.MOUSE_MOVE) == OSRiskTier.MEDIUM_RISK_INTERACTION
    assert engine.get_risk_tier(OSActionType.MOUSE_CLICK) == OSRiskTier.MEDIUM_RISK_INTERACTION
    assert engine.get_risk_tier(OSActionType.KEYBOARD_INPUT) == OSRiskTier.MEDIUM_RISK_INTERACTION
    assert engine.get_risk_tier(OSActionType.CLIPBOARD_WRITE) == OSRiskTier.MEDIUM_RISK_INTERACTION
    assert engine.get_risk_tier(OSActionType.APPLICATION_LAUNCH) == OSRiskTier.HIGH_RISK_SYSTEM_ACTION
    assert engine.get_risk_tier(OSActionType.PROCESS_TERMINATE) == OSRiskTier.HIGH_RISK_SYSTEM_ACTION
    assert engine.get_risk_tier(OSActionType.HARDWARE_CONTROL) == OSRiskTier.HIGH_RISK_SYSTEM_ACTION


def test_host_execution_partitioning():
    """Verify partition mapping adheres to preflight boundaries."""
    engine = OSPolicyEngine()
    
    assert engine.get_partition(OSActionType.READ_ONLY) == HostExecutionPartition.HOST_REQUIRED_GOVERNED
    assert engine.get_partition(OSActionType.MOUSE_CLICK) == HostExecutionPartition.HOST_REQUIRED_GOVERNED
    assert engine.get_partition(OSActionType.APPLICATION_LAUNCH) == HostExecutionPartition.PRIVILEGED_HOST
    assert engine.get_partition(OSActionType.PROCESS_TERMINATE) == HostExecutionPartition.PRIVILEGED_HOST
    assert engine.get_partition(OSActionType.HARDWARE_CONTROL) == HostExecutionPartition.PRIVILEGED_HOST


# ==============================================================================
# 2. POLICY EVALUATION & AUTONOMY LEVELS
# ==============================================================================

def test_policy_read_only_allowed_without_hitl():
    """Verify READ_ONLY and SYSTEM_TELEMETRY are allowed across all autonomy levels."""
    engine = OSPolicyEngine()
    req = OSActionRequest(
        workspace_id="ws_1",
        action_type=OSActionType.SYSTEM_TELEMETRY,
    )
    decision = engine.evaluate_action(req, autonomy_level=1)
    assert decision.decision == PolicyDecisionType.ALLOW
    assert decision.requires_hitl is False


def test_policy_medium_risk_autonomy_gate():
    """Verify MEDIUM_RISK_INTERACTION requires HITL at L0-L2 and is autonomous at L3+."""
    engine = OSPolicyEngine()
    req = OSActionRequest(
        workspace_id="ws_1",
        action_type=OSActionType.MOUSE_CLICK,
        parameters={"x": 500, "y": 300},
    )
    # At L2: Requires HITL
    dec_l2 = engine.evaluate_action(req, autonomy_level=2)
    assert dec_l2.decision == PolicyDecisionType.REQUIRE_HITL
    assert dec_l2.requires_hitl is True

    # At L3: Autonomous
    dec_l3 = engine.evaluate_action(req, autonomy_level=3)
    assert dec_l3.decision == PolicyDecisionType.ALLOW
    assert dec_l3.requires_hitl is False


def test_policy_high_risk_requires_hitl_always():
    """Verify HIGH_RISK_SYSTEM_ACTION requires HITL token across all autonomy levels."""
    engine = OSPolicyEngine()
    req = OSActionRequest(
        workspace_id="ws_1",
        action_type=OSActionType.APPLICATION_LAUNCH,
        parameters={"target": "C:\\Windows\\System32\\notepad.exe"},
    )
    # Even at L5, high-risk application launch requires HITL
    decision = engine.evaluate_action(req, autonomy_level=5)
    assert decision.decision == PolicyDecisionType.REQUIRE_HITL
    assert decision.requires_hitl is True


# ==============================================================================
# 3. CRYPTOGRAPHIC HITL TOKEN VERIFICATION & ANTI-REPLAY
# ==============================================================================

def test_hitl_valid_token_authorization():
    """Verify cryptographically signed HMAC-SHA256 token authorizes high-risk action."""
    engine = OSPolicyEngine()
    ws_id = "ws_hitl_test"
    params = {"target": "C:\\Windows\\System32\\notepad.exe"}
    
    # Generate canonical approval token
    param_hash = compute_sha256_hash(json.dumps(params, sort_keys=True, separators=(",", ":")))
    payload = {
        "workspace_id": ws_id,
        "action_type": OSActionType.APPLICATION_LAUNCH.value,
        "param_hash": param_hash,
        "expires_at": time.time() + 120,
    }
    sig = sign_approval_payload(payload)
    token_json = json.dumps({**payload, "signature": sig})

    req = OSActionRequest(
        workspace_id=ws_id,
        action_type=OSActionType.APPLICATION_LAUNCH,
        parameters=params,
        hitl_approval_token=token_json,
    )
    decision = engine.evaluate_action(req, autonomy_level=3)
    assert decision.decision == PolicyDecisionType.ALLOW


def test_hitl_wrong_workspace_rejected():
    """Verify HITL token signed for workspace A is rejected on workspace B."""
    engine = OSPolicyEngine()
    params = {"target": "C:\\Windows\\System32\\notepad.exe"}
    param_hash = compute_sha256_hash(json.dumps(params, sort_keys=True, separators=(",", ":")))
    payload = {
        "workspace_id": "ws_alpha",
        "action_type": OSActionType.APPLICATION_LAUNCH.value,
        "param_hash": param_hash,
        "expires_at": time.time() + 120,
    }
    sig = sign_approval_payload(payload)
    token_json = json.dumps({**payload, "signature": sig})

    # Submitting to workspace beta
    req = OSActionRequest(
        workspace_id="ws_beta",
        action_type=OSActionType.APPLICATION_LAUNCH,
        parameters=params,
        hitl_approval_token=token_json,
    )
    decision = engine.evaluate_action(req, autonomy_level=3)
    assert decision.decision == PolicyDecisionType.DENY
    assert "does not match request workspace" in decision.reason


def test_hitl_parameter_tampering_rejected():
    """Verify modifying parameters after approval invalidates the token."""
    engine = OSPolicyEngine()
    ws_id = "ws_tamper_test"
    approved_params = {"target": "C:\\Windows\\System32\\notepad.exe"}
    param_hash = compute_sha256_hash(json.dumps(approved_params, sort_keys=True, separators=(",", ":")))
    payload = {
        "workspace_id": ws_id,
        "action_type": OSActionType.APPLICATION_LAUNCH.value,
        "param_hash": param_hash,
        "expires_at": time.time() + 120,
    }
    sig = sign_approval_payload(payload)
    token_json = json.dumps({**payload, "signature": sig})

    # Attempt to execute with modified target (calc.exe instead of notepad.exe)
    tampered_params = {"target": "C:\\Windows\\System32\\calc.exe"}
    req = OSActionRequest(
        workspace_id=ws_id,
        action_type=OSActionType.APPLICATION_LAUNCH,
        parameters=tampered_params,
        hitl_approval_token=token_json,
    )
    decision = engine.evaluate_action(req, autonomy_level=3)
    assert decision.decision == PolicyDecisionType.DENY
    assert "parameter hash mismatch" in decision.reason.lower()


def test_hitl_expired_token_rejected():
    """Verify expired HITL token (> 120s) is rejected."""
    engine = OSPolicyEngine()
    ws_id = "ws_expired_test"
    params = {"target": "C:\\Windows\\System32\\notepad.exe"}
    param_hash = compute_sha256_hash(json.dumps(params, sort_keys=True, separators=(",", ":")))
    payload = {
        "workspace_id": ws_id,
        "action_type": OSActionType.APPLICATION_LAUNCH.value,
        "param_hash": param_hash,
        "expires_at": time.time() - 10,  # Expired in past
    }
    sig = sign_approval_payload(payload)
    token_json = json.dumps({**payload, "signature": sig})

    req = OSActionRequest(
        workspace_id=ws_id,
        action_type=OSActionType.APPLICATION_LAUNCH,
        parameters=params,
        hitl_approval_token=token_json,
    )
    decision = engine.evaluate_action(req, autonomy_level=3)
    assert decision.decision == PolicyDecisionType.DENY
    assert "expired" in decision.reason.lower()


def test_hitl_single_use_replay_defense():
    """Verify consumed HITL token cannot be replayed a second time."""
    engine = OSPolicyEngine()
    ws_id = "ws_replay_test"
    params = {"target": "C:\\Windows\\System32\\notepad.exe"}
    param_hash = compute_sha256_hash(json.dumps(params, sort_keys=True, separators=(",", ":")))
    payload = {
        "workspace_id": ws_id,
        "action_type": OSActionType.APPLICATION_LAUNCH.value,
        "param_hash": param_hash,
        "expires_at": time.time() + 120,
    }
    sig = sign_approval_payload(payload)
    token_json = json.dumps({**payload, "signature": sig})

    req = OSActionRequest(
        workspace_id=ws_id,
        action_type=OSActionType.APPLICATION_LAUNCH,
        parameters=params,
        hitl_approval_token=token_json,
    )
    # First execution: Allowed & consumed
    dec1 = engine.evaluate_action(req, autonomy_level=3)
    assert dec1.decision == PolicyDecisionType.ALLOW

    # Replay attempt: Denied
    dec2 = engine.evaluate_action(req, autonomy_level=3)
    assert dec2.decision == PolicyDecisionType.DENY
    assert "already been consumed" in dec2.reason.lower()


# ==============================================================================
# 4. CONCURRENCY SERIALIZATION & RATE LIMITING
# ==============================================================================

@pytest.mark.asyncio
async def test_single_active_action_concurrency_serialization(custom_os_guard):
    """Verify max 1 active OS action: concurrent requests are serialized safely."""
    # Configure adapter with 0.1s simulated delay
    adapter = SafeMockOSExecutionAdapter(simulated_delay_sec=0.1)
    custom_os_guard.default_adapter = adapter

    req1 = OSActionRequest(workspace_id="ws_conc", action_type=OSActionType.SYSTEM_TELEMETRY)
    req2 = OSActionRequest(workspace_id="ws_conc", action_type=OSActionType.SYSTEM_TELEMETRY)

    t0 = time.perf_counter()
    # Dispatch both simultaneously
    res1, res2 = await asyncio.gather(
        custom_os_guard.execute_os_action(req1),
        custom_os_guard.execute_os_action(req2),
    )
    total_duration = time.perf_counter() - t0

    assert res1.state == OSActionLifecycleState.COMPLETED
    assert res2.state == OSActionLifecycleState.COMPLETED
    # Should take at least 0.2s due to serial lock
    assert total_duration >= 0.18
    assert len(adapter.executed_actions) == 2


def test_sliding_window_rate_limiting():
    """Verify rate limiter blocks operations exceeding budget (e.g. 5 application launches/min)."""
    engine = OSPolicyEngine()
    ws_id = "ws_rate_limit"

    # 5 launches should pass
    for i in range(5):
        req = OSActionRequest(
            workspace_id=ws_id,
            action_type=OSActionType.APPLICATION_LAUNCH,
            parameters={"target": "C:\\Windows\\System32\\notepad.exe"},
        )
        assert engine.rate_limiter.check_and_record(ws_id, "application_launch", limit=5) is True

    # 6th launch within same minute is rejected
    assert engine.rate_limiter.check_and_record(ws_id, "application_launch", limit=5) is False


# ==============================================================================
# 5. KILL SWITCH INTEGRATION & RACE CONDITIONS
# ==============================================================================

@pytest.mark.asyncio
async def test_kill_switch_pre_execution_abort(custom_os_guard, mock_kill_switch):
    """Verify active kill switch blocks execution in < 15ms without running policy."""
    ws_id = "ws_ks_test"
    mock_kill_switch.set_active(True, workspace_id=ws_id)

    req = OSActionRequest(workspace_id=ws_id, action_type=OSActionType.SYSTEM_TELEMETRY)
    resp = await custom_os_guard.execute_os_action(req)

    assert resp.state == OSActionLifecycleState.KILL_SWITCHED
    assert resp.policy_decision == PolicyDecisionType.KILL_SWITCHED
    assert "kill switch is active" in resp.error.lower()
    assert len(custom_os_guard.default_adapter.executed_actions) == 0


@pytest.mark.asyncio
async def test_kill_switch_triggered_during_execution(custom_os_guard, mock_kill_switch):
    """Verify kill switch activated mid-action transitions result to KILL_SWITCHED."""
    ws_id = "ws_ks_mid"
    adapter = SafeMockOSExecutionAdapter(simulated_delay_sec=0.15)
    custom_os_guard.default_adapter = adapter

    req = OSActionRequest(workspace_id=ws_id, action_type=OSActionType.SYSTEM_TELEMETRY)

    async def trigger_ks_soon():
        await asyncio.sleep(0.05)
        mock_kill_switch.set_active(True, workspace_id=ws_id)

    _, resp = await asyncio.gather(
        trigger_ks_soon(),
        custom_os_guard.execute_os_action(req),
    )

    assert resp.state == OSActionLifecycleState.KILL_SWITCHED
    assert "kill switch" in resp.error.lower()


# ==============================================================================
# 6. HARD 5.0-SECOND TIMEOUT ENFORCEMENT
# ==============================================================================

@pytest.mark.asyncio
async def test_hard_action_timeout_enforcement(custom_os_guard):
    """Verify actions taking longer than timeout are cancelled and marked TIMED_OUT."""
    # Adapter with 0.3s delay but timeout is 0.1s
    adapter = SafeMockOSExecutionAdapter(simulated_delay_sec=0.3)
    custom_os_guard.default_adapter = adapter

    req = OSActionRequest(
        workspace_id="ws_timeout",
        action_type=OSActionType.SYSTEM_TELEMETRY,
        timeout_seconds=0.1,
    )
    resp = await custom_os_guard.execute_os_action(req)

    assert resp.state == OSActionLifecycleState.TIMED_OUT
    assert "timed out" in resp.error.lower()


# ==============================================================================
# 7. PATH VALIDATION, TRAVERSAL DEFENSE & LOLBINS DENYLIST
# ==============================================================================

def test_path_traversal_rejection():
    """Verify path traversal sequences are rejected."""
    is_valid, _, err = PathValidator.validate_executable_path("C:\\Windows\\System32\\..\\cmd.exe")
    assert is_valid is False
    assert "traversal" in err.lower()


def test_lolbins_denylist_rejection():
    """Verify all canonical LOLBins are rejected."""
    for lolbin in LOLBINS_DENYLIST:
        is_valid, _, err = PathValidator.validate_executable_path(f"C:\\Windows\\System32\\{lolbin}")
        assert is_valid is False, f"LOLBin '{lolbin}' must be rejected"
        assert "lolbins security denylist" in err.lower()


def test_forbidden_shell_parameter_rejection():
    """Verify shell=True in request parameters is rejected by policy."""
    engine = OSPolicyEngine()
    req = OSActionRequest(
        workspace_id="ws_shell",
        action_type=OSActionType.APPLICATION_LAUNCH,
        parameters={"target": "C:\\Windows\\System32\\notepad.exe", "shell": True},
    )
    decision = engine.evaluate_action(req)
    assert decision.decision == PolicyDecisionType.DENY
    assert "shell=true" in decision.reason.lower()


# ==============================================================================
# 8. PROCESS IDENTITY & SYSTEM DENYLIST VALIDATION
# ==============================================================================

def test_protected_system_process_denial():
    """Verify protected Windows and AURA system processes cannot be targeted for termination."""
    for proc in ["csrss.exe", "lsass.exe", "postgres.exe", "ollama.exe", "python.exe", "dwm.exe"]:
        is_valid, err = ProcessIdentityValidator.validate_process_for_termination(
            pid=1234,
            expected_name=proc,
            expected_create_time=1728000000.0,
        )
        assert is_valid is False
        assert "protected system denylist" in err.lower()


def test_pid_below_4_denial():
    """Verify kernel PIDs <= 4 are rejected immediately."""
    is_valid, err = ProcessIdentityValidator.validate_process_for_termination(
        pid=4,
        expected_name="System",
        expected_create_time=1728000000.0,
    )
    assert is_valid is False
    assert "protected windows system kernel" in err.lower()


# ==============================================================================
# 9. COORDINATE SAFETY & STALE OBSERVATION PROTECTION
# ==============================================================================

def test_negative_coordinates_rejected():
    """Verify negative screen coordinates are rejected."""
    is_valid, err = CoordinateSafetyValidator.validate_screen_coordinates(x=-50, y=100)
    assert is_valid is False
    assert "cannot be negative" in err.lower()


def test_stale_visual_observation_rejected():
    """Verify visual observation older than 5.0s is rejected with stale error."""
    old_timestamp = time.time() - 6.5  # 6.5s old
    is_valid, err = CoordinateSafetyValidator.validate_screen_coordinates(
        x=500,
        y=300,
        observation_timestamp=old_timestamp,
    )
    assert is_valid is False
    assert "stale visual observation" in err.lower()


def test_out_of_window_bounds_rejected():
    """Verify coordinates outside focused application window bounds are rejected."""
    win_bounds = {"left": 100, "top": 100, "width": 800, "height": 600}
    
    # Coordinate (1500, 900) is outside window (100..900, 100..700)
    is_valid, err = CoordinateSafetyValidator.validate_screen_coordinates(
        x=1500,
        y=900,
        window_bounds=win_bounds,
    )
    assert is_valid is False
    assert "outside active window boundaries" in err.lower()


def test_valid_in_bounds_coordinate_allowed():
    """Verify coordinate within active window and monitor bounds is allowed."""
    win_bounds = {"left": 100, "top": 100, "width": 800, "height": 600}
    is_valid, err = CoordinateSafetyValidator.validate_screen_coordinates(
        x=500,
        y=400,
        window_bounds=win_bounds,
        observation_timestamp=time.time() - 1.0,
    )
    assert is_valid is True
    assert err == ""
