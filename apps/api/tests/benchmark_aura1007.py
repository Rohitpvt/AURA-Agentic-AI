"""AURA-1007 Performance & Latency Benchmark Certification Suite.

Measures:
1. Session Transition Throughput (µs/op)
2. Autostart Registry Inspection Latency (ms)
3. Named Pipe Authenticated IPC Latency (ms)
4. Kill Switch Interruption Propagation (µs)
5. Observation Freshness Store Index & Expiry Throughput (ops/sec)
"""

import asyncio
import json
import os
import sys
import time
import uuid
from pathlib import Path

# Ensure api directory is on sys.path for direct script execution
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.daemon.autostart import AutostartManager
from app.daemon.session_manager import WindowsSessionManager, SessionState, WTS_SESSION_LOCK, WTS_SESSION_UNLOCK
from app.services.browser.governance import ObservationFreshnessStore
from app.services.browser.models import AXTreeNode, PageObservation, TabInfo
from app.services.kill_switch import EmergencyKillSwitchService
from app.tray.ipc import AuraIpcAuthManager, AuraNamedPipeServer
from app.tray.types import TrayIPCCommand


@pytest.mark.asyncio
async def test_benchmark_session_state_transition_latency():
    """Benchmark session manager lock/unlock processing latency."""
    mgr = WindowsSessionManager(session_id=1)
    iterations = 2000

    start_time = time.perf_counter()
    for _ in range(iterations):
        mgr.handle_wts_message(WTS_SESSION_LOCK, session_id=1)
        mgr.handle_wts_message(WTS_SESSION_UNLOCK, session_id=1)
    duration = time.perf_counter() - start_time

    avg_latency_us = (duration / (iterations * 2)) * 1_000_000
    print(f"\n[BENCHMARK] Session state transition avg latency: {avg_latency_us:.2f} µs/op")
    assert avg_latency_us < 500.0  # Must be sub-millisecond


@pytest.mark.asyncio
async def test_benchmark_autostart_inspection_latency():
    """Benchmark Autostart status inspection latency."""
    autostart = AutostartManager()
    iterations = 100

    start_time = time.perf_counter()
    for _ in range(iterations):
        _ = autostart.is_autostart_enabled()
    duration = time.perf_counter() - start_time

    avg_ms = (duration / iterations) * 1000.0
    print(f"\n[BENCHMARK] Autostart status check avg latency: {avg_ms:.2f} ms")
    assert avg_ms < 10.0  # Fast registry read


@pytest.mark.asyncio
async def test_benchmark_named_pipe_ipc_latency():
    """Benchmark authenticated Named Pipe command processing latency."""
    token = AuraIpcAuthManager.get_or_create_token()
    server = AuraNamedPipeServer()
    iterations = 500

    req_json = json.dumps({"command": "get_status", "token": token})

    start_time = time.perf_counter()
    for _ in range(iterations):
        resp = await server.process_raw_request(req_json)
        assert resp["status"] == "success"
    duration = time.perf_counter() - start_time

    avg_ms = (duration / iterations) * 1000.0
    print(f"\n[BENCHMARK] Tray IPC command dispatch avg latency: {avg_ms:.2f} ms")
    assert avg_ms < 5.0  # Ultra-low latency IPC


@pytest.mark.asyncio
async def test_benchmark_kill_switch_propagation():
    """Benchmark kill switch activation and check latency."""
    kill_switch = EmergencyKillSwitchService()
    iterations = 5000

    start_time = time.perf_counter()
    for _ in range(iterations):
        kill_switch.set_active(True)
        assert kill_switch.is_active() is True
        kill_switch.set_active(False)
        assert kill_switch.is_active() is False
    duration = time.perf_counter() - start_time

    avg_us = (duration / (iterations * 2)) * 1_000_000
    print(f"\n[BENCHMARK] Kill-switch toggle & check latency: {avg_us:.2f} µs")
    assert avg_us < 5000.0


@pytest.mark.asyncio
async def test_benchmark_freshness_store_throughput():
    """Benchmark page observation freshness storage and query throughput."""
    store = ObservationFreshnessStore()
    ws_id = uuid.uuid4()
    tab_id = "bench_tab"
    node = AXTreeNode(node_id=1, role="button", name="OK")

    iterations = 5000
    start_time = time.perf_counter()
    for _ in range(iterations):
        store.record_observation(ws_id, tab_id, "https://bench.internal", "Benchmark", [node])
        _ = store.get_observation(ws_id, tab_id)
        _ = store.get_element(ws_id, tab_id, 1)
    duration = time.perf_counter() - start_time

    ops_per_sec = (iterations * 3) / duration
    print(f"\n[BENCHMARK] Freshness store throughput: {ops_per_sec:.0f} ops/sec")
    assert ops_per_sec > 10_000.0


if __name__ == "__main__":
    asyncio.run(test_benchmark_session_state_transition_latency())
    asyncio.run(test_benchmark_autostart_inspection_latency())
    asyncio.run(test_benchmark_named_pipe_ipc_latency())
    asyncio.run(test_benchmark_kill_switch_propagation())
    asyncio.run(test_benchmark_freshness_store_throughput())
    print("\nALL AURA-1007 BENCHMARKS COMPLETED SUCCESSFULLY.")
