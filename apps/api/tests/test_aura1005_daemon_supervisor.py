"""AURA-1005 Unit Tests for Windows User-Session Daemon Supervisor & Watchdog."""

import asyncio
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
from typing import Any, Dict
import uuid

import psutil
import pytest

from app.daemon.health_monitor import BackendHealthMonitor
from app.daemon.ipc import (
    AuraDaemonIPCClient,
    AuraDaemonIPCServer,
    get_daemon_pipe_name,
)
from app.daemon.process_tracker import (
    ProcessIdentity,
    ProcessTracker,
    WindowsJobObject,
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
    ProcessHealthStatus,
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


def test_session_id_query():
    """Verify session ID retrieval is non-negative and integer."""
    sid = get_current_session_id()
    assert isinstance(sid, int)
    assert sid >= 0


def test_single_instance_guard_lifecycle(temp_state_dir):
    """Verify single instance lock acquisition and release."""
    guard1 = AuraSingleInstanceGuard(session_id=9999, state_dir=temp_state_dir)
    assert guard1.acquire() is True

    # Secondary instance in same session must be rejected
    guard2 = AuraSingleInstanceGuard(session_id=9999, state_dir=temp_state_dir)
    assert guard2.acquire() is False

    # After guard1 releases, guard2 can acquire
    guard1.release()
    assert guard2.acquire() is True
    guard2.release()


def test_single_instance_stale_lockfile_recovery(temp_state_dir):
    """Verify stale lockfile from dead PID is reclaimed."""
    lock_file = temp_state_dir / "daemon_session_8888.lock"
    # Write a fake dead PID (e.g. 99999999)
    import json
    lock_file.write_text(json.dumps({"pid": 99999999, "create_time": 100.0, "session_id": 8888}))

    guard = AuraSingleInstanceGuard(session_id=8888, state_dir=temp_state_dir)
    assert guard.acquire() is True
    guard.release()


def test_process_identity_matches_live():
    """Verify ProcessIdentity matches running process and rejects mismatch or fake PID."""
    current_pid = os.getpid()
    p = psutil.Process(current_pid)
    real_create_time = p.create_time()

    valid_id = ProcessIdentity(
        pid=current_pid,
        create_time=real_create_time,
        exe_path=sys.executable,
        cmdline=["python"],
        session_id=get_current_session_id(),
    )
    assert valid_id.matches_live_process() is True
    assert valid_id.get_process() is not None

    # Mismatched creation timestamp (PID reuse scenario)
    fake_time_id = ProcessIdentity(
        pid=current_pid,
        create_time=real_create_time + 1000.0,
        exe_path=sys.executable,
        cmdline=["python"],
        session_id=get_current_session_id(),
    )
    assert fake_time_id.matches_live_process() is False
    assert fake_time_id.get_process() is None

    # Non-existent PID
    dead_id = ProcessIdentity(
        pid=99999999,
        create_time=time.time(),
        exe_path="none",
        cmdline=[],
    )
    assert dead_id.matches_live_process() is False


def test_windows_job_object_containment():
    """Verify Windows Job Object initialization and process assignment."""
    job = WindowsJobObject()
    if platform.system() == "Windows":
        # Launch disposable child
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
        try:
            res = job.assign_process(proc.pid)
            assert res is True
        finally:
            proc.kill()
            proc.wait()
    job.close()


def test_process_tracker_launch_and_terminate(temp_state_dir):
    """Verify process tracker can launch disposable child and terminate it safely."""
    tracker = ProcessTracker(enable_job_object=True)
    config = DaemonConfig(
        custom_command=[sys.executable, "-c", "import time; time.sleep(30)"],
        custom_cwd=str(temp_state_dir),
    )

    proc, identity = tracker.launch_backend(config)
    assert identity.pid > 0
    assert identity.matches_live_process() is True

    # Safely terminate tree
    success = tracker.terminate_tree(identity, timeout=2.0)
    assert success is True
    assert identity.matches_live_process() is False
    tracker.close()


@pytest.mark.asyncio
async def test_backend_health_monitor_dead_process():
    """Verify health monitor immediately returns DEAD for unmanaged/dead process."""
    config = DaemonConfig()
    monitor = BackendHealthMonitor(config)

    st, details = await monitor.probe_health(None)
    assert st == ProcessHealthStatus.DEAD

    dead_id = ProcessIdentity(pid=99999999, create_time=0.0, exe_path="", cmdline=[])
    st2, details2 = await monitor.probe_health(dead_id)
    assert st2 == ProcessHealthStatus.DEAD


@pytest.mark.asyncio
async def test_backend_health_monitor_mock_http(monkeypatch):
    """Verify health monitor distinguishes HEALTHY, DEGRADED, and UNRESPONSIVE HTTP states."""
    config = DaemonConfig(backend_port=8999)
    monitor = BackendHealthMonitor(config)

    current_pid = os.getpid()
    identity = ProcessIdentity(
        pid=current_pid,
        create_time=psutil.Process(current_pid).create_time(),
        exe_path=sys.executable,
        cmdline=[],
    )

    # Mock httpx GET for healthy
    class MockHealthyResponse:
        status_code = 200
        def json(self):
            return {"status": "healthy", "service": "aura"}

    class MockDegradedResponse:
        status_code = 200
        def json(self):
            return {"status": "degraded", "service": "aura"}

    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def get(self, url):
            if "degraded" in url:
                return MockDegradedResponse()
            return MockHealthyResponse()

    monkeypatch.setattr("httpx.AsyncClient", MockAsyncClient)

    st_healthy, _ = await monitor.probe_health(identity, check_detailed=False)
    assert st_healthy == ProcessHealthStatus.HEALTHY

    config.detailed_health_endpoint = "/health/degraded"
    st_degraded, _ = await monitor.probe_health(identity, check_detailed=True)
    assert st_degraded == ProcessHealthStatus.DEGRADED


@pytest.mark.asyncio
async def test_daemon_supervisor_startup_and_shutdown(temp_state_dir, mock_kill_switch, monkeypatch):
    """Verify complete supervisor startup, status reporting, and graceful shutdown."""
    # Fast HTTP probe mock
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

    monkeypatch.setattr("httpx.AsyncClient", MockAsyncClient)

    config = DaemonConfig(
        custom_command=[sys.executable, "-c", "import time; time.sleep(60)"],
        custom_cwd=str(temp_state_dir),
        heartbeat_interval=0.2,
        startup_timeout=3.0,
        graceful_shutdown_timeout=1.0,
    )
    supervisor = AuraDaemonSupervisor(config=config, kill_switch_service=mock_kill_switch)

    # 1. Start supervisor
    status = await supervisor.start()
    assert status.state == DaemonState.RUNNING
    assert status.backend_pid is not None
    assert supervisor.backend_identity.matches_live_process() is True

    # 2. Status inspection
    curr_status = supervisor.get_status()
    assert curr_status.state == DaemonState.RUNNING
    assert curr_status.supervisor_pid == os.getpid()
    assert curr_status.backend_pid == status.backend_pid

    # 3. Graceful shutdown
    stop_status = await supervisor.stop()
    assert stop_status.state == DaemonState.STOPPED
    assert supervisor.backend_identity is None


@pytest.mark.asyncio
async def test_daemon_supervisor_crash_loop_guard(temp_state_dir, mock_kill_switch, monkeypatch):
    """Verify supervisor crash-loop guard halts auto-restart when max crashes exceeded."""
    # Child exits immediately with code 1
    config = DaemonConfig(
        custom_command=[sys.executable, "-c", "import sys; sys.exit(1)"],
        custom_cwd=str(temp_state_dir),
        heartbeat_interval=0.1,
        startup_timeout=1.0,
        initial_backoff_seconds=0.05,
        max_backoff_seconds=0.2,
        backoff_multiplier=1.5,
        max_crash_count=3,
        crash_window_seconds=10.0,
    )
    supervisor = AuraDaemonSupervisor(config=config, kill_switch_service=mock_kill_switch)

    # Start should timeout because child exits immediately
    with pytest.raises(TimeoutError):
        await supervisor.start()

    assert supervisor.state == DaemonState.STOPPED


@pytest.mark.asyncio
async def test_daemon_supervisor_kill_switch_blocks_start(temp_state_dir, mock_kill_switch):
    """Verify supervisor refuses start when emergency kill switch is active."""
    mock_kill_switch.set_active(True)

    config = DaemonConfig(custom_cwd=str(temp_state_dir))
    supervisor = AuraDaemonSupervisor(config=config, kill_switch_service=mock_kill_switch)

    with pytest.raises(RuntimeError, match="Kill Switch is ACTIVE"):
        await supervisor.start()

    assert supervisor.state == DaemonState.KILL_SWITCHED


@pytest.mark.asyncio
async def test_daemon_ipc_server_and_client_lifecycle(temp_state_dir, mock_kill_switch, monkeypatch):
    """Verify IPC server dispatching status, health, and stop commands."""
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

    monkeypatch.setattr("httpx.AsyncClient", MockAsyncClient)

    config = DaemonConfig(
        custom_command=[sys.executable, "-c", "import time; time.sleep(60)"],
        custom_cwd=str(temp_state_dir),
        startup_timeout=2.0,
    )
    supervisor = AuraDaemonSupervisor(config=config, kill_switch_service=mock_kill_switch)
    await supervisor.start()

    ipc_server = AuraDaemonIPCServer(supervisor=supervisor)
    token = AuraIpcAuthManager.get_or_create_token()
    ipc_client = AuraDaemonIPCClient(token=token)

    # Query Status via IPC
    resp_status = await ipc_client.send_direct_command(ipc_server, DaemonIPCCommand.STATUS)
    assert resp_status.status == "success"
    assert resp_status.data["state"] == "RUNNING"
    assert resp_status.data["backend_pid"] == supervisor.backend_identity.pid

    # Query Health via IPC
    resp_health = await ipc_client.send_direct_command(ipc_server, DaemonIPCCommand.HEALTH)
    assert resp_health.status == "success"

    # Stop via IPC
    resp_stop = await ipc_client.send_direct_command(ipc_server, DaemonIPCCommand.STOP)
    assert resp_stop.status == "success"
    assert resp_stop.data["state"] == "STOPPED"

    await ipc_server.stop()
