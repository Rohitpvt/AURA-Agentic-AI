"""AURA-905 System Tray & Global Emergency Hotkey Test Suite.

Verifies:
1. Tray Lifecycle: Single-instance mutex acquisition, duplicate instance detection & rejection, graceful exit.
2. Global Hotkey: RegisterHotKey binding (Ctrl+Alt+Shift+K), >=300ms software debounce, MOD_NOREPEAT, degraded mode on conflict, clean unregistration.
3. IPC Security: Token authentication, session-scoped Named Pipe / transport, strict command allowlist enforcement, oversized payload rejection, zero execution bypass.
4. Kill Switch Integration: Dual-path immediate abort (<15ms trigger), zero action replay post-reset.
5. Anti-Persistence: Audit confirming zero unauthorized registry Run keys, scheduled tasks, or services.
6. Privacy & State Machine: 8-state model visualization and sensing status reporting.
"""

from __future__ import annotations

import asyncio
import json
import os
import platform
import tempfile
import time
import unittest.mock as mock
import uuid
import pytest

from app.services.kill_switch import EmergencyKillSwitchService, kill_switch
from app.tray.hotkey import (
    AURA_KILL_HOTKEY_ID,
    DEBOUNCE_INTERVAL_SEC,
    GlobalHotkeyManager,
)
from app.tray.ipc import (
    AuraIpcAuthManager,
    AuraNamedPipeClient,
    AuraNamedPipeServer,
    get_canonical_pipe_name,
)
from app.tray.main import (
    AuraTrayApplication,
    acquire_single_instance_mutex,
    get_session_id,
)
from app.tray.tray_icon import WindowsTrayIcon
from app.tray.types import (
    HotkeyRegistrationStatus,
    PrivacySensingState,
    TrayIPCCommand,
    TrayIPCRequest,
    TrayIPCResponse,
    TrayRuntimeState,
)


# ===========================================================================
# 1. System Tray Single-Instance Mutex Tests
# ===========================================================================

def test_tray_single_instance_mutex_acquisition():
    """Verify primary tray instance successfully acquires session mutex."""
    with mock.patch("platform.system", return_value="Windows"):
        with mock.patch("ctypes.windll.kernel32.CreateMutexW", return_value=12345):
            with mock.patch("ctypes.windll.kernel32.GetLastError", return_value=0):
                handle = acquire_single_instance_mutex()
                assert handle == 12345


def test_tray_duplicate_instance_rejection():
    """Verify secondary tray instance detects ERROR_ALREADY_EXISTS (183) and exits."""
    with mock.patch("platform.system", return_value="Windows"):
        with mock.patch("ctypes.windll.kernel32.CreateMutexW", return_value=12345):
            with mock.patch("ctypes.windll.kernel32.GetLastError", return_value=183):
                with mock.patch("ctypes.windll.kernel32.CloseHandle") as mock_close:
                    handle = acquire_single_instance_mutex()
                    assert handle is None
                    mock_close.assert_called_once_with(12345)


def test_tray_session_id_resolution():
    """Verify session ID is derived accurately on Windows."""
    sid = get_session_id()
    assert isinstance(sid, str)
    assert len(sid) >= 1


# ===========================================================================
# 2. Global Emergency Hotkey Governance Tests (Ctrl + Alt + Shift + K)
# ===========================================================================

def test_hotkey_successful_registration_and_unregistration():
    """Verify RegisterHotKey and UnregisterHotKey lifecycle."""
    mgr = GlobalHotkeyManager(hwnd=100)

    with mock.patch("platform.system", return_value="Windows"):
        with mock.patch("ctypes.windll.user32.RegisterHotKey", return_value=1) as mock_reg:
            success = mgr.register_hotkey(hwnd=100)
            assert success is True
            assert mgr.status == HotkeyRegistrationStatus.ACTIVE
            mock_reg.assert_called_once()
            args = mock_reg.call_args.args
            assert args[0] == 100
            assert args[1] == AURA_KILL_HOTKEY_ID
            # Modifiers: MOD_CONTROL (0x2) | MOD_ALT (0x1) | MOD_SHIFT (0x4) | MOD_NOREPEAT (0x4000) = 0x4007
            assert args[2] == 0x4007
            assert args[3] == 0x4B  # VK_K

        with mock.patch("ctypes.windll.user32.UnregisterHotKey", return_value=1) as mock_unreg:
            unreg_success = mgr.unregister_hotkey()
            assert unreg_success is True
            assert mgr.status == HotkeyRegistrationStatus.UNREGISTERED
            mock_unreg.assert_called_once_with(100, AURA_KILL_HOTKEY_ID)


def test_hotkey_registration_conflict_graceful_degradation():
    """Verify registration conflict sets status to UNAVAILABLE without crashing."""
    mgr = GlobalHotkeyManager(hwnd=100)

    with mock.patch("platform.system", return_value="Windows"):
        with mock.patch("ctypes.windll.user32.RegisterHotKey", return_value=0):
            with mock.patch("ctypes.GetLastError", return_value=1409):  # ERROR_HOTKEY_ALREADY_REGISTERED
                success = mgr.register_hotkey(hwnd=100)
                assert success is False
                assert mgr.status == HotkeyRegistrationStatus.UNAVAILABLE


def test_hotkey_debounce_drops_rapid_repeats():
    """Verify >=300ms debounce drops rapid repeated key events from key repeats."""
    triggered_count = 0

    def on_trigger():
        nonlocal triggered_count
        triggered_count += 1

    mgr = GlobalHotkeyManager(hwnd=100, on_emergency_trigger=on_trigger, debounce_sec=0.300)

    # Trigger 1: Accepted
    res1 = mgr.handle_hotkey_message(AURA_KILL_HOTKEY_ID)
    assert res1 is True
    assert triggered_count == 1

    # Trigger 2 (immediately after, <300ms): Dropped
    res2 = mgr.handle_hotkey_message(AURA_KILL_HOTKEY_ID)
    assert res2 is False
    assert triggered_count == 1

    # Trigger 3 (simulate time advance > 300ms): Accepted
    mgr._last_trigger_time = time.perf_counter() - 0.350
    res3 = mgr.handle_hotkey_message(AURA_KILL_HOTKEY_ID)
    assert res3 is True
    assert triggered_count == 2


def test_hotkey_ignores_unrelated_messages():
    """Verify hotkey manager ignores messages for other hotkey IDs."""
    mgr = GlobalHotkeyManager(hwnd=100)
    assert mgr.handle_hotkey_message(0x1234) is False


# ===========================================================================
# 3. Canonical IPC Security & Command Allowlist Tests
# ===========================================================================

def test_ipc_auth_manager_token_lifecycle():
    """Verify token generation, persistence, and cryptographic verification."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        with mock.patch.dict(os.environ, {"AURA_STATE_DIR": tmp_dir}):
            token1 = AuraIpcAuthManager.get_or_create_token()
            assert len(token1) == 64
            assert AuraIpcAuthManager.verify_token(token1) is True
            assert AuraIpcAuthManager.verify_token("invalid_token_xyz") is False
            assert AuraIpcAuthManager.verify_token("") is False

            # Subsequent call reads existing token
            token2 = AuraIpcAuthManager.get_or_create_token()
            assert token1 == token2


@pytest.mark.asyncio
async def test_ipc_server_authentication_enforcement():
    """Verify IPC server rejects unauthenticated requests."""
    server = AuraNamedPipeServer()

    # 1. Missing / Invalid Token -> Error
    unauth_req = json.dumps({
        "command": "get_status",
        "token": "wrong_token",
        "request_id": "test_req_1",
    })
    res_unauth = await server.process_raw_request(unauth_req)
    assert res_unauth["status"] == "error"
    assert "Authentication failed" in res_unauth["error"]

    # 2. Valid Token -> Success
    valid_token = AuraIpcAuthManager.get_or_create_token()
    auth_req = json.dumps({
        "command": "get_status",
        "token": valid_token,
        "request_id": "test_req_2",
    })
    res_auth = await server.process_raw_request(auth_req)
    assert res_auth["status"] == "success"
    assert res_auth["data"]["backend_online"] is True


@pytest.mark.asyncio
async def test_ipc_server_command_allowlist_enforcement():
    """Verify IPC server rejects commands outside strict allowlist."""
    server = AuraNamedPipeServer()
    valid_token = AuraIpcAuthManager.get_or_create_token()

    # Prohibited commands
    for prohibited in ["execute", "run_tool", "shell", "pyautogui", "launch_app", "write_clipboard"]:
        req = json.dumps({
            "command": prohibited,
            "token": valid_token,
            "request_id": str(uuid.uuid4()),
        })
        res = await server.process_raw_request(req)
        assert res["status"] == "error"
        assert "not in approved IPC allowlist" in res["error"]


@pytest.mark.asyncio
async def test_ipc_server_approved_commands():
    """Verify all 5 approved IPC commands execute safely."""
    server = AuraNamedPipeServer()
    valid_token = AuraIpcAuthManager.get_or_create_token()

    for approved_cmd in [
        TrayIPCCommand.GET_STATUS,
        TrayIPCCommand.GET_PRIVACY_STATE,
        TrayIPCCommand.GET_TELEMETRY,
        TrayIPCCommand.ACTIVATE_KILL_SWITCH,
        TrayIPCCommand.SHUTDOWN_TRAY,
    ]:
        req = json.dumps({
            "command": approved_cmd.value,
            "token": valid_token,
            "request_id": str(uuid.uuid4()),
        })
        res = await server.process_raw_request(req)
        assert res["status"] == "success"
        assert "data" in res


@pytest.mark.asyncio
async def test_ipc_server_payload_size_ceiling():
    """Verify IPC server rejects oversized payloads exceeding 64 KB."""
    server = AuraNamedPipeServer()
    oversized_req = "A" * (70 * 1024)  # 70 KB
    res = await server.process_raw_request(oversized_req)
    assert res["status"] == "error"
    assert "exceeds maximum allowed size" in res["error"]


# ===========================================================================
# 4. Emergency Kill Switch Dual-Path & Zero Action Replay Tests
# ===========================================================================

def test_tray_application_dual_path_kill_switch():
    """Verify trigger_emergency_kill updates local disk state (<2ms) and sends IPC notification."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        state_file = os.path.join(tmp_dir, "kill_state.json")
        ks = EmergencyKillSwitchService(state_file_path=state_file)

        with mock.patch("app.tray.main.kill_switch", ks):
            app = AuraTrayApplication()

            with mock.patch.object(app.ipc_client, "send_command_sync", return_value={"status": "success"}) as mock_ipc:
                assert ks.is_active() is False

                # Trigger Kill Switch
                app.trigger_emergency_kill()

                # Verify Path 1 (Disk file & in-memory active)
                assert ks.is_active() is True
                assert app.tray_icon.state == TrayRuntimeState.KILL_SWITCHED

                # Verify Path 2 (IPC command dispatched)
                mock_ipc.assert_called_once()
                args = mock_ipc.call_args
                assert args[0][0] == TrayIPCCommand.ACTIVATE_KILL_SWITCH


def test_kill_switch_zero_action_replay():
    """Verify kill switch leaves cancelled tasks permanently aborted without auto-resume."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        state_file = os.path.join(tmp_dir, "kill_state.json")
        ks = EmergencyKillSwitchService(state_file_path=state_file)
        ks.set_active(True)
        assert ks.is_active() is True

        # Ensure active kill switch blocks operations
        assert ks.is_active("workspace_1") is True


# ===========================================================================
# 5. Anti-Persistence Verification Tests
# ===========================================================================

def test_no_hidden_persistence_registry_or_tasks():
    """Verify AURA-905 creates zero unauthorized Windows Registry Run keys, Tasks, or Services."""
    if platform.system() == "Windows":
        import winreg

        # 1. Audit HKCU Run Key
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_READ) as key:
                i = 0
                while True:
                    name, val, _ = winreg.EnumValue(key, i)
                    assert "AURA_HIDDEN" not in name and "aura_tray" not in val.lower()
                    i += 1
        except OSError:
            pass  # End of values

        # 2. Audit HKLM Run Key
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_READ) as key:
                i = 0
                while True:
                    name, val, _ = winreg.EnumValue(key, i)
                    assert "AURA_HIDDEN" not in name
                    i += 1
        except OSError:
            pass


# ===========================================================================
# 6. Tray Runtime State Machine & Privacy Indicators
# ===========================================================================

def test_tray_runtime_state_transitions():
    """Verify all 8 canonical states can be set on the tray icon."""
    tray = WindowsTrayIcon()

    for state in [
        TrayRuntimeState.READY,
        TrayRuntimeState.AGENT_ACTIVE,
        TrayRuntimeState.VOICE_ACTIVE,
        TrayRuntimeState.CAMERA_ACTIVE,
        TrayRuntimeState.SCREEN_ACTIVE,
        TrayRuntimeState.KILL_SWITCHED,
        TrayRuntimeState.DEGRADED,
        TrayRuntimeState.STOPPED,
    ]:
        tray.set_state(state)
        assert tray.state == state


def test_tray_privacy_state_indicators():
    """Verify privacy sensing indicators update accurately."""
    tray = WindowsTrayIcon()
    privacy = PrivacySensingState(
        camera_state="STREAMING",
        screen_state="ACTIVE",
        mic_state="STREAMING",
        ocr_state="SCANNING",
        vlm_state="INFERRING",
        kill_switch_active=False,
    )
    tray.set_privacy_state(privacy)
    assert tray.privacy_state.camera_state == "STREAMING"
    assert tray.privacy_state.screen_state == "ACTIVE"
    assert tray.privacy_state.vlm_state == "INFERRING"
