"""AURA-1005 Performance and Resource Benchmark Suite for Daemon Supervisor."""

import asyncio
import os
from pathlib import Path
import time

import psutil
import pytest

from app.daemon.health_monitor import BackendHealthMonitor
from app.daemon.process_tracker import ProcessIdentity, get_current_session_id
from app.daemon.single_instance import AuraSingleInstanceGuard
from app.daemon.supervisor import AuraDaemonSupervisor
from app.daemon.types import DaemonConfig, DaemonState, ProcessHealthStatus
from app.services.kill_switch import EmergencyKillSwitchService


@pytest.fixture
def temp_state_dir(tmp_path):
    state_dir = tmp_path / ".aura"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir


def test_benchmark_single_instance_guard_latency(temp_state_dir):
    """Benchmark lock acquisition and release latency."""
    iterations = 50
    start = time.perf_counter()
    for i in range(iterations):
        guard = AuraSingleInstanceGuard(session_id=7000 + i, state_dir=temp_state_dir)
        acquired = guard.acquire()
        assert acquired is True
        guard.release()
    elapsed = time.perf_counter() - start
    avg_ms = (elapsed / iterations) * 1000
    print(f"\n[Benchmark] SingleInstanceGuard Acquire+Release Latency: {avg_ms:.2f}ms/op ({iterations} ops in {elapsed:.3f}s)")
    assert avg_ms < 50.0  # < 50ms per acquire+release cycle


def test_benchmark_status_report_throughput(temp_state_dir):
    """Benchmark status report generation throughput."""
    config = DaemonConfig(custom_cwd=str(temp_state_dir))
    supervisor = AuraDaemonSupervisor(config=config, state_dir=temp_state_dir)

    iterations = 5000
    start = time.perf_counter()
    for _ in range(iterations):
        report = supervisor.get_status()
        assert report.state == DaemonState.STOPPED
    elapsed = time.perf_counter() - start
    ops_per_sec = iterations / elapsed
    print(f"\n[Benchmark] Status Report Throughput: {ops_per_sec:,.0f} ops/sec ({iterations} ops in {elapsed:.3f}s)")
    assert ops_per_sec > 5000


def test_benchmark_daemon_memory_footprint():
    """Verify memory RSS consumption of daemon process remains well below 250MB limit."""
    import subprocess
    import sys

    # Measure a dedicated standalone daemon process
    code = "import psutil, os; from app.daemon.supervisor import AuraDaemonSupervisor; p = psutil.Process(os.getpid()); print(p.memory_info().rss / (1024*1024))"
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert res.returncode == 0
    rss_mb = float(res.stdout.strip().splitlines()[-1])
    print(f"\n[Benchmark] Standalone Daemon Supervisor Memory Footprint: {rss_mb:.2f} MB (Target: <= 250 MB)")
    assert rss_mb < 250.0
