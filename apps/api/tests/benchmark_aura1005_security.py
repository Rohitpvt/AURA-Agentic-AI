"""AURA-1005 Security Performance & Memory Stability Benchmark Suite."""

import asyncio
import os
from pathlib import Path
import time

import psutil
import pytest

from app.daemon.ipc import (
    AuraDaemonIPCClient,
    AuraDaemonIPCServer,
)
from app.daemon.process_tracker import get_current_session_id
from app.daemon.single_instance import AuraSingleInstanceGuard
from app.daemon.supervisor import AuraDaemonSupervisor
from app.daemon.types import (
    DaemonConfig,
    DaemonIPCCommand,
    DaemonState,
)
from app.services.kill_switch import EmergencyKillSwitchService
from app.tray.ipc import AuraIpcAuthManager


@pytest.fixture
def temp_state_dir(tmp_path):
    state_dir = tmp_path / ".aura"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir


def test_benchmark_mutex_acquisition_throughput(temp_state_dir):
    """Benchmark SingleInstanceGuard acquisition throughput under rapid cycling."""
    iterations = 100
    start = time.perf_counter()
    for i in range(iterations):
        guard = AuraSingleInstanceGuard(session_id=8000 + i, state_dir=temp_state_dir)
        assert guard.acquire() is True
        guard.release()
    elapsed = time.perf_counter() - start
    ops_sec = iterations / elapsed
    print(f"\n[Benchmark] Mutex Acquisition Throughput: {ops_sec:,.0f} ops/sec ({iterations} ops in {elapsed:.3f}s)")
    assert ops_sec > 300


@pytest.mark.asyncio
async def test_benchmark_ipc_message_throughput(temp_state_dir):
    """Benchmark IPC server message processing throughput."""
    config = DaemonConfig(custom_cwd=str(temp_state_dir))
    supervisor = AuraDaemonSupervisor(config=config, state_dir=temp_state_dir)
    ipc_server = AuraDaemonIPCServer(supervisor=supervisor)
    token = AuraIpcAuthManager.get_or_create_token()
    client = AuraDaemonIPCClient(token=token)

    iterations = 2000
    start = time.perf_counter()
    for _ in range(iterations):
        res = await client.send_direct_command(ipc_server, DaemonIPCCommand.STATUS)
        assert res.status == "success"
    elapsed = time.perf_counter() - start
    ops_sec = iterations / elapsed
    print(f"\n[Benchmark] IPC Request Throughput: {ops_sec:,.0f} ops/sec ({iterations} ops in {elapsed:.3f}s)")
    assert ops_sec > 1000


def test_benchmark_memory_leak_stability(temp_state_dir):
    """Verify no memory leak across repeated status report cycles."""
    config = DaemonConfig(custom_cwd=str(temp_state_dir))
    supervisor = AuraDaemonSupervisor(config=config, state_dir=temp_state_dir)

    p = psutil.Process(os.getpid())
    initial_rss = p.memory_info().rss / (1024 * 1024)

    for _ in range(10000):
        _ = supervisor.get_status()

    final_rss = p.memory_info().rss / (1024 * 1024)
    rss_growth = final_rss - initial_rss
    print(f"\n[Benchmark] Memory Growth after 10,000 status queries: {rss_growth:.2f} MB (Final RSS: {final_rss:.2f} MB)")
    assert rss_growth < 20.0  # Zero significant leak
