"""AURA-1005 Live Windows Validation Suite for Daemon Supervisor & Watchdog."""

import asyncio
from http.server import BaseHTTPRequestHandler, HTTPServer
import os
from pathlib import Path
import platform
import socket
import sys
import threading
import time
from typing import Any, Dict

import pytest

from app.daemon.health_monitor import BackendHealthMonitor
from app.daemon.process_tracker import ProcessIdentity, ProcessTracker
from app.daemon.single_instance import AuraSingleInstanceGuard
from app.daemon.supervisor import AuraDaemonSupervisor
from app.daemon.types import DaemonConfig, DaemonState, ProcessHealthStatus
from app.services.kill_switch import EmergencyKillSwitchService


class MockHealthServer(BaseHTTPRequestHandler):
    """Simple synchronous HTTP handler for health probes."""
    is_healthy: bool = True

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            status_str = "healthy" if MockHealthServer.is_healthy else "degraded"
            self.wfile.write(f'{{"status": "{status_str}", "service": "aura-test"}}'.encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Suppress standard logging output
        pass


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.asyncio
async def test_live_windows_daemon_lifecycle(tmp_path):
    """Live validation of Windows Daemon Supervisor using real local subprocesses and health servers."""
    state_dir = tmp_path / ".aura"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_file = state_dir / "kill_state.json"
    kill_switch = EmergencyKillSwitchService(state_file_path=str(state_file))

    port = find_free_port()
    MockHealthServer.is_healthy = True
    httpd = HTTPServer(("127.0.0.1", port), MockHealthServer)
    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()

    try:
        # 1. Start supervisor with disposable child
        config = DaemonConfig(
            backend_host="127.0.0.1",
            backend_port=port,
            health_endpoint="/health",
            custom_command=[sys.executable, "-c", "import time; time.sleep(60)"],
            custom_cwd=str(state_dir),
            heartbeat_interval=0.2,
            startup_timeout=3.0,
            initial_backoff_seconds=0.1,
            max_backoff_seconds=0.5,
            healthy_reset_duration=1.0,
        )

        supervisor = AuraDaemonSupervisor(
            config=config,
            kill_switch_service=kill_switch,
            state_dir=state_dir,
        )

        # 2. Live Startup
        start_report = await supervisor.start()
        assert start_report.state == DaemonState.RUNNING
        assert start_report.backend_pid is not None
        assert supervisor.backend_identity.matches_live_process() is True

        # 3. Live Heartbeat Probe
        await asyncio.sleep(0.5)
        status = supervisor.get_status()
        assert status.state == DaemonState.RUNNING
        assert status.backend_health == ProcessHealthStatus.HEALTHY

        # 4. Live Degradation Check
        MockHealthServer.is_healthy = False
        await asyncio.sleep(0.5)
        status_degraded = supervisor.get_status()
        assert status_degraded.state == DaemonState.DEGRADED
        MockHealthServer.is_healthy = True

        # 5. Live Crash Recovery
        # Kill current backend process externally
        assert supervisor.backend_identity is not None
        old_pid = supervisor.backend_identity.pid
        proc = supervisor.backend_identity.get_process()
        if proc:
            proc.kill()

        # Allow watchdog to detect crash and respawn
        await asyncio.sleep(0.8)
        recovered_status = supervisor.get_status()
        assert recovered_status.state == DaemonState.RUNNING
        assert recovered_status.backend_pid is not None
        assert recovered_status.backend_pid != old_pid
        assert supervisor.total_restarts >= 1

        # 6. Live Kill Switch Interruption
        kill_switch.set_active(True)
        await asyncio.sleep(0.4)
        ks_status = supervisor.get_status()
        assert ks_status.state == DaemonState.KILL_SWITCHED
        assert ks_status.backend_pid is None

        # 7. Live Graceful Shutdown
        stop_report = await supervisor.stop()
        assert stop_report.state == DaemonState.STOPPED

    finally:
        httpd.shutdown()
        httpd.server_close()
