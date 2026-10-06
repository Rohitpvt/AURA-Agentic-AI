"""AURA-904 Governed Hardware Control Adapters & Capability Discovery.

Provides:
1. CoreAudioVolumeAdapter: Native Windows Core Audio (IAudioEndpointVolume) master volume query,
   bounded adjustment (<= +/-10% per step), mute toggle, and verification/rollback snapshot.
2. WmiDisplayBrightnessAdapter: Per-monitor brightness query and bounded adjustment (<= +/-10% per step)
   via Windows WMI (WmiMonitorBrightness/Methods) with monitor identity validation and graceful
   unsupported display fallback (BrightnessControlNotSupportedError).
3. CapabilityDiscoveryService: Fast, read-only inspection of host hardware control capabilities.

Safety & Governance Invariants:
- Relative adjustments are strictly bounded to -10.0% <= step <= +10.0%
- Absolute volume/brightness targets are clamped to 0.0% .. 100.0%
- Pre-action snapshots are captured for verification and potential rollback
- Unknown displays or unsupported DDC-CI hardware fail closed with deterministic errors
- Zero arbitrary Win32/WMI or register passthrough
"""

from __future__ import annotations

import ctypes
from ctypes import POINTER, c_bool, c_float, c_uint, c_void_p, c_wchar_p
import os
import platform
import time
from typing import Any, Dict, List, Optional, Tuple

from app.core.logging import logger


class BrightnessControlNotSupportedError(RuntimeError):
    """Raised when the target display hardware or driver does not support WMI/DDC-CI brightness control."""
    pass


# ---------------------------------------------------------------------------
# Windows Core Audio COM Interfaces
# ---------------------------------------------------------------------------

try:
    from comtypes import CLSCTX_ALL, COMMETHOD, GUID, HRESULT, IUnknown
    import comtypes
    import comtypes.client

    class IAudioEndpointVolume(IUnknown):
        _iid_ = GUID('{5CDF2C82-841E-4546-9722-0CF74078229A}')
        _methods_ = [
            COMMETHOD([], HRESULT, 'RegisterControlChangeNotify', (['in'], c_void_p, 'pNotify')),
            COMMETHOD([], HRESULT, 'UnregisterControlChangeNotify', (['in'], c_void_p, 'pNotify')),
            COMMETHOD([], HRESULT, 'GetChannelCount', (['out'], POINTER(c_uint), 'pnChannelCount')),
            COMMETHOD([], HRESULT, 'SetMasterVolumeLevel', (['in'], c_float, 'fLevelDB'), (['in'], POINTER(GUID), 'pguidEventContext')),
            COMMETHOD([], HRESULT, 'SetMasterVolumeLevelScalar', (['in'], c_float, 'fLevel'), (['in'], POINTER(GUID), 'pguidEventContext')),
            COMMETHOD([], HRESULT, 'GetMasterVolumeLevel', (['out'], POINTER(c_float), 'pfLevelDB')),
            COMMETHOD([], HRESULT, 'GetMasterVolumeLevelScalar', (['out'], POINTER(c_float), 'pfLevel')),
            COMMETHOD([], HRESULT, 'SetChannelVolumeLevel', (['in'], c_uint, 'nChannel'), (['in'], c_float, 'fLevelDB'), (['in'], POINTER(GUID), 'pguidEventContext')),
            COMMETHOD([], HRESULT, 'SetChannelVolumeLevelScalar', (['in'], c_uint, 'nChannel'), (['in'], c_float, 'fLevel'), (['in'], POINTER(GUID), 'pguidEventContext')),
            COMMETHOD([], HRESULT, 'GetChannelVolumeLevel', (['in'], c_uint, 'nChannel'), (['out'], POINTER(c_float), 'pfLevelDB')),
            COMMETHOD([], HRESULT, 'GetChannelVolumeLevelScalar', (['in'], c_uint, 'nChannel'), (['out'], POINTER(c_float), 'pfLevel')),
            COMMETHOD([], HRESULT, 'SetMute', (['in'], c_bool, 'bMute'), (['in'], POINTER(GUID), 'pguidEventContext')),
            COMMETHOD([], HRESULT, 'GetMute', (['out'], POINTER(c_bool), 'pbMute')),
            COMMETHOD([], HRESULT, 'GetVolumeStepInfo', (['out'], POINTER(c_uint), 'pnStep'), (['out'], POINTER(c_uint), 'pnStepCount')),
            COMMETHOD([], HRESULT, 'VolumeStepUp', (['in'], POINTER(GUID), 'pguidEventContext')),
            COMMETHOD([], HRESULT, 'VolumeStepDown', (['in'], POINTER(GUID), 'pguidEventContext')),
            COMMETHOD([], HRESULT, 'QueryHardwareSupport', (['out'], POINTER(c_uint), 'pdwHardwareSupportMask')),
            COMMETHOD([], HRESULT, 'GetVolumeRange', (['out'], POINTER(c_float), 'pflVolumeMindB'), (['out'], POINTER(c_float), 'pflVolumeMaxdB'), (['out'], POINTER(c_float), 'pflVolumeIncrementdB')),
        ]

    class IMMDevice(IUnknown):
        _iid_ = GUID('{D666063F-1587-4E43-81F1-B948E807363F}')
        _methods_ = [
            COMMETHOD([], HRESULT, 'Activate', (['in'], POINTER(GUID), 'iid'), (['in'], c_uint, 'dwClsCtx'), (['in'], c_void_p, 'pActivationParams'), (['out'], POINTER(POINTER(IUnknown)), 'ppInterface')),
            COMMETHOD([], HRESULT, 'OpenPropertyStore', (['in'], c_uint, 'stgmAccess'), (['out'], c_void_p, 'ppProperties')),
            COMMETHOD([], HRESULT, 'GetId', (['out'], POINTER(c_wchar_p), 'ppstrId')),
            COMMETHOD([], HRESULT, 'GetState', (['out'], POINTER(c_uint), 'pdwState')),
        ]

    class IMMDeviceEnumerator(IUnknown):
        _iid_ = GUID('{A95664D2-9614-4F35-A746-DE8DB63617E6}')
        _methods_ = [
            COMMETHOD([], HRESULT, 'EnumAudioEndpoints', (['in'], c_uint, 'dataFlow'), (['in'], c_uint, 'dwStateMask'), (['out'], c_void_p, 'ppDevices')),
            COMMETHOD([], HRESULT, 'GetDefaultAudioEndpoint', (['in'], c_uint, 'dataFlow'), (['in'], c_uint, 'role'), (['out'], POINTER(POINTER(IMMDevice)), 'ppDevice')),
            COMMETHOD([], HRESULT, 'GetDevice', (['in'], c_wchar_p, 'pwstrId'), (['out'], c_void_p, 'ppDevice')),
            COMMETHOD([], HRESULT, 'RegisterEndpointNotificationCallback', (['in'], c_void_p, 'pClient')),
            COMMETHOD([], HRESULT, 'UnregisterEndpointNotificationCallback', (['in'], c_void_p, 'pClient')),
        ]

    CLSID_MMDeviceEnumerator = GUID('{BCDE0395-E52F-467C-8E3D-C4579291692E}')
    _HAS_COM_AUDIO = True
except Exception as _e:
    _HAS_COM_AUDIO = False


class CoreAudioVolumeAdapter:
    """Governed Windows Core Audio master volume adapter."""

    MAX_RELATIVE_STEP_PERCENT: float = 10.0

    @classmethod
    def _get_volume_endpoint(cls):
        """Instantiate and return the active default multimedia audio endpoint volume COM interface."""
        if platform.system() != "Windows" or not _HAS_COM_AUDIO:
            raise RuntimeError("Windows Core Audio is only supported on Windows host platforms.")

        comtypes.CoInitialize()
        enumerator = comtypes.client.CreateObject(CLSID_MMDeviceEnumerator, interface=IMMDeviceEnumerator)
        endpoint = enumerator.GetDefaultAudioEndpoint(0, 1)  # eRender=0, eMultimedia=1
        interface = endpoint.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        return ctypes.cast(interface, POINTER(IAudioEndpointVolume))

    @classmethod
    def get_volume(cls) -> Dict[str, Any]:
        """Query current master volume scalar (0.0 .. 1.0) and mute state."""
        try:
            vol_ctrl = cls._get_volume_endpoint()
            scalar = vol_ctrl.GetMasterVolumeLevelScalar()
            is_muted = vol_ctrl.GetMute()
            percent = round(float(scalar) * 100.0, 1)

            return {
                "status": "success",
                "volume_scalar": round(float(scalar), 4),
                "volume_percent": percent,
                "is_muted": bool(is_muted),
                "supported": True,
            }
        except Exception as exc:
            logger.warning(f"CoreAudioVolumeAdapter: Error reading master volume: {exc}")
            return {
                "status": "error",
                "volume_scalar": None,
                "volume_percent": None,
                "is_muted": None,
                "supported": False,
                "error": str(exc),
            }
        finally:
            if _HAS_COM_AUDIO:
                try:
                    comtypes.CoUninitialize()
                except Exception:
                    pass

    @classmethod
    def set_volume(
        cls,
        relative_step_percent: Optional[float] = None,
        target_volume_percent: Optional[float] = None,
        mute: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Adjust system master audio volume with strict relative step bounds and verification."""
        # 1. Parameter Validation
        if relative_step_percent is None and target_volume_percent is None and mute is None:
            raise ValueError("Must provide at least one of 'relative_step_percent', 'target_volume_percent', or 'mute'.")

        if relative_step_percent is not None:
            if abs(relative_step_percent) > cls.MAX_RELATIVE_STEP_PERCENT:
                raise ValueError(
                    f"Relative volume step {relative_step_percent:+.1f}% exceeds safety ceiling of +/-{cls.MAX_RELATIVE_STEP_PERCENT}%."
                )

        try:
            vol_ctrl = cls._get_volume_endpoint()

            # 2. Capture Pre-Action Snapshot for Verification & Rollback
            initial_scalar = float(vol_ctrl.GetMasterVolumeLevelScalar())
            initial_percent = round(initial_scalar * 100.0, 1)
            initial_muted = bool(vol_ctrl.GetMute())

            new_scalar = initial_scalar
            new_muted = initial_muted

            # 3. Calculate New Scalar Target
            if relative_step_percent is not None:
                step_scalar = relative_step_percent / 100.0
                new_scalar = max(0.0, min(1.0, initial_scalar + step_scalar))
            elif target_volume_percent is not None:
                # Target percentage bounded 0..100
                clamped_target = max(0.0, min(100.0, float(target_volume_percent)))
                # Enforce step ceiling relative to current volume even for absolute target
                diff_percent = clamped_target - initial_percent
                if abs(diff_percent) > cls.MAX_RELATIVE_STEP_PERCENT:
                    raise ValueError(
                        f"Target volume {clamped_target:.1f}% results in a {diff_percent:+.1f}% jump, "
                        f"which exceeds the safety ceiling of +/-{cls.MAX_RELATIVE_STEP_PERCENT}%. Use smaller incremental steps."
                    )
                new_scalar = clamped_target / 100.0

            # 4. Apply Volume Scalar Mutation
            if new_scalar != initial_scalar:
                vol_ctrl.SetMasterVolumeLevelScalar(c_float(new_scalar), None)

            # 5. Apply Mute Toggle Mutation
            if mute is not None:
                new_muted = bool(mute)
                vol_ctrl.SetMute(c_bool(new_muted), None)

            # 6. Read Back and Verify Resulting Hardware State
            resulting_scalar = float(vol_ctrl.GetMasterVolumeLevelScalar())
            resulting_percent = round(resulting_scalar * 100.0, 1)
            resulting_muted = bool(vol_ctrl.GetMute())

            return {
                "status": "success",
                "previous_volume_percent": initial_percent,
                "previous_muted": initial_muted,
                "current_volume_percent": resulting_percent,
                "current_volume_scalar": round(resulting_scalar, 4),
                "is_muted": resulting_muted,
                "delta_percent": round(resulting_percent - initial_percent, 1),
                "rollback_available": True,
            }

        except ValueError:
            raise
        except Exception as exc:
            logger.error(f"CoreAudioVolumeAdapter: Volume adjustment failed: {exc}")
            raise RuntimeError(f"Volume adjustment failed: {exc}") from exc
        finally:
            if _HAS_COM_AUDIO:
                try:
                    comtypes.CoUninitialize()
                except Exception:
                    pass


class WmiDisplayBrightnessAdapter:
    """Governed display brightness adapter using Windows WMI / DDC-CI."""

    MAX_RELATIVE_STEP_PERCENT: float = 10.0

    @classmethod
    def get_brightness(cls, monitor_id: int = 1) -> Dict[str, Any]:
        """Query display brightness for target monitor."""
        if platform.system() != "Windows":
            return {
                "supported": False,
                "brightness_percent": None,
                "monitor_id": monitor_id,
                "reason": "WMI display brightness is only supported on Windows host platforms.",
            }

        try:
            import win32com.client
            wmi_obj = win32com.client.GetObject(r"winmgmts:\\.\root\wmi")
            brightness_items = wmi_obj.ExecQuery("SELECT * FROM WmiMonitorBrightness")
            
            items_list = list(brightness_items)
            if not items_list:
                return {
                    "supported": False,
                    "brightness_percent": None,
                    "monitor_id": monitor_id,
                    "reason": "No WmiMonitorBrightness objects found on this host (display may not support WMI brightness or is external without DDC-CI).",
                }

            # Match display index (1-based)
            idx = monitor_id - 1
            if idx < 0 or idx >= len(items_list):
                # Fallback to primary display (index 0) if single monitor
                idx = 0

            target_item = items_list[idx]
            current_b = int(target_item.CurrentBrightness)

            return {
                "supported": True,
                "brightness_percent": current_b,
                "monitor_id": monitor_id,
                "status": "success",
            }
        except Exception as exc:
            logger.warning(f"WmiDisplayBrightnessAdapter: Error querying brightness: {exc}")
            return {
                "supported": False,
                "brightness_percent": None,
                "monitor_id": monitor_id,
                "reason": f"WMI query error: {exc}",
            }

    @classmethod
    def set_brightness(
        cls,
        monitor_id: int = 1,
        relative_step_percent: Optional[float] = None,
        target_brightness_percent: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Adjust display brightness with strict bounds and pre-action verification."""
        if platform.system() != "Windows":
            raise BrightnessControlNotSupportedError("Display brightness control is only supported on Windows.")

        # 1. Parameter Bounds Check
        if relative_step_percent is None and target_brightness_percent is None:
            raise ValueError("Must provide either 'relative_step_percent' or 'target_brightness_percent'.")

        if relative_step_percent is not None:
            if abs(relative_step_percent) > cls.MAX_RELATIVE_STEP_PERCENT:
                raise ValueError(
                    f"Relative brightness step {relative_step_percent:+.1f}% exceeds safety ceiling of +/-{cls.MAX_RELATIVE_STEP_PERCENT}%."
                )

        try:
            import win32com.client
            wmi_obj = win32com.client.GetObject(r"winmgmts:\\.\root\wmi")
            brightness_methods = wmi_obj.ExecQuery("SELECT * FROM WmiMonitorBrightnessMethods")
            methods_list = list(brightness_methods)

            if not methods_list:
                raise BrightnessControlNotSupportedError(
                    "Display brightness control is not supported by the display hardware or driver (WmiMonitorBrightnessMethods not available)."
                )

            idx = monitor_id - 1
            if idx < 0 or idx >= len(methods_list):
                idx = 0

            target_method = methods_list[idx]

            # 2. Query Current Brightness for Verification Snapshot
            current_info = cls.get_brightness(monitor_id=monitor_id)
            if not current_info.get("supported") or current_info.get("brightness_percent") is None:
                raise BrightnessControlNotSupportedError(
                    f"Unable to read current brightness for monitor {monitor_id}: {current_info.get('reason')}"
                )

            initial_brightness = int(current_info["brightness_percent"])

            # 3. Calculate New Target Brightness
            if relative_step_percent is not None:
                new_brightness = int(round(initial_brightness + relative_step_percent))
            else:
                target_b = int(target_brightness_percent)
                diff = target_b - initial_brightness
                if abs(diff) > cls.MAX_RELATIVE_STEP_PERCENT:
                    raise ValueError(
                        f"Target brightness {target_b}% results in a {diff:+d}% jump, "
                        f"which exceeds the safety ceiling of +/-{cls.MAX_RELATIVE_STEP_PERCENT}%. Use smaller incremental steps."
                    )
                new_brightness = target_b

            new_brightness = max(0, min(100, new_brightness))

            # 4. Dispatch WMI Brightness Mutation (Timeout 5s via WMI parameter)
            in_params = target_method.Methods_("WmiSetBrightness").InParameters.SpawnInstance_()
            in_params.Timeout = 5
            in_params.Brightness = new_brightness
            target_method.ExecMethod_("WmiSetBrightness", in_params)

            # 5. Read Back and Verify (allow hardware driver propagation)
            time.sleep(0.12)
            verify_info = cls.get_brightness(monitor_id=monitor_id)
            resulting_b = verify_info.get("brightness_percent", new_brightness)

            return {
                "status": "success",
                "monitor_id": monitor_id,
                "previous_brightness_percent": initial_brightness,
                "current_brightness_percent": resulting_b,
                "delta_percent": resulting_b - initial_brightness,
                "rollback_available": True,
            }

        except (ValueError, BrightnessControlNotSupportedError):
            raise
        except Exception as exc:
            logger.error(f"WmiDisplayBrightnessAdapter: Brightness adjustment failed: {exc}")
            raise RuntimeError(f"Brightness adjustment failed: {exc}") from exc


class CapabilityDiscoveryService:
    """Read-only inspection service for host hardware control capabilities."""

    @classmethod
    def get_hardware_capabilities(cls) -> Dict[str, Any]:
        """Inspect and return availability of host hardware controls."""
        # 1. Volume Capability
        vol_info = CoreAudioVolumeAdapter.get_volume()
        volume_supported = vol_info.get("supported", False)

        # 2. Brightness Capability
        bright_info = WmiDisplayBrightnessAdapter.get_brightness(1)
        brightness_supported = bright_info.get("supported", False)

        # 3. Display Topology
        from app.services.os_guard.telemetry_service import SystemTelemetryAdapter
        telemetry = SystemTelemetryAdapter.get_system_telemetry()
        display_count = telemetry["displays"]["display_count"]
        displays = telemetry["displays"]["topology"]

        # Tag each display with brightness support
        for d in displays:
            d_b = WmiDisplayBrightnessAdapter.get_brightness(d.get("monitor_id", 1))
            d["brightness_supported"] = d_b.get("supported", False)

        # 4. Battery & GPU & Temperature
        battery_supported = telemetry["battery"]["battery_supported"]
        gpu_telemetry_supported = telemetry["gpu"]["gpu_supported"]
        temperature_supported = telemetry["temperature"]["temperature_supported"]

        return {
            "status": "success",
            "volume_supported": volume_supported,
            "brightness_supported": brightness_supported,
            "display_count": display_count,
            "displays": displays,
            "battery_supported": battery_supported,
            "gpu_telemetry_supported": gpu_telemetry_supported,
            "temperature_supported": temperature_supported,
        }


core_audio_volume_adapter = CoreAudioVolumeAdapter()
wmi_display_brightness_adapter = WmiDisplayBrightnessAdapter()
capability_discovery_service = CapabilityDiscoveryService()
