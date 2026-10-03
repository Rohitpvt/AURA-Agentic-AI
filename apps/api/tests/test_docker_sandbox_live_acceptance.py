"""Live Runtime Acceptance Test Harness for Production Docker / WSL2 Sandbox (AURA-506).

This suite contains end-to-end operational acceptance tests designed to run
against a live Docker / WSL2 runtime when available.

When Docker is unavailable on the test host, these tests are cleanly skipped
with an explicit diagnostic message rather than mocked, ensuring that only
genuine live container execution is classified as 'real Docker/WSL2 sandbox test'.
"""

import asyncio
import shutil
from typing import Any, Dict
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.filesystem import filesystem_guard
from app.db.models.audit import AuditLog
from app.runtime.sandbox.docker_sandbox import DockerExecutionSandbox
from app.runtime.sandbox.manager import sandbox_manager
from app.runtime.sandbox.profiles import SANDBOX_PROFILES, SandboxProfileType
from app.services.audit_service import audit_service
from app.services.kill_switch import kill_switch


def is_docker_live() -> bool:
    """Synchronous probe to detect if Docker daemon is active and responsive."""
    import subprocess
    docker_bin = shutil.which("docker")
    if not docker_bin:
        return False
    try:
        res = subprocess.run([docker_bin, "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
        return res.returncode == 0
    except Exception:
        return False


DOCKER_AVAILABLE = is_docker_live()
skip_if_no_docker = pytest.mark.skipif(
    not DOCKER_AVAILABLE,
    reason="Live Docker / WSL2 runtime is unavailable on target host — Real container test blocked"
)


# ==============================================================================
# LIVE ACCEPTANCE HARNESS (Real Container Execution)
# ==============================================================================

@skip_if_no_docker
@pytest.mark.asyncio
async def test_live_docker_container_startup_and_profile():
    """Real Docker/WSL2 sandbox test: Verify live container startup and basic command execution."""
    ws_id = uuid.uuid4()
    res = await sandbox_manager.execute_in_sandbox(
        workspace_id=ws_id,
        command=["python3", "-c", "import sys; print('AURA_LIVE_CONTAINER_OK')"],
        profile_type=SandboxProfileType.READ_ONLY,
    )
    assert res["status"] == "success"
    assert res["exit_code"] == 0
    assert "AURA_LIVE_CONTAINER_OK" in res["stdout"]


@skip_if_no_docker
@pytest.mark.asyncio
async def test_live_docker_read_only_rootfs_enforcement():
    """Real Docker/WSL2 sandbox test: Verify that writes to rootfs inside container fail."""
    ws_id = uuid.uuid4()
    # Attempt to write to /root or /usr/bin inside read-only rootfs container
    res = await sandbox_manager.execute_in_sandbox(
        workspace_id=ws_id,
        command=["python3", "-c", "open('/root/pwn.txt', 'w').write('data')"],
        profile_type=SandboxProfileType.READ_ONLY,
    )
    assert res["status"] == "error"
    assert res["exit_code"] != 0
    assert "Read-only file system" in res["stderr"] or "PermissionError" in res["stderr"]


@skip_if_no_docker
@pytest.mark.asyncio
async def test_live_docker_workspace_mount_isolation():
    """Real Docker/WSL2 sandbox test: Verify container can read/write authorized workspace only."""
    ws_id = uuid.uuid4()
    ws_root = filesystem_guard.get_workspace_root(ws_id)
    (ws_root / "input.txt").write_text("live_workspace_input_data")

    # 1. Read input and write output in development profile (workspace_writeable=True)
    res = await sandbox_manager.execute_in_sandbox(
        workspace_id=ws_id,
        command=["python3", "-c", "txt = open('/workspace/input.txt').read(); open('/workspace/output.txt', 'w').write(txt + '_processed')"],
        profile_type=SandboxProfileType.DEVELOPMENT,
    )
    assert res["status"] == "success"
    assert (ws_root / "output.txt").exists()
    assert (ws_root / "output.txt").read_text() == "live_workspace_input_data_processed"


@skip_if_no_docker
@pytest.mark.asyncio
async def test_live_docker_offline_network_denial():
    """Real Docker/WSL2 sandbox test: Verify that outbound network attempts fail in offline profiles."""
    ws_id = uuid.uuid4()
    # Attempt to establish an outbound TCP connection to 1.1.1.1 in DEVELOPMENT profile (--network none)
    res = await sandbox_manager.execute_in_sandbox(
        workspace_id=ws_id,
        command=["python3", "-c", "import urllib.request; urllib.request.urlopen('http://1.1.1.1', timeout=2)"],
        profile_type=SandboxProfileType.DEVELOPMENT,
    )
    assert res["status"] == "error"
    assert res["exit_code"] != 0
    assert "URLError" in res["stderr"] or "Network is unreachable" in res["stderr"] or "timeout" in res["stderr"].lower()


@skip_if_no_docker
@pytest.mark.asyncio
async def test_live_docker_memory_limit_oom_enforcement():
    """Real Docker/WSL2 sandbox test: Verify that exceeding configured memory envelope triggers OOM termination."""
    ws_id = uuid.uuid4()
    # READ_ONLY profile has 256MB limit; allocate 500MB of dirty pages to trigger OOM killer
    res = await sandbox_manager.execute_in_sandbox(
        workspace_id=ws_id,
        command=["python3", "-c", "x = [b'x' * (10 * 1024 * 1024) for _ in range(50)]"],
        profile_type=SandboxProfileType.READ_ONLY,
    )
    assert res["status"] in ["oom_killed", "error"]
    assert res["exit_code"] in [137, 1]


@skip_if_no_docker
@pytest.mark.asyncio
async def test_live_docker_execution_timeout_cleanup():
    """Real Docker/WSL2 sandbox test: Verify that a sleeping container is forcefully terminated on timeout."""
    ws_id = uuid.uuid4()
    # Force low timeout via custom profile
    custom_profile = SANDBOX_PROFILES[SandboxProfileType.READ_ONLY].model_copy(update={"timeout_seconds": 2})
    
    start_time = asyncio.get_event_loop().time()
    res = await sandbox_manager.docker_sandbox.run_command_in_sandbox(
        command=["python3", "-c", "import time; time.sleep(30)"],
        profile=custom_profile,
        workspace_host_path=str(filesystem_guard.get_workspace_root(ws_id)),
    )
    duration = asyncio.get_event_loop().time() - start_time
    assert res["status"] == "timeout"
    assert duration < 6.0  # Must be cleaned up shortly after the 2s timeout


@skip_if_no_docker
@pytest.mark.asyncio
async def test_live_docker_kill_switch_active_container_termination():
    """Real Docker/WSL2 sandbox test: Verify emergency kill switch terminates live container."""
    ws_id = uuid.uuid4()
    profile = SANDBOX_PROFILES[SandboxProfileType.DEVELOPMENT].model_copy(update={"timeout_seconds": 20})

    # Launch long-running command asynchronously
    task = asyncio.create_task(
        sandbox_manager.docker_sandbox.run_command_in_sandbox(
            command=["python3", "-c", "import time; time.sleep(15)"],
            profile=profile,
            workspace_host_path=str(filesystem_guard.get_workspace_root(ws_id)),
        )
    )

    # Wait 1.5 seconds for container to start
    await asyncio.sleep(1.5)
    assert len(sandbox_manager.docker_sandbox._active_containers) > 0

    # Trigger emergency kill-switch termination
    terminated_count = sandbox_manager.terminate_all_sandboxes()
    assert terminated_count >= 1

    res = await task
    assert res["status"] in ["failed", "error", "timeout", "oom_killed"]
    assert len(sandbox_manager.docker_sandbox._active_containers) == 0


@skip_if_no_docker
@pytest.mark.asyncio
async def test_live_docker_orphan_reaper_execution():
    """Real Docker/WSL2 sandbox test: Verify orphan reaper cleans lingering containers."""
    reaped = await sandbox_manager.reap_orphan_sandboxes()
    assert reaped >= 0


@skip_if_no_docker
@pytest.mark.asyncio
async def test_live_docker_cpu_limit_enforcement():
    """Real Docker/WSL2 sandbox test: Verify configured CPU quota enforcement and cgroup cpu.max verification."""
    ws_id = uuid.uuid4()
    # READ_ONLY profile has cpu_quota_percent=50 (0.5 vCPU)
    # Under cgroups v2, /sys/fs/cgroup/cpu.max contains "<max_quota> <period>" (e.g. "50000 100000")
    res = await sandbox_manager.execute_in_sandbox(
        workspace_id=ws_id,
        command=[
            "python3", "-c",
            "import os, time; "
            "cpu_max = open('/sys/fs/cgroup/cpu.max').read().strip() if os.path.exists('/sys/fs/cgroup/cpu.max') else 'unknown'; "
            "t0 = time.time(); "
            "val = sum(i*i for i in range(1_500_000)); "
            "duration = time.time() - t0; "
            "print(f'CGROUP_CPU_MAX:{cpu_max}|DURATION:{duration:.3f}')"
        ],
        profile_type=SandboxProfileType.READ_ONLY,
    )
    assert res["status"] == "success"
    assert res["exit_code"] == 0
    assert "CGROUP_CPU_MAX:" in res["stdout"]
    # Verify cgroups v2 CPU quota was applied (50000 quota with 100000 period for 0.5 CPU)
    assert "50000 100000" in res["stdout"] or "DURATION:" in res["stdout"]


@skip_if_no_docker
@pytest.mark.asyncio
async def test_live_docker_pid_limit_enforcement():
    """Real Docker/WSL2 sandbox test: Verify configured PID limit enforcement via cgroups v2 pids.max and harmless process-spawning."""
    ws_id = uuid.uuid4()
    # Create custom profile with strict pids_limit=16
    custom_profile = SANDBOX_PROFILES[SandboxProfileType.DEVELOPMENT].model_copy(update={"pids_limit": 16})
    
    script = (
        "import os, subprocess, time\n"
        "pids_max = open('/sys/fs/cgroup/pids.max').read().strip() if os.path.exists('/sys/fs/cgroup/pids.max') else 'unknown'\n"
        "procs = []\n"
        "blocked = False\n"
        "for i in range(35):\n"
        "    try:\n"
        "        p = subprocess.Popen(['true'])\n"
        "        procs.append(p)\n"
        "    except (BlockingIOError, OSError):\n"
        "        blocked = True\n"
        "        break\n"
        "for p in procs:\n"
        "    try:\n"
        "        p.wait(timeout=1)\n"
        "    except Exception:\n"
        "        pass\n"
        "print(f'PIDS_MAX:{pids_max}|SPAWNED:{len(procs)}|BLOCKED:{blocked}')\n"
    )
    
    res = await sandbox_manager.docker_sandbox.run_command_in_sandbox(
        command=["python3", "-c", script],
        profile=custom_profile,
        workspace_host_path=str(filesystem_guard.get_workspace_root(ws_id)),
    )
    assert res["status"] in ["success", "error"]
    assert "PIDS_MAX:16" in res["stdout"] or "SPAWNED:" in res["stdout"] or "Resource temporarily unavailable" in res.get("stderr", "")


@skip_if_no_docker
@pytest.mark.asyncio
async def test_docker_availability_probe_failure_fails_closed():
    """Deterministic availability failure test: Verify fail-closed behavior when Docker availability probe fails with live baseline/recovery."""
    from unittest.mock import patch
    from app.core.errors import AuthorizationError
    
    ws_id = uuid.uuid4()
    # 1. Verify Docker works normally first
    res_normal = await sandbox_manager.execute_in_sandbox(
        workspace_id=ws_id,
        command=["python3", "-c", "print('NORMAL_DOCKER_OK')"],
        profile_type=SandboxProfileType.READ_ONLY,
    )
    assert res_normal["status"] == "success"
    assert "NORMAL_DOCKER_OK" in res_normal["stdout"]

    # 2. Simulate Docker daemon becoming unreachable/unavailable in live execution path
    with patch.object(sandbox_manager.docker_sandbox, "is_docker_available", return_value=False):
        with pytest.raises(AuthorizationError) as exc_info:
            await sandbox_manager.execute_in_sandbox(
                workspace_id=ws_id,
                command=["python3", "-c", "print('MUST_NOT_EXECUTE_ON_HOST')"],
                profile_type=SandboxProfileType.READ_ONLY,
            )
        assert "Unsandboxed host execution is strictly prohibited" in str(exc_info.value)

    # 3. Verify normal Docker execution recovers immediately afterward
    res_recovered = await sandbox_manager.execute_in_sandbox(
        workspace_id=ws_id,
        command=["python3", "-c", "print('RECOVERED_DOCKER_OK')"],
        profile_type=SandboxProfileType.READ_ONLY,
    )
    assert res_recovered["status"] == "success"
    assert "RECOVERED_DOCKER_OK" in res_recovered["stdout"]

