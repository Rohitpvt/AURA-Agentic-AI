"""AURA-1006 Windows Interactive User Session Awareness & Security Tests."""

import asyncio
import os
import platform
import sys
import time
import pytest

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
from app.daemon.process_tracker import get_current_session_id
from app.daemon.single_instance import AuraSingleInstanceGuard
from app.daemon.supervisor import AuraDaemonSupervisor
from app.daemon.types import DaemonConfig, DaemonState
from app.services.kill_switch import EmergencyKillSwitchService


@pytest.mark.asyncio
async def test_session_manager_initialization():
    """Verify session manager correctly identifies current interactive session."""
    mgr = WindowsSessionManager()
    assert mgr.session_id is not None
    assert mgr.state == SessionState.ACTIVE
    info = mgr.get_session_info()
    assert info["session_id"] == mgr.session_id
    assert info["state"] == "ACTIVE"


@pytest.mark.asyncio
async def test_session_lock_and_unlock_transitions():
    """Verify lock and unlock events transition session state and trigger listeners."""
    mgr = WindowsSessionManager(session_id=1)
    events_received = []

    def on_event(state, code):
        events_received.append((state, code))

    mgr.register_listener(on_event)

    # 1. Lock event
    new_state = mgr.handle_wts_message(WTS_SESSION_LOCK, session_id=1)
    assert new_state == SessionState.LOCKED
    assert mgr.state == SessionState.LOCKED
    assert len(events_received) == 1
    assert events_received[-1] == (SessionState.LOCKED, WTS_SESSION_LOCK)

    # 2. Unlock event
    new_state = mgr.handle_wts_message(WTS_SESSION_UNLOCK, session_id=1)
    assert new_state == SessionState.ACTIVE
    assert mgr.state == SessionState.ACTIVE
    assert len(events_received) == 2
    assert events_received[-1] == (SessionState.ACTIVE, WTS_SESSION_UNLOCK)


@pytest.mark.asyncio
async def test_session_disconnect_and_logoff():
    """Verify disconnect and logoff events transition correctly."""
    mgr = WindowsSessionManager(session_id=2)
    state_history = []

    mgr.register_listener(lambda state, code: state_history.append(state))

    # Console Disconnect
    mgr.handle_wts_message(WTS_CONSOLE_DISCONNECT, session_id=2)
    assert mgr.state == SessionState.DISCONNECTED

    # Reconnect
    mgr.handle_wts_message(WTS_CONSOLE_CONNECT, session_id=2)
    assert mgr.state == SessionState.ACTIVE

    # Logoff
    mgr.handle_wts_message(WTS_SESSION_LOGOFF, session_id=2)
    assert mgr.state == SessionState.LOGGING_OFF
    assert state_history == [
        SessionState.DISCONNECTED,
        SessionState.ACTIVE,
        SessionState.LOGGING_OFF,
    ]


@pytest.mark.asyncio
async def test_cross_session_event_isolation():
    """Verify events targeted at other session IDs are ignored."""
    mgr = WindowsSessionManager(session_id=1)
    events = []
    mgr.register_listener(lambda s, c: events.append((s, c)))

    # Event for Session 999 should be ignored
    res = mgr.handle_wts_message(WTS_SESSION_LOCK, session_id=999)
    assert res == SessionState.ACTIVE
    assert mgr.state == SessionState.ACTIVE
    assert len(events) == 0


def test_duplicate_instance_prevention(tmp_path):
    """Verify second guard / supervisor cannot start in the same interactive session."""
    guard1 = AuraSingleInstanceGuard(session_id=7777, state_dir=tmp_path)
    assert guard1.acquire() is True

    guard2 = AuraSingleInstanceGuard(session_id=7777, state_dir=tmp_path)
    assert guard2.acquire() is False

    guard1.release()
    assert guard2.acquire() is True
    guard2.release()


@pytest.mark.asyncio
async def test_stale_ipc_and_session_transition(tmp_path):
    """Verify session manager unregisters cleanly without resource leaks."""
    mgr = WindowsSessionManager(session_id=get_current_session_id())
    # Register / unregister session notification
    mgr.register_session_notification(0)
    mgr.unregister_session_notification()
    assert mgr._registered_hwnd is None
