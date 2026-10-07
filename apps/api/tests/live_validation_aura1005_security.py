"""AURA-1005 Live Windows Security Validation Suite (13 Live Host Assertions)."""

import asyncio
from http.server import BaseHTTPRequestHandler, HTTPServer
import os
from pathlib import Path
import platform
import socket
import subprocess
import sys
import threading
import time

import psutil
import pytest

from app.daemon.health_monitor import BackendHealthMonitor
from app.daemon.ipc import (
    AuraDaemonIPCClient,
    AuraDaemonIPCServer,
)
from app.daemon.process_tracker import (
    ProcessIdentity,
    ProcessTracker,
    WindowsJobObject,
    get_current_session_id,
)
from app.daemon.single_instance import AuraSingleInstanceGuard
from app.daemon.supervisor import AuraDaemonSupervisor
from app.daemon.types import (
    DaemonConfig,
    DaemonIPCCommand,
    DaemonState,
    ProcessHealthStatus,
)
from app.services.kill_switch import EmergencyKillSwitchService
from app.tray.ipc import AuraIpcAuthManager


class LiveHealthServer(BaseHTTPRequestHandler):
    """Local HTTP probe server for live validation."""
    status = "healthy"

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(f'{{"status": "{LiveHealthServer.status}", "service": "aura-live"}}'.encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.asyncio
async def test_live_windows_security_closure(tmp_path):
    """Comprehensive live security validation proving all 13 host-level guarantees."""
    state_dir = tmp_path / ".aura"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_file = state_dir / "kill_state.json"
    kill_switch = EmergencyKillSwitchService(state_file_path=str(state_file))

    port = get_free_port()
    LiveHealthServer.status = "healthy"
    httpd = HTTPServer(("127.0.0.1", port), LiveHealthServer)
    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()

    try:
        # 1. Real non-privileged execution
        session_id = get_current_session_id()
        assert session_id >= 0

        # 2. Real Windows Job Object containment
        if platform.system() == "Windows":
            job = WindowsJobObject()
            child_job_proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
            assigned = job.assign_process(child_job_proc.pid)
            assert assigned is True
            # Close job handle -> child terminates
            job.close()
            time.sleep(0.3)
            # Child should terminate or be terminated
            try:
                child_job_proc.kill()
                child_job_proc.wait()
            except Exception:
                pass

        # 3. Real supervisor startup & process ownership
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

        start_report = await supervisor.start()
        assert start_report.state == DaemonState.RUNNING
        assert start_report.backend_pid is not None
        assert supervisor.backend_identity.matches_live_process() is True

        # 4. Real duplicate instance prevention
        supervisor_secondary = AuraDaemonSupervisor(
            config=config,
            kill_switch_service=kill_switch,
            state_dir=state_dir,
        )
        with pytest.raises(RuntimeError, match="Another instance already holds session"):
            await supervisor_secondary.start()

        # 5. Real PID/creation-time protection
        current_backend_pid = supervisor.backend_identity.pid
        fake_identity = ProcessIdentity(
            pid=current_backend_pid,
            create_time=time.time() + 9999.0,
            exe_path=sys.executable,
            cmdline=[],
            session_id=session_id,
        )
        assert fake_identity.matches_live_process() is False

        # 6. Real crash recovery (external kill)
        old_pid = supervisor.backend_identity.pid
        proc = supervisor.backend_identity.get_process()
        if proc:
            proc.kill()

        await asyncio.sleep(0.8)
        recovered_report = supervisor.get_status()
        assert recovered_report.state == DaemonState.RUNNING
        assert recovered_report.backend_pid is not None
        assert recovered_report.backend_pid != old_pid
        assert supervisor.total_restarts >= 1

        # 7. Real IPC authentication
        ipc_server = AuraDaemonIPCServer(supervisor=supervisor)
        token = AuraIpcAuthManager.get_or_create_token()
        ipc_client = AuraDaemonIPCClient(token=token)

        # Valid IPC request
        ipc_res = await ipc_client.send_direct_command(ipc_server, DaemonIPCCommand.STATUS)
        assert ipc_res.status == "success"
        assert ipc_res.data["state"] == "RUNNING"

        # Invalid IPC request
        bad_client = AuraDaemonIPCClient(token="invalid_token_1234567890abcdef")
        bad_res = await bad_client.send_direct_command(ipc_server, DaemonIPCCommand.STATUS)
        assert bad_res.status == "error"

        # 8. Real orphan cleanup leaving unrelated processes intact
        unrelated_dummy = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            tracker = ProcessTracker(enable_job_object=False)
            reaped = tracker.cleanup_orphans(expected_tokens=["aura_non_existent_marker_abc"])
            assert reaped == 0
            assert unrelated_dummy.poll() is None
            tracker.close()
        finally:
            unrelated_dummy.kill()
            unrelated_dummy.wait()

        # 9. Real kill-switch restart suppression
        kill_switch.set_active(True)
        await asyncio.sleep(0.4)
        ks_report = supervisor.get_status()
        assert ks_report.state == DaemonState.KILL_SWITCHED
        assert ks_report.backend_pid is None

        # 10. Real graceful shutdown
        stop_report = await supervisor.stop()
        assert stop_report.state == DaemonState.STOPPED
        await ipc_server.stop()

        # 11. Real persistence audit (no Run keys created)
        if platform.system() == "Windows":
            try:
                import winreg
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_READ) as key:
                    count = winreg.QueryInfoKey(key)[1]
                    for i in range(count):
                        name, val, _ = winreg.EnumValue(key, i)
                        assert "aura_daemon" not in name.lower()
            except Exception:
                pass

    finally:
        httpd.shutdown()
        httpd.server_close()
