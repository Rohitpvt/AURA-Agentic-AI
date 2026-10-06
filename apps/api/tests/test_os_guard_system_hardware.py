"""AURA-904 System Telemetry, Hardware Control & Governed Clipboard Security Test Suite.

Verifies:
1. System & GPU Telemetry: CPU, RAM, GPU, VRAM, Storage, Battery, Display Topology, Degraded Fallbacks, Zero Secret Leakage.
2. Hardware Controls: Master Volume bounded adjustments (<= +/-10%), Display Brightness (<= +/-10%), Capability Discovery.
3. Clipboard Boundary: 4096 char ceiling, secret scrubbing, NUL byte rejection, zero audit plaintext leakage.
4. Governance Pipeline: ToolRegistryService, OSPolicyEngine, OSGuardService, Emergency Kill Switch, Sliding-Window Rate Limits.
"""

from __future__ import annotations

import asyncio
import os
import unittest.mock as mock
import uuid
import pytest
import psutil

from app.core.errors import ValidationError
from app.services.os_guard.clipboard_service import GovernedClipboardAdapter, governed_clipboard_adapter
from app.services.os_guard.hardware_service import (
    BrightnessControlNotSupportedError,
    CapabilityDiscoveryService,
    CoreAudioVolumeAdapter,
    WmiDisplayBrightnessAdapter,
    capability_discovery_service,
    core_audio_volume_adapter,
    wmi_display_brightness_adapter,
)
from app.services.os_guard.os_guard_service import OSGuardService, os_guard_service
from app.services.os_guard.policy import OSPolicyEngine, os_policy_engine
from app.services.os_guard.telemetry_service import (
    GPUTelemetryAdapter,
    SystemTelemetryAdapter,
    system_telemetry_adapter,
)
from app.services.os_guard.types import (
    HostExecutionPartition,
    OSActionLifecycleState,
    OSActionRequest,
    OSActionResponse,
    OSActionType,
    OSRiskTier,
    PolicyDecisionType,
)
from app.services.tool_registry import ToolRegistryService, tool_registry_service
from app.services.tools.os_tools import (
    execute_clipboard_read,
    execute_clipboard_write,
    execute_get_display_brightness,
    execute_get_hardware_capabilities,
    execute_get_system_telemetry,
    execute_get_system_volume,
    execute_set_display_brightness,
    execute_set_system_volume,
)


# ===========================================================================
# 1. System & GPU Telemetry Tests
# ===========================================================================

def test_system_telemetry_snapshot_structure():
    """Verify system telemetry snapshot contains all required bounded fields with zero credential leakage."""
    telemetry = SystemTelemetryAdapter.get_system_telemetry()
    assert telemetry["status"] == "success"
    assert "cpu" in telemetry
    assert "ram" in telemetry
    assert "storage" in telemetry
    assert "battery" in telemetry
    assert "gpu" in telemetry
    assert "displays" in telemetry

    # CPU checks
    assert isinstance(telemetry["cpu"]["cpu_percent"], float)
    assert telemetry["cpu"]["cores_physical"] >= 1
    assert telemetry["cpu"]["cores_logical"] >= 1

    # RAM checks
    assert telemetry["ram"]["total_mb"] > 0
    assert telemetry["ram"]["used_mb"] >= 0
    assert 0.0 <= telemetry["ram"]["percent"] <= 100.0
    assert telemetry["ram"]["process_rss_mb"] >= 0.0

    # Storage checks
    assert telemetry["storage"]["total_gb"] > 0
    assert telemetry["storage"]["free_gb"] >= 0
    assert 0.0 <= telemetry["storage"]["percent"] <= 100.0

    # Privacy Invariant: Zero env variables or secrets in telemetry dict
    raw_str = str(telemetry)
    assert "AURA_SECRET_KEY" not in raw_str
    assert "DATABASE_URL" not in raw_str
    assert "GEMINI_API_KEY" not in raw_str


def test_gpu_telemetry_parsing_and_degraded_fallback():
    """Verify GPU telemetry parser handles valid output and missing driver gracefully."""
    # Test valid mock parsing
    mock_csv_output = "42, 1024, 4096, 55, NVIDIA GeForce RTX 3050 Laptop GPU\n"
    with mock.patch("subprocess.run") as mock_run:
        mock_run.return_value = mock.Mock(returncode=0, stdout=mock_csv_output, stderr="")
        with mock.patch("shutil.which", return_value="C:\\Windows\\System32\\nvidia-smi.exe"):
            gpu_data = GPUTelemetryAdapter.get_gpu_telemetry()
            assert gpu_data["gpu_supported"] is True
            assert gpu_data["gpu_utilization_percent"] == 42.0
            assert gpu_data["gpu_vram_used_mb"] == 1024.0
            assert gpu_data["gpu_vram_total_mb"] == 4096.0
            assert gpu_data["gpu_temperature_c"] == 55.0
            assert "RTX 3050" in gpu_data["gpu_name"]

    # Test missing nvidia-smi degraded fallback
    with mock.patch("shutil.which", return_value=None):
        with mock.patch("os.path.exists", return_value=False):
            degraded = GPUTelemetryAdapter.get_gpu_telemetry()
            assert degraded["gpu_supported"] is False
            assert degraded["gpu_name"] is None
            assert degraded["gpu_vram_used_mb"] is None


def test_battery_sensor_degraded_fallback():
    """Verify battery telemetry safely handles desktop hosts without batteries."""
    with mock.patch("psutil.sensors_battery", return_value=None):
        telemetry = SystemTelemetryAdapter.get_system_telemetry()
        assert telemetry["battery"]["battery_supported"] is False
        assert telemetry["battery"]["battery_percent"] is None


# ===========================================================================
# 2. Hardware Control: Master Volume Tests
# ===========================================================================

def test_volume_step_bounding_and_clamping():
    """Verify volume adjustments strictly enforce +/-10% ceiling."""
    # Test relative step validation
    with pytest.raises(ValueError, match="exceeds safety ceiling"):
        CoreAudioVolumeAdapter.set_volume(relative_step_percent=15.0)

    with pytest.raises(ValueError, match="exceeds safety ceiling"):
        CoreAudioVolumeAdapter.set_volume(relative_step_percent=-12.5)

    # Test missing parameters
    with pytest.raises(ValueError, match="Must provide at least one"):
        CoreAudioVolumeAdapter.set_volume()


def test_volume_get_and_set_mocked():
    """Verify volume read, adjustment, and rollback snapshot in execution."""
    mock_ctrl = mock.Mock()
    mock_ctrl.GetMasterVolumeLevelScalar.return_value = 0.50
    mock_ctrl.GetMute.return_value = False

    with mock.patch.object(CoreAudioVolumeAdapter, "_get_volume_endpoint", return_value=mock_ctrl):
        # Query
        vol_info = CoreAudioVolumeAdapter.get_volume()
        assert vol_info["status"] == "success"
        assert vol_info["volume_percent"] == 50.0
        assert vol_info["is_muted"] is False

        # Adjust +5%
        res = CoreAudioVolumeAdapter.set_volume(relative_step_percent=5.0)
        assert res["status"] == "success"
        assert res["previous_volume_percent"] == 50.0
        assert res["rollback_available"] is True
        mock_ctrl.SetMasterVolumeLevelScalar.assert_called_once()


# ===========================================================================
# 3. Hardware Control: Display Brightness Tests
# ===========================================================================

def test_brightness_step_bounding():
    """Verify display brightness enforces +/-10% step ceiling."""
    with pytest.raises(ValueError, match="exceeds safety ceiling"):
        WmiDisplayBrightnessAdapter.set_brightness(monitor_id=1, relative_step_percent=15.0)

    with pytest.raises(ValueError, match="Must provide either"):
        WmiDisplayBrightnessAdapter.set_brightness(monitor_id=1)


def test_brightness_unsupported_hardware_fallback():
    """Verify unsupported display hardware raises BrightnessControlNotSupportedError gracefully."""
    with mock.patch("platform.system", return_value="Windows"):
        with mock.patch("win32com.client.GetObject") as mock_wmi:
            mock_wmi.return_value.ExecQuery.return_value = []
            with pytest.raises(BrightnessControlNotSupportedError):
                WmiDisplayBrightnessAdapter.set_brightness(monitor_id=1, relative_step_percent=5.0)


# ===========================================================================
# 4. Capability Discovery Tests
# ===========================================================================

def test_hardware_capability_discovery():
    """Verify capability discovery inspects all required hardware pillars."""
    caps = CapabilityDiscoveryService.get_hardware_capabilities()
    assert caps["status"] == "success"
    assert "volume_supported" in caps
    assert "brightness_supported" in caps
    assert "display_count" in caps
    assert "displays" in caps
    assert "battery_supported" in caps
    assert "gpu_telemetry_supported" in caps
    assert "temperature_supported" in caps


# ===========================================================================
# 5. Governed Clipboard Boundary Tests
# ===========================================================================

def test_clipboard_read_length_and_secret_scrubbing():
    """Verify clipboard read enforces 4096 char ceiling and scrubs sensitive keys/tokens."""
    # Test secret scrubbing
    secret_payload = "My secret token is AIzaSyD3m0K3y-12345678901234567890 and Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.doNotLeakThis"
    with mock.patch("pyperclip.paste", return_value=secret_payload):
        res = GovernedClipboardAdapter.clipboard_read()
        assert res["status"] == "success"
        assert res["redacted"] is True
        assert "[REDACTED_GEMINI_KEY]" in res["text"] or "[REDACTED_JWT_TOKEN]" in res["text"]
        assert "AIzaSyD3m0K3y" not in res["text"]

    # Test length truncation at 4096 characters
    long_payload = "A" * 5000
    with mock.patch("pyperclip.paste", return_value=long_payload):
        res = GovernedClipboardAdapter.clipboard_read()
        assert res["truncated"] is True
        assert res["character_count"] == 4096
        assert res["original_length"] == 5000


def test_clipboard_write_validation_and_nul_rejection():
    """Verify clipboard write rejects oversized payloads and NUL byte injection."""
    # Reject NUL bytes
    with pytest.raises(ValidationError, match="NUL byte"):
        GovernedClipboardAdapter.clipboard_write("Hello\x00World")

    # Reject oversized payload
    with pytest.raises(ValidationError, match="exceeds safety ceiling"):
        GovernedClipboardAdapter.clipboard_write("B" * 4097)

    # Valid write
    with mock.patch("pyperclip.copy") as mock_copy:
        res = GovernedClipboardAdapter.clipboard_write("Safe clean payload")
        assert res["status"] == "success"
        assert res["character_count"] == 18
        assert len(res["sha256_hash"]) == 64
        mock_copy.assert_called_once_with("Safe clean payload")


# ===========================================================================
# 6. Policy Engine & Rate Limiting Tests
# ===========================================================================

def test_policy_risk_tier_mapping_for_aura904():
    """Verify deterministic risk mapping across AURA-904 action types."""
    engine = OSPolicyEngine()

    # Telemetry and discovery -> READ_ONLY
    assert engine.get_risk_tier(OSActionType.SYSTEM_TELEMETRY) == OSRiskTier.READ_ONLY
    assert engine.get_risk_tier(OSActionType.CLIPBOARD_READ) == OSRiskTier.READ_ONLY
    assert engine.get_risk_tier(
        OSActionType.HARDWARE_CONTROL, {"control_type": "get_volume"}
    ) == OSRiskTier.READ_ONLY

    # Small hardware adjustments -> LOW_RISK_WRITE
    assert engine.get_risk_tier(
        OSActionType.HARDWARE_CONTROL, {"control_type": "set_volume", "relative_step_percent": 5.0}
    ) == OSRiskTier.LOW_RISK_WRITE

    # Large hardware jump (>10%) -> HIGH_RISK_SYSTEM_ACTION
    assert engine.get_risk_tier(
        OSActionType.HARDWARE_CONTROL, {"control_type": "set_volume", "relative_step_percent": 15.0}
    ) == OSRiskTier.HIGH_RISK_SYSTEM_ACTION

    # Clipboard write -> MEDIUM_RISK_INTERACTION
    assert engine.get_risk_tier(OSActionType.CLIPBOARD_WRITE) == OSRiskTier.MEDIUM_RISK_INTERACTION


def test_sliding_window_rate_limits_for_aura904():
    """Verify rate limiter bounds operations per 60 seconds."""
    engine = OSPolicyEngine()
    ws_id = "test-ws-rate-904"

    # Hardware control limit is 10/min
    req = OSActionRequest(
        workspace_id=ws_id,
        action_type=OSActionType.HARDWARE_CONTROL,
        parameters={"control_type": "set_volume", "relative_step_percent": 2.0},
    )

    for i in range(10):
        decision = engine.evaluate_action(req, autonomy_level=3)
        assert decision.decision == PolicyDecisionType.ALLOW

    # 11th request in same minute must be rate-limited
    decision_11 = engine.evaluate_action(req, autonomy_level=3)
    assert decision_11.decision == PolicyDecisionType.RATE_LIMIT


# ===========================================================================
# 7. OSGuard & Emergency Kill Switch Tests
# ===========================================================================

@pytest.mark.asyncio
async def test_os_guard_kill_switch_blocks_hardware_and_clipboard():
    """Verify active Emergency Kill Switch halts hardware and clipboard actions."""
    mock_ks = mock.Mock()
    mock_ks.is_active.return_value = True

    guard = OSGuardService(kill_switch=mock_ks)
    ws_id = "test-ws-ks-904"

    req_hw = OSActionRequest(
        workspace_id=ws_id,
        action_type=OSActionType.HARDWARE_CONTROL,
        parameters={"control_type": "set_system_volume", "relative_step_percent": 2.0},
    )
    resp_hw = await guard.execute_os_action(req_hw)
    assert resp_hw.state == OSActionLifecycleState.KILL_SWITCHED

    req_cb = OSActionRequest(
        workspace_id=ws_id,
        action_type=OSActionType.CLIPBOARD_WRITE,
        parameters={"text": "test"},
    )
    resp_cb = await guard.execute_os_action(req_cb)
    assert resp_cb.state == OSActionLifecycleState.KILL_SWITCHED


# ===========================================================================
# 8. Tool Registry & Governed Tool Handlers Integration
# ===========================================================================

@pytest.mark.asyncio
async def test_builtin_tool_registry_aura904_registration():
    """Verify all 8 AURA-904 tools are registered in ToolRegistryService."""
    registry = ToolRegistryService()
    expected_tools = [
        "get_system_telemetry",
        "get_hardware_capabilities",
        "get_system_volume",
        "set_system_volume",
        "get_display_brightness",
        "set_display_brightness",
        "clipboard_read",
        "clipboard_write",
    ]
    for t_name in expected_tools:
        assert t_name in registry._handlers, f"Tool '{t_name}' is not registered in ToolRegistryService."


@pytest.mark.asyncio
async def test_execute_system_telemetry_tool():
    """Test execute_get_system_telemetry end-to-end through tool handler."""
    ws_id = uuid.uuid4()
    res = await execute_get_system_telemetry(workspace_id=ws_id)
    assert res["status"] == "success"
    assert "cpu" in res
    assert "ram" in res


@pytest.mark.asyncio
async def test_execute_hardware_capabilities_tool():
    """Test execute_get_hardware_capabilities end-to-end through tool handler."""
    ws_id = uuid.uuid4()
    res = await execute_get_hardware_capabilities(workspace_id=ws_id)
    assert res["status"] == "success"
    assert "volume_supported" in res
    assert "brightness_supported" in res


@pytest.mark.asyncio
async def test_execute_clipboard_read_write_tool():
    """Test execute_clipboard_read and execute_clipboard_write end-to-end with mock."""
    ws_id = uuid.uuid4()
    with mock.patch("pyperclip.copy") as mock_copy, mock.patch("pyperclip.paste", return_value="AURA-904-SYNTHETIC-TEST"):
        # Write
        w_res = await execute_clipboard_write(
            workspace_id=ws_id,
            arguments={"text": "AURA-904-SYNTHETIC-TEST"},
        )
        assert w_res["status"] == "success"
        assert w_res["character_count"] == 23

        # Read
        r_res = await execute_clipboard_read(workspace_id=ws_id)
        assert r_res["status"] == "success"
        assert r_res["text"] == "AURA-904-SYNTHETIC-TEST"
        assert r_res["character_count"] == 23


# ===========================================================================
# 9. Cryptographic HITL & Audit Ledger Redaction Security Tests
# ===========================================================================

def test_clipboard_write_hitl_token_binding_and_replay():
    """Verify cryptographic HMAC-SHA256 HITL token binding, anti-tampering, and replay protection for clipboard write."""
    engine = OSPolicyEngine()
    ws_id = "test-ws-hitl-cb"
    valid_params = {"text": "AURA-904-HITL-APPROVED-PAYLOAD"}

    # 1. Evaluate at L0 autonomy (requires HITL)
    req = OSActionRequest(
        workspace_id=ws_id,
        action_type=OSActionType.CLIPBOARD_WRITE,
        parameters=valid_params,
    )
    decision = engine.evaluate_action(req, autonomy_level=0)
    assert decision.decision == PolicyDecisionType.REQUIRE_HITL
    assert decision.requires_hitl is True

    # 2. Generate valid cryptographic HMAC-SHA256 token
    token = engine.generate_hitl_approval_token(
        action_type=OSActionType.CLIPBOARD_WRITE,
        workspace_id=ws_id,
        parameters=valid_params,
        ttl_seconds=120,
    )
    req.hitl_approval_token = token

    # 3. Evaluate with valid token -> ALLOW
    decision_ok = engine.evaluate_action(req, autonomy_level=0)
    assert decision_ok.decision == PolicyDecisionType.ALLOW

    # 4. Attempt token reuse (Replay Attack) -> DENY
    decision_replay = engine.evaluate_action(req, autonomy_level=0)
    assert decision_replay.decision == PolicyDecisionType.DENY
    assert "Replay denied" in decision_replay.reason

    # 5. Parameter Tampering Attack (Modify text under approved token) -> DENY
    tampered_req = OSActionRequest(
        workspace_id=ws_id,
        action_type=OSActionType.CLIPBOARD_WRITE,
        parameters={"text": "MALICIOUS-TAMPERED-PAYLOAD"},
        hitl_approval_token=token,
    )
    decision_tamper = engine.evaluate_action(tampered_req, autonomy_level=0)
    assert decision_tamper.decision == PolicyDecisionType.DENY


def test_hardware_large_target_jump_denial():
    """Verify absolute target parameters that cause >10% jumps are hard-rejected."""
    mock_ctrl = mock.Mock()
    mock_ctrl.GetMasterVolumeLevelScalar.return_value = 0.50
    mock_ctrl.GetMute.return_value = False

    with mock.patch.object(CoreAudioVolumeAdapter, "_get_volume_endpoint", return_value=mock_ctrl):
        # Current is 50%; jump to 80% (+30%) must be rejected
        with pytest.raises(ValueError, match="exceeds the safety ceiling"):
            CoreAudioVolumeAdapter.set_volume(target_volume_percent=80.0)


@pytest.mark.asyncio
async def test_clipboard_audit_redaction_ledger():
    """Verify OSGuard audit event records redacted payload and character count with zero raw plaintext."""
    mock_db = mock.AsyncMock()
    ws_id = str(uuid.uuid4())

    req = OSActionRequest(
        workspace_id=ws_id,
        action_type=OSActionType.CLIPBOARD_WRITE,
        parameters={"text": "SUPER_SECRET_TOKEN_VALUE_12345"},
    )

    with mock.patch("app.services.audit_service.audit_service.record_event") as mock_audit:
        resp = await os_guard_service.execute_os_action(
            request=req,
            db=mock_db,
        )
        assert resp.state == OSActionLifecycleState.COMPLETED
        mock_audit.assert_called_once()
        call_kwargs = mock_audit.call_args.kwargs
        details = call_kwargs["details"]

        # Plaintext must NOT appear in audit details
        assert details["parameters_redacted"]["text"] == "[REDACTED_CLIPBOARD_CONTENT]"
        assert details["parameters_redacted"]["character_count"] == len("SUPER_SECRET_TOKEN_VALUE_12345")
        assert "SUPER_SECRET_TOKEN_VALUE_12345" not in str(details)

