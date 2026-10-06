"""AURA-904 System & Hardware Telemetry Adapter.

Provides read-only, bounded, local snapshots of:
1. CPU utilization (total and per-core) and processor core counts via psutil
2. System RAM utilization (total, used, available, percentage) via psutil
3. Process RSS memory consumption of the active AURA server
4. Storage utilization (total, free, percentage) of host disk
5. Battery and power status via psutil.sensors_battery()
6. GPU & VRAM telemetry via local nvidia-smi with 1.5s timeout and degraded fallback
7. Display topology from ScreenCaptureService
8. Temperature metrics where safely available

Privacy Invariants:
- Zero process command-line argument leakage
- Zero environment variable leakage
- Zero credential or secret leakage
- Zero cloud monitoring dependencies ($0.00 zero-cost floor)
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from typing import Any, Dict, List, Optional
import psutil

from app.core.logging import logger


class GPUTelemetryAdapter:
    """Safe local GPU telemetry collector using non-shell nvidia-smi queries."""

    NVIDIA_SMI_TIMEOUT_SEC: float = 1.5

    @classmethod
    def get_gpu_telemetry(cls) -> Dict[str, Any]:
        """Query local NVIDIA GPU metrics via nvidia-smi with fixed argument set and timeout.
        
        Returns:
            Dict containing gpu_supported, gpu_name, gpu_utilization_percent,
            gpu_vram_used_mb, gpu_vram_total_mb, gpu_temperature_c.
        """
        # 1. Locate nvidia-smi on system path
        nvsmi_path = shutil.which("nvidia-smi")
        if not nvsmi_path:
            # Common Windows default path check
            default_win_path = r"C:\Windows\System32\nvidia-smi.exe"
            if os.path.exists(default_win_path):
                nvsmi_path = default_win_path

        if not nvsmi_path:
            return {
                "gpu_supported": False,
                "gpu_name": None,
                "gpu_utilization_percent": None,
                "gpu_vram_used_mb": None,
                "gpu_vram_total_mb": None,
                "gpu_temperature_c": None,
                "reason": "nvidia-smi executable not found on host",
            }

        try:
            # Fixed query arguments: no user input, shell=False
            query_cmd = [
                nvsmi_path,
                "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu,name",
                "--format=csv,noheader,nounits",
            ]
            result = subprocess.run(
                query_cmd,
                capture_output=True,
                text=True,
                timeout=cls.NVIDIA_SMI_TIMEOUT_SEC,
                shell=False,
            )

            if result.returncode != 0 or not result.stdout.strip():
                return {
                    "gpu_supported": False,
                    "gpu_name": None,
                    "gpu_utilization_percent": None,
                    "gpu_vram_used_mb": None,
                    "gpu_vram_total_mb": None,
                    "gpu_temperature_c": None,
                    "reason": f"nvidia-smi query returned code {result.returncode}: {result.stderr.strip()}",
                }

            # Parse CSV output (first line for primary GPU)
            line = result.stdout.strip().splitlines()[0]
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 5:
                utilization = float(parts[0])
                vram_used = float(parts[1])
                vram_total = float(parts[2])
                temp_c = float(parts[3])
                gpu_name = parts[4]

                return {
                    "gpu_supported": True,
                    "gpu_name": gpu_name,
                    "gpu_utilization_percent": utilization,
                    "gpu_vram_used_mb": vram_used,
                    "gpu_vram_total_mb": vram_total,
                    "gpu_temperature_c": temp_c,
                }
            else:
                return {
                    "gpu_supported": False,
                    "gpu_name": None,
                    "gpu_utilization_percent": None,
                    "gpu_vram_used_mb": None,
                    "gpu_vram_total_mb": None,
                    "gpu_temperature_c": None,
                    "reason": f"Unexpected nvidia-smi CSV column count ({len(parts)})",
                }

        except subprocess.TimeoutExpired:
            logger.warning(f"GPUTelemetryAdapter: nvidia-smi timed out after {cls.NVIDIA_SMI_TIMEOUT_SEC}s")
            return {
                "gpu_supported": False,
                "gpu_name": None,
                "gpu_utilization_percent": None,
                "gpu_vram_used_mb": None,
                "gpu_vram_total_mb": None,
                "gpu_temperature_c": None,
                "reason": f"nvidia-smi query timed out after {cls.NVIDIA_SMI_TIMEOUT_SEC}s",
            }
        except Exception as exc:
            logger.warning(f"GPUTelemetryAdapter: Error querying GPU metrics: {exc}")
            return {
                "gpu_supported": False,
                "gpu_name": None,
                "gpu_utilization_percent": None,
                "gpu_vram_used_mb": None,
                "gpu_vram_total_mb": None,
                "gpu_temperature_c": None,
                "reason": f"GPU query error: {exc}",
            }


class SystemTelemetryAdapter:
    """Read-only system metrics provider with zero secret leakage."""

    @classmethod
    def get_system_telemetry(cls) -> Dict[str, Any]:
        """Collect bounded, structured snapshot of local host system telemetry."""
        # 1. CPU Metrics
        cpu_percent = psutil.cpu_percent(interval=0.0)
        cpu_cores_physical = psutil.cpu_count(logical=False) or 1
        cpu_cores_logical = psutil.cpu_count(logical=True) or 1
        cpu_per_core = psutil.cpu_percent(interval=0.0, percpu=True)

        # 2. RAM Metrics
        vmem = psutil.virtual_memory()
        ram_total_mb = round(vmem.total / (1024.0 * 1024.0), 2)
        ram_used_mb = round(vmem.used / (1024.0 * 1024.0), 2)
        ram_available_mb = round(vmem.available / (1024.0 * 1024.0), 2)
        ram_percent = vmem.percent

        # 3. Process RSS
        try:
            curr_proc = psutil.Process()
            process_rss_mb = round(curr_proc.memory_info().rss / (1024.0 * 1024.0), 2)
        except Exception:
            process_rss_mb = 0.0

        # 4. Storage Metrics (Root Drive)
        try:
            root_drive = os.path.abspath(os.sep)
            disk_info = psutil.disk_usage(root_drive)
            storage_total_gb = round(disk_info.total / (1024.0**3), 2)
            storage_free_gb = round(disk_info.free / (1024.0**3), 2)
            storage_percent = disk_info.percent
        except Exception:
            storage_total_gb = 0.0
            storage_free_gb = 0.0
            storage_percent = 0.0

        # 5. Battery and Power Status
        battery_supported = False
        battery_percent: Optional[float] = None
        power_plugged: Optional[bool] = None
        is_charging: Optional[bool] = None
        try:
            battery_sensors = psutil.sensors_battery()
            if battery_sensors is not None:
                battery_supported = True
                battery_percent = round(battery_sensors.percent, 1)
                power_plugged = battery_sensors.power_plugged
                is_charging = battery_sensors.power_plugged and battery_sensors.percent < 100.0
        except Exception:
            pass

        # 6. GPU Telemetry
        gpu_telemetry = GPUTelemetryAdapter.get_gpu_telemetry()
        gpu_supported = gpu_telemetry.get("gpu_supported", False)
        temperature_supported = gpu_supported and gpu_telemetry.get("gpu_temperature_c") is not None

        # 7. Display Topology (reusing ScreenCaptureService)
        display_count = 1
        display_topology: List[Dict[str, Any]] = []
        try:
            from app.services.vision.screen_capture import ScreenCaptureService
            sc = ScreenCaptureService()
            monitors = sc.list_monitors()
            display_count = len(monitors)
            for m in monitors:
                display_topology.append({
                    "monitor_id": m.monitor_id,
                    "name": m.name,
                    "width": m.width,
                    "height": m.height,
                    "is_primary": m.is_primary,
                    "dpi_scale": m.dpi_scale,
                })
        except Exception as disp_err:
            logger.debug(f"SystemTelemetryAdapter: Display topology retrieval notice: {disp_err}")
            display_topology.append({
                "monitor_id": 1,
                "name": "Default Display",
                "width": 1920,
                "height": 1080,
                "is_primary": True,
                "dpi_scale": 1.0,
            })

        return {
            "status": "success",
            "timestamp": time.time(),
            "cpu": {
                "cpu_percent": cpu_percent,
                "cores_physical": cpu_cores_physical,
                "cores_logical": cpu_cores_logical,
                "per_core_percent": cpu_per_core,
            },
            "ram": {
                "total_mb": ram_total_mb,
                "used_mb": ram_used_mb,
                "available_mb": ram_available_mb,
                "percent": ram_percent,
                "process_rss_mb": process_rss_mb,
            },
            "storage": {
                "total_gb": storage_total_gb,
                "free_gb": storage_free_gb,
                "percent": storage_percent,
            },
            "battery": {
                "battery_supported": battery_supported,
                "battery_percent": battery_percent,
                "power_plugged": power_plugged,
                "is_charging": is_charging,
            },
            "gpu": gpu_telemetry,
            "temperature": {
                "temperature_supported": temperature_supported,
                "gpu_temperature_c": gpu_telemetry.get("gpu_temperature_c"),
            },
            "displays": {
                "display_count": display_count,
                "topology": display_topology,
            },
        }


system_telemetry_adapter = SystemTelemetryAdapter()
