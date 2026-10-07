"""AURA-1005 Process Identity Tracking, Windows Job Object Containment & Lifecycle Management."""

import asyncio
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import platform
import signal
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import psutil

from app.core.logging import logger
from app.daemon.types import DaemonConfig


# Win32 Structures for Job Objects
class IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    ]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryLimit", ctypes.c_size_t),
        ("PeakJobMemoryLimit", ctypes.c_size_t),
    ]


JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JobObjectExtendedLimitInformation = 9
PROCESS_SET_QUOTA = 0x0100
PROCESS_TERMINATE = 0x0001


def get_current_session_id() -> int:
    """Retrieve the Windows Terminal Services / User Session ID for the current process."""
    if platform.system() == "Windows":
        try:
            sid = wintypes.DWORD()
            if ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(sid)):
                return int(sid.value)
        except Exception as exc:
            logger.debug(f"Failed to query Windows session ID: {exc}")
    return 0


class WindowsJobObject:
    """Encapsulates a Win32 Job Object ensuring child processes terminate when supervisor closes."""

    def __init__(self):
        self._handle: Optional[int] = None
        self._is_windows = platform.system() == "Windows"
        if self._is_windows:
            self._create_job_object()

    def _create_job_object(self) -> None:
        try:
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.CreateJobObjectW(None, None)
            if not handle:
                err = kernel32.GetLastError()
                logger.warning(f"WindowsJobObject: CreateJobObjectW failed with error {err}")
                return

            info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            success = kernel32.SetInformationJobObject(
                handle,
                JobObjectExtendedLimitInformation,
                ctypes.byref(info),
                ctypes.sizeof(info),
            )
            if not success:
                err = kernel32.GetLastError()
                logger.warning(f"WindowsJobObject: SetInformationJobObject failed with error {err}")
                kernel32.CloseHandle(handle)
                return

            self._handle = handle
            logger.debug(f"WindowsJobObject: Initialized job handle {handle} with KILL_ON_JOB_CLOSE")
        except Exception as exc:
            logger.warning(f"WindowsJobObject: Failed initializing Job Object: {exc}")

    def assign_process(self, pid: int) -> bool:
        """Assign an active process by PID to this Job Object."""
        if not self._is_windows or not self._handle:
            return False
        try:
            kernel32 = ctypes.windll.kernel32
            # Open process handle with required access rights
            h_proc = kernel32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, pid)
            if not h_proc:
                err = kernel32.GetLastError()
                logger.debug(f"WindowsJobObject: OpenProcess({pid}) failed with error {err}")
                return False

            try:
                success = kernel32.AssignProcessToJobObject(self._handle, h_proc)
                if not success:
                    err = kernel32.GetLastError()
                    logger.debug(f"WindowsJobObject: AssignProcessToJobObject({pid}) failed with error {err}")
                    return False
                logger.debug(f"WindowsJobObject: Successfully assigned PID {pid} to Job Object")
                return True
            finally:
                kernel32.CloseHandle(h_proc)
        except Exception as exc:
            logger.debug(f"WindowsJobObject: Error assigning PID {pid}: {exc}")
            return False

    def close(self) -> None:
        """Close the job object handle."""
        if self._handle and self._is_windows:
            try:
                ctypes.windll.kernel32.CloseHandle(self._handle)
                self._handle = None
            except Exception:
                pass


class ProcessIdentity:
    """Strong identity descriptor for a managed process preventing PID reuse vulnerabilities."""

    def __init__(
        self,
        pid: int,
        create_time: float,
        exe_path: str,
        cmdline: List[str],
        session_id: Optional[int] = None,
        launch_time: Optional[float] = None,
    ):
        self.pid = pid
        self.create_time = create_time
        self.exe_path = exe_path
        self.cmdline = cmdline
        self.session_id = session_id if session_id is not None else get_current_session_id()
        self.launch_time = launch_time or time.time()

    def matches_live_process(self) -> bool:
        """Verify if the running OS process with this PID matches our tracked creation timestamp and session."""
        try:
            if not psutil.pid_exists(self.pid):
                return False
            p = psutil.Process(self.pid)
            if not p.is_running() or p.status() == psutil.STATUS_ZOMBIE:
                return False
            # Validate creation time within 0.5s tolerance
            if abs(p.create_time() - self.create_time) >= 0.5:
                return False
            # If on Windows, check user session ID where supported
            if platform.system() == "Windows":
                try:
                    sid = wintypes.DWORD()
                    if ctypes.windll.kernel32.ProcessIdToSessionId(self.pid, ctypes.byref(sid)):
                        if int(sid.value) != self.session_id:
                            return False
                except Exception:
                    pass
            return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return False

    def get_process(self) -> Optional[psutil.Process]:
        """Return psutil.Process instance if identity matches live OS process."""
        if self.matches_live_process():
            try:
                return psutil.Process(self.pid)
            except Exception:
                return None
        return None

    def __repr__(self) -> str:
        return f"<ProcessIdentity pid={self.pid} create_time={self.create_time:.2f} session={self.session_id}>"


class ProcessTracker:
    """Manages process spawning, containment, strong identity verification, and termination."""

    def __init__(self, enable_job_object: bool = True):
        self.enable_job_object = enable_job_object
        self.job_object = WindowsJobObject() if enable_job_object else None

    def launch_backend(
        self,
        config: DaemonConfig,
        extra_env: Optional[Dict[str, str]] = None,
    ) -> Tuple[asyncio.subprocess.Process, ProcessIdentity]:
        """Launch the AURA backend runtime in a controlled subprocess with strict arguments."""
        # 1. Resolve executable and command array
        executable = sys.executable
        if config.custom_command:
            cmd = config.custom_command
        else:
            cmd = [
                executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                config.backend_host,
                "--port",
                str(config.backend_port),
            ]

        # 2. Resolve working directory safely
        if config.custom_cwd:
            cwd = Path(config.custom_cwd).resolve()
        else:
            cwd = Path(__file__).resolve().parent.parent.parent  # apps/api
        if not cwd.exists() or not cwd.is_dir():
            raise RuntimeError(f"Configured working directory does not exist: {cwd}")

        # 3. Prepare controlled environment
        env = dict(os.environ)
        env["AURA_SUPERVISED_DAEMON"] = "1"
        env["AURA_PORT"] = str(config.backend_port)
        if extra_env:
            env.update(extra_env)

        # 4. Windows process flags (CREATE_NEW_PROCESS_GROUP for clean signal routing)
        creation_flags = 0
        if platform.system() == "Windows":
            creation_flags = 0x00000200  # CREATE_NEW_PROCESS_GROUP

        # 5. Spawn subprocess synchronously via subprocess or async
        # We will use psutil / subprocess under asyncio loop
        import subprocess
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creation_flags,
        )

        pid = proc.pid
        session_id = get_current_session_id()

        # 6. Capture create_time from psutil
        try:
            p = psutil.Process(pid)
            create_time = p.create_time()
            exe_path = p.exe()
        except Exception:
            create_time = time.time()
            exe_path = executable

        # 7. Assign to Windows Job Object
        if self.job_object:
            self.job_object.assign_process(pid)

        identity = ProcessIdentity(
            pid=pid,
            create_time=create_time,
            exe_path=exe_path,
            cmdline=cmd,
            session_id=session_id,
            launch_time=time.time(),
        )

        logger.info(
            f"ProcessTracker: Launched AURA backend PID {pid} (session={session_id}, cwd='{cwd}')"
        )
        return proc, identity

    def terminate_tree(self, identity: ProcessIdentity, timeout: float = 5.0) -> bool:
        """Safely terminate a managed process and all its children with strict identity validation."""
        if not identity.matches_live_process():
            logger.debug(f"ProcessTracker: PID {identity.pid} is already dead or does not match identity")
            return True

        pid = identity.pid
        try:
            parent = psutil.Process(pid)
            children = parent.children(recursive=True)
            all_procs = children + [parent]

            # 1. Send graceful termination signal
            for p in all_procs:
                try:
                    if platform.system() == "Windows":
                        p.send_signal(signal.CTRL_BREAK_EVENT)
                    else:
                        p.terminate()
                except Exception:
                    try:
                        p.terminate()
                    except Exception:
                        pass

            # 2. Wait bounded timeout for graceful exit
            gone, alive = psutil.wait_procs(all_procs, timeout=timeout)

            # 3. Force kill any remaining processes
            if alive:
                for p in alive:
                    try:
                        p.kill()
                    except Exception:
                        pass
                psutil.wait_procs(alive, timeout=2.0)

            logger.info(f"ProcessTracker: Successfully terminated process tree for PID {pid}")
            return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return True
        except Exception as exc:
            logger.warning(f"ProcessTracker: Error terminating process tree for PID {pid}: {exc}")
            return False

    def cleanup_orphans(self, expected_tokens: Optional[List[str]] = None) -> int:
        """Sweep and terminate any stale AURA backend processes in the current user session."""
        tokens = expected_tokens or ["uvicorn", "app.main:app"]
        current_session = get_current_session_id()
        current_pid = os.getpid()
        reaped = 0

        try:
            for p in psutil.process_iter(["pid", "name", "cmdline", "create_time"]):
                try:
                    p_pid = p.info["pid"]
                    if p_pid == current_pid:
                        continue

                    # Check session ID on Windows
                    if platform.system() == "Windows":
                        try:
                            sid = wintypes.DWORD()
                            if ctypes.windll.kernel32.ProcessIdToSessionId(p_pid, ctypes.byref(sid)):
                                if int(sid.value) != current_session:
                                    continue
                        except Exception:
                            pass

                    cmdline = p.info.get("cmdline") or []
                    cmd_str = " ".join(cmdline).lower()
                    if all(t.lower() in cmd_str for t in tokens):
                        logger.info(f"ProcessTracker: Cleaning up orphan AURA backend process PID {p_pid}")
                        p.kill()
                        reaped += 1
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
        except Exception as exc:
            logger.debug(f"ProcessTracker: Error sweeping orphan processes: {exc}")

        return reaped

    def close(self) -> None:
        """Close tracker and any associated Job Object."""
        if self.job_object:
            self.job_object.close()
            self.job_object = None
