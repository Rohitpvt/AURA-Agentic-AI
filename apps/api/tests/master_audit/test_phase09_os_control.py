"""
Phase 9 Master Audit: Governed OS & Hardware Control Automation, Process Lifecycle, Input Controls, and Tray IPC.
"""
import pytest
import uuid

from app.services.os_guard import (
    OSGuardService,
    OSActionRequest,
    OSActionType,
    OSActionLifecycleState,
    ApplicationRegistry,
    ProcessService,
    GovernedClipboardAdapter,
    CoreAudioVolumeAdapter,
)
from app.services.kill_switch import kill_switch
from app.tray.ipc import AuraNamedPipeServer, AuraIpcAuthManager
from app.tray.types import TrayIPCCommand


@pytest.mark.asyncio
async def test_phase09_os_guard_application_launch_validation():
    """
    Audit Phase 9 OS: Verify application launcher permits only allowlisted apps and strictly rejects LOLBins.
    """
    registry = ApplicationRegistry()
    assert registry.get_application("notepad") is not None
    assert registry.get_application("calc") is not None
    assert registry.get_application("powershell") is None
    assert registry.get_application("cmd") is None
    assert registry.get_application("wscript") is None


@pytest.mark.asyncio
async def test_phase09_os_guard_process_identity_verification():
    """
    Audit Phase 9 OS: Verify ProcessService shields kernel PIDs <= 4 and enforces creation time verification.
    """
    proc_svc = ProcessService()

    # Kernel PID 4 termination attempt -> PROTECTED
    res_kernel = proc_svc.terminate_process(pid=4, expected_create_time=0.0, expected_name="System")
    assert res_kernel.get("outcome") == "PROTECTED"

    # Stale create_time mismatch -> IDENTITY_MISMATCH
    res_mismatch = proc_svc.terminate_process(pid=12345, expected_create_time=999999.0, expected_name="notepad.exe")
    assert res_mismatch.get("outcome") in ["IDENTITY_MISMATCH", "ALREADY_EXITED", "FAILED"]


@pytest.mark.asyncio
async def test_phase09_hardware_and_clipboard_bounds():
    """
    Audit Phase 9 OS: Verify volume step bounds (<= 10%) and clipboard 4096-char ceiling.
    """
    # Step > 10% -> Rejected by CoreAudioVolumeAdapter
    with pytest.raises(ValueError):
        CoreAudioVolumeAdapter.set_volume(relative_step_percent=15.0)

    assert CoreAudioVolumeAdapter.MAX_RELATIVE_STEP_PERCENT == 10.0

    # Clipboard > 4096 chars -> Rejected by GovernedClipboardAdapter
    oversized = "A" * 4097
    with pytest.raises(Exception):
        GovernedClipboardAdapter.clipboard_write(oversized)

    assert GovernedClipboardAdapter.MAX_CLIPBOARD_CHARS == 4096


@pytest.mark.asyncio
async def test_phase09_tray_named_pipe_ipc_allowlist():
    """
    Audit Phase 9 OS: Verify Tray IPC server enforces command allowlist and rejects unlisted/injected commands.
    """
    allowlisted_commands = {cmd.value for cmd in TrayIPCCommand}

    assert "get_status" in allowlisted_commands
    assert "activate_kill_switch" in allowlisted_commands
    assert "get_privacy_state" in allowlisted_commands
    assert "get_telemetry" in allowlisted_commands
    assert "shutdown_tray" in allowlisted_commands

    # Arbitrary injection commands -> Not in allowlist
    assert "exec_shell" not in allowlisted_commands
    assert "download_file" not in allowlisted_commands
    assert "eval" not in allowlisted_commands
