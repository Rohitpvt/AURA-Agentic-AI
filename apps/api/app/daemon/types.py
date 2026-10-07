"""AURA-1005 Windows User-Session Background Daemon & Watchdog Supervisor Type Definitions."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
import time
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field as PydanticField


class DaemonState(str, Enum):
    """Authoritative lifecycle state of the AURA Daemon Supervisor."""
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    DEGRADED = "DEGRADED"
    RESTARTING = "RESTARTING"
    STOPPING = "STOPPING"
    KILL_SWITCHED = "KILL_SWITCHED"


class ProcessHealthStatus(str, Enum):
    """Health classification for managed backend processes."""
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNRESPONSIVE = "UNRESPONSIVE"
    DEAD = "DEAD"
    UNKNOWN = "UNKNOWN"


class DaemonIPCCommand(str, Enum):
    """Strict pre-approved command allowlist for Daemon Supervisor IPC."""
    STATUS = "status"
    START = "start"
    STOP = "stop"
    RESTART = "restart"
    SHUTDOWN = "shutdown"
    HEALTH = "health"


class DaemonConfig(BaseModel):
    """Configuration settings for the Daemon Supervisor."""
    backend_host: str = PydanticField(default="127.0.0.1", description="Backend binding host")
    backend_port: int = PydanticField(default=8000, description="Backend HTTP port")
    health_endpoint: str = PydanticField(default="/health", description="Liveness probe endpoint")
    detailed_health_endpoint: str = PydanticField(default="/api/v1/health/detailed", description="Detailed health probe endpoint")
    heartbeat_interval: float = PydanticField(default=5.0, description="Watchdog probe interval in seconds")
    health_timeout: float = PydanticField(default=2.0, description="HTTP health check timeout in seconds")
    startup_timeout: float = PydanticField(default=15.0, description="Max seconds to wait for healthy status during startup")
    graceful_shutdown_timeout: float = PydanticField(default=5.0, description="Seconds to wait for graceful process exit before force kill")
    
    # Backoff and Crash Loop Guard
    initial_backoff_seconds: float = PydanticField(default=1.0, description="Initial backoff delay after crash")
    max_backoff_seconds: float = PydanticField(default=30.0, description="Maximum backoff delay ceiling")
    backoff_multiplier: float = PydanticField(default=2.0, description="Exponential backoff factor")
    max_crash_count: int = PydanticField(default=5, description="Maximum crashes allowed within crash window")
    crash_window_seconds: float = PydanticField(default=60.0, description="Sliding window duration for crash loop detection")
    healthy_reset_duration: float = PydanticField(default=30.0, description="Seconds of continuous health required to reset crash counters")
    
    # Process management
    auto_restart: bool = PydanticField(default=True, description="Enable automatic watchdog restart on crash")
    enable_job_object: bool = PydanticField(default=True, description="Use Windows Job Object for process tree containment")
    custom_command: Optional[List[str]] = PydanticField(default=None, description="Optional custom command array for test/dev subprocesses")
    custom_cwd: Optional[str] = PydanticField(default=None, description="Optional custom working directory")


class DaemonStatusReport(BaseModel):
    """Comprehensive status report for the daemon supervisor and backend runtime."""
    state: DaemonState = PydanticField(..., description="Current supervisor lifecycle state")
    supervisor_pid: int = PydanticField(..., description="Supervisor process PID")
    session_id: int = PydanticField(..., description="Windows user session ID")
    uptime_seconds: float = PydanticField(default=0.0, description="Supervisor uptime in seconds")
    backend_pid: Optional[int] = PydanticField(default=None, description="Managed backend PID if running")
    backend_create_time: Optional[float] = PydanticField(default=None, description="Backend process creation timestamp")
    backend_health: ProcessHealthStatus = PydanticField(default=ProcessHealthStatus.UNKNOWN, description="Latest evaluated health status")
    backend_health_details: Dict[str, Any] = PydanticField(default_factory=dict, description="Detailed health probe response")
    consecutive_crashes: int = PydanticField(default=0, description="Number of crashes in current crash window")
    total_restarts: int = PydanticField(default=0, description="Lifetime total supervisor restarts")
    kill_switch_active: bool = PydanticField(default=False, description="Whether kill switch is currently active")
    last_health_check_time: Optional[float] = PydanticField(default=None, description="Timestamp of most recent health probe")
    last_restart_time: Optional[float] = PydanticField(default=None, description="Timestamp of most recent restart attempt")
    timestamp: float = PydanticField(default_factory=time.time, description="Report generation timestamp")


class DaemonIPCRequest(BaseModel):
    """Validated IPC request payload for Daemon Supervisor."""
    command: DaemonIPCCommand = PydanticField(..., description="Approved supervisor IPC command")
    token: str = PydanticField(..., description="Shared local secret token for authentication")
    request_id: str = PydanticField(default_factory=lambda: str(uuid.uuid4()), description="Unique request identifier")
    timestamp: float = PydanticField(default_factory=time.time, description="Request generation timestamp")
    parameters: Dict[str, Any] = PydanticField(default_factory=dict, description="Command parameters")


class DaemonIPCResponse(BaseModel):
    """Validated IPC response payload from Daemon Supervisor."""
    status: str = PydanticField(..., description="success or error")
    request_id: str = PydanticField(..., description="Echo of request identifier")
    data: Dict[str, Any] = PydanticField(default_factory=dict, description="Response payload")
    error: Optional[str] = PydanticField(default=None, description="Error message if status is error")
    timestamp: float = PydanticField(default_factory=time.time, description="Response generation timestamp")
