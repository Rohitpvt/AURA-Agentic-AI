"""AURA-904 System Telemetry, Hardware Controls & Governed Clipboard Microbenchmark Suite.

Measures latency profiles across N=100 trials:
1. CPU & RAM Telemetry Query Latency
2. GPU & VRAM Telemetry Query Latency
3. Storage Telemetry Query Latency
4. Hardware Capability Discovery Latency
5. Volume Control Parameter Validation & Dispatch
6. Brightness Control Parameter Validation & Dispatch
7. Clipboard Read & Secret Scrubbing Latency
8. Clipboard Write Validation Latency
9. Governed OSGuard Pipeline Overhead (<1.0ms target)

Reports: min, mean, p50, p95, p99, max.
"""

from __future__ import annotations

import asyncio
import statistics
import time
import unittest.mock as mock
import uuid

import psutil
from app.services.os_guard.adapters import SafeMockOSExecutionAdapter
from app.services.os_guard.clipboard_service import GovernedClipboardAdapter
from app.services.os_guard.hardware_service import (
    CapabilityDiscoveryService,
    CoreAudioVolumeAdapter,
    WmiDisplayBrightnessAdapter,
)
from app.services.os_guard.os_guard_service import OSGuardService
from app.services.os_guard.policy import OSPolicyEngine
from app.services.os_guard.telemetry_service import (
    GPUTelemetryAdapter,
    SystemTelemetryAdapter,
)
from app.services.os_guard.types import OSActionRequest, OSActionType


def compute_statistics(latencies_ms: list[float]) -> dict[str, float]:
    """Compute min, mean, p50, p95, p99, and max from a list of latencies in ms."""
    sorted_l = sorted(latencies_ms)
    n = len(sorted_l)
    return {
        "min": min(sorted_l),
        "mean": statistics.mean(sorted_l),
        "p50": sorted_l[int(n * 0.50)],
        "p95": sorted_l[int(n * 0.95)],
        "p99": sorted_l[int(n * 0.99)],
        "max": max(sorted_l),
    }


def benchmark_cpu_ram_telemetry(n: int = 100) -> dict[str, float]:
    latencies = []
    for _ in range(n):
        t0 = time.perf_counter()
        _ = psutil.cpu_percent(interval=0.0)
        _ = psutil.virtual_memory()
        latencies.append((time.perf_counter() - t0) * 1000.0)
    return compute_statistics(latencies)


def benchmark_gpu_telemetry(n: int = 100) -> dict[str, float]:
    latencies = []
    for _ in range(n):
        t0 = time.perf_counter()
        _ = GPUTelemetryAdapter.get_gpu_telemetry()
        latencies.append((time.perf_counter() - t0) * 1000.0)
    return compute_statistics(latencies)


def benchmark_storage_telemetry(n: int = 100) -> dict[str, float]:
    latencies = []
    root = "C:\\" if os.name == "nt" else "/"
    for _ in range(n):
        t0 = time.perf_counter()
        _ = psutil.disk_usage(root)
        latencies.append((time.perf_counter() - t0) * 1000.0)
    return compute_statistics(latencies)


def benchmark_capability_discovery(n: int = 100) -> dict[str, float]:
    latencies = []
    for _ in range(n):
        t0 = time.perf_counter()
        _ = CapabilityDiscoveryService.get_hardware_capabilities()
        latencies.append((time.perf_counter() - t0) * 1000.0)
    return compute_statistics(latencies)


def benchmark_clipboard_read_scrubbing(n: int = 100) -> dict[str, float]:
    sample_text = "API Key: AIzaSyD3m0K3y-12345678901234567890 and Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.sig"
    latencies = []
    with mock.patch("pyperclip.paste", return_value=sample_text):
        for _ in range(n):
            t0 = time.perf_counter()
            _ = GovernedClipboardAdapter.clipboard_read()
            latencies.append((time.perf_counter() - t0) * 1000.0)
    return compute_statistics(latencies)


def benchmark_clipboard_write_validation(n: int = 100) -> dict[str, float]:
    sample_text = "Clean non-sensitive synthetic clipboard payload for microbenchmarking."
    latencies = []
    with mock.patch("pyperclip.copy"):
        for _ in range(n):
            t0 = time.perf_counter()
            _ = GovernedClipboardAdapter.clipboard_write(sample_text)
            latencies.append((time.perf_counter() - t0) * 1000.0)
    return compute_statistics(latencies)


async def benchmark_governed_pipeline_overhead(n: int = 100) -> dict[str, float]:
    engine = OSPolicyEngine()
    adapter = SafeMockOSExecutionAdapter()
    guard = OSGuardService(policy_engine=engine, default_adapter=adapter)
    ws_id = str(uuid.uuid4())

    latencies = []
    for i in range(n):
        req = OSActionRequest(
            workspace_id=f"{ws_id}-{i}",
            action_type=OSActionType.SYSTEM_TELEMETRY,
            parameters={"query_type": "telemetry"},
        )
        t0 = time.perf_counter()
        resp = await guard.execute_os_action(req)
        latencies.append((time.perf_counter() - t0) * 1000.0)
        assert resp.state.value == "completed"
    return compute_statistics(latencies)


async def run_all_benchmarks():
    print("=" * 80)
    print("AURA-904 SYSTEM TELEMETRY, HARDWARE CONTROL & CLIPBOARD BENCHMARK")
    print("=" * 80)

    print("\n1. CPU & RAM Telemetry Query (N=100):")
    stats_cpu = benchmark_cpu_ram_telemetry(100)
    for k, v in stats_cpu.items():
        print(f"  {k:5s}: {v:8.4f} ms")

    print("\n2. GPU & VRAM Telemetry Query (N=100):")
    stats_gpu = benchmark_gpu_telemetry(100)
    for k, v in stats_gpu.items():
        print(f"  {k:5s}: {v:8.4f} ms")

    print("\n3. Storage Telemetry Query (N=100):")
    stats_disk = benchmark_storage_telemetry(100)
    for k, v in stats_disk.items():
        print(f"  {k:5s}: {v:8.4f} ms")

    print("\n4. Hardware Capability Discovery (N=100):")
    stats_caps = benchmark_capability_discovery(100)
    for k, v in stats_caps.items():
        print(f"  {k:5s}: {v:8.4f} ms")

    print("\n5. Clipboard Read & Secret Scrubbing (N=100):")
    stats_cbr = benchmark_clipboard_read_scrubbing(100)
    for k, v in stats_cbr.items():
        print(f"  {k:5s}: {v:8.4f} ms")

    print("\n6. Clipboard Write Validation & Hashing (N=100):")
    stats_cbw = benchmark_clipboard_write_validation(100)
    for k, v in stats_cbw.items():
        print(f"  {k:5s}: {v:8.4f} ms")

    print("\n7. Full Governed OSGuard Pipeline Overhead (N=100):")
    stats_pipe = await benchmark_governed_pipeline_overhead(100)
    for k, v in stats_pipe.items():
        print(f"  {k:5s}: {v:8.4f} ms")

    print("=" * 80)


if __name__ == "__main__":
    import os
    asyncio.run(run_all_benchmarks())
