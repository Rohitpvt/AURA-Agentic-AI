"""AURA-1005 Windows User-Session Background Daemon & Watchdog Supervisor."""

import asyncio
import os
import time
from typing import Any, Dict, List, Optional

from app.core.logging import logger
from app.daemon.health_monitor import BackendHealthMonitor
from app.daemon.process_tracker import ProcessIdentity, ProcessTracker, get_current_session_id
from app.daemon.single_instance import AuraSingleInstanceGuard
from app.daemon.types import (
    DaemonConfig,
    DaemonState,
    DaemonStatusReport,
    ProcessHealthStatus,
)
from app.services.kill_switch import EmergencyKillSwitchService


class AuraDaemonSupervisor:
    """Authoritative Windows User-Session Supervisor managing AURA backend lifecycle & health."""

    def __init__(
        self,
        config: Optional[DaemonConfig] = None,
        kill_switch_service: Optional[EmergencyKillSwitchService] = None,
        single_instance_guard: Optional[AuraSingleInstanceGuard] = None,
        state_dir: Optional[Any] = None,
    ):
        self.config = config or DaemonConfig()
        self.session_id = get_current_session_id()
        self.state = DaemonState.STOPPED
        
        self.tracker = ProcessTracker(enable_job_object=self.config.enable_job_object)
        self.single_instance = single_instance_guard or AuraSingleInstanceGuard(
            session_id=self.session_id,
            state_dir=state_dir,
        )
        self.monitor = BackendHealthMonitor(self.config)
        self.kill_switch = kill_switch_service or EmergencyKillSwitchService()

        self.backend_proc: Optional[Any] = None
        self.backend_identity: Optional[ProcessIdentity] = None
        
        # Uptime and metrics
        self.supervisor_start_time: float = time.time()
        self.consecutive_crashes: int = 0
        self.crash_history: List[float] = []
        self.total_restarts: int = 0
        self.healthy_since: Optional[float] = None
        self.last_health_check_time: Optional[float] = None
        self.last_restart_time: Optional[float] = None
        self.last_health_details: Dict[str, Any] = {}
        self.last_health_status: ProcessHealthStatus = ProcessHealthStatus.UNKNOWN

        self._watchdog_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self._stop_event = asyncio.Event()

    async def start(self) -> DaemonStatusReport:
        """Start the supervisor daemon and spawn the managed backend runtime."""
        async with self._lock:
            if self.state in [DaemonState.RUNNING, DaemonState.STARTING]:
                return self.get_status()

            # 1. Acquire Single Instance Mutex/Lock
            if not self.single_instance.acquire():
                raise RuntimeError(
                    f"AuraDaemonSupervisor: Another instance already holds session {self.session_id} lock"
                )

            # 2. Verify Emergency Kill Switch
            if self.kill_switch.is_active():
                self.state = DaemonState.KILL_SWITCHED
                self.single_instance.release()
                raise RuntimeError("AuraDaemonSupervisor: Cannot start while Emergency Kill Switch is ACTIVE")

            try:
                # 3. Defensive Orphan Sweep
                self.tracker.cleanup_orphans()

                # 4. Launch Backend Process
                self.state = DaemonState.STARTING
                self._stop_event.clear()

                self.backend_proc, self.backend_identity = self.tracker.launch_backend(self.config)

                # 5. Await Initial Healthy Status
                start_deadline = time.time() + self.config.startup_timeout
                is_healthy = False

                while time.time() < start_deadline:
                    if self.kill_switch.is_active():
                        await self._handle_kill_switch_active()
                        raise RuntimeError("AuraDaemonSupervisor: Kill switch activated during startup")

                    health_st, details = await self.monitor.probe_health(self.backend_identity)
                    self.last_health_status = health_st
                    self.last_health_details = details
                    self.last_health_check_time = time.time()

                    if health_st in [ProcessHealthStatus.HEALTHY, ProcessHealthStatus.DEGRADED]:
                        is_healthy = True
                        break

                    if health_st == ProcessHealthStatus.DEAD:
                        logger.error("AuraDaemonSupervisor: Backend died during initial startup")
                        break

                    await asyncio.sleep(0.5)

                if not is_healthy:
                    logger.warning("AuraDaemonSupervisor: Backend failed to reach healthy state within startup timeout")
                    if self.backend_identity:
                        self.tracker.terminate_tree(self.backend_identity, timeout=2.0)
                    self.backend_identity = None
                    self.backend_proc = None
                    self.state = DaemonState.STOPPED
                    self.single_instance.release()
                    raise TimeoutError("Backend failed to reach healthy status within startup timeout")

            except Exception as exc:
                if self.state not in [DaemonState.KILL_SWITCHED, DaemonState.STOPPED]:
                    self.state = DaemonState.STOPPED
                if self.backend_identity:
                    self.tracker.terminate_tree(self.backend_identity, timeout=2.0)
                    self.backend_identity = None
                    self.backend_proc = None
                self.single_instance.release()
                if not isinstance(exc, (RuntimeError, TimeoutError)):
                    logger.error(f"AuraDaemonSupervisor: Failed to start backend: {exc}")
                raise

            self.state = DaemonState.RUNNING
            self.healthy_since = time.time()
            logger.info(
                f"AuraDaemonSupervisor: Backend PID {self.backend_identity.pid} reached RUNNING state in session {self.session_id}"
            )

            # 6. Start Watchdog Heartbeat
            self._watchdog_task = asyncio.create_task(self._watchdog_loop())
            return self.get_status()

    async def _watchdog_loop(self) -> None:
        """Periodic background health watchdog and crash recovery loop."""
        logger.debug("AuraDaemonSupervisor: Watchdog heartbeat loop started")

        while not self._stop_event.is_set() and self.state in [
            DaemonState.RUNNING,
            DaemonState.DEGRADED,
            DaemonState.RESTARTING,
        ]:
            try:
                # 1. Kill Switch Check
                if self.kill_switch.is_active():
                    await self._handle_kill_switch_active()
                    break

                # 2. Health Probe
                health_st, details = await self.monitor.probe_health(self.backend_identity)
                self.last_health_status = health_st
                self.last_health_details = details
                self.last_health_check_time = time.time()

                if health_st == ProcessHealthStatus.HEALTHY:
                    if self.healthy_since is None:
                        self.healthy_since = time.time()
                    elif time.time() - self.healthy_since >= self.config.healthy_reset_duration:
                        # Reset crash counter after sustained healthy runtime
                        self.consecutive_crashes = 0
                    self.state = DaemonState.RUNNING

                elif health_st == ProcessHealthStatus.DEGRADED:
                    # Optional dependency degraded (Ollama, pgvector) - do NOT restart healthy API!
                    self.state = DaemonState.DEGRADED
                    logger.debug("AuraDaemonSupervisor: Backend reporting DEGRADED sub-dependency")

                elif health_st in [ProcessHealthStatus.DEAD, ProcessHealthStatus.UNRESPONSIVE]:
                    logger.warning(
                        f"AuraDaemonSupervisor: Backend unhealthy ({health_st.value}), details: {details}"
                    )
                    if not self.config.auto_restart:
                        self.state = DaemonState.STOPPED
                        break

                    # Crash Loop Guard
                    now = time.time()
                    self.crash_history.append(now)
                    # Filter history to sliding window
                    self.crash_history = [t for t in self.crash_history if now - t <= self.config.crash_window_seconds]
                    self.consecutive_crashes += 1
                    self.healthy_since = None

                    if len(self.crash_history) >= self.config.max_crash_count:
                        logger.error(
                            f"AuraDaemonSupervisor: Crash Loop Guard Triggered ({len(self.crash_history)} crashes in {self.config.crash_window_seconds}s). Halting auto-restart."
                        )
                        self.state = DaemonState.DEGRADED
                        break

                    # Exponential Backoff Delay
                    backoff = min(
                        self.config.initial_backoff_seconds * (self.config.backoff_multiplier ** (self.consecutive_crashes - 1)),
                        self.config.max_backoff_seconds,
                    )
                    self.state = DaemonState.RESTARTING
                    logger.info(
                        f"AuraDaemonSupervisor: Backoff restart #{self.consecutive_crashes} scheduled in {backoff:.1f}s"
                    )

                    # Bounded sleep with interrupt support
                    sleep_interval = 0.2
                    slept = 0.0
                    while slept < backoff:
                        if self._stop_event.is_set() or self.kill_switch.is_active():
                            break
                        await asyncio.sleep(sleep_interval)
                        slept += sleep_interval

                    if self._stop_event.is_set():
                        break
                    if self.kill_switch.is_active():
                        await self._handle_kill_switch_active()
                        break

                    # Perform Respawn
                    await self._perform_restart()

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"AuraDaemonSupervisor: Watchdog error: {exc}")

            # Heartbeat sleep
            try:
                await asyncio.sleep(self.config.heartbeat_interval)
            except asyncio.CancelledError:
                break

        logger.debug("AuraDaemonSupervisor: Watchdog heartbeat loop terminated")

    async def _perform_restart(self) -> bool:
        """Respawn backend process after failure."""
        logger.info("AuraDaemonSupervisor: Performing backend respawn")
        self.last_restart_time = time.time()

        if self.backend_identity:
            self.tracker.terminate_tree(self.backend_identity, timeout=2.0)
            self.backend_identity = None
            self.backend_proc = None

        try:
            self.backend_proc, self.backend_identity = self.tracker.launch_backend(self.config)
            self.total_restarts += 1
            self.state = DaemonState.RUNNING
            return True
        except Exception as exc:
            logger.error(f"AuraDaemonSupervisor: Failed respawning backend: {exc}")
            self.state = DaemonState.DEGRADED
            return False

    async def _handle_kill_switch_active(self) -> None:
        """Handle emergency kill-switch activation: immediate halt and no resurrection."""
        logger.warning(
            "AuraDaemonSupervisor: Emergency Kill Switch ACTIVE - terminating managed backend runtime"
        )
        self.state = DaemonState.KILL_SWITCHED
        if self._watchdog_task:
            self._watchdog_task.cancel()

        if self.backend_identity:
            self.tracker.terminate_tree(self.backend_identity, timeout=2.0)
            self.backend_identity = None
            self.backend_proc = None

    async def stop(self) -> DaemonStatusReport:
        """Gracefully stop the supervisor and all child processes."""
        async with self._lock:
            if self.state == DaemonState.STOPPED:
                return self.get_status()

            logger.info("AuraDaemonSupervisor: Graceful shutdown initiated")
            self.state = DaemonState.STOPPING
            self._stop_event.set()

            if self._watchdog_task:
                self._watchdog_task.cancel()
                try:
                    await self._watchdog_task
                except (asyncio.CancelledError, Exception):
                    pass
                self._watchdog_task = None

            if self.backend_identity:
                self.tracker.terminate_tree(
                    self.backend_identity,
                    timeout=self.config.graceful_shutdown_timeout,
                )
                self.backend_identity = None
                self.backend_proc = None

            self.state = DaemonState.STOPPED
            self.single_instance.release()
            self.tracker.close()
            logger.info("AuraDaemonSupervisor: Graceful shutdown complete")
            return self.get_status()

    async def restart(self) -> DaemonStatusReport:
        """Explicit operator restart request."""
        async with self._lock:
            logger.info("AuraDaemonSupervisor: Operator restart requested")
            if self.kill_switch.is_active():
                self.state = DaemonState.KILL_SWITCHED
                raise RuntimeError("Cannot restart while kill switch is active")

            # Reset crash loop counters on intentional manual restart
            self.consecutive_crashes = 0
            self.crash_history.clear()

            if self.backend_identity:
                self.tracker.terminate_tree(self.backend_identity, timeout=self.config.graceful_shutdown_timeout)
                self.backend_identity = None
                self.backend_proc = None

            self.backend_proc, self.backend_identity = self.tracker.launch_backend(self.config)
            self.total_restarts += 1
            self.state = DaemonState.RUNNING
            self.healthy_since = time.time()
            return self.get_status()

    def get_status(self) -> DaemonStatusReport:
        """Generate current status report."""
        backend_pid = self.backend_identity.pid if self.backend_identity else None
        backend_create_time = self.backend_identity.create_time if self.backend_identity else None

        return DaemonStatusReport(
            state=self.state,
            supervisor_pid=os.getpid(),
            session_id=self.session_id,
            uptime_seconds=time.time() - self.supervisor_start_time,
            backend_pid=backend_pid,
            backend_create_time=backend_create_time,
            backend_health=self.last_health_status,
            backend_health_details=self.last_health_details,
            consecutive_crashes=self.consecutive_crashes,
            total_restarts=self.total_restarts,
            kill_switch_active=self.kill_switch.is_active(),
            last_health_check_time=self.last_health_check_time,
            last_restart_time=self.last_restart_time,
        )
