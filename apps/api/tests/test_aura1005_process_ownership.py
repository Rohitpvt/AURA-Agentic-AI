"""AURA-1005 Process Ownership, PID Reuse Defense, and Orphan Reaper Verification Suite."""

import asyncio
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
from typing import List, Optional

import psutil
import pytest

from app.daemon.process_tracker import (
    ProcessIdentity,
    ProcessTracker,
    get_current_session_id,
)
from app.daemon.types import DaemonConfig


@pytest.fixture
def temp_state_dir(tmp_path):
    state_dir = tmp_path / ".aura"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir


def test_true_process_ownership_tuple():
    """Verify that process ownership is strictly validated by (PID, create_time, exe_path, cmdline, session_id)."""
    current_pid = os.getpid()
    p = psutil.Process(current_pid)
    real_create_time = p.create_time()
    real_exe = p.exe()
    session_id = get_current_session_id()

    identity = ProcessIdentity(
        pid=current_pid,
        create_time=real_create_time,
        exe_path=real_exe,
        cmdline=["python"],
        session_id=session_id,
    )

    assert identity.matches_live_process() is True
    assert identity.get_process() is not None
    assert identity.get_process().pid == current_pid


def test_pid_reuse_timestamp_discrepancy_fails_closed():
    """Prove that if a PID is reused by a new process, the creation timestamp mismatch fails closed."""
    current_pid = os.getpid()
    p = psutil.Process(current_pid)
    real_create_time = p.create_time()

    # Forged identity representing a stale process from an earlier time with the same PID
    stale_identity = ProcessIdentity(
        pid=current_pid,
        create_time=real_create_time - 3600.0,  # 1 hour ago
        exe_path=sys.executable,
        cmdline=["python"],
        session_id=get_current_session_id(),
    )

    assert stale_identity.matches_live_process() is False
    assert stale_identity.get_process() is None

    # ProcessTracker must refuse to send signals or kill this process
    tracker = ProcessTracker(enable_job_object=False)
    result = tracker.terminate_tree(stale_identity, timeout=1.0)
    assert result is True  # Safely returns without touching current process
    assert psutil.pid_exists(current_pid) is True
    tracker.close()


def test_same_name_unrelated_process_isolation(temp_state_dir):
    """Prove that an unrelated process with the same binary name (python.exe) is never terminated."""
    # Launch an unrelated disposable python process
    unrelated_proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assert unrelated_proc.poll() is None
        unrelated_pid = unrelated_proc.pid

        tracker = ProcessTracker(enable_job_object=False)
        # Orphan sweep looking for AURA uvicorn backend
        reaped = tracker.cleanup_orphans(expected_tokens=["app.main:app", "uvicorn"])
        assert reaped == 0

        # Verify unrelated process is completely unharmed
        assert psutil.pid_exists(unrelated_pid) is True
        assert unrelated_proc.poll() is None
        tracker.close()
    finally:
        unrelated_proc.kill()
        unrelated_proc.wait()


def test_cross_session_mismatched_session_id():
    """Verify that a process identity with a mismatched session ID fails ownership validation on Windows."""
    if platform.system() == "Windows":
        current_pid = os.getpid()
        p = psutil.Process(current_pid)
        current_session = get_current_session_id()

        # Identity claiming session 99999 (different session)
        cross_session_id = ProcessIdentity(
            pid=current_pid,
            create_time=p.create_time(),
            exe_path=sys.executable,
            cmdline=["python"],
            session_id=current_session + 9999,
        )

        assert cross_session_id.matches_live_process() is False
        assert cross_session_id.get_process() is None


def test_orphan_reaper_five_case_matrix(temp_state_dir):
    """Prove the 5-case orphan reaper decision matrix."""
    tracker = ProcessTracker(enable_job_object=False)

    # Case A: Valid owned active process with unique token
    proc_a = subprocess.Popen([
        sys.executable,
        "-c",
        "import time; time.sleep(30)",
        "--aura-marker-stale-test-12345",
    ])

    # Case B: Stale owned process with matching token
    proc_b = subprocess.Popen([
        sys.executable,
        "-c",
        "import time; time.sleep(30)",
        "--aura-marker-stale-test-12345",
    ])

    # Case C: Same-name unrelated process (no matching token)
    proc_c = subprocess.Popen([
        sys.executable,
        "-c",
        "import time; time.sleep(30)",
        "--unrelated-worker",
    ])

    try:
        assert proc_a.poll() is None
        assert proc_b.poll() is None
        assert proc_c.poll() is None

        # Execute orphan sweep specifically for the test marker token
        reaped = tracker.cleanup_orphans(expected_tokens=["--aura-marker-stale-test-12345"])
        assert reaped == 2

        # Give OS time to update process state
        time.sleep(0.3)

        # Case A & B (matching tokens) were reaped
        assert proc_a.poll() is not None or not psutil.pid_exists(proc_a.pid)
        assert proc_b.poll() is not None or not psutil.pid_exists(proc_b.pid)

        # Case C (unrelated process) MUST remain untouched
        assert psutil.pid_exists(proc_c.pid) is True
        assert proc_c.poll() is None

        # Case D: Dead PID is safely ignored
        dead_id = ProcessIdentity(pid=99999999, create_time=0.0, exe_path="", cmdline=[])
        assert tracker.terminate_tree(dead_id) is True

        # Case E: Existing PID with mismatched timestamp is safely ignored
        mismatched_id = ProcessIdentity(
            pid=proc_c.pid,
            create_time=psutil.Process(proc_c.pid).create_time() + 999.0,
            exe_path=sys.executable,
            cmdline=[],
        )
        assert tracker.terminate_tree(mismatched_id) is True
        assert proc_c.poll() is None

    finally:
        for p in [proc_a, proc_b, proc_c]:
            try:
                p.kill()
                p.wait()
            except Exception:
                pass
        tracker.close()
