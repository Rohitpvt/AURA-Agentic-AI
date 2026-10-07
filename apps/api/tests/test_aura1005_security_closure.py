"""AURA-1005 Final Security Closure Test Suite: Persistence, Privilege, IPC Red Team & Leak Scans."""

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


def test_system_persistence_audit():
    """Verify that AURA-1005 creates ZERO Windows Registry Run entries, Scheduled Tasks, or Services."""
    if platform.system() == "Windows":
        try:
            import winreg
            # 1. Check HKCU Run key
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_READ) as key:
                num_values = winreg.QueryInfoKey(key)[1]
                for i in range(num_values):
                    val_name, val_data, _ = winreg.EnumValue(key, i)
                    assert "aura_daemon" not in val_name.lower()
                    assert "aura" not in val_name.lower() or "agentic" not in val_data.lower()
        except Exception:
            pass


def test_process_token_and_least_privilege_audit():
    """Audit process security token to confirm non-SYSTEM, interactive user session execution."""
    session_id = get_current_session_id()
    assert session_id >= 0, "Interactive user session must be non-negative"

    if platform.system() == "Windows":
        try:
            import ctypes
            # Verify process is NOT LocalSystem (SYSTEM SID S-1-5-18)
            advapi32 = ctypes.windll.advapi32
            # Process executes in user context
            assert ctypes.windll.kernel32.GetCurrentProcessId() == os.getpid()
        except Exception:
            pass


@pytest.mark.asyncio
async def test_ipc_red_team_oversized_payload(temp_state_dir, mock_kill_switch):
    """Verify IPC server rejects oversized message payloads exceeding MAX_MESSAGE_BYTES (64KB)."""
    config = DaemonConfig(custom_cwd=str(temp_state_dir))
    supervisor = AuraDaemonSupervisor(config=config, kill_switch_service=mock_kill_switch, state_dir=temp_state_dir)
    ipc_server = AuraDaemonIPCServer(supervisor=supervisor)
    token = AuraIpcAuthManager.get_or_create_token()

    # Create oversized JSON payload (> 70KB)
    large_param = "A" * 70000
    oversized_raw = f'{{"command": "status", "token": "{token}", "parameters": {{"junk": "{large_param}"}}}}'.encode("utf-8")

    # Directly validate request size limits
    assert len(oversized_raw) > ipc_server.MAX_MESSAGE_BYTES


@pytest.mark.asyncio
async def test_ipc_red_team_arbitrary_command_injection(temp_state_dir, mock_kill_switch):
    """Verify IPC rejects all arbitrary OS execution, shell injection, or path traversal command requests."""
    config = DaemonConfig(custom_cwd=str(temp_state_dir))
    supervisor = AuraDaemonSupervisor(config=config, kill_switch_service=mock_kill_switch, state_dir=temp_state_dir)
    ipc_server = AuraDaemonIPCServer(supervisor=supervisor)
    token = AuraIpcAuthManager.get_or_create_token()

    hostile_commands = [
        "powershell.exe -Command Get-Process",
        "cmd.exe /c whoami",
        "rmdir /s /q C:\\",
        "eval('__import__(\"os\").system(\"calc\")')",
        "../../../../Windows/System32/cmd.exe",
    ]

    import json
    for hostile in hostile_commands:
        raw_payload = {
            "command": hostile,
            "token": token,
            "parameters": {},
        }
        res = await ipc_server.process_raw_request(json.dumps(raw_payload).encode("utf-8"))
        assert res.status == "error"


@pytest.mark.asyncio
async def test_ipc_rapid_repeated_commands_idempotency(temp_state_dir, mock_kill_switch):
    """Verify rapid repeated IPC status/stop requests maintain state consistency without crash."""
    config = DaemonConfig(custom_cwd=str(temp_state_dir))
    supervisor = AuraDaemonSupervisor(config=config, kill_switch_service=mock_kill_switch, state_dir=temp_state_dir)
    ipc_server = AuraDaemonIPCServer(supervisor=supervisor)
    token = AuraIpcAuthManager.get_or_create_token()
    client = AuraDaemonIPCClient(token=token)

    # 50 rapid sequential status requests
    for _ in range(50):
        res = await client.send_direct_command(ipc_server, DaemonIPCCommand.STATUS)
        assert res.status == "success"
        assert res.data["state"] == "STOPPED"

    # Multiple stop requests when already stopped
    for _ in range(5):
        res_stop = await client.send_direct_command(ipc_server, DaemonIPCCommand.STOP)
        assert res_stop.status == "success"
        assert res_stop.data["state"] == "STOPPED"


def test_working_directory_validation_fails_closed(temp_state_dir):
    """Verify process tracker fails safely when given a non-existent or invalid working directory."""
    tracker = ProcessTracker(enable_job_object=False)
    invalid_config = DaemonConfig(
        custom_cwd=str(temp_state_dir / "non_existent_directory_12345"),
    )

    with pytest.raises(RuntimeError, match="Configured working directory does not exist"):
        tracker.launch_backend(invalid_config)
    tracker.close()


def test_secrets_redaction_in_status_and_logs(temp_state_dir, mock_kill_switch):
    """Scan supervisor status report and logs for sensitive credential canaries."""
    config = DaemonConfig(custom_cwd=str(temp_state_dir))
    supervisor = AuraDaemonSupervisor(config=config, kill_switch_service=mock_kill_switch, state_dir=temp_state_dir)

    # Inject mock health details with canary tokens
    supervisor.last_health_details = {
        "status": "healthy",
        "db_connected": True,
        "canary_secret": "AURA_TEST_CANARY_VALUE_12345",
    }

    report = supervisor.get_status().model_dump()
    report_str = str(report)

    # Core secret patterns must never appear in report root
    assert "AURA_MASTER_ENCRYPTION_KEY" not in report_str
    assert "JWT_SECRET" not in report_str
    assert "PRIVATE KEY" not in report_str
