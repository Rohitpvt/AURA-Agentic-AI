"""AURA-904 Live Host Validation Script."""

import asyncio
import os
import uuid
import pyperclip

from app.services.os_guard.telemetry_service import SystemTelemetryAdapter
from app.services.os_guard.hardware_service import (
    CapabilityDiscoveryService,
    CoreAudioVolumeAdapter,
    WmiDisplayBrightnessAdapter,
)
from app.services.os_guard.clipboard_service import GovernedClipboardAdapter
from app.services.os_guard.os_guard_service import OSGuardService
from app.services.os_guard.policy import OSPolicyEngine
from app.services.os_guard.adapters import WindowsOSExecutionAdapter
from app.services.os_guard.types import OSActionLifecycleState, OSActionRequest, OSActionType


async def live_validation():
    print("--- AURA-904 LIVE HOST VALIDATION ---")

    # 1. Telemetry
    telem = SystemTelemetryAdapter.get_system_telemetry()
    print(f"CPU Percent: {telem['cpu']['cpu_percent']}% ({telem['cpu']['cores_physical']} physical / {telem['cpu']['cores_logical']} logical cores)")
    print(f"RAM: {telem['ram']['used_mb']} MB / {telem['ram']['total_mb']} MB ({telem['ram']['percent']}%)")
    print(f"Process RSS: {telem['ram']['process_rss_mb']} MB")
    print(f"Storage: {telem['storage']['free_gb']} GB free / {telem['storage']['total_gb']} GB ({telem['storage']['percent']}%)")
    print(f"Battery supported: {telem['battery']['battery_supported']}, Percent: {telem['battery']['battery_percent']}%")
    print(f"GPU Supported: {telem['gpu']['gpu_supported']}, Name: {telem['gpu']['gpu_name']}, VRAM: {telem['gpu']['gpu_vram_used_mb']} / {telem['gpu']['gpu_vram_total_mb']} MB, Temp: {telem['gpu']['gpu_temperature_c']}°C")

    # 2. Capability Discovery
    caps = CapabilityDiscoveryService.get_hardware_capabilities()
    print(f"Capabilities: Volume={caps['volume_supported']}, Brightness={caps['brightness_supported']}, Displays={caps['display_count']}")

    # 3. Governed Master Volume Live Test (Bounded +/-2% test + restore)
    initial_vol = CoreAudioVolumeAdapter.get_volume()
    print(f"Initial Volume: {initial_vol['volume_percent']}%, Muted: {initial_vol['is_muted']}")
    if initial_vol["supported"]:
        step = -2.0 if initial_vol["volume_percent"] > 5.0 else +2.0
        adjusted = CoreAudioVolumeAdapter.set_volume(relative_step_percent=step)
        print(f"Adjusted Volume ({step:+.1f}%): resulting={adjusted['current_volume_percent']}%")
        # Restore initial
        restore_step = -step
        restored = CoreAudioVolumeAdapter.set_volume(relative_step_percent=restore_step)
        print(f"Restored Volume ({restore_step:+.1f}%): resulting={restored['current_volume_percent']}%")

    # 4. Governed Display Brightness Live Test
    initial_b = WmiDisplayBrightnessAdapter.get_brightness(1)
    print(f"Initial Brightness: {initial_b}")

    # 5. Synthetic Clipboard Live Test
    saved_clip = pyperclip.paste()
    synthetic_val = "AURA-904-SYNTHETIC-TEST"
    GovernedClipboardAdapter.clipboard_write(synthetic_val)
    read_back = GovernedClipboardAdapter.clipboard_read()
    print(f"Clipboard Readback: text='{read_back['text']}', char_count={read_back['character_count']}, redacted={read_back['redacted']}")
    # Restore user's previous clipboard
    pyperclip.copy(saved_clip)
    print("Previous user clipboard restored.")

    # 6. Kill Switch Live Test
    from unittest.mock import Mock
    mock_ks = Mock()
    mock_ks.is_active.return_value = True
    guard = OSGuardService(kill_switch=mock_ks)
    req = OSActionRequest(
        workspace_id=str(uuid.uuid4()),
        action_type=OSActionType.HARDWARE_CONTROL,
        parameters={"control_type": "set_system_volume", "relative_step_percent": 2.0},
    )
    resp = await guard.execute_os_action(req)
    print(f"Kill Switch Live Check State: {resp.state.value} (Expected: kill_switched)")
    assert resp.state == OSActionLifecycleState.KILL_SWITCHED

    print("--- LIVE VALIDATION COMPLETED SUCCESSFULLY ---")


if __name__ == "__main__":
    asyncio.run(live_validation())
