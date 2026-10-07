"""AURA-1006 Controlled Autostart Security & Governance Tests."""

import json
import os
import platform
import sys
import pytest
from pathlib import Path

from app.daemon.autostart import AutostartManager, AURA_AUTOSTART_KEY_NAME, AURA_REG_RUN_PATH
from app.daemon.main import run_supervisor_daemon
from app.services.kill_switch import EmergencyKillSwitchService


def test_autostart_default_off_fresh_state(tmp_path):
    """Verify autostart is STRICTLY OFF by default in a clean/fresh environment."""
    mgr = AutostartManager(state_dir=tmp_path)
    # Ensure fresh state has no mock file and no HKCU Run entry
    if not mgr.is_windows:
        assert not (tmp_path / "autostart_state.json").exists()
        assert mgr.is_autostart_enabled() is False
    else:
        # On Windows, check registry or mock state
        status = mgr.get_autostart_status()
        assert status["entry_type"] == "HKCU_RUN"
        assert status["value_name"] == AURA_AUTOSTART_KEY_NAME


def test_autostart_explicit_enable_and_disable(tmp_path):
    """Verify autostart can be explicitly enabled and cleanly disabled with zero leftovers."""
    mgr = AutostartManager(state_dir=tmp_path)
    
    # Explicit enable
    enabled = mgr.enable_autostart()
    assert enabled is True
    assert mgr.is_autostart_enabled() is True

    status = mgr.get_autostart_status()
    assert status["enabled"] is True
    assert status["command"] is not None
    assert "-m app.daemon.main --start" in status["command"]

    # Explicit disable
    disabled = mgr.disable_autostart()
    assert disabled is True
    assert mgr.is_autostart_enabled() is False

    status_after = mgr.get_autostart_status()
    assert status_after["enabled"] is False
    assert status_after["command"] is None


def test_autostart_secret_leak_prevention(tmp_path):
    """Verify autostart rejects any commands attempting to embed secrets or tokens."""
    mgr = AutostartManager(state_dir=tmp_path)

    bad_commands = [
        'python.exe -m app.daemon.main --token "AURA_MASTER_ENCRYPTION_KEY=12345"',
        'python.exe -m app.daemon.main --key "JWT_SECRET=secret"',
        'python.exe -m app.daemon.main --password "admin123"',
        'python.exe -m app.daemon.main --secret "PRIVATE KEY DATA"',
    ]

    for bad_cmd in bad_commands:
        with pytest.raises(ValueError, match="forbidden secret pattern"):
            mgr.enable_autostart(custom_command=bad_cmd)


def test_autostart_no_admin_or_system_escalation(tmp_path):
    """Verify autostart registers exclusively under HKCU (user scope) and never HKLM or SYSTEM."""
    mgr = AutostartManager(state_dir=tmp_path)
    status = mgr.get_autostart_status()
    # Must target HKEY_CURRENT_USER
    assert status["entry_type"] == "HKCU_RUN"
    assert "HKEY_CURRENT_USER" in status["registry_path"]
    assert "HKEY_LOCAL_MACHINE" not in status["registry_path"]


@pytest.mark.asyncio
async def test_kill_switch_prevents_autostart_resurrection(tmp_path, monkeypatch):
    """Verify daemon supervisor respects active kill switch upon startup and aborts."""
    monkeypatch.setenv("AURA_STATE_DIR", str(tmp_path))
    ks = EmergencyKillSwitchService(state_file_path=str(tmp_path / "kill_state.json"))
    ks.set_active(True)
    assert ks.is_active()

    # Attempting to run supervisor should immediately exit/halt
    with pytest.raises(SystemExit) as exc_info:
        await run_supervisor_daemon()
    assert exc_info.value.code == 1

    # Cleanup
    ks.set_active(False)
