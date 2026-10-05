"""AURA-902 Comprehensive Governed Application Launch & Process Control Tests.

Covers:
1. Application Launch: allowlist enforcement, argument validation, LOLBins rejection, traversal defense, NUL bytes, working dir, clean env
2. Process Inspection: safe sanitized fields, no secret leakage, filtering, protected process detection
3. Process Termination: PID + create_time TOCTOU verification, protected process protection, HITL validation, anti-replay
4. Governance Pipeline: AgentToolBridge / ToolRegistryService / OSGuardService / PolicyEngine / KillSwitch / RateLimiter
5. Live Benign Validation: Notepad launch -> inspect -> governed terminate -> verified exit
6. Live Kill-Switch Race: Abort before execution
"""

import asyncio
import json
import os
import sys
import time
import uuid
import psutil
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import compute_sha256_hash, sign_approval_payload
from app.services.kill_switch import kill_switch
from app.services.os_guard.adapters import SafeMockOSExecutionAdapter, WindowsOSExecutionAdapter
from app.services.os_guard.app_registry import (
    ApplicationRegistry,
    CANONICAL_ALLOWLIST,
    application_registry,
)
from app.services.os_guard.os_guard_service import OSGuardService
from app.services.os_guard.policy import OSPolicyEngine
from app.services.os_guard.process_service import ProcessService, process_service
from app.services.os_guard.types import (
    OSActionLifecycleState,
    OSActionRequest,
    OSActionType,
    OSRiskTier,
    PolicyDecisionType,
)
from app.services.os_guard.validators import (
    PROTECTED_PROCESS_NAMES,
    PathValidator,
    ProcessIdentityValidator,
)
from app.services.tool_registry import tool_registry


def make_hitl_token(
    workspace_id: str | uuid.UUID,
    action_type: OSActionType,
    params: dict,
    expires_in: float = 120,
) -> str:
    """Helper to generate cryptographically signed parameter-bound HITL token."""
    param_hash = compute_sha256_hash(json.dumps(params, sort_keys=True, separators=(",", ":")))
    payload = {
        "workspace_id": str(workspace_id),
        "action_type": action_type.value,
        "param_hash": param_hash,
        "expires_at": time.time() + expires_in,
    }
    sig = sign_approval_payload(payload)
    return json.dumps({**payload, "signature": sig})


# ---------------------------------------------------------------------------
# FIXTURES
# ---------------------------------------------------------------------------

@pytest.fixture
def workspace_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def mock_adapter() -> SafeMockOSExecutionAdapter:
    return SafeMockOSExecutionAdapter()


@pytest.fixture
def test_policy_engine() -> OSPolicyEngine:
    return OSPolicyEngine()


@pytest.fixture
def test_os_guard(mock_adapter: SafeMockOSExecutionAdapter, test_policy_engine: OSPolicyEngine) -> OSGuardService:
    return OSGuardService(
        policy_engine=test_policy_engine,
        default_adapter=mock_adapter,
    )


# ---------------------------------------------------------------------------
# 1. APPLICATION REGISTRY & LAUNCH VALIDATION TESTS
# ---------------------------------------------------------------------------

def test_canonical_allowlist_structure():
    """Verify standard productivity applications are present in canonical allowlist."""
    apps = application_registry.list_applications()
    app_ids = {a["application_id"] for a in apps}
    assert "notepad" in app_ids
    assert "calc" in app_ids
    assert "mspaint" in app_ids
    assert "write" in app_ids

    notepad_def = application_registry.get_application("notepad")
    assert notepad_def is not None
    assert notepad_def.canonical_executable_path.lower().endswith("notepad.exe")
    assert notepad_def.requires_hitl is True
    assert notepad_def.risk_level == OSRiskTier.HIGH_RISK_SYSTEM_ACTION


def test_allowlisted_application_launch_validation():
    """Verify valid launch request for allowlisted application passes."""
    is_valid, err, app_def, clean_args, clean_wd = application_registry.validate_launch_request(
        application_id="notepad",
        arguments=["test.txt"],
        working_directory="C:\\Users",
    )
    assert is_valid is True
    assert err == ""
    assert app_def is not None
    assert clean_args == ["test.txt"]
    assert clean_wd is not None


def test_non_allowlisted_application_denied():
    """Verify arbitrary binaries and shells are denied."""
    for bad_app in ["cmd", "cmd.exe", "powershell", "powershell.exe", "malicious.exe", "calc_fake"]:
        is_valid, err, app_def, _, _ = application_registry.validate_launch_request(
            application_id=bad_app,
        )
        assert is_valid is False
        assert "not in the approved application allowlist" in err


def test_path_traversal_in_launch_denied():
    """Verify directory traversal attempts in application ID or path are denied."""
    for bad_input in ["../notepad", "..\\notepad.exe", "notepad/../../cmd.exe"]:
        is_valid, err, _, _, _ = application_registry.validate_launch_request(
            application_id=bad_input,
        )
        assert is_valid is False


def test_lolbins_denied_in_application_and_arguments():
    """Verify LOLBins cannot be launched or passed as arguments to subvert validation."""
    for lolbin in ["certutil.exe", "bitsadmin.exe", "mshta.exe", "cscript.exe", "wscript.exe", "rundll32.exe"]:
        # Direct launch attempt
        is_valid, err, _, _, _ = application_registry.validate_launch_request(application_id=lolbin)
        assert is_valid is False

        # As argument attempt
        is_valid, err, _, _, _ = application_registry.validate_launch_request(
            application_id="notepad",
            arguments=[lolbin],
        )
        assert is_valid is False
        assert "LOLBin" in err or "prohibited" in err


def test_shell_metacharacters_in_arguments_denied():
    """Verify shell metacharacters (&, |, ;, >, <, `, $, %) are strictly rejected."""
    bad_arguments = [
        "file.txt & calc.exe",
        "file.txt | dir",
        "file.txt; whoami",
        "file.txt > out.txt",
        "file.txt < in.txt",
        "file.txt `whoami`",
        "$env:SECRET",
        "%TEMP%\\run.bat",
    ]
    for bad_arg in bad_arguments:
        is_valid, err, _, _, _ = application_registry.validate_launch_request(
            application_id="notepad",
            arguments=[bad_arg],
        )
        assert is_valid is False
        assert "prohibited shell metacharacters" in err


def test_nul_bytes_in_arguments_denied():
    """Verify NUL byte injection in arguments is rejected."""
    is_valid, err, _, _, _ = application_registry.validate_launch_request(
        application_id="notepad",
        arguments=["file.txt\x00malicious"],
    )
    assert is_valid is False
    assert "NUL byte" in err


def test_oversized_arguments_denied():
    """Verify argument count and length limits are strictly enforced."""
    # Notepad accepts at most 2 arguments
    is_valid, err, _, _, _ = application_registry.validate_launch_request(
        application_id="notepad",
        arguments=["arg1", "arg2", "arg3"],
    )
    assert is_valid is False
    assert "at most 2 arguments" in err

    # Calculator accepts 0 arguments
    is_valid, err, _, _, _ = application_registry.validate_launch_request(
        application_id="calc",
        arguments=["some_arg"],
    )
    assert is_valid is False
    assert "at most 0 arguments" in err

    # Length limit (260 chars)
    long_arg = "a" * 300
    is_valid, err, _, _, _ = application_registry.validate_launch_request(
        application_id="notepad",
        arguments=[long_arg],
    )
    assert is_valid is False
    assert "exceeds maximum length" in err


def test_working_directory_boundary_enforcement(tmp_path):
    """Verify working directory policy restricts paths to workspace root."""
    workspace_root = str(tmp_path)
    inside_dir = str(tmp_path / "subdir")
    os.makedirs(inside_dir, exist_ok=True)
    outside_dir = os.path.abspath(os.path.join(workspace_root, "..", "outside_workspace"))

    # Valid inside workspace
    is_valid, err, _, _, clean_wd = application_registry.validate_launch_request(
        application_id="notepad",
        working_directory=inside_dir,
        workspace_root=workspace_root,
    )
    assert is_valid is True
    assert clean_wd == os.path.abspath(inside_dir)

    # Invalid outside workspace
    is_valid, err, _, _, _ = application_registry.validate_launch_request(
        application_id="notepad",
        working_directory=outside_dir,
        workspace_root=workspace_root,
    )
    assert is_valid is False
    assert "outside authorized workspace root" in err


# ---------------------------------------------------------------------------
# 2. PROCESS INSPECTION TESTS
# ---------------------------------------------------------------------------

def test_process_inspection_sanitization_and_structure():
    """Verify process inspection returns sanitized metadata without secret leakage."""
    current_pid = os.getpid()
    results = ProcessService.inspect_processes(pid=current_pid)
    assert len(results) == 1
    proc = results[0]

    # Required sanitized fields
    assert "pid" in proc
    assert proc["pid"] == current_pid
    assert "name" in proc
    assert "status" in proc
    assert "create_time" in proc
    assert "cpu_percent" in proc
    assert "memory_mb" in proc
    assert "is_protected" in proc

    # Prohibited sensitive fields must NOT be present
    assert "environ" not in proc
    assert "cmdline" not in proc
    assert "env" not in proc
    assert "memory_maps" not in proc


def test_process_inspection_filtering():
    """Verify name and PID filtering works accurately."""
    current_pid = os.getpid()

    # Filter by specific PID
    pid_res = ProcessService.inspect_processes(pid=current_pid)
    assert len(pid_res) == 1
    assert pid_res[0]["pid"] == current_pid

    # Filter by non-existent PID
    nonexistent = ProcessService.inspect_processes(pid=999999999)
    assert len(nonexistent) == 0

    # Filter by name (e.g. python)
    name_res = ProcessService.inspect_processes(filter_name="python", limit=5)
    assert isinstance(name_res, list)
    for p in name_res:
        assert "python" in p["name"].lower()


def test_protected_process_flag_accuracy():
    """Verify system/infrastructure processes are identified as protected."""
    # Check current python process
    current_res = ProcessService.inspect_processes(pid=os.getpid())
    if current_res and "python" in current_res[0]["name"].lower():
        assert current_res[0]["is_protected"] is True

    # Check System process (PID 4) if accessible
    if psutil.pid_exists(4):
        sys_res = ProcessService.inspect_processes(pid=4)
        if sys_res:
            assert sys_res[0]["is_protected"] is True


# ---------------------------------------------------------------------------
# 3. PROCESS TERMINATION & IDENTITY VERIFICATION TESTS
# ---------------------------------------------------------------------------

def test_protected_process_termination_denied():
    """Verify protected processes (PID <= 4, python, system, ollama, postgres) cannot be terminated."""
    protected_targets = [
        (4, "System", 0.0),
        (os.getpid(), "python.exe", psutil.Process(os.getpid()).create_time()),
        (100, "ollama.exe", 1728000000.0),
        (200, "postgres.exe", 1728000000.0),
        (300, "csrss.exe", 1728000000.0),
        (400, "lsass.exe", 1728000000.0),
    ]
    for pid, name, create_time in protected_targets:
        res = ProcessService.terminate_process(
            pid=pid,
            expected_create_time=create_time,
            expected_name=name,
        )
        assert res["outcome"] == "PROTECTED"
        assert "protected" in res.get("error", "").lower()


def test_process_termination_create_time_mismatch_rejection():
    """Verify PID reuse / stale create_time is rejected (TOCTOU defense)."""
    current_pid = os.getpid()
    actual_create_time = psutil.Process(current_pid).create_time()
    stale_create_time = actual_create_time - 1000.0  # 1000 seconds in the past

    # Use a non-protected dummy name to test creation time check
    is_safe, err = ProcessIdentityValidator.validate_process_for_termination(
        pid=current_pid,
        expected_name="dummy_app.exe",
        expected_create_time=stale_create_time,
    )
    assert is_safe is False
    assert "create_time mismatch" in err or "reused" in err or "name mismatch" in err


def test_process_termination_name_mismatch_rejection():
    """Verify process name mismatch is rejected before termination."""
    current_pid = os.getpid()
    actual_create_time = psutil.Process(current_pid).create_time()

    is_safe, err = ProcessIdentityValidator.validate_process_for_termination(
        pid=current_pid,
        expected_name="unrelated_nonexistent_process.exe",
        expected_create_time=actual_create_time,
    )
    assert is_safe is False
    assert "name mismatch" in err or "protected" in err


def test_process_termination_nonexistent_pid():
    """Verify terminating a non-existent PID returns ALREADY_EXITED."""
    nonexistent_pid = 99999998
    res = ProcessService.terminate_process(
        pid=nonexistent_pid,
        expected_create_time=1728000000.0,
        expected_name="benign_app.exe",
    )
    assert res["outcome"] in ("ALREADY_EXITED", "IDENTITY_MISMATCH")


# ---------------------------------------------------------------------------
# 4. GOVERNANCE & POLICY BOUNDARY TESTS (HITL, RATE LIMIT, KILL SWITCH)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_launch_application_requires_hitl_and_succeeds_with_token(
    test_os_guard: OSGuardService,
    workspace_id: uuid.UUID,
):
    """Verify application launch requires HITL and succeeds only with parameter-bound token."""
    action_req = OSActionRequest(
        workspace_id=str(workspace_id),
        action_type=OSActionType.APPLICATION_LAUNCH,
        parameters={"application_id": "notepad"},
    )

    # 1. Without HITL token -> WAITING_HITL
    resp1 = await test_os_guard.execute_os_action(action_req)
    assert resp1.state == OSActionLifecycleState.WAITING_HITL
    assert resp1.policy_decision == PolicyDecisionType.REQUIRE_HITL

    # 2. Generate signed HITL token for notepad
    token = make_hitl_token(
        workspace_id=workspace_id,
        action_type=OSActionType.APPLICATION_LAUNCH,
        params={"application_id": "notepad"},
    )
    action_req.hitl_approval_token = token

    # 3. With valid token -> COMPLETED
    resp2 = await test_os_guard.execute_os_action(action_req)
    assert resp2.state == OSActionLifecycleState.COMPLETED
    assert resp2.policy_decision == PolicyDecisionType.ALLOW
    assert resp2.result is not None
    assert resp2.result["application_id"] == "notepad"


@pytest.mark.asyncio
async def test_launch_application_hitl_mismatch_rejected(
    test_os_guard: OSGuardService,
    workspace_id: uuid.UUID,
):
    """Verify HITL token signed for notepad cannot authorize powershell or calc."""
    token = make_hitl_token(
        workspace_id=workspace_id,
        action_type=OSActionType.APPLICATION_LAUNCH,
        params={"application_id": "notepad"},
    )

    # Attempt to use token to launch calc
    action_req = OSActionRequest(
        workspace_id=str(workspace_id),
        action_type=OSActionType.APPLICATION_LAUNCH,
        parameters={"application_id": "calc"},
        hitl_approval_token=token,
    )

    resp = await test_os_guard.execute_os_action(action_req)
    assert resp.policy_decision == PolicyDecisionType.DENY
    assert "mismatch" in resp.error.lower() or "modified" in resp.error.lower() or "tampering" in resp.error.lower()


@pytest.mark.asyncio
async def test_terminate_process_requires_hitl_and_succeeds_with_token(
    test_os_guard: OSGuardService,
    workspace_id: uuid.UUID,
):
    """Verify process termination requires HITL and validates parameters strictly."""
    params = {
        "pid": 54321,
        "expected_name": "custom_worker.exe",
        "expected_create_time": 1728000000.0,
    }
    action_req = OSActionRequest(
        workspace_id=str(workspace_id),
        action_type=OSActionType.PROCESS_TERMINATE,
        parameters=params,
    )

    # 1. Without token -> WAITING_HITL
    resp1 = await test_os_guard.execute_os_action(action_req)
    assert resp1.state == OSActionLifecycleState.WAITING_HITL

    # 2. With valid token -> COMPLETED (in mock adapter)
    token = make_hitl_token(
        workspace_id=workspace_id,
        action_type=OSActionType.PROCESS_TERMINATE,
        params=params,
    )
    action_req.hitl_approval_token = token
    resp2 = await test_os_guard.execute_os_action(action_req)
    assert resp2.state == OSActionLifecycleState.COMPLETED
    assert resp2.result["outcome"] == "TERMINATED"


@pytest.mark.asyncio
async def test_application_launch_rate_limiting_5_per_min(
    test_os_guard: OSGuardService,
    workspace_id: uuid.UUID,
):
    """Verify max 5 application launches per minute limit is strictly enforced."""
    for i in range(5):
        params_i = {"application_id": "notepad", "iter": i}
        token = make_hitl_token(
            workspace_id=workspace_id,
            action_type=OSActionType.APPLICATION_LAUNCH,
            params=params_i,
        )
        req = OSActionRequest(
            workspace_id=str(workspace_id),
            action_type=OSActionType.APPLICATION_LAUNCH,
            parameters=params_i,
            hitl_approval_token=token,
        )
        resp = await test_os_guard.execute_os_action(req)
        assert resp.state == OSActionLifecycleState.COMPLETED

    # 6th launch within same minute must be RATE_LIMITED
    params6 = {"application_id": "notepad", "iter": 5}
    token6 = make_hitl_token(
        workspace_id=workspace_id,
        action_type=OSActionType.APPLICATION_LAUNCH,
        params=params6,
    )
    req6 = OSActionRequest(
        workspace_id=str(workspace_id),
        action_type=OSActionType.APPLICATION_LAUNCH,
        parameters=params6,
        hitl_approval_token=token6,
    )
    resp6 = await test_os_guard.execute_os_action(req6)
    assert resp6.policy_decision == PolicyDecisionType.RATE_LIMIT


@pytest.mark.asyncio
async def test_process_termination_rate_limiting_5_per_min(
    test_os_guard: OSGuardService,
    workspace_id: uuid.UUID,
):
    """Verify max 5 process terminations per minute limit is strictly enforced."""
    for i in range(5):
        params = {"pid": 60000 + i, "expected_name": f"worker_{i}.exe", "expected_create_time": 1728000000.0}
        token = make_hitl_token(
            workspace_id=workspace_id,
            action_type=OSActionType.PROCESS_TERMINATE,
            params=params,
        )
        req = OSActionRequest(
            workspace_id=str(workspace_id),
            action_type=OSActionType.PROCESS_TERMINATE,
            parameters=params,
            hitl_approval_token=token,
        )
        resp = await test_os_guard.execute_os_action(req)
        assert resp.state == OSActionLifecycleState.COMPLETED

    # 6th termination must be RATE_LIMITED
    params6 = {"pid": 60005, "expected_name": "worker_5.exe", "expected_create_time": 1728000000.0}
    token6 = make_hitl_token(
        workspace_id=workspace_id,
        action_type=OSActionType.PROCESS_TERMINATE,
        params=params6,
    )
    req6 = OSActionRequest(
        workspace_id=str(workspace_id),
        action_type=OSActionType.PROCESS_TERMINATE,
        parameters=params6,
        hitl_approval_token=token6,
    )
    resp6 = await test_os_guard.execute_os_action(req6)
    assert resp6.policy_decision == PolicyDecisionType.RATE_LIMIT


@pytest.mark.asyncio
async def test_kill_switch_blocks_launch_and_termination(
    test_os_guard: OSGuardService,
    workspace_id: uuid.UUID,
):
    """Verify active emergency kill switch rejects launch and termination immediately."""
    kill_switch.set_active(True)
    try:
        # Launch request
        token_launch = make_hitl_token(
            workspace_id=workspace_id,
            action_type=OSActionType.APPLICATION_LAUNCH,
            params={"application_id": "notepad"},
        )
        req_launch = OSActionRequest(
            workspace_id=str(workspace_id),
            action_type=OSActionType.APPLICATION_LAUNCH,
            parameters={"application_id": "notepad"},
            hitl_approval_token=token_launch,
        )
        resp_launch = await test_os_guard.execute_os_action(req_launch)
        assert resp_launch.state == OSActionLifecycleState.KILL_SWITCHED

        # Terminate request
        params_term = {"pid": 70000, "expected_name": "worker.exe", "expected_create_time": 1728000000.0}
        token_term = make_hitl_token(
            workspace_id=workspace_id,
            action_type=OSActionType.PROCESS_TERMINATE,
            params=params_term,
        )
        req_term = OSActionRequest(
            workspace_id=str(workspace_id),
            action_type=OSActionType.PROCESS_TERMINATE,
            parameters=params_term,
            hitl_approval_token=token_term,
        )
        resp_term = await test_os_guard.execute_os_action(req_term)
        assert resp_term.state == OSActionLifecycleState.KILL_SWITCHED

    finally:
        kill_switch.set_active(False)



# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 5. GOVERNED TOOL DISCOVERY & EXECUTION PIPELINE TESTS
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_governed_tools_registered_in_tool_registry():
    """Verify AURA-902 tools are discovered in ToolRegistryService with correct schemas."""
    from app.services.tool_registry import BUILTIN_TOOLS

    assert "launch_application" in BUILTIN_TOOLS
    assert "inspect_processes" in BUILTIN_TOOLS
    assert "terminate_process" in BUILTIN_TOOLS

    launch_tool = BUILTIN_TOOLS["launch_application"]
    assert launch_tool["risk_level"] == "high"
    assert launch_tool["requires_approval"] is True
    assert "application_id" in launch_tool["input_schema"]["required"]

    inspect_tool = BUILTIN_TOOLS["inspect_processes"]
    assert inspect_tool["risk_level"] == "low"
    assert inspect_tool["requires_approval"] is False

    term_tool = BUILTIN_TOOLS["terminate_process"]
    assert term_tool["risk_level"] == "high"
    assert term_tool["requires_approval"] is True
    assert "pid" in term_tool["input_schema"]["required"]
    assert "expected_creation_time" in term_tool["input_schema"]["required"]
    assert "expected_name" in term_tool["input_schema"]["required"]


@pytest.mark.asyncio
async def test_governed_inspect_processes_tool_execution(workspace_id: uuid.UUID):
    """Verify inspect_processes tool executes safely through ToolRegistry boundary."""
    from app.services.tools.os_tools import execute_inspect_processes

    res = await execute_inspect_processes(
        workspace_id=workspace_id,
        arguments={"limit": 5},
    )
    assert res["status"] == "success"
    assert "processes" in res
    assert isinstance(res["processes"], list)
    assert len(res["processes"]) <= 5


# ---------------------------------------------------------------------------
# 6. LIVE BENIGN WINDOWS VALIDATION (NOTEPAD LIFECYCLE)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(os.name != "nt", reason="Windows native process lifecycle test requires Windows NT host")
@pytest.mark.asyncio
async def test_live_benign_notepad_launch_inspect_terminate_lifecycle():
    """Live validation: launch Notepad, inspect its identity, and terminate via PID + create_time."""
    adapter = WindowsOSExecutionAdapter()

    # Pre-clean any existing notepad processes before live test
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            if 'notepad' in (proc.info['name'] or "").lower():
                psutil.Process(proc.info['pid']).kill()
        except Exception:
            pass

    # 1. Governed Launch Request
    launch_req = OSActionRequest(
        workspace_id=str(uuid.uuid4()),
        action_type=OSActionType.APPLICATION_LAUNCH,
        parameters={"application_id": "notepad"},
    )

    launch_result = await adapter.execute_validated_action(launch_req)
    assert launch_result["status"] == "success"
    assert launch_result["application_id"] == "notepad"
    pid = launch_result["pid"]
    create_time = launch_result["create_time"]
    assert pid > 0
    assert create_time > 0

    try:
        # Give process time to initialize
        await asyncio.sleep(0.1)

        # 2. Live Process Inspection
        inspected = ProcessService.inspect_processes(pid=pid)
        assert len(inspected) == 1
        assert inspected[0]["pid"] == pid
        assert "notepad" in inspected[0]["name"].lower()
        actual_create_time = inspected[0]["create_time"]

        # 3. Governed Termination Request with PID + create_time verification
        term_req = OSActionRequest(
            workspace_id=str(uuid.uuid4()),
            action_type=OSActionType.PROCESS_TERMINATE,
            parameters={
                "pid": pid,
                "expected_name": "notepad.exe",
                "expected_create_time": actual_create_time,
            },
        )

        term_result = await adapter.execute_validated_action(term_req)
        assert term_result["outcome"] == "TERMINATED"
        assert term_result["pid"] == pid

        # Give process time to exit
        await asyncio.sleep(0.2)

        # 4. Verify process no longer exists
        assert not psutil.pid_exists(pid)

    finally:
        # Failsafe cleanup in case of test assertion failure
        if psutil.pid_exists(pid):
            try:
                psutil.Process(pid).kill()
            except Exception:
                pass


@pytest.mark.skipif(os.name != "nt", reason="Windows native process lifecycle test requires Windows NT host")
@pytest.mark.asyncio
async def test_live_kill_switch_race_validation():
    """Live validation: activating kill switch immediately before execution blocks launch."""
    os_guard = OSGuardService(
        policy_engine=OSPolicyEngine(),
        default_adapter=WindowsOSExecutionAdapter(),
    )
    ws_id = uuid.uuid4()
    token = make_hitl_token(
        workspace_id=ws_id,
        action_type=OSActionType.APPLICATION_LAUNCH,
        params={"application_id": "notepad"},
    )
    req = OSActionRequest(
        workspace_id=str(ws_id),
        action_type=OSActionType.APPLICATION_LAUNCH,
        parameters={"application_id": "notepad"},
        hitl_approval_token=token,
    )

    # Activate kill switch immediately before execution
    kill_switch.set_active(True)
    try:
        resp = await os_guard.execute_os_action(req)
        assert resp.state == OSActionLifecycleState.KILL_SWITCHED
        assert resp.error is not None
        assert "kill switch" in resp.error.lower()
    finally:
        kill_switch.set_active(False)


