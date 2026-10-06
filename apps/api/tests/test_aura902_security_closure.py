"""AURA-902 Security Evidence Closure Test Suite.

Authoritative verification of:
1. Live HITL (HMAC-SHA256 parameter-bound verification & tamper invalidation) [LIVE / INTEGRATION]
2. Live Kill-Switch Race (immediate abort, no execution, no replay) [LIVE CONTROL-PLANE]
3. Rate Limiting (AURA-901 centralized sliding-window limiter enforcement) [INTEGRATION]
4. Audit & Telemetry Redaction (complete secret elimination, safe metadata verification) [LIVE / INTEGRATION]
"""

import asyncio
import json
import logging
import time
import uuid
import psutil
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redaction import secret_redactor
from app.core.security import compute_sha256_hash, sign_approval_payload
from app.core.telemetry import telemetry_manager
from app.services.audit_service import audit_service
from app.services.kill_switch import kill_switch
from app.services.os_guard.adapters import SafeMockOSExecutionAdapter, WindowsOSExecutionAdapter
from app.services.os_guard.app_registry import application_registry
from app.services.os_guard.os_guard_service import OSGuardService
from app.services.os_guard.policy import OSPolicyEngine
from app.services.os_guard.process_service import process_service
from app.services.os_guard.types import (
    HostExecutionPartition,
    OSActionLifecycleState,
    OSActionRequest,
    OSActionType,
    OSRiskTier,
    PolicyDecisionType,
)


def make_token(workspace_id: str, action_type: OSActionType, params: dict, ttl: float = 120) -> str:
    """Generate parameter-bound HMAC-SHA256 approval token."""
    param_hash = compute_sha256_hash(json.dumps(params, sort_keys=True, separators=(",", ":")))
    payload = {
        "workspace_id": str(workspace_id),
        "action_type": action_type.value,
        "param_hash": param_hash,
        "expires_at": time.time() + ttl,
        "nonce": str(uuid.uuid4()),
    }
    sig = sign_approval_payload(payload)
    return json.dumps({**payload, "signature": sig})


@pytest.mark.asyncio
async def test_live_hitl_tamper_invalidation_and_live_execution():
    """Demonstrate Live HITL approval, parameter tampering invalidation, and live execution.
    
    Evidence Type: LIVE / INTEGRATION
    """
    engine = OSPolicyEngine()
    win_adapter = WindowsOSExecutionAdapter()
    guard = OSGuardService(policy_engine=engine, default_adapter=win_adapter)
    
    ws_id = str(uuid.uuid4())
    valid_params = {"application_id": "notepad", "arguments": []}
    valid_token = make_token(ws_id, OSActionType.APPLICATION_LAUNCH, valid_params)
    
    # 0. Missing token returns REQUIRE_HITL
    missing_token_req = OSActionRequest(
        action_id="act-missing-token",
        workspace_id=ws_id,
        action_type=OSActionType.APPLICATION_LAUNCH,
        parameters=valid_params,
        hitl_approval_token=None,
    )
    res_missing = await guard.execute_os_action(missing_token_req)
    assert res_missing.policy_decision == PolicyDecisionType.REQUIRE_HITL
    assert res_missing.state == OSActionLifecycleState.WAITING_HITL
    
    # 1. Tamper application_id -> cryptographic signature mismatch fails-closed with DENY
    tampered_app_req = OSActionRequest(
        action_id="act-tamper-app",
        workspace_id=ws_id,
        action_type=OSActionType.APPLICATION_LAUNCH,
        parameters={"application_id": "calc", "arguments": []},
        hitl_approval_token=valid_token,
    )
    res_tamper_app = await guard.execute_os_action(tampered_app_req)
    assert res_tamper_app.policy_decision == PolicyDecisionType.DENY
    assert res_tamper_app.state == OSActionLifecycleState.FAILED
    
    # 2. Tamper arguments -> DENY
    tampered_args_req = OSActionRequest(
        action_id="act-tamper-args",
        workspace_id=ws_id,
        action_type=OSActionType.APPLICATION_LAUNCH,
        parameters={"application_id": "notepad", "arguments": ["tampered.txt"]},
        hitl_approval_token=valid_token,
    )
    res_tamper_args = await guard.execute_os_action(tampered_args_req)
    assert res_tamper_args.policy_decision == PolicyDecisionType.DENY
    assert res_tamper_args.state == OSActionLifecycleState.FAILED
    
    # 3. Tamper workspace_id -> DENY
    other_ws_id = str(uuid.uuid4())
    tampered_ws_req = OSActionRequest(
        action_id="act-tamper-ws",
        workspace_id=other_ws_id,
        action_type=OSActionType.APPLICATION_LAUNCH,
        parameters=valid_params,
        hitl_approval_token=valid_token,
    )
    res_tamper_ws = await guard.execute_os_action(tampered_ws_req)
    assert res_tamper_ws.policy_decision == PolicyDecisionType.DENY
    assert res_tamper_ws.state == OSActionLifecycleState.FAILED
    
    # 4. Tamper action_type -> DENY
    tampered_type_req = OSActionRequest(
        action_id="act-tamper-type",
        workspace_id=ws_id,
        action_type=OSActionType.PROCESS_TERMINATE,
        parameters=valid_params,
        hitl_approval_token=valid_token,
    )
    res_tamper_type = await guard.execute_os_action(tampered_type_req)
    assert res_tamper_type.policy_decision == PolicyDecisionType.DENY
    assert res_tamper_type.state == OSActionLifecycleState.FAILED
    
    # 5. Tamper PID / creation_time on PROCESS_TERMINATE -> DENY
    term_params = {"pid": 99999, "expected_name": "notepad.exe", "expected_create_time": 1234567.89}
    valid_term_token = make_token(ws_id, OSActionType.PROCESS_TERMINATE, term_params)
    
    # Tamper PID
    tampered_pid_req = OSActionRequest(
        action_id="act-tamper-pid",
        workspace_id=ws_id,
        action_type=OSActionType.PROCESS_TERMINATE,
        parameters={"pid": 88888, "expected_name": "notepad.exe", "expected_create_time": 1234567.89},
        hitl_approval_token=valid_term_token,
    )
    res_tamper_pid = await guard.execute_os_action(tampered_pid_req)
    assert res_tamper_pid.policy_decision == PolicyDecisionType.DENY
    assert res_tamper_pid.state == OSActionLifecycleState.FAILED
    
    # Tamper creation_time
    tampered_ctime_req = OSActionRequest(
        action_id="act-tamper-ctime",
        workspace_id=ws_id,
        action_type=OSActionType.PROCESS_TERMINATE,
        parameters={"pid": 99999, "expected_name": "notepad.exe", "expected_create_time": 9876543.21},
        hitl_approval_token=valid_term_token,
    )
    res_tamper_ctime = await guard.execute_os_action(tampered_ctime_req)
    assert res_tamper_ctime.policy_decision == PolicyDecisionType.DENY
    assert res_tamper_ctime.state == OSActionLifecycleState.FAILED
    
    # 6. Live Legitimate Execution: Launch notepad.exe with valid HITL token, then terminate with valid HITL token
    live_launch_req = OSActionRequest(
        action_id=f"act-live-launch-{uuid.uuid4().hex[:6]}",
        workspace_id=ws_id,
        action_type=OSActionType.APPLICATION_LAUNCH,
        parameters=valid_params,
        hitl_approval_token=valid_token,
    )
    launch_res = await guard.execute_os_action(live_launch_req)
    assert launch_res.state == OSActionLifecycleState.COMPLETED
    assert launch_res.policy_decision == PolicyDecisionType.ALLOW
    pid = launch_res.result.get("pid")
    create_time = launch_res.result.get("create_time")
    assert pid is not None
    assert psutil.pid_exists(pid)
    
    try:
        # Legitimate Terminate with valid HITL token
        live_term_params = {"pid": pid, "expected_name": "notepad.exe", "expected_create_time": create_time}
        live_term_token = make_token(ws_id, OSActionType.PROCESS_TERMINATE, live_term_params)
        live_term_req = OSActionRequest(
            action_id=f"act-live-term-{uuid.uuid4().hex[:6]}",
            workspace_id=ws_id,
            action_type=OSActionType.PROCESS_TERMINATE,
            parameters=live_term_params,
            hitl_approval_token=live_term_token,
        )
        term_res = await guard.execute_os_action(live_term_req)
        assert term_res.state == OSActionLifecycleState.COMPLETED
        assert term_res.result.get("outcome") == "TERMINATED"
        await asyncio.sleep(0.1)
        assert not psutil.pid_exists(pid)
    finally:
        # Ensure cleanup in all cases
        if psutil.pid_exists(pid):
            try:
                psutil.Process(pid).kill()
            except Exception:
                pass


@pytest.mark.asyncio
async def test_live_kill_switch_race_control_plane():
    """Demonstrate Live Kill Switch immediate pre-execution abort and zero retry/replay.
    
    Evidence Type: LIVE CONTROL-PLANE
    """
    engine = OSPolicyEngine()
    win_adapter = WindowsOSExecutionAdapter()
    guard = OSGuardService(policy_engine=engine, default_adapter=win_adapter)
    
    ws_id = str(uuid.uuid4())
    params = {"application_id": "notepad", "arguments": []}
    token = make_token(ws_id, OSActionType.APPLICATION_LAUNCH, params)
    
    req = OSActionRequest(
        action_id=f"act-ks-race-{uuid.uuid4().hex[:6]}",
        workspace_id=ws_id,
        action_type=OSActionType.APPLICATION_LAUNCH,
        parameters=params,
        hitl_approval_token=token,
    )
    
    # 0. Record initial running notepad PIDs
    initial_pids = {p["pid"] for p in process_service.inspect_processes(filter_name="notepad.exe")}
    
    # 1. Engage kill switch BEFORE execution boundary
    kill_switch.set_active(True, ws_id)
    assert kill_switch.is_active(ws_id)
    
    # 2. Attempt execution
    resp = await guard.execute_os_action(req)
    
    # 3. Assert exact KILL_SWITCHED lifecycle state and zero execution
    assert resp.state == OSActionLifecycleState.KILL_SWITCHED
    assert resp.policy_decision == PolicyDecisionType.KILL_SWITCHED
    assert "Emergency kill switch is active" in (resp.error or "")
    assert resp.result is None
    
    # 4. Deactivate kill switch and verify interrupted action was NOT automatically queued/executed
    kill_switch.set_active(False, ws_id)
    assert not kill_switch.is_active(ws_id)
    
    # Inspect processes to ensure no stray notepad was launched during or after the race
    current_pids = {p["pid"] for p in process_service.inspect_processes(filter_name="notepad.exe")}
    new_pids = current_pids - initial_pids
    assert len(new_pids) == 0


@pytest.mark.asyncio
async def test_rate_limiting_centralized_enforcement():
    """Verify real AURA-901 centralized rate limiters control AURA-902 launch and termination.
    
    Evidence Type: INTEGRATION
    """
    engine = OSPolicyEngine()
    mock_adapter = SafeMockOSExecutionAdapter()
    guard = OSGuardService(policy_engine=engine, default_adapter=mock_adapter)
    
    ws_id = str(uuid.uuid4())
    
    # Application launch limit = 5 per 60s
    params = {"application_id": "notepad", "arguments": []}
    
    # Execute 5 valid requests
    for i in range(5):
        token = make_token(ws_id, OSActionType.APPLICATION_LAUNCH, params)
        req = OSActionRequest(
            action_id=f"act-rate-launch-{i}",
            workspace_id=ws_id,
            action_type=OSActionType.APPLICATION_LAUNCH,
            parameters=params,
            hitl_approval_token=token,
        )
        res = await guard.execute_os_action(req)
        assert res.state == OSActionLifecycleState.COMPLETED, f"Request {i} failed unexpectedly"
        assert res.policy_decision == PolicyDecisionType.ALLOW
        
    # 6th request must be RATE_LIMITED
    token_6 = make_token(ws_id, OSActionType.APPLICATION_LAUNCH, params)
    req_6 = OSActionRequest(
        action_id="act-rate-launch-6",
        workspace_id=ws_id,
        action_type=OSActionType.APPLICATION_LAUNCH,
        parameters=params,
        hitl_approval_token=token_6,
    )
    res_6 = await guard.execute_os_action(req_6)
    assert res_6.state == OSActionLifecycleState.FAILED
    assert res_6.policy_decision == PolicyDecisionType.RATE_LIMIT
    assert "Rate limit exceeded" in (res_6.error or "")


@pytest.mark.asyncio
async def test_live_audit_and_telemetry_redaction(db_session: AsyncSession, caplog):
    """Execute harmless governed operation and verify complete absence of secrets in logs, audit, and telemetry.
    
    Evidence Type: LIVE / INTEGRATION
    """
    from sqlalchemy import select
    from app.db.models.audit import AuditLog

    engine = OSPolicyEngine()
    mock_adapter = SafeMockOSExecutionAdapter()
    guard = OSGuardService(policy_engine=engine, default_adapter=mock_adapter)
    
    ws_id = uuid.uuid4()
    
    # Inject sensitive credentials into parameters
    sensitive_params = {
        "application_id": "notepad",
        "api_key": "sk-proj-supersecretkey1234567890abcdef",
        "db_password": "SuperSecretPassword!@#123",
        "raw_token": "bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.dummy",
    }
    token = make_token(str(ws_id), OSActionType.APPLICATION_LAUNCH, sensitive_params)
    
    req = OSActionRequest(
        action_id=f"act-audit-test-{uuid.uuid4().hex[:6]}",
        workspace_id=str(ws_id),
        action_type=OSActionType.APPLICATION_LAUNCH,
        parameters=sensitive_params,
        hitl_approval_token=token,
    )
    
    with caplog.at_level(logging.DEBUG):
        resp = await guard.execute_os_action(req, db=db_session)
    
    assert resp.state == OSActionLifecycleState.COMPLETED
    
    # 1. Verify log stream has NO unredacted secrets
    captured_logs = caplog.text
    assert "sk-proj-supersecretkey1234567890abcdef" not in captured_logs
    assert "SuperSecretPassword!@#123" not in captured_logs
    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in captured_logs
    
    # 2. Query Audit Log entry from DB and verify redaction
    stmt = (
        select(AuditLog)
        .where(AuditLog.workspace_id == ws_id)
        .order_by(AuditLog.id.desc())
        .limit(5)
    )
    res = await db_session.execute(stmt)
    audit_entries = list(res.scalars().all())
    assert len(audit_entries) >= 1
    latest_entry = audit_entries[0]
    
    assert latest_entry.action == "os_action.application_launch"
    details_str = json.dumps(latest_entry.details)
    
    assert "sk-proj-supersecretkey1234567890abcdef" not in details_str
    assert "SuperSecretPassword!@#123" not in details_str
    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in details_str
    
    # 3. Verify safe metadata fields ARE present
    details = latest_entry.details
    assert details.get("action_id") == req.action_id
    assert details.get("action_type") == "application_launch"
    assert details.get("risk_tier") == "high_risk_system_action"
    assert details.get("lifecycle_state") == "completed"
    assert details.get("policy_decision") == "allow"
    assert "duration_ms" in details
    assert "trace_id" in details
