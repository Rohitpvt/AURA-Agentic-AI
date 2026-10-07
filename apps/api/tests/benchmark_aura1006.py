"""AURA-1006 Performance & Latency Benchmark Suite."""

import asyncio
import json
import time
import pytest

from app.daemon.autostart import AutostartManager
from app.daemon.session_manager import WindowsSessionManager, SessionState, WTS_SESSION_LOCK, WTS_SESSION_UNLOCK
from app.tray.ipc import AuraIpcAuthManager, AuraNamedPipeServer
from app.tray.types import TrayIPCCommand


@pytest.mark.asyncio
async def test_benchmark_session_state_transition_throughput():
    """Benchmark session manager lock/unlock processing throughput."""
    mgr = WindowsSessionManager(session_id=1)
    iterations = 1000

    start_time = time.perf_counter()
    for i in range(iterations):
        mgr.handle_wts_message(WTS_SESSION_LOCK if i % 2 == 0 else WTS_SESSION_UNLOCK, session_id=1)
    elapsed = time.perf_counter() - start_time

    avg_us = (elapsed / iterations) * 1_000_000
    print(f"\n[BENCHMARK] Session State Transition: {avg_us:.2f} µs/op ({iterations/elapsed:.0f} ops/sec)")
    assert avg_us < 2000  # Must be well under 2ms per transition including logging


@pytest.mark.asyncio
async def test_benchmark_autostart_query_latency(tmp_path):
    """Benchmark Autostart status query latency."""
    mgr = AutostartManager(state_dir=tmp_path)
    iterations = 100

    start_time = time.perf_counter()
    for _ in range(iterations):
        _ = mgr.get_autostart_status()
    elapsed = time.perf_counter() - start_time

    avg_ms = (elapsed / iterations) * 1000
    print(f"\n[BENCHMARK] Autostart Query Latency: {avg_ms:.2f} ms/op")
    assert avg_ms < 5.0  # Must be under 5ms per registry query


@pytest.mark.asyncio
async def test_benchmark_tray_ipc_request_processing(tmp_path, monkeypatch):
    """Benchmark Tray IPC request parsing, authentication, and dispatch."""
    monkeypatch.setenv("AURA_STATE_DIR", str(tmp_path))
    token = AuraIpcAuthManager.get_or_create_token()
    server = AuraNamedPipeServer()

    payload = json.dumps({"command": "GET_STATUS", "token": token})
    iterations = 500

    start_time = time.perf_counter()
    for _ in range(iterations):
        res = await server.process_raw_request(payload)
        assert res["status"] == "success"
    elapsed = time.perf_counter() - start_time

    avg_ms = (elapsed / iterations) * 1000
    print(f"\n[BENCHMARK] Tray IPC Processing Latency: {avg_ms:.2f} ms/op ({iterations/elapsed:.0f} req/sec)")
    assert avg_ms < 2.0  # Must process in <2ms
