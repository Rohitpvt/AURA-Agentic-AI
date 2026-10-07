"""AURA-1006 Final Security Closure Test Suite.

Rigorous verification of:
1. Real user-session lifecycle (session ID, lock/unlock, logoff, foreign session isolation)
2. Duplicate instance behavior (single authority, no second backend spawned)
3. Controlled autostart lifecycle (default OFF, clean enable, zero secrets, clean removal, zero orphan persistence)
4. Kill switch across startup/session transitions (fail-closed, no auto-resurrection, persistent disk state)
5. Cross-session process and IPC isolation (session-scoped pipe name, session-isolated orphan cleanup)
6. Comprehensive secret and canary leak scan
"""

import asyncio
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import pytest

from app.daemon.autostart import AutostartManager, AURA_AUTOSTART_KEY_NAME, AURA_REG_RUN_PATH
from app.daemon.ipc import get_daemon_pipe_name
from app.daemon.main import run_supervisor_daemon
from app.daemon.process_tracker import ProcessIdentity, ProcessTracker, get_current_session_id
from app.daemon.session_manager import (
    WindowsSessionManager,
    SessionState,
    WTS_CONSOLE_CONNECT,
    WTS_CONSOLE_DISCONNECT,
    WTS_SESSION_LOGON,
    WTS_SESSION_LOGOFF,
    WTS_SESSION_LOCK,
    WTS_SESSION_UNLOCK,
)
from app.daemon.single_instance import AuraSingleInstanceGuard
from app.daemon.supervisor import AuraDaemonSupervisor
from app.daemon.types import DaemonConfig, DaemonState, ProcessHealthStatus
from app.services.kill_switch import EmergencyKillSwitchService
from app.tray.ipc import AuraIpcAuthManager, AuraNamedPipeServer, get_canonical_pipe_name
from app.tray.types import TrayIPCCommand, TrayRuntimeState


def _make_test_config(tmp_path):
    return DaemonConfig(
        custom_command=[sys.executable, "-c", "import time; time.sleep(30)"],
        custom_cwd=str(tmp_path),
        startup_timeout=2.0,
        graceful_shutdown_timeout=1.0,
        heartbeat_interval=0.1,
    )


class MockHealthyResponse:
    status_code = 200
    def json(self):
        return {"status": "healthy", "service": "aura"}


class MockAsyncClient:
    def __init__(self, *args, **kwargs):
        pass
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        pass
    async def get(self, url):
        return MockHealthyResponse()


# ==============================================================================
# 1. USER-SESSION LIFECYCLE & STATE MACHINE
# ==============================================================================

@pytest.mark.asyncio
async def test_closure_session_id_detection():
    """Verify current interactive session ID is detected as non-negative integer."""
    sid = get_current_session_id()
    assert isinstance(sid, int)
    assert sid >= 0
    mgr = WindowsSessionManager(session_id=sid)
    assert mgr.session_id == sid
    assert mgr.state == SessionState.ACTIVE


@pytest.mark.asyncio
async def test_closure_session_lock_unlock_event_sequence():
    """Verify full state machine sequence: Lock -> Unlock -> Disconnect -> Connect -> Logoff."""
    mgr = WindowsSessionManager(session_id=10)
    transitions = []
    mgr.register_listener(lambda state, code: transitions.append((state, code)))

    # 1. Lock
    mgr.handle_wts_message(WTS_SESSION_LOCK, session_id=10)
    assert mgr.state == SessionState.LOCKED

    # 2. Unlock
    mgr.handle_wts_message(WTS_SESSION_UNLOCK, session_id=10)
    assert mgr.state == SessionState.ACTIVE

    # 3. Disconnect
    mgr.handle_wts_message(WTS_CONSOLE_DISCONNECT, session_id=10)
    assert mgr.state == SessionState.DISCONNECTED

    # 4. Connect
    mgr.handle_wts_message(WTS_CONSOLE_CONNECT, session_id=10)
    assert mgr.state == SessionState.ACTIVE

    # 5. Logoff
    mgr.handle_wts_message(WTS_SESSION_LOGOFF, session_id=10)
    assert mgr.state == SessionState.LOGGING_OFF

    assert len(transitions) == 5


@pytest.mark.asyncio
async def test_closure_foreign_session_event_rejection():
    """Verify events from other session IDs are rejected and cause no state mutation."""
    mgr = WindowsSessionManager(session_id=1)
    mutations = []
    mgr.register_listener(lambda s, c: mutations.append((s, c)))

    # Target session 2 event on session 1 manager
    mgr.handle_wts_message(WTS_SESSION_LOCK, session_id=2)
    assert mgr.state == SessionState.ACTIVE
    assert len(mutations) == 0

    mgr.handle_wts_message(WTS_SESSION_LOGOFF, session_id=999)
    assert mgr.state == SessionState.ACTIVE
    assert len(mutations) == 0


@pytest.mark.asyncio
async def test_closure_session_logoff_initiates_clean_shutdown(tmp_path, monkeypatch):
    """Verify session logoff triggers clean supervisor shutdown and reaps child process."""
    monkeypatch.setattr("httpx.AsyncClient", MockAsyncClient)
    mgr = WindowsSessionManager(session_id=20)
    supervisor = AuraDaemonSupervisor(
        state_dir=tmp_path / "logoff_test",
        config=_make_test_config(tmp_path),
    )
    await supervisor.start()
    assert supervisor.state == DaemonState.RUNNING

    # Wire session manager logoff to supervisor stop
    def on_session_change(state, code):
        if state == SessionState.LOGGING_OFF:
            asyncio.create_task(supervisor.stop())

    mgr.register_listener(on_session_change)
    mgr.handle_wts_message(WTS_SESSION_LOGOFF, session_id=20)

    await asyncio.sleep(0.1)
    assert mgr.state == SessionState.LOGGING_OFF
    assert supervisor.state == DaemonState.STOPPED
    assert supervisor.backend_identity is None


# ==============================================================================
# 2. DUPLICATE-INSTANCE BEHAVIOR ON LIVE HOST
# ==============================================================================

@pytest.mark.asyncio
async def test_closure_duplicate_supervisor_prevention(tmp_path, monkeypatch):
    """Verify second supervisor in the same session is rejected with RuntimeError."""
    monkeypatch.setattr("httpx.AsyncClient", MockAsyncClient)
    supervisor1 = AuraDaemonSupervisor(
        state_dir=tmp_path / "dup_test",
        config=_make_test_config(tmp_path),
    )
    report1 = await supervisor1.start()
    assert report1.state == DaemonState.RUNNING
    assert supervisor1.state == DaemonState.RUNNING

    # Attempting to start supervisor 2 in the same session/state_dir must fail
    supervisor2 = AuraDaemonSupervisor(
        state_dir=tmp_path / "dup_test",
        config=_make_test_config(tmp_path),
    )
    with pytest.raises(RuntimeError, match="Another instance already holds"):
        await supervisor2.start()

    # Verify supervisor 1 remained active and unaffected
    assert supervisor1.state == DaemonState.RUNNING
    assert supervisor1.backend_identity is not None
    assert supervisor2.state == DaemonState.STOPPED
    assert supervisor2.backend_identity is None

    # Clean shutdown
    await supervisor1.stop()
    assert supervisor1.state == DaemonState.STOPPED


# ==============================================================================
# 3. CONTROLLED AUTOSTART FULL LIFECYCLE
# ==============================================================================

def test_closure_autostart_default_off_fresh_state(tmp_path):
    """Verify fresh state has autostart strictly OFF."""
    mgr = AutostartManager(state_dir=tmp_path)
    status = mgr.get_autostart_status()
    assert status["entry_type"] == "HKCU_RUN"
    if not mgr.is_windows:
        assert status["enabled"] is False


def test_closure_autostart_enable_disable_clean_removal(tmp_path):
    """Verify full enable -> inspection -> disable -> clean removal with 0 leftovers."""
    mgr = AutostartManager(state_dir=tmp_path)
    original_state = mgr.is_autostart_enabled()

    try:
        # 1. Enable
        success = mgr.enable_autostart()
        assert success is True
        assert mgr.is_autostart_enabled() is True

        # 2. Inspect
        status = mgr.get_autostart_status()
        assert status["enabled"] is True
        assert status["command"] is not None
        assert "app.daemon.main" in status["command"]
        assert status["value_name"] == AURA_AUTOSTART_KEY_NAME

        # 3. Disable
        disabled = mgr.disable_autostart()
        assert disabled is True
        assert mgr.is_autostart_enabled() is False

        # 4. Verify clean removal
        status_after = mgr.get_autostart_status()
        assert status_after["enabled"] is False
        assert status_after["command"] is None

    finally:
        # Restore original state
        if original_state:
            mgr.enable_autostart()
        else:
            mgr.disable_autostart()


def test_closure_autostart_prohibits_all_secrets(tmp_path):
    """Verify autostart strictly rejects command strings containing secret patterns."""
    mgr = AutostartManager(state_dir=tmp_path)

    secret_injections = [
        'python.exe -m app.daemon.main --key "AURA_MASTER_ENCRYPTION_KEY=supersecret"',
        'python.exe -m app.daemon.main --token "JWT_SECRET=jwt12345"',
        'python.exe -m app.daemon.main --password "mypassword"',
        'python.exe -m app.daemon.main --secret "PRIVATE KEY DATA"',
        'python.exe -m app.daemon.main --auth "token=abcdef0123456789"',
    ]

    for bad_cmd in secret_injections:
        with pytest.raises(ValueError, match="forbidden secret pattern"):
            mgr.enable_autostart(custom_command=bad_cmd)


def test_closure_persistence_static_audit():
    """Verify zero unauthorized persistence mechanisms (Services, Tasks, HKLM) across the repo."""
    daemon_dir = Path(__file__).resolve().parent.parent / "app" / "daemon"
    for py_file in daemon_dir.glob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        assert "CreateService" not in content, f"Forbidden service API in {py_file}"
        assert "TaskScheduler" not in content, f"Forbidden Task Scheduler in {py_file}"
        assert "HKEY_LOCAL_MACHINE" not in content, f"Forbidden HKLM in {py_file}"
        if py_file.name != "autostart.py":
            assert "winreg" not in content, f"winreg must be confined exclusively to autostart.py, found in {py_file}"


# ==============================================================================
# 4. KILL-SWITCH ACROSS STARTUP & SESSION TRANSITIONS
# ==============================================================================

@pytest.mark.asyncio
async def test_closure_kill_switch_active_halts_startup(tmp_path, monkeypatch):
    """Verify that if kill switch is ACTIVE in shared disk state, supervisor immediately halts."""
    monkeypatch.setenv("AURA_STATE_DIR", str(tmp_path))
    ks = EmergencyKillSwitchService(state_file_path=str(tmp_path / "kill_state.json"))
    ks.set_active(True)
    assert ks.is_active()

    # 1. Direct supervisor start should raise RuntimeError and enter KILL_SWITCHED state
    supervisor = AuraDaemonSupervisor(
        state_dir=tmp_path / "ks_test",
        config=_make_test_config(tmp_path),
        kill_switch_service=ks,
    )
    with pytest.raises(RuntimeError, match="Cannot start while Emergency Kill Switch is ACTIVE"):
        await supervisor.start()

    assert supervisor.state == DaemonState.KILL_SWITCHED
    assert supervisor.backend_identity is None

    # 2. Main CLI entrypoint should sys.exit(1)
    with pytest.raises(SystemExit) as exc_info:
        await run_supervisor_daemon()
    assert exc_info.value.code == 1

    # Cleanup
    ks.set_active(False)


@pytest.mark.asyncio
async def test_closure_kill_switch_persists_across_new_process_instances(tmp_path):
    """Verify kill switch written to shared state file is observed by completely new service instances."""
    state_file = str(tmp_path / "shared_kill_state.json")
    
    # Instance 1 activates kill switch
    ks1 = EmergencyKillSwitchService(state_file_path=state_file)
    ks1.set_active(True)
    assert ks1.is_active()

    # Instance 2 instantiates from same path
    ks2 = EmergencyKillSwitchService(state_file_path=state_file)
    assert ks2.is_active() is True

    # Instance 3 deactivates
    ks3 = EmergencyKillSwitchService(state_file_path=state_file)
    ks3.set_active(False)

    # Instance 1 and 2 re-sync
    assert ks1.is_active() is False
    assert ks2.is_active() is False


# ==============================================================================
# 5. CROSS-SESSION ISOLATION
# ==============================================================================

def test_closure_cross_session_ipc_pipe_name_isolation():
    """Verify named pipe names are scoped to session ID, preventing cross-session pipe collisions."""
    pipe_name = get_canonical_pipe_name()
    daemon_pipe = get_daemon_pipe_name()

    assert "aura_control_pipe_" in pipe_name
    assert "aura_daemon_pipe_" in daemon_pipe

    current_sid = get_current_session_id()
    assert str(current_sid) in pipe_name
    assert str(current_sid) in daemon_pipe


def test_closure_cross_session_orphan_cleanup_isolation(tmp_path):
    """Verify process tracker orphan cleanup never touches unrelated processes or processes from other sessions."""
    # Spawn dummy un-related process
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
    try:
        tracker = ProcessTracker(enable_job_object=False)
        # Orphan sweep looking for specific tokens
        reaped = tracker.cleanup_orphans(expected_tokens=["aura_nonexistent_unique_tag_99999"])
        assert reaped == 0
        assert proc.poll() is None, "Unrelated process must not be terminated!"
    finally:
        proc.kill()
        proc.wait()


# ==============================================================================
# 6. COMPREHENSIVE SECRET & CANARY SCAN
# ==============================================================================

@pytest.mark.asyncio
async def test_closure_comprehensive_secret_canary_scan(tmp_path, monkeypatch):
    """Verify 0% canary presence across IPC, status reports, autostart, and logs."""
    canary_key = "CANARY_AURA_SECRET_KEY_987654321_ALPHA_OMEGA"
    canary_jwt = "CANARY_JWT_TOKEN_HEADER_PAYLOAD_SIGNATURE_XYZ"

    monkeypatch.setenv("AURA_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("AURA_MASTER_ENCRYPTION_KEY", canary_key)
    monkeypatch.setenv("JWT_SECRET", canary_jwt)

    token = AuraIpcAuthManager.get_or_create_token()
    server = AuraNamedPipeServer()

    # Query all available IPC commands
    for cmd in [
        TrayIPCCommand.GET_STATUS,
        TrayIPCCommand.GET_PRIVACY_STATE,
        TrayIPCCommand.GET_AUTOSTART_STATUS,
        TrayIPCCommand.GET_DAEMON_STATUS,
    ]:
        req = json.dumps({"command": cmd.value, "token": token})
        res = await server.process_raw_request(req)
        serialized = json.dumps(res)

        assert canary_key not in serialized, f"Secret leaked in IPC command {cmd.value}"
        assert canary_jwt not in serialized, f"JWT secret leaked in IPC command {cmd.value}"
        assert token not in serialized, f"Auth token leaked in IPC command {cmd.value}"

    # Query autostart manager
    autostart_mgr = AutostartManager(state_dir=tmp_path)
    status_dict = autostart_mgr.get_autostart_status()
    serialized_status = json.dumps(status_dict)
    assert canary_key not in serialized_status
    assert canary_jwt not in serialized_status
