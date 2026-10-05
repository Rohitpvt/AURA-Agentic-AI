"""AURA-902 Process Inspection & Governed Termination Service.

Provides:
1. Safe read-only process inspection without sensitive environment or secret leakage
2. Governed process termination with PID + creation_time identity verification
3. Protected process denylist enforcement (System, Defender, AURA infrastructure)
4. Structured termination outcomes (TERMINATED, ALREADY_EXITED, IDENTITY_MISMATCH, PROTECTED, FAILED)
5. Zero shell commands (no taskkill.exe / cmd invocation)
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional
import psutil

from app.core.logging import logger
from app.services.os_guard.validators import PROTECTED_PROCESS_NAMES, ProcessIdentityValidator


class ProcessService:
    """Safe local Windows process inspection and governed termination engine."""

    @staticmethod
    def inspect_processes(
        filter_name: Optional[str] = None,
        pid: Optional[int] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Inspect running processes safely without exposing environment variables or command-line secrets."""
        max_limit = min(max(1, limit), 100)
        results: List[Dict[str, Any]] = []

        # If specific PID requested
        if pid is not None:
            if not psutil.pid_exists(pid):
                return []
            try:
                p = psutil.Process(pid)
                results.append(ProcessService._extract_safe_process_info(p))
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                return []
            return results

        clean_filter = filter_name.strip().lower() if filter_name else None

        # Iterate active processes directly by PID for high-performance enumeration
        for pid_val in psutil.pids():
            if pid_val <= 0:
                continue
            try:
                p = psutil.Process(pid_val)
                p_name = p.name()
                if clean_filter and clean_filter not in p_name.lower():
                    continue

                info = ProcessService._extract_safe_process_info(p)
                results.append(info)
                if len(results) >= max_limit:
                    break
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
            except Exception as e:
                logger.debug(f"ProcessService: Error inspecting process ({e})")
                continue

        return results

    @staticmethod
    def _extract_safe_process_info(proc: psutil.Process) -> Dict[str, Any]:
        """Extract safe, sanitized process metadata."""
        p_name = ""
        try:
            p_name = proc.name()
        except Exception:
            p_name = "unknown"

        p_create_time = 0.0
        try:
            p_create_time = proc.create_time()
        except Exception:
            pass

        p_status = "running"
        p_cpu = 0.0
        p_mem_mb = 0.0

        clean_p_name = p_name.lower().strip()
        name_with_exe = clean_p_name if clean_p_name.endswith(".exe") else f"{clean_p_name}.exe"
        name_without_exe = clean_p_name[:-4] if clean_p_name.endswith(".exe") else clean_p_name

        is_protected = (
            proc.pid <= 4
            or clean_p_name in PROTECTED_PROCESS_NAMES
            or name_with_exe in PROTECTED_PROCESS_NAMES
            or name_without_exe in PROTECTED_PROCESS_NAMES
        )

        return {
            "pid": proc.pid,
            "name": p_name,
            "status": p_status,
            "create_time": p_create_time,
            "cpu_percent": p_cpu,
            "memory_mb": p_mem_mb,
            "is_protected": is_protected,
        }

    @staticmethod
    def terminate_process(
        pid: int,
        expected_create_time: float,
        expected_name: str,
        timeout_sec: float = 3.0,
    ) -> Dict[str, Any]:
        """Terminate a specific validated process on the host using native API."""
        t_req = time.time()

        # 1. Validate Process Identity & Safety Rules
        is_safe, err = ProcessIdentityValidator.validate_process_for_termination(
            pid=pid,
            expected_name=expected_name,
            expected_create_time=expected_create_time,
        )
        if not is_safe:
            outcome = "PROTECTED" if "protected" in err.lower() else "IDENTITY_MISMATCH"
            return {
                "pid": pid,
                "process_name": expected_name,
                "create_time": expected_create_time,
                "termination_requested_at": t_req,
                "termination_completed_at": time.time(),
                "outcome": outcome,
                "error": err,
            }

        # 2. Check if PID exists
        if not psutil.pid_exists(pid):
            return {
                "pid": pid,
                "process_name": expected_name,
                "create_time": expected_create_time,
                "termination_requested_at": t_req,
                "termination_completed_at": time.time(),
                "outcome": "ALREADY_EXITED",
            }

        try:
            proc = psutil.Process(pid)

            # Re-verify name and create_time immediately before killing
            actual_name = proc.name().lower()
            actual_create_time = proc.create_time()

            clean_exp_name = expected_name.lower().strip()
            if not clean_exp_name.endswith(".exe") and clean_exp_name != "system":
                clean_exp_name = f"{clean_exp_name}.exe"

            if actual_name != clean_exp_name and actual_name != expected_name.lower():
                return {
                    "pid": pid,
                    "process_name": expected_name,
                    "create_time": expected_create_time,
                    "termination_requested_at": t_req,
                    "termination_completed_at": time.time(),
                    "outcome": "IDENTITY_MISMATCH",
                    "error": f"Process name changed from '{expected_name}' to '{actual_name}' before termination",
                }

            if expected_create_time > 0 and abs(actual_create_time - expected_create_time) > 0.05:
                return {
                    "pid": pid,
                    "process_name": expected_name,
                    "create_time": expected_create_time,
                    "termination_requested_at": t_req,
                    "termination_completed_at": time.time(),
                    "outcome": "IDENTITY_MISMATCH",
                    "error": f"Process create_time changed (PID recycled by new process)",
                }

            # 3. Perform Terminate
            proc.terminate()
            try:
                proc.wait(timeout=timeout_sec)
            except psutil.TimeoutExpired:
                # Force kill if didn't terminate in timeout
                proc.kill()
                proc.wait(timeout=1.0)

            t_done = time.time()
            logger.info(f"ProcessService: Successfully terminated process '{expected_name}' (PID: {pid})")

            return {
                "pid": pid,
                "process_name": expected_name,
                "create_time": actual_create_time,
                "termination_requested_at": t_req,
                "termination_completed_at": t_done,
                "outcome": "TERMINATED",
            }

        except psutil.NoSuchProcess:
            return {
                "pid": pid,
                "process_name": expected_name,
                "create_time": expected_create_time,
                "termination_requested_at": t_req,
                "termination_completed_at": time.time(),
                "outcome": "ALREADY_EXITED",
            }
        except psutil.AccessDenied as ad_err:
            return {
                "pid": pid,
                "process_name": expected_name,
                "create_time": expected_create_time,
                "termination_requested_at": t_req,
                "termination_completed_at": time.time(),
                "outcome": "FAILED",
                "error": f"Access denied when terminating PID {pid}: {ad_err}",
            }
        except Exception as e:
            return {
                "pid": pid,
                "process_name": expected_name,
                "create_time": expected_create_time,
                "termination_requested_at": t_req,
                "termination_completed_at": time.time(),
                "outcome": "FAILED",
                "error": f"Failed to terminate PID {pid}: {e}",
            }


process_service = ProcessService()
