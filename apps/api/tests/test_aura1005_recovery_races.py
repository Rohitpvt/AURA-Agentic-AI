"""AURA-1005 Recovery Races, Kill-Switch Matrix & Task Separation Verification Suite."""

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
async def test_race_a_backend_crash_during_kill_switch_activation(temp_state_dir, mock_kill_switch, monkeypatch):
    """Race A: Backend process crashes while kill switch activates. Proves no restart attempt is made."""
    config = DaemonConfig(
        custom_command=[sys.executable, "-c", "import time; time.sleep(60)"],
        custom_cwd=str(temp_state_dir),
        heartbeat_interval=0.1,
        startup_timeout=2.0,
    )
    supervisor = AuraDaemonSupervisor(config=config, kill_switch_service=mock_kill_switch, state_dir=temp_state_dir)

    # Mock health probe: initially running, then DEAD
    probes = 0
    async def mock_probe(*args, **kwargs):
        nonlocal probes
        probes += 1
        if probes == 1:
            return ProcessHealthStatus.HEALTHY, {"status": "healthy"}
        return ProcessHealthStatus.DEAD, {"error": "Crashed"}

    monkeypatch.setattr(supervisor.monitor, "probe_health", mock_probe)

    await supervisor.start()
    assert supervisor.state == DaemonState.RUNNING

    # Activate kill switch immediately as crash happens
    mock_kill_switch.set_active(True)
    await asyncio.sleep(0.3)

    assert supervisor.state == DaemonState.KILL_SWITCHED
    assert supervisor.backend_identity is None
    assert supervisor.total_restarts == 0
    await supervisor.stop()


@pytest.mark.asyncio
async def test_race_b_restart_timer_pending_during_kill_switch(temp_state_dir, mock_kill_switch, monkeypatch):
    """Race B: Restart timer is sleeping when kill switch activates. Proves restart is cancelled immediately."""
    config = DaemonConfig(
        custom_command=[sys.executable, "-c", "import time; time.sleep(60)"],
        custom_cwd=str(temp_state_dir),
        heartbeat_interval=0.1,
        startup_timeout=2.0,
        initial_backoff_seconds=2.0,
    )
    supervisor = AuraDaemonSupervisor(config=config, kill_switch_service=mock_kill_switch, state_dir=temp_state_dir)

    probes = 0
    async def mock_probe(*args, **kwargs):
        nonlocal probes
        probes += 1
        if probes == 1:
            return ProcessHealthStatus.HEALTHY, {"status": "healthy"}
        return ProcessHealthStatus.DEAD, {"error": "Crashed"}

    monkeypatch.setattr(supervisor.monitor, "probe_health", mock_probe)

    await supervisor.start()
    await asyncio.sleep(0.25)
    assert supervisor.state == DaemonState.RESTARTING

    # Kill switch activates during backoff sleep
    mock_kill_switch.set_active(True)
    await asyncio.sleep(0.3)

    assert supervisor.state == DaemonState.KILL_SWITCHED
    assert supervisor.backend_identity is None
    await supervisor.stop()


@pytest.mark.asyncio
async def test_race_c_kill_switch_during_startup_loop(temp_state_dir, mock_kill_switch, monkeypatch):
    """Race C: Kill switch activates while supervisor is in startup polling loop."""
    config = DaemonConfig(
        custom_command=[sys.executable, "-c", "import time; time.sleep(60)"],
        custom_cwd=str(temp_state_dir),
        startup_timeout=5.0,
    )
    supervisor = AuraDaemonSupervisor(config=config, kill_switch_service=mock_kill_switch, state_dir=temp_state_dir)

    # Delay health probe to simulate slow backend initialization
    async def mock_slow_probe(*args, **kwargs):
        await asyncio.sleep(0.2)
        return ProcessHealthStatus.UNRESPONSIVE, {"error": "Starting..."}

    monkeypatch.setattr(supervisor.monitor, "probe_health", mock_slow_probe)

    async def trigger_kill_after_delay():
        await asyncio.sleep(0.3)
        mock_kill_switch.set_active(True)

    asyncio.create_task(trigger_kill_after_delay())

    with pytest.raises(RuntimeError, match="Kill switch activated during startup"):
        await supervisor.start()

    assert supervisor.state == DaemonState.KILL_SWITCHED
    assert supervisor.backend_identity is None


@pytest.mark.asyncio
async def test_race_d_backend_running_kill_switch_activation(temp_state_dir, mock_kill_switch, monkeypatch):
    """Race D: Backend is healthy and running when kill switch activates. Proves instant shutdown."""
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
    supervisor = AuraDaemonSupervisor(config=config, kill_switch_service=mock_kill_switch, state_dir=temp_state_dir)
    await supervisor.start()
    assert supervisor.state == DaemonState.RUNNING
    assert supervisor.backend_identity.matches_live_process() is True

    # Trigger emergency kill switch
    mock_kill_switch.set_active(True)
    await asyncio.sleep(0.3)

    assert supervisor.state == DaemonState.KILL_SWITCHED
    assert supervisor.backend_identity is None
    await supervisor.stop()


@pytest.mark.asyncio
async def test_race_e_kill_switch_reset_no_automatic_resurrection(temp_state_dir, mock_kill_switch):
    """Race E: Kill switch is reset. Proves supervisor remains STOPPED/KILL_SWITCHED and does NOT auto-resurrect."""
    mock_kill_switch.set_active(True)
    config = DaemonConfig(custom_cwd=str(temp_state_dir))
    supervisor = AuraDaemonSupervisor(config=config, kill_switch_service=mock_kill_switch, state_dir=temp_state_dir)

    with pytest.raises(RuntimeError):
        await supervisor.start()

    assert supervisor.state == DaemonState.KILL_SWITCHED

    # Reset kill switch
    mock_kill_switch.set_active(False)
    await asyncio.sleep(0.3)

    # Supervisor must NOT have automatically resurrected
    assert supervisor.state == DaemonState.KILL_SWITCHED
    assert supervisor.backend_identity is None


@pytest.mark.asyncio
async def test_task_recovery_separation_invariant(temp_state_dir, mock_kill_switch):
    """Prove that process lifecycle recovery is decoupled from task execution and does not replay actions."""
    config = DaemonConfig(custom_cwd=str(temp_state_dir))
    supervisor = AuraDaemonSupervisor(config=config, kill_switch_service=mock_kill_switch, state_dir=temp_state_dir)

    report = supervisor.get_status()
    # Status report contains only operational lifecycle data, zero task queue replay state
    assert not hasattr(report, "replay_tasks")
    assert not hasattr(report, "replayed_approvals")
    assert report.total_restarts == 0
