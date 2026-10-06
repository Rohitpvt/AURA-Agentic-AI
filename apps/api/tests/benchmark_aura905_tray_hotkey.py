"""AURA-905 System Tray & Global Emergency Hotkey Performance Benchmark Suite.

Measures latency profiles across N=100 trials:
1. Tray Startup & Mutex Acquisition Latency
2. State Update & Indicator Synchronization Latency
3. IPC Named Pipe Round-Trip (Authenticated Request -> Response)
4. Global Hotkey Registration & Unregistration Latency
5. Hotkey-to-Kill-Switch Authority Latency (Direct + Atomic State Flush < 15.0ms target)
6. Tray Graceful Shutdown & Resource Cleanup Latency

Reports: min, mean, p50, p95, p99, max.
"""

from __future__ import annotations

import asyncio
import os
import statistics
import sys
from pathlib import Path
import tempfile
import time
from typing import Dict, List
import unittest.mock as mock
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.kill_switch import EmergencyKillSwitchService
from app.tray.hotkey import GlobalHotkeyManager
from app.tray.ipc import AuraIpcAuthManager, AuraNamedPipeClient, AuraNamedPipeServer
from app.tray.main import AuraTrayApplication, acquire_single_instance_mutex
from app.tray.tray_icon import WindowsTrayIcon
from app.tray.types import (
    HotkeyRegistrationStatus,
    PrivacySensingState,
    TrayIPCCommand,
    TrayIPCRequest,
    TrayIPCResponse,
    TrayRuntimeState,
)


def compute_statistics(latencies_ms: List[float]) -> Dict[str, float]:
    """Compute min, mean, p50, p95, p99, and max from a list of latencies in ms."""
    sorted_l = sorted(latencies_ms)
    n = len(sorted_l)
    if n == 0:
        return {"min": 0.0, "mean": 0.0, "p50": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0}
    return {
        "min": round(min(sorted_l), 4),
        "mean": round(statistics.mean(sorted_l), 4),
        "p50": round(sorted_l[int(n * 0.50)], 4),
        "p95": round(sorted_l[int(n * 0.95)], 4),
        "p99": round(sorted_l[int(n * 0.99)], 4),
        "max": round(max(sorted_l), 4),
    }


def benchmark_tray_startup(n: int = 100) -> Dict[str, float]:
    """Benchmark tray application instantiation, session resolution, and mutex acquisition."""
    latencies: List[float] = []
    for _ in range(n):
        t0 = time.perf_counter()
        with mock.patch("ctypes.windll.kernel32.CreateMutexW", return_value=12345), \
             mock.patch("ctypes.windll.kernel32.GetLastError", return_value=0), \
             mock.patch("ctypes.windll.kernel32.CloseHandle", return_value=None):
            handle = acquire_single_instance_mutex()
            app = AuraTrayApplication()
            latencies.append((time.perf_counter() - t0) * 1000.0)
            assert handle is not None
            app.shutdown()
    return compute_statistics(latencies)


def benchmark_state_update(n: int = 100) -> Dict[str, float]:
    """Benchmark tray state sync and tooltip/indicator updates."""
    tray_icon = WindowsTrayIcon()
    tray_icon.hwnd = 12345
    latencies: List[float] = []
    states = list(TrayRuntimeState)
    with mock.patch("win32gui.Shell_NotifyIcon", return_value=True), \
         mock.patch("win32gui.LoadIcon", return_value=1):
        for i in range(n):
            target_state = states[i % len(states)]
            t0 = time.perf_counter()
            tray_icon.set_state(target_state)
            tray_icon.set_privacy_state(PrivacySensingState(camera_state="ACTIVE", mic_state="IDLE"))
            latencies.append((time.perf_counter() - t0) * 1000.0)
    return compute_statistics(latencies)


def benchmark_ipc_round_trip(n: int = 100) -> Dict[str, float]:
    """Benchmark authenticated IPC command processing round-trip."""
    import concurrent.futures

    def _run_ipc_benchmark():
        with tempfile.TemporaryDirectory() as tmpdir:
            token_path = Path(tmpdir) / ".auth_token"
            with mock.patch("app.tray.ipc.AuraIpcAuthManager.get_token_path", return_value=token_path):
                token = AuraIpcAuthManager.get_or_create_token()
                server = AuraNamedPipeServer()
                
                req = TrayIPCRequest(
                    command=TrayIPCCommand.GET_STATUS,
                    token=token,
                    session_id=1,
                    payload={},
                )
                raw_str = req.model_dump_json()
                
                latencies: List[float] = []
                for _ in range(n):
                    t0 = time.perf_counter()
                    res = asyncio.run(server.process_raw_request(raw_str))
                    latencies.append((time.perf_counter() - t0) * 1000.0)
                    assert res.get("status") == "success"
                return compute_statistics(latencies)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_run_ipc_benchmark)
        return future.result()


def benchmark_hotkey_registration(n: int = 100) -> Dict[str, float]:
    """Benchmark Win32 RegisterHotKey and UnregisterHotKey cycles."""
    latencies: List[float] = []
    manager = GlobalHotkeyManager(hwnd=99999, on_emergency_trigger=lambda: None)
    with mock.patch("ctypes.windll.user32.RegisterHotKey", return_value=1), \
         mock.patch("ctypes.windll.user32.UnregisterHotKey", return_value=1):
        for _ in range(n):
            t0 = time.perf_counter()
            success = manager.register_hotkey(hwnd=99999)
            manager.unregister_hotkey()
            latencies.append((time.perf_counter() - t0) * 1000.0)
            assert success is True
    return compute_statistics(latencies)


def benchmark_hotkey_to_kill_switch_authority(n: int = 100) -> Dict[str, float]:
    """Benchmark end-to-end hotkey activation to atomic kill-switch disk commit."""
    latencies: List[float] = []
    with tempfile.TemporaryDirectory() as tmpdir:
        state_file = os.path.join(tmpdir, "kill_state.json")
        ks_instance = EmergencyKillSwitchService(state_file_path=state_file)
        with mock.patch("app.tray.main.kill_switch", ks_instance):
            app = AuraTrayApplication()
            for _ in range(n):
                # Reset switch
                ks_instance.set_active(False)
                t0 = time.perf_counter()
                # Direct invocation of emergency trigger
                app.trigger_emergency_kill()
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                latencies.append(elapsed_ms)
                assert ks_instance.is_active()
            app.shutdown()
    return compute_statistics(latencies)


def benchmark_tray_shutdown(n: int = 100) -> Dict[str, float]:
    """Benchmark tray shutdown, mutex release, hotkey unregister, and cleanup."""
    latencies: List[float] = []
    for _ in range(n):
        with mock.patch("ctypes.windll.user32.UnregisterHotKey", return_value=1), \
             mock.patch("win32api.CloseHandle", return_value=None):
            app = AuraTrayApplication()
            t0 = time.perf_counter()
            app.shutdown()
            latencies.append((time.perf_counter() - t0) * 1000.0)
    return compute_statistics(latencies)


def run_full_benchmark_suite(iterations: int = 100) -> Dict[str, Dict[str, float]]:
    """Run the entire AURA-905 microbenchmark suite and return detailed statistics."""
    results = {
        "tray_startup": benchmark_tray_startup(iterations),
        "state_update": benchmark_state_update(iterations),
        "ipc_round_trip": benchmark_ipc_round_trip(iterations),
        "hotkey_registration": benchmark_hotkey_registration(iterations),
        "hotkey_to_kill_switch": benchmark_hotkey_to_kill_switch_authority(iterations),
        "tray_shutdown": benchmark_tray_shutdown(iterations),
    }
    return results


def print_benchmark_report(results: Dict[str, Dict[str, float]]) -> None:
    """Format and print benchmark results."""
    print("\n" + "=" * 90)
    print("AURA-905 SYSTEM TRAY & GLOBAL EMERGENCY HOTKEY MICROBENCHMARK REPORT (N=100)")
    print("=" * 90)
    headers = f"{'Benchmark Operation':<34} | {'min (ms)':<9} | {'mean (ms)':<9} | {'p50 (ms)':<9} | {'p95 (ms)':<9} | {'p99 (ms)':<9} | {'max (ms)':<9}"
    print(headers)
    print("-" * 90)
    for op, stats in results.items():
        print(
            f"{op:<34} | {stats['min']:<9.4f} | {stats['mean']:<9.4f} | {stats['p50']:<9.4f} | {stats['p95']:<9.4f} | {stats['p99']:<9.4f} | {stats['max']:<9.4f}"
        )
    print("=" * 90)
    hotkey_p99 = results["hotkey_to_kill_switch"]["p99"]
    print(f"CRITICAL SLA: Emergency Hotkey -> Authority Latency (p99): {hotkey_p99:.4f} ms (Target <= 15.0 ms)")
    assert hotkey_p99 <= 15.0, f"Emergency hotkey p99 latency {hotkey_p99}ms exceeded target of 15.0ms!"


@pytest.mark.asyncio
async def test_aura905_benchmark():
    """Pytest hook to execute AURA-905 benchmark during regression test runs."""
    results = run_full_benchmark_suite(100)
    print_benchmark_report(results)
    assert results["hotkey_to_kill_switch"]["p99"] <= 15.0


if __name__ == "__main__":
    results = run_full_benchmark_suite(100)
    print_benchmark_report(results)
