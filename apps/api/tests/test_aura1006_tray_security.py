"""AURA-1006 Win32 Tray Integration & IPC Security Tests."""

import asyncio
import json
import os
import secrets
import time
import pytest

from app.tray.ipc import AuraIpcAuthManager, AuraNamedPipeServer
from app.tray.types import TrayIPCCommand, TrayRuntimeState
from app.services.kill_switch import EmergencyKillSwitchService


@pytest.mark.asyncio
async def test_tray_ipc_authentication_enforcement(tmp_path, monkeypatch):
    """Verify IPC server strictly enforces token authentication."""
    monkeypatch.setenv("AURA_STATE_DIR", str(tmp_path))
    valid_token = AuraIpcAuthManager.get_or_create_token()

    server = AuraNamedPipeServer()

    # 1. Unauthenticated request (no token)
    req_unauth = json.dumps({"command": "get_status"})
    res = await server.process_raw_request(req_unauth)
    assert res["status"] == "error"
    assert "Authentication failed" in res["error"]

    # 2. Invalid token
    req_bad_token = json.dumps({"command": "get_status", "token": "invalid_fake_token_12345"})
    res = await server.process_raw_request(req_bad_token)
    assert res["status"] == "error"
    assert "Authentication failed" in res["error"]

    # 3. Valid token
    req_valid = json.dumps({"command": "get_status", "token": valid_token})
    res = await server.process_raw_request(req_valid)
    assert res["status"] == "success"
    assert "runtime_state" in res["data"]


@pytest.mark.asyncio
async def test_tray_ipc_prohibited_and_malformed_commands(tmp_path, monkeypatch):
    """Verify malformed commands, prohibited strings, and unknown payloads are rejected."""
    monkeypatch.setenv("AURA_STATE_DIR", str(tmp_path))
    token = AuraIpcAuthManager.get_or_create_token()
    server = AuraNamedPipeServer()

    # 1. Malformed JSON
    res = await server.process_raw_request("{invalid_json_")
    assert res["status"] == "error"

    # 2. Arbitrary non-allowlisted command
    req_cmd_inject = json.dumps({
        "command": "run_shell_command",
        "token": token,
        "parameters": {"cmd": "calc.exe"},
    })
    res = await server.process_raw_request(req_cmd_inject)
    assert res["status"] == "error"
    assert "prohibited or not in approved IPC allowlist" in res["error"]

    # 3. Dangerous system commands
    for dangerous in ["DROP_DATABASE", "FORMAT_DRIVE", "EXEC_ARBITRARY", "ELEVATE_SYSTEM"]:
        req_bad = json.dumps({"command": dangerous, "token": token})
        res = await server.process_raw_request(req_bad)
        assert res["status"] == "error"


@pytest.mark.asyncio
async def test_tray_ipc_oversized_payload_protection(tmp_path, monkeypatch):
    """Verify payloads exceeding 64 KB are rejected."""
    monkeypatch.setenv("AURA_STATE_DIR", str(tmp_path))
    token = AuraIpcAuthManager.get_or_create_token()
    server = AuraNamedPipeServer()

    huge_string = "A" * 70000  # 70 KB > 64 KB
    huge_payload = json.dumps({
        "command": "get_status",
        "token": token,
        "parameters": {"blob": huge_string},
    })

    res = await server.process_raw_request(huge_payload)
    assert res["status"] == "error"
    assert "maximum allowed size" in res["error"]


@pytest.mark.asyncio
async def test_tray_ipc_kill_switch_operation(tmp_path, monkeypatch):
    """Verify kill switch command can be triggered truthfully via IPC."""
    monkeypatch.setenv("AURA_STATE_DIR", str(tmp_path))
    token = AuraIpcAuthManager.get_or_create_token()
    server = AuraNamedPipeServer()

    ks = EmergencyKillSwitchService(state_file_path=str(tmp_path / "kill_state.json"))
    ks.set_active(False)
    assert not ks.is_active()

    # Dispatch kill switch
    req_ks = json.dumps({
        "command": "activate_kill_switch",
        "token": token,
        "parameters": {"reason": "Tray manual emergency activation"},
    })
    res = await server.process_raw_request(req_ks)
    assert res["status"] == "success"
    assert res["data"]["status"] == "KILL_SWITCHED"

    # Query status afterwards
    req_status = json.dumps({"command": "get_status", "token": token})
    res_status = await server.process_raw_request(req_status)
    assert res_status["status"] == "success"
    assert res_status["data"]["kill_switch_active"] is True
    assert res_status["data"]["runtime_state"] == "KILL_SWITCHED"

    # Reset
    from app.services.kill_switch import kill_switch
    kill_switch.set_active(False)


@pytest.mark.asyncio
async def test_tray_ipc_truthful_status_and_privacy(tmp_path, monkeypatch):
    """Verify status and privacy queries return truthful values."""
    monkeypatch.setenv("AURA_STATE_DIR", str(tmp_path))
    token = AuraIpcAuthManager.get_or_create_token()
    server = AuraNamedPipeServer()

    # Privacy state query
    req_privacy = json.dumps({"command": "get_privacy_state", "token": token})
    res_priv = await server.process_raw_request(req_privacy)
    assert res_priv["status"] == "success"
    data = res_priv["data"]
    assert "camera_state" in data
    assert "screen_state" in data
    assert "mic_state" in data
    assert "ocr_state" in data
    assert "vlm_state" in data


@pytest.mark.asyncio
async def test_tray_ipc_secret_leak_scan(tmp_path, monkeypatch):
    """Verify no secret tokens or keys leak into serialized responses."""
    monkeypatch.setenv("AURA_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("AURA_MASTER_ENCRYPTION_KEY", "super_secret_master_key_9999")
    token = AuraIpcAuthManager.get_or_create_token()
    server = AuraNamedPipeServer()

    for cmd in [
        TrayIPCCommand.GET_STATUS,
        TrayIPCCommand.GET_PRIVACY_STATE,
        TrayIPCCommand.GET_AUTOSTART_STATUS,
        TrayIPCCommand.GET_DAEMON_STATUS,
    ]:
        req = json.dumps({"command": cmd.value, "token": token})
        res = await server.process_raw_request(req)
        serialized = json.dumps(res)
        assert "super_secret_master_key_9999" not in serialized
        # Ensure the active token itself isn't reflected back in plain text
        assert token not in serialized
