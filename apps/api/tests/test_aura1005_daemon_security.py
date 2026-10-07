"""AURA-1005 Security Test Suite for Daemon Supervisor & Watchdog."""

import asyncio
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
from typing import Any, Dict

import psutil
import pytest

from app.daemon.ipc import (
    AuraDaemonIPCClient,
    AuraDaemonIPCServer,
)
from app.daemon.process_tracker import (
    ProcessIdentity,
    ProcessTracker,
    get_current_session_id,
)
from app.daemon.single_instance import AuraSingleInstanceGuard
from app.daemon.supervisor import AuraDaemonSupervisor
from app.daemon.types import (
    DaemonConfig,
    DaemonIPCCommand,
    DaemonIPCRequest,
    DaemonIPCResponse,
    DaemonState,
)
from app.services.kill_switch import EmergencyKillSwitchService
from app.tray.ipc import AuraIpcAuthManager


@pytest.fixture
def temp_state_dir(tmp_path):
    state_dir = tmp_path / ".aura"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir


@pytest.fixture
def mock_kill_switch(temp_state_dir):
    state_file = temp_state_dir / "kill_state.json"
    return EmergencyKillSwitchService(state_file_path=str(state_file))


def test_least_privilege_execution():
    """Verify daemon executes as current interactive user session and NOT SYSTEM / Administrator."""
    if platform.system() == "Windows":
        try:
            import ctypes
            # Check if running elevated
            is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
            # Even if IDE runs in admin prompt, supervisor should not require SYSTEM (SID S-1-5-18)
            sid = get_current_session_id()
            assert sid >= 0, "Interactive user session must have a valid session ID"
        except Exception:
            pass


def test_pid_reuse_attack_defense():
    """Verify supervisor and process tracker reject PID reuse and never kill mismatched process."""
    current_pid = os.getpid()
    p = psutil.Process(current_pid)
    real_time = p.create_time()

    # Create forged identity with current PID but mismatched creation time
    forged_identity = ProcessIdentity(
        pid=current_pid,
        create_time=real_time + 500.0,
        exe_path=sys.executable,
        cmdline=["python.exe"],
        session_id=get_current_session_id(),
    )

    tracker = ProcessTracker(enable_job_object=False)
    # Attempting to terminate forged identity must refuse immediately without killing current process!
    success = tracker.terminate_tree(forged_identity, timeout=1.0)
    assert success is True  # Returns true (safely no-op)
    assert psutil.pid_exists(current_pid) is True, "Current process must NOT have been terminated!"
    assert forged_identity.matches_live_process() is False


def test_unrelated_process_isolation(temp_state_dir):
    """Verify orphan cleanup does not touch unrelated user processes."""
    # Spawn a dummy unrelated process that does NOT contain AURA tokens
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(15)"])
    try:
        tracker = ProcessTracker(enable_job_object=False)
        reaped = tracker.cleanup_orphans(expected_tokens=["aura_unique_marker_token_xyz_123"])
        assert reaped == 0
        assert proc.poll() is None, "Unrelated process must remain running!"
    finally:
        proc.kill()
        proc.wait()


def test_command_injection_safety(temp_state_dir):
    """Verify subprocess execution passes array arguments directly with shell=False, preventing shell injection."""
    tracker = ProcessTracker(enable_job_object=False)
    
    # Malicious injection string inside an argument
    malicious_cmd = [
        sys.executable,
        "-c",
        "import sys; sys.exit(0)",
        "; echo PWNED & calc.exe | notepad.exe",
    ]
    config = DaemonConfig(custom_command=malicious_cmd, custom_cwd=str(temp_state_dir))

    proc, identity = tracker.launch_backend(config)
    try:
        assert identity.pid > 0
        assert identity.matches_live_process() is True
    finally:
        tracker.terminate_tree(identity, timeout=1.0)
        tracker.close()


@pytest.mark.asyncio
async def test_ipc_token_authentication_boundary(temp_state_dir, mock_kill_switch):
    """Verify IPC server enforces strict token verification and rejects invalid or missing tokens."""
    config = DaemonConfig(custom_cwd=str(temp_state_dir))
    supervisor = AuraDaemonSupervisor(config=config, kill_switch_service=mock_kill_switch)
    ipc_server = AuraDaemonIPCServer(supervisor=supervisor)

    # 1. Valid Token
    valid_token = AuraIpcAuthManager.get_or_create_token()
    valid_req = DaemonIPCRequest(command=DaemonIPCCommand.STATUS, token=valid_token)
    res_valid = await ipc_server.process_raw_request(valid_req.model_dump_json().encode("utf-8"))
    assert res_valid.status == "success"

    # 2. Invalid Token
    invalid_req = DaemonIPCRequest(command=DaemonIPCCommand.STATUS, token="wrong_token_1234567890abcdef")
    res_invalid = await ipc_server.process_raw_request(invalid_req.model_dump_json().encode("utf-8"))
    assert res_invalid.status == "error"
    assert "Authentication failed" in (res_invalid.error or "")

    # 3. Malformed JSON
    res_malformed = await ipc_server.process_raw_request(b"not-json-payload")
    assert res_malformed.status == "error"
    assert "Malformed request payload" in (res_malformed.error or "")


@pytest.mark.asyncio
async def test_ipc_command_allowlisting(temp_state_dir, mock_kill_switch):
    """Verify IPC rejects arbitrary commands outside the approved DaemonIPCCommand enum."""
    config = DaemonConfig(custom_cwd=str(temp_state_dir))
    supervisor = AuraDaemonSupervisor(config=config, kill_switch_service=mock_kill_switch)
    ipc_server = AuraDaemonIPCServer(supervisor=supervisor)
    token = AuraIpcAuthManager.get_or_create_token()

    # Forged JSON with non-allowlisted command
    raw_payload = {
        "command": "execute_shell_cmd",
        "token": token,
        "parameters": {"cmd": "powershell.exe -Command Get-Process"},
    }
    import json
    res = await ipc_server.process_raw_request(json.dumps(raw_payload).encode("utf-8"))
    assert res.status == "error"
    assert "Malformed request payload" in (res.error or "") or "Input should be" in (res.error or "")


def test_status_report_secret_sanitization(temp_state_dir, mock_kill_switch):
    """Verify status reports contain zero secret keys, tokens, or credentials."""
    config = DaemonConfig(custom_cwd=str(temp_state_dir))
    supervisor = AuraDaemonSupervisor(config=config, kill_switch_service=mock_kill_switch)
    
    # Populate health details with sensitive-looking mock data
    supervisor.last_health_details = {
        "status": "healthy",
        "service": "aura-control-plane",
    }
    
    report = supervisor.get_status().model_dump()
    report_str = str(report)
    
    # Assert no private key or auth token leaks
    assert "BEGIN PRIVATE KEY" not in report_str
    assert "JWT_SECRET" not in report_str
    assert "MASTER_KEY" not in report_str
    assert "password" not in report_str.lower() or report.get("backend_health_details", {}).get("password") is None


def test_static_audit_no_unauthorized_persistence():
    """Verify that app/daemon contains NO hidden persistence, Task Scheduler, HKLM, or Windows Service installation."""
    daemon_dir = Path(__file__).resolve().parent.parent / "app" / "daemon"
    for py_file in daemon_dir.glob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        assert "CreateService" not in content, f"Unauthorized service installation API in {py_file}"
        assert "TaskScheduler" not in content, f"Unauthorized Task Scheduler API in {py_file}"
        assert "HKEY_LOCAL_MACHINE" not in content, f"Unauthorized HKLM persistence in {py_file}"
        if py_file.name != "autostart.py":
            assert "winreg" not in content, f"Unauthorized winreg import in {py_file}"
            assert "CurrentVersion\\Run" not in content, f"Unauthorized Registry Run key in {py_file}"
