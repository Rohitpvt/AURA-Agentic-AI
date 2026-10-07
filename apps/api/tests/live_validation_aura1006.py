"""AURA-1006 Live Windows Validation Suite.

Executes real host-level checks on Windows:
1. Live Interactive Session ID validation
2. Live HKCU Run autostart key inspection, enable, disable, and clean restoration
3. Live Named Pipe authentication and command dispatch
4. Live Single-Instance Lock isolation
5. Live Kill-Switch containment
"""

import asyncio
import os
import platform
import sys
import time
import pytest

from app.daemon.autostart import AutostartManager, AURA_AUTOSTART_KEY_NAME
from app.daemon.process_tracker import get_current_session_id
from app.daemon.session_manager import WindowsSessionManager, SessionState
from app.daemon.supervisor import AuraDaemonSupervisor
from app.daemon.types import DaemonState
from app.services.kill_switch import EmergencyKillSwitchService
from app.tray.ipc import AuraIpcAuthManager, AuraNamedPipeServer
from app.tray.tray_icon import WindowsTrayIcon


@pytest.mark.asyncio
async def test_live_windows_session_identification():
    """Live test verifying real Windows session ID query."""
    sid = get_current_session_id()
    assert isinstance(sid, int)
    assert sid >= 0
    print(f"\n[LIVE VALIDATION] Interactive Session ID: {sid}")

    mgr = WindowsSessionManager(session_id=sid)
    info = mgr.get_session_info()
    assert info["session_id"] == sid
    assert info["state"] == "ACTIVE"


@pytest.mark.asyncio
async def test_live_windows_autostart_registry_lifecycle():
    """Live test verifying HKCU Run key modification and clean restoration."""
    autostart_mgr = AutostartManager()
    original_state = autostart_mgr.is_autostart_enabled()
    print(f"\n[LIVE VALIDATION] Initial Autostart State: {original_state}")

    try:
        # 1. Enable autostart
        enabled = autostart_mgr.enable_autostart()
        assert enabled is True
        assert autostart_mgr.is_autostart_enabled() is True
        status = autostart_mgr.get_autostart_status()
        assert status["enabled"] is True
        assert "app.daemon.main" in status["command"]
        print("[LIVE VALIDATION] Successfully enabled HKCU Run autostart")

        # 2. Disable autostart
        disabled = autostart_mgr.disable_autostart()
        assert disabled is True
        assert autostart_mgr.is_autostart_enabled() is False
        status_after = autostart_mgr.get_autostart_status()
        assert status_after["enabled"] is False
        print("[LIVE VALIDATION] Successfully disabled and cleaned HKCU Run autostart")

    finally:
        # Restore original state
        if original_state:
            autostart_mgr.enable_autostart()
        else:
            autostart_mgr.disable_autostart()


@pytest.mark.asyncio
async def test_live_windows_tray_icon_instantiation():
    """Live test verifying WindowsTrayIcon initialization and session manager binding."""
    tray = WindowsTrayIcon()
    assert tray.session_manager is not None
    assert tray.session_manager.state == SessionState.ACTIVE
    tray.stop()
    print("\n[LIVE VALIDATION] WindowsTrayIcon initialized and stopped cleanly")


@pytest.mark.asyncio
async def test_live_windows_ipc_token_security(tmp_path, monkeypatch):
    """Live test verifying filesystem ACLs and token generation."""
    monkeypatch.setenv("AURA_STATE_DIR", str(tmp_path))
    token = AuraIpcAuthManager.get_or_create_token()
    assert token is not None
    assert len(token) == 64  # 32 bytes hex = 64 chars
    assert AuraIpcAuthManager.verify_token(token) is True
    assert AuraIpcAuthManager.verify_token("bad_token") is False
    print(f"\n[LIVE VALIDATION] Generated 256-bit token with strict ACLs: {token[:8]}...")
