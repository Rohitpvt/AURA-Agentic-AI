"""AURA-1005 Session-Scoped Single Instance Mutex & Lock Guard."""

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import platform
import time
from typing import Optional

import psutil

from app.core.logging import logger
from app.daemon.process_tracker import get_current_session_id

ERROR_ALREADY_EXISTS = 183


class AuraSingleInstanceGuard:
    """Ensures exactly one AURA Daemon Supervisor runs per Windows interactive user session."""

    def __init__(self, session_id: Optional[int] = None, state_dir: Optional[Path] = None):
        self.session_id = session_id if session_id is not None else get_current_session_id()
        self.state_dir = state_dir or (Path(os.environ.get("AURA_STATE_DIR", Path.home() / ".aura")))
        self.state_dir.mkdir(parents=True, exist_ok=True)
        
        self._mutex_handle: Optional[int] = None
        self._lock_file: Path = self.state_dir / f"daemon_session_{self.session_id}.lock"
        self._is_locked: bool = False
        self._is_windows = platform.system() == "Windows"

    def acquire(self) -> bool:
        """Attempt to acquire exclusive ownership of the session supervisor lock.
        
        Returns True if lock was acquired successfully, False if another instance already holds it.
        """
        # 1. Windows Named Mutex Check
        if self._is_windows:
            try:
                kernel32 = ctypes.windll.kernel32
                mutex_name = f"Local\\AuraDaemonSupervisor_Session_{self.session_id}"
                handle = kernel32.CreateMutexW(None, True, mutex_name)
                err = kernel32.GetLastError()
                
                if err == ERROR_ALREADY_EXISTS:
                    logger.warning(
                        f"AuraSingleInstanceGuard: Another supervisor is already active in session {self.session_id} (Mutex exists)"
                    )
                    if handle:
                        kernel32.CloseHandle(handle)
                    return False
                
                if not handle:
                    logger.warning(f"AuraSingleInstanceGuard: CreateMutexW failed with error {err}")
                    return False

                self._mutex_handle = handle
            except Exception as exc:
                logger.warning(f"AuraSingleInstanceGuard: Failed creating Win32 mutex ({exc})")

        # 2. State Lock File Verification & Recovery
        if self._lock_file.exists():
            try:
                data = json.loads(self._lock_file.read_text(encoding="utf-8"))
                holder_pid = data.get("pid")
                holder_create_time = data.get("create_time", 0.0)

                # Check if holder process is another active process holding the lock
                if holder_pid and holder_pid != os.getpid() and psutil.pid_exists(holder_pid):
                    p = psutil.Process(holder_pid)
                    if p.is_running() and p.status() != psutil.STATUS_ZOMBIE:
                        if abs(p.create_time() - holder_create_time) < 0.5:
                            logger.warning(
                                f"AuraSingleInstanceGuard: Active supervisor PID {holder_pid} holds lockfile"
                            )
                            if self._mutex_handle and self._is_windows:
                                ctypes.windll.kernel32.CloseHandle(self._mutex_handle)
                                self._mutex_handle = None
                            return False
            except Exception as exc:
                logger.debug(f"AuraSingleInstanceGuard: Stale lockfile read failed ({exc}), reclaiming")

        # 3. Write Current Supervisor Identity to Lock File
        try:
            current_pid = os.getpid()
            create_time = psutil.Process(current_pid).create_time()
            lock_data = {
                "pid": current_pid,
                "create_time": create_time,
                "session_id": self.session_id,
                "acquired_at": time.time(),
            }
            self._lock_file.write_text(json.dumps(lock_data, indent=2), encoding="utf-8")
            self._is_locked = True
            logger.debug(f"AuraSingleInstanceGuard: Acquired lock for session {self.session_id} (PID {current_pid})")
            return True
        except Exception as exc:
            logger.error(f"AuraSingleInstanceGuard: Failed writing lockfile ({exc})")
            if self._mutex_handle and self._is_windows:
                ctypes.windll.kernel32.CloseHandle(self._mutex_handle)
                self._mutex_handle = None
            return False

    def release(self) -> None:
        """Release mutex and clean up lock file."""
        if self._mutex_handle and self._is_windows:
            try:
                ctypes.windll.kernel32.ReleaseMutex(self._mutex_handle)
                ctypes.windll.kernel32.CloseHandle(self._mutex_handle)
            except Exception:
                pass
            self._mutex_handle = None

        if self._is_locked:
            try:
                if self._lock_file.exists():
                    self._lock_file.unlink(missing_ok=True)
            except Exception:
                pass
            self._is_locked = False
            logger.debug(f"AuraSingleInstanceGuard: Released lock for session {self.session_id}")

    def __enter__(self):
        if not self.acquire():
            raise RuntimeError(f"Another AURA supervisor is already running in session {self.session_id}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
