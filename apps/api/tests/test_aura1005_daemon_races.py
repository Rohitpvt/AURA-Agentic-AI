"""AURA-1005 Race Condition and Concurrency Verification Test Suite."""

import asyncio
import os
from pathlib import Path
import sys
import time

import pytest

from app.daemon.health_monitor import BackendHealthMonitor
from app.daemon.process_tracker import ProcessIdentity
from app.daemon.single_instance import AuraSingleInstanceGuard
from app.daemon.supervisor import AuraDaemonSupervisor
from app.daemon.types import DaemonConfig, DaemonState, ProcessHealthStatus
from app.services.kill_switch import EmergencyKillSwitchService


@pytest.fixture
def temp_state_dir(tmp_path):
    state_dir = tmp_path / ".aura"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir


@pytest.fixture
def mock_kill_switch(temp_state_dir):
    state_file = temp_state_dir / "kill_state.json"
    return EmergencyKillSwitchService(state_file_path=str(state_file))


@pytest.mark.asyncio
async def test_race_start_vs_start(temp_state_dir, mock_kill_switch, monkeypatch):
    """Verify concurrent start() calls on same supervisor resolve safely without duplicate backend launches."""
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

    # Launch two concurrent start tasks
    res1, res2 = await asyncio.gather(supervisor.start(), supervisor.start())
    assert res1.state == DaemonState.RUNNING
    assert res2.state == DaemonState.RUNNING
    assert res1.backend_pid == res2.backend_pid

    await supervisor.stop()


@pytest.mark.asyncio
async def test_race_dual_supervisor_instances(temp_state_dir, mock_kill_switch, monkeypatch):
    """Verify two separate supervisor instances in same session cannot both acquire lock."""
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
    sup1 = AuraDaemonSupervisor(config=config, kill_switch_service=mock_kill_switch)
    sup2 = AuraDaemonSupervisor(config=config, kill_switch_service=mock_kill_switch)

    await sup1.start()
    assert sup1.state == DaemonState.RUNNING

    # Second supervisor instance must be rejected
    with pytest.raises(RuntimeError, match="Another instance already holds session"):
        await sup2.start()

    assert sup2.state == DaemonState.STOPPED
    await sup1.stop()


@pytest.mark.asyncio
async def test_race_kill_switch_during_backoff_sleep(temp_state_dir, mock_kill_switch, monkeypatch):
    """Verify kill switch activated during backoff sleep halts auto-restart and sets KILL_SWITCHED."""
    # Child exits immediately
    config = DaemonConfig(
        custom_command=[sys.executable, "-c", "import sys; sys.exit(1)"],
        custom_cwd=str(temp_state_dir),
        heartbeat_interval=0.1,
        startup_timeout=2.0,
        initial_backoff_seconds=2.0,
    )
    supervisor = AuraDaemonSupervisor(config=config, kill_switch_service=mock_kill_switch)

    # Mock health probe: initially running, then DEAD
    probes = 0
    async def mock_probe(*args, **kwargs):
        nonlocal probes
        probes += 1
        if probes == 1:
            return ProcessHealthStatus.HEALTHY, {"status": "healthy"}
        return ProcessHealthStatus.DEAD, {"error": "Process terminated"}

    monkeypatch.setattr(supervisor.monitor, "probe_health", mock_probe)

    await supervisor.start()
    assert supervisor.state == DaemonState.RUNNING

    # Allow watchdog to detect DEAD and enter backoff sleep
    await asyncio.sleep(0.3)
    assert supervisor.state == DaemonState.RESTARTING

    # Activate kill switch mid-sleep
    mock_kill_switch.set_active(True)
    await asyncio.sleep(0.4)

    # Must transition to KILL_SWITCHED and cancel restart
    assert supervisor.state == DaemonState.KILL_SWITCHED
    assert supervisor.backend_identity is None

    await supervisor.stop()


@pytest.mark.asyncio
async def test_race_stop_during_running(temp_state_dir, mock_kill_switch, monkeypatch):
    """Verify stop() cleanly cancels watchdog loop and frees all process handles."""
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
        heartbeat_interval=0.1,
        startup_timeout=2.0,
    )
    supervisor = AuraDaemonSupervisor(config=config, kill_switch_service=mock_kill_switch)
    await supervisor.start()
    assert supervisor.state == DaemonState.RUNNING

    # Trigger stop while watchdog is actively probing
    stop_report = await supervisor.stop()
    assert stop_report.state == DaemonState.STOPPED
    assert supervisor.backend_identity is None
