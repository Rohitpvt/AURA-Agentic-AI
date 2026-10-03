"""Managed Process Registry and Process Tree Lifecycle Governance for AURA (AURA-507).

Provides:
1. Thread-safe and async-safe registration of all host-level subprocesses spawned by AURA.
2. Strong process identity validation (PID + create_time) to prevent accidental termination of unrelated processes on PID reuse.
3. Deep recursive process-tree termination on Windows 11 and POSIX systems (parents, children, grandchildren).
4. Multi-pass bounded sweeps to catch rapid fork races during emergency termination.
5. Fail-safe cleanup and active process enumeration.
"""

import asyncio
import os
import signal
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

import psutil

from app.core.logging import logger


@dataclass
class ManagedProcessInfo:
    """Metadata tracking a managed OS subprocess."""
    pid: int
    create_time: float
    workspace_id: Optional[uuid.UUID] = None
    task_id: Optional[uuid.UUID] = None
    category: str = "general"
    command: List[str] = field(default_factory=list)
    registered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    is_active: bool = True

    def matches_live_process(self) -> bool:
        """Verify if PID currently running on the OS matches the registered process creation time."""
        try:
            p = psutil.Process(self.pid)
            if not p.is_running() or p.status() == psutil.STATUS_ZOMBIE:
                return False
            # Allow minor floating point tolerance (0.2s) in create_time comparison
            return abs(p.create_time() - self.create_time) < 0.5
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return False


class ManagedProcessRegistry:
    """Authoritative registry supervising host OS subprocesses spawned by AURA."""

    def __init__(self):
        self._processes: Dict[int, ManagedProcessInfo] = {}
        self._lock = asyncio.Lock()

    async def register_process(
        self,
        process: Any,  # asyncio.subprocess.Process or subprocess.Popen or PID int
        workspace_id: Optional[uuid.UUID] = None,
        task_id: Optional[uuid.UUID] = None,
        category: str = "general",
        command: Optional[List[str]] = None,
    ) -> Optional[ManagedProcessInfo]:
        """Register an OS subprocess with its creation timestamp to ensure strict ownership."""
        pid = getattr(process, "pid", process)
        if not isinstance(pid, int) or pid <= 0:
            return None

        # Determine creation timestamp from OS
        try:
            p = psutil.Process(pid)
            create_time = p.create_time()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            create_time = time.time()

        sanitized_cmd = [str(c)[:100] for c in (command or [])]
        info = ManagedProcessInfo(
            pid=pid,
            create_time=create_time,
            workspace_id=workspace_id,
            task_id=task_id,
            category=category,
            command=sanitized_cmd,
        )

        async with self._lock:
            self._processes[pid] = info
            logger.debug(
                f"ManagedProcessRegistry: Registered PID {pid} (category='{category}', workspace={workspace_id})"
            )

        return info

    async def unregister_process(self, pid: int) -> None:
        """Unregister a cleanly exited subprocess."""
        async with self._lock:
            self._processes.pop(pid, None)

    async def get_active_processes(self, workspace_id: Optional[uuid.UUID] = None) -> List[ManagedProcessInfo]:
        """List verified active managed processes, reconciling dead ones."""
        async with self._lock:
            active_list: List[ManagedProcessInfo] = []
            stale_pids: List[int] = []

            for pid, info in list(self._processes.items()):
                if workspace_id is not None and info.workspace_id != workspace_id:
                    continue
                if info.matches_live_process():
                    active_list.append(info)
                else:
                    stale_pids.append(pid)

            for spid in stale_pids:
                self._processes.pop(spid, None)

            return active_list

    def terminate_process_tree_sync(
        self,
        pid: int,
        expected_create_time: Optional[float] = None,
        timeout: float = 3.0,
    ) -> Dict[str, Any]:
        """Synchronously and recursively terminate a process and all its children/grandchildren on Windows/POSIX."""
        t0 = time.perf_counter()
        terminated_pids: Set[int] = set()
        errors: List[str] = []

        try:
            parent = psutil.Process(pid)
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            return {
                "root_pid": pid,
                "status": "already_exited",
                "terminated_pids": [],
                "duration_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            }
        except psutil.AccessDenied as e:
            logger.warning(f"ManagedProcessRegistry: Access denied accessing PID {pid}: {e}")
            return {
                "root_pid": pid,
                "status": "access_denied",
                "terminated_pids": [],
                "duration_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            }

        # Validate Identity & PID-reuse protection
        if expected_create_time is not None:
            try:
                actual_create_time = parent.create_time()
                if abs(actual_create_time - expected_create_time) >= 0.5:
                    logger.error(
                        f"ManagedProcessRegistry: PID REUSE DETECTED! PID {pid} create_time ({actual_create_time}) "
                        f"does not match registered create_time ({expected_create_time}). Refusing to terminate."
                    )
                    return {
                        "root_pid": pid,
                        "status": "pid_reuse_aborted",
                        "terminated_pids": [],
                        "duration_ms": round((time.perf_counter() - t0) * 1000.0, 2),
                    }
            except Exception as ex:
                logger.warning(f"ManagedProcessRegistry: Error checking create_time for PID {pid}: {ex}")

        # Multi-pass termination sweep (2 passes to catch rapid forks during termination)
        for pass_num in range(2):
            try:
                children = parent.children(recursive=True)
            except (psutil.NoSuchProcess, psutil.ZombieProcess):
                children = []
            except Exception as ex:
                errors.append(f"pass_{pass_num}_children_enum_error: {str(ex)}")
                children = []

            all_targets = children + [parent]

            # 1. First attempt graceful termination
            for p in all_targets:
                try:
                    if p.is_running():
                        p.terminate()
                        terminated_pids.add(p.pid)
                except (psutil.NoSuchProcess, psutil.ZombieProcess):
                    pass
                except Exception as ex:
                    errors.append(f"terminate_err_pid_{p.pid}: {str(ex)}")

            # 2. Wait bounded time for processes to exit
            gone, alive = psutil.wait_procs(all_targets, timeout=min(timeout / 2.0, 1.5))

            # 3. Force SIGKILL / TerminateProcess on any survivors
            for p in alive:
                try:
                    if p.is_running():
                        logger.warning(f"ManagedProcessRegistry: Force killing surviving PID {p.pid}")
                        p.kill()
                        terminated_pids.add(p.pid)
                except (psutil.NoSuchProcess, psutil.ZombieProcess):
                    pass
                except Exception as ex:
                    errors.append(f"kill_err_pid_{p.pid}: {str(ex)}")

            # Final short wait for force-kills
            if alive:
                psutil.wait_procs(alive, timeout=0.5)

        # On Windows, if process still exists, use taskkill as kernel-level guarantee
        if sys.platform == "win32":
            try:
                if parent.is_running():
                    import subprocess
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(pid)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=2.0,
                    )
            except Exception:
                pass

        duration_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        return {
            "root_pid": pid,
            "status": "terminated",
            "terminated_pids": sorted(list(terminated_pids)),
            "errors": errors,
            "duration_ms": duration_ms,
        }

    async def terminate_process_tree(
        self,
        pid: int,
        expected_create_time: Optional[float] = None,
        timeout: float = 3.0,
    ) -> Dict[str, Any]:
        """Asynchronously terminate a process tree in a non-blocking worker thread."""
        loop = asyncio.get_event_loop()
        res = await loop.run_in_executor(
            None,
            self.terminate_process_tree_sync,
            pid,
            expected_create_time,
            timeout,
        )
        await self.unregister_process(pid)
        return res

    async def terminate_all_processes(
        self,
        workspace_id: Optional[uuid.UUID] = None,
        timeout: float = 4.0,
    ) -> Dict[str, Any]:
        """Terminate all registered OS processes matching workspace or globally."""
        t0 = time.perf_counter()
        async with self._lock:
            targets: List[ManagedProcessInfo] = []
            for pid, info in list(self._processes.items()):
                if workspace_id is None or info.workspace_id == workspace_id:
                    targets.append(info)
                    self._processes.pop(pid, None)

        if not targets:
            return {
                "status": "empty",
                "processes_terminated": 0,
                "pids": [],
                "duration_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            }

        logger.info(f"ManagedProcessRegistry: Terminating {len(targets)} managed process trees (workspace={workspace_id})")
        all_terminated_pids: Set[int] = set()

        for info in targets:
            res = await self.terminate_process_tree(
                pid=info.pid,
                expected_create_time=info.create_time,
                timeout=timeout,
            )
            all_terminated_pids.update(res.get("terminated_pids", []))

        duration_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        return {
            "status": "completed",
            "processes_terminated": len(targets),
            "total_pids_reaped": len(all_terminated_pids),
            "pids": sorted(list(all_terminated_pids)),
            "duration_ms": duration_ms,
        }


# Global singleton
managed_process_registry = ManagedProcessRegistry()
