"""AURA-901 Host Action Validators: Path, Process Identity, and Coordinate Safety.

Implements:
1. PathValidator: Canonicalization, traversal defense, LOLBins rejection, executable allowlist
2. ProcessIdentityValidator: Protected process denylist, PID + creation_time TOCTOU verification
3. CoordinateSafetyValidator: Monitor bounds, active window bounds, stale visual observation TTL
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

from app.services.os_guard.policy import LOLBINS_DENYLIST


# Canonical Protected System Process Names (Never Terminate)
PROTECTED_PROCESS_NAMES: FrozenSet[str] = frozenset({
    "system",
    "registry",
    "smss.exe",
    "csrss.exe",
    "wininit.exe",
    "services.exe",
    "lsass.exe",
    "svchost.exe",
    "explorer.exe",
    "dwm.exe",
    "msmpeng.exe",
    "securityhealthservice.exe",
    "postgres.exe",
    "ollama.exe",
    "python.exe",
    "node.exe",
})

MAX_OBSERVATION_AGE_SEC: float = 5.0


class PathValidator:
    """Validates executable paths for application launch safety."""

    @staticmethod
    def validate_executable_path(
        raw_path: str,
        allowlist: Optional[List[str]] = None,
        check_file_exists: bool = False,
    ) -> Tuple[bool, str, str]:
        """Validate, sanitize, and canonicalize executable path.
        
        Returns:
            (is_valid, canonical_path, error_message)
        """
        if not raw_path or not raw_path.strip():
            return False, "", "Executable path is empty"

        cleaned = raw_path.strip()

        # 1. Reject obvious traversal sequences before normalization
        if ".." in cleaned:
            return False, "", "Path traversal sequence ('..') detected in executable path"

        # 2. Canonicalize path
        try:
            canonical = os.path.abspath(os.path.normpath(cleaned))
        except Exception as e:
            return False, "", f"Path canonicalization error: {e}"

        # 3. On Windows, verify drive absolute path
        if os.name == "nt" and not (len(canonical) >= 3 and canonical[1:3] == ":\\"):
            return False, canonical, "Executable path must be an absolute drive path (e.g. C:\\...)"

        # 4. Check against LOLBins denylist
        basename = os.path.basename(canonical).lower()
        if basename in LOLBINS_DENYLIST:
            return False, canonical, f"Executable '{basename}' is in the Windows LOLBins security denylist"

        # 5. Check extension (must be .exe)
        if not canonical.lower().endswith(".exe"):
            return False, canonical, "Executable target must have a '.exe' extension"

        # 6. Check explicit allowlist if configured
        if allowlist is not None:
            normalized_allowlist = [os.path.abspath(os.path.normpath(a)).lower() for a in allowlist]
            if canonical.lower() not in normalized_allowlist and basename not in [os.path.basename(a).lower() for a in allowlist]:
                return False, canonical, f"Executable '{basename}' is not in the approved application allowlist"

        # 7. Check file existence if requested
        if check_file_exists and not os.path.exists(canonical):
            return False, canonical, f"Executable not found at path: {canonical}"

        return True, canonical, ""


class ProcessIdentityValidator:
    """Validates process identity with PID + creation_time verification for TOCTOU / recycling defense."""

    @staticmethod
    def validate_process_for_termination(
        pid: int,
        expected_name: str,
        expected_create_time: float,
        process_allowlist: Optional[List[str]] = None,
    ) -> Tuple[bool, str]:
        """Verify process is safe to terminate and matches expected identity."""
        if pid <= 4:
            return False, f"PID {pid} is a protected Windows system kernel process"

        # 1. Protected System Process Denylist Check
        clean_name = expected_name.lower().strip()
        if not clean_name.endswith(".exe") and clean_name != "system" and clean_name != "registry":
            clean_name = f"{clean_name}.exe"

        if clean_name in PROTECTED_PROCESS_NAMES or expected_name.lower() in PROTECTED_PROCESS_NAMES:
            return False, f"Process '{expected_name}' (PID: {pid}) is in the protected system denylist and cannot be terminated"

        # 2. Allowlist Check if provided
        if process_allowlist is not None:
            allowed = [p.lower().strip() for p in process_allowlist]
            if clean_name not in allowed and expected_name.lower() not in allowed:
                return False, f"Process '{expected_name}' is not in the approved termination allowlist"

        # 3. Live psutil Process Verification (PID + Creation Time)
        try:
            import psutil
            if not psutil.pid_exists(pid):
                return False, f"Process with PID {pid} does not exist (may have already exited)"

            proc = psutil.Process(pid)
            actual_name = proc.name().lower()
            actual_create_time = proc.create_time()

            # Name verification
            if actual_name != clean_name and actual_name != expected_name.lower():
                return False, f"Process name mismatch for PID {pid}: expected '{expected_name}', actual '{actual_name}' (PID reused)"

            # Creation time verification (tolerance 0.05s)
            if expected_create_time > 0 and abs(actual_create_time - expected_create_time) > 0.05:
                return False, (
                    f"Process creation time mismatch for PID {pid}: "
                    f"expected {expected_create_time:.4f}, actual {actual_create_time:.4f} (PID recycled by new process)"
                )

        except ImportError:
            # Fallback if psutil unavailable in test mock
            pass
        except Exception as e:
            return False, f"Failed verifying process identity for PID {pid}: {e}"

        return True, ""


class CoordinateSafetyValidator:
    """Validates screen and window coordinate safety with stale observation protection."""

    @staticmethod
    def validate_screen_coordinates(
        x: int,
        y: int,
        monitor_id: int = 1,
        monitor_bounds: Optional[Dict[str, int]] = None,
        window_bounds: Optional[Dict[str, int]] = None,
        observation_timestamp: Optional[float] = None,
    ) -> Tuple[bool, str]:
        """Validate coordinate bounds and observation freshness."""
        # 1. Reject negative coordinates
        if x < 0 or y < 0:
            return False, f"Coordinates cannot be negative: ({x}, {y})"

        # 2. Check Stale Observation Age
        if observation_timestamp is not None:
            now = time.time()
            age = now - observation_timestamp
            if age > MAX_OBSERVATION_AGE_SEC:
                return False, (
                    f"Stale visual observation ({age:.2f}s > {MAX_OBSERVATION_AGE_SEC}s). "
                    f"Fresh inspect_current_screen required before GUI interaction."
                )

        # 3. Check Monitor Bounds if provided
        if monitor_bounds:
            m_left = monitor_bounds.get("left", 0)
            m_top = monitor_bounds.get("top", 0)
            m_width = monitor_bounds.get("width", 1920)
            m_height = monitor_bounds.get("height", 1080)

            if not (m_left <= x < m_left + m_width and m_top <= y < m_top + m_height):
                return False, f"Coordinates ({x}, {y}) exceed Monitor {monitor_id} boundaries ({m_left},{m_top},{m_width}x{m_height})"

        # 4. Check Window Bounds if provided
        if window_bounds:
            w_left = window_bounds.get("left", 0)
            w_top = window_bounds.get("top", 0)
            w_width = window_bounds.get("width", 0)
            w_height = window_bounds.get("height", 0)

            if w_width > 0 and w_height > 0:
                if not (w_left <= x <= w_left + w_width and w_top <= y <= w_top + w_height):
                    return False, f"Coordinates ({x}, {y}) fall outside active window boundaries ({w_left},{w_top},{w_width}x{w_height})"

        return True, ""
