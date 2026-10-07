"""AURA-1005 Windows User-Session Background Daemon & Watchdog Supervisor Package."""

from app.daemon.health_monitor import BackendHealthMonitor
from app.daemon.ipc import (
    AuraDaemonIPCClient,
    AuraDaemonIPCServer,
    get_daemon_pipe_name,
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
    DaemonIPCRequest,
    DaemonIPCResponse,
    DaemonState,
    DaemonStatusReport,
    ProcessHealthStatus,
)

__all__ = [
    "AuraDaemonSupervisor",
    "AuraSingleInstanceGuard",
    "ProcessTracker",
    "ProcessIdentity",
    "WindowsJobObject",
    "BackendHealthMonitor",
    "AuraDaemonIPCServer",
    "AuraDaemonIPCClient",
    "DaemonConfig",
    "DaemonState",
    "ProcessHealthStatus",
    "DaemonIPCCommand",
    "DaemonIPCRequest",
    "DaemonIPCResponse",
    "DaemonStatusReport",
    "get_current_session_id",
    "get_daemon_pipe_name",
]
