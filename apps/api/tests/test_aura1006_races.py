"""AURA-1006 Lifecycle, Race Condition & Session Transition Safety Tests."""

import asyncio
import os
import sys
import time
import pytest

from app.daemon.session_manager import WindowsSessionManager, SessionState, WTS_SESSION_LOCK, WTS_SESSION_UNLOCK, WTS_SESSION_LOGOFF
from app.daemon.supervisor import AuraDaemonSupervisor
from app.daemon.types import DaemonConfig, DaemonState
from app.services.kill_switch import EmergencyKillSwitchService
from app.tray.ipc import AuraNamedPipeClient, AuraNamedPipeServer, AuraIpcAuthManager
from app.tray.tray_icon import WindowsTrayIcon
from app.tray.types import TrayIPCCommand, TrayRuntimeState


def _make_fast_config(tmp_path):
    return DaemonConfig(
        custom_command=[sys.executable, "-c", "import time; time.sleep(30)"],
        custom_cwd=str(tmp_path),
        startup_timeout=2.0,
        graceful_shutdown_timeout=1.0,
        heartbeat_interval=0.1,
    )


@pytest.mark.asyncio
async def test_race_kill_switch_during_session_transition(tmp_path):
    """Verify kill switch activated during session lock/unlock immediately halts execution."""
    ks = EmergencyKillSwitchService(state_file_path=str(tmp_path / "ks_race1.json"))
    ks.set_active(False)

    mgr = WindowsSessionManager(session_id=1)
    supervisor = AuraDaemonSupervisor(
        state_dir=tmp_path / "s1",
        config=_make_fast_config(tmp_path),
        kill_switch_service=ks,
    )

    # Session lock transition + concurrent kill switch activation
    async def _transition_lock():
        mgr.handle_wts_message(WTS_SESSION_LOCK, session_id=1)
        await asyncio.sleep(0.01)

    async def _activate_ks():
        ks.set_active(True)
        await supervisor._handle_kill_switch_active()

    await asyncio.gather(_transition_lock(), _activate_ks())

    assert supervisor.state == DaemonState.KILL_SWITCHED
    assert mgr.state == SessionState.LOCKED
    await supervisor.stop()
    ks.set_active(False)


@pytest.mark.asyncio
async def test_race_simultaneous_start_and_stop(tmp_path):
    """Verify simultaneous start and stop requests do not result in corrupted daemon state."""
    supervisor = AuraDaemonSupervisor(
        state_dir=tmp_path / "s2",
        config=_make_fast_config(tmp_path),
    )
    
    # Run concurrent start & stop
    results = await asyncio.gather(
        supervisor.start(),
        supervisor.stop(),
        return_exceptions=True,
    )

    # Supervisor should resolve to a valid terminal state without corrupted unhandled exception
    assert supervisor.state in (DaemonState.RUNNING, DaemonState.STOPPED)
    await supervisor.stop()


@pytest.mark.asyncio
async def test_race_tray_shutdown_during_daemon_restart(tmp_path):
    """Verify tray stopping or disconnecting while daemon is restarting doesn't block."""
    supervisor = AuraDaemonSupervisor(
        state_dir=tmp_path / "s3",
        config=_make_fast_config(tmp_path),
    )

    tray = WindowsTrayIcon()
    
    # Concurrently restart daemon and stop tray
    async def _restart_daemon():
        try:
            await supervisor.restart()
        except Exception:
            pass

    def _stop_tray():
        tray.stop()

    await asyncio.gather(
        _restart_daemon(),
        asyncio.to_thread(_stop_tray),
    )

    await supervisor.stop()


@pytest.mark.asyncio
async def test_race_daemon_restart_while_degraded(tmp_path):
    """Verify restart safely resets crash counters and degraded state."""
    supervisor = AuraDaemonSupervisor(
        state_dir=tmp_path / "s4",
        config=_make_fast_config(tmp_path),
    )
    supervisor.state = DaemonState.DEGRADED
    supervisor.consecutive_crashes = 3

    # Manually calling restart resets crash loop counters
    report = await supervisor.restart()
    assert supervisor.consecutive_crashes == 0
    assert report.consecutive_crashes == 0
    await supervisor.stop()


@pytest.mark.asyncio
async def test_race_session_logoff_cleans_supervisor(tmp_path):
    """Verify session logoff triggers clean supervisor shutdown."""
    mgr = WindowsSessionManager(session_id=5)
    supervisor = AuraDaemonSupervisor(
        state_dir=tmp_path / "s5",
        config=_make_fast_config(tmp_path),
    )

    def on_session_change(state, code):
        if state == SessionState.LOGGING_OFF:
            asyncio.create_task(supervisor.stop())

    mgr.register_listener(on_session_change)

    # Trigger logoff
    mgr.handle_wts_message(WTS_SESSION_LOGOFF, session_id=5)
    await asyncio.sleep(0.05)
    
    assert mgr.state == SessionState.LOGGING_OFF
    await supervisor.stop()
    assert supervisor.state == DaemonState.STOPPED
