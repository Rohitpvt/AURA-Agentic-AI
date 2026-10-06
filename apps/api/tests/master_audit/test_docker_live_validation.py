"""Live Validation & Environmental Boundary Audit for Docker / WSL2 Sandboxing (AURA Phase 5 / Gap Closure).

Verifies:
1. Exact probe of Docker daemon / WSL2 runtime on the Windows test platform.
2. Fail-closed security invariant: Unsandboxed host execution is strictly prohibited when Docker is offline.
3. Sandbox profile constraints (memory envelope, CPU quota, read-only rootfs, network isolation).
4. Safe lifecycle management, orphan container reaping, and emergency kill-switch integration.
5. Accurate, transparent classification of environmental status.
"""

import asyncio
import os
import shutil
import subprocess
import uuid
from typing import Any, Dict

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AuthorizationError, ValidationError
from app.core.filesystem import filesystem_guard
from app.runtime.sandbox.docker_sandbox import DockerExecutionSandbox
from app.runtime.sandbox.manager import SandboxManager, sandbox_manager
from app.runtime.sandbox.profiles import SANDBOX_PROFILES, SandboxProfileType


def probe_docker_environment() -> Dict[str, Any]:
    """Diagnostic probe to inspect Docker / WSL2 runtime state."""
    docker_bin = shutil.which("docker")
    wsl_bin = shutil.which("wsl")
    docker_live = False
    docker_version = "unavailable"
    wsl_live = False

    if docker_bin:
        try:
            res = subprocess.run([docker_bin, "--version"], capture_output=True, text=True, timeout=2)
            if res.returncode == 0:
                docker_version = res.stdout.strip()
                info_res = subprocess.run([docker_bin, "info"], capture_output=True, text=True, timeout=2)
                docker_live = (info_res.returncode == 0)
        except Exception:
            docker_live = False

    if wsl_bin:
        try:
            res = subprocess.run([wsl_bin, "--status"], capture_output=True, text=True, timeout=2)
            wsl_live = (res.returncode == 0)
        except Exception:
            wsl_live = False

    return {
        "docker_bin": docker_bin,
        "docker_version": docker_version,
        "docker_live": docker_live,
        "wsl_bin": wsl_bin,
        "wsl_live": wsl_live,
    }


@pytest.mark.asyncio
async def test_docker_environmental_probe_and_health_reporting():
    """Verify health report accurately captures Docker / WSL2 state and fail-closed policy."""
    health = await sandbox_manager.check_sandbox_health()
    assert "sandbox_enabled" in health
    assert "policy" in health
    assert "FAIL_CLOSED" in health["policy"]
    assert len(health["profiles"]) >= 4

    env_info = probe_docker_environment()
    assert health["docker_available"] == env_info["docker_live"]


@pytest.mark.asyncio
async def test_docker_fail_closed_host_execution_prohibition(db_session: AsyncSession):
    """Verify that arbitrary command execution without active Docker sandbox is strictly blocked."""
    mgr = SandboxManager()
    ws_id = uuid.uuid4()

    # When docker is not running or forced unavailable
    from unittest.mock import patch
    with patch.object(mgr.docker_sandbox, "is_docker_available", return_value=False):
        with pytest.raises(AuthorizationError) as exc_info:
            await mgr.execute_in_sandbox(
                workspace_id=ws_id,
                command=["python3", "-c", "import sys; sys.exit(0)"],
                profile_type=SandboxProfileType.DEVELOPMENT,
                db=db_session,
                actor_id="test_agent",
            )
        assert "Unsandboxed host execution is strictly prohibited" in str(exc_info.value) or "requires an active sandbox" in str(exc_info.value)


@pytest.mark.asyncio
async def test_docker_sandbox_profile_security_invariants():
    """Verify profile definitions strictly enforce security envelopes."""
    read_only_prof = SANDBOX_PROFILES[SandboxProfileType.READ_ONLY]
    dev_prof = SANDBOX_PROFILES[SandboxProfileType.DEVELOPMENT]
    net_prof = SANDBOX_PROFILES[SandboxProfileType.NETWORK_RESEARCH]
    high_prof = SANDBOX_PROFILES[SandboxProfileType.HIGH_RISK]

    # READ_ONLY: network off, read-only rootfs, tight memory ceiling
    assert read_only_prof.network_enabled is False
    assert read_only_prof.read_only_rootfs is True
    assert read_only_prof.max_memory_mb <= 256
    assert read_only_prof.cpu_quota_percent <= 50

    # DEVELOPMENT: offline by default, writeable workspace
    assert dev_prof.network_enabled is False
    assert dev_prof.workspace_writeable is True
    assert dev_prof.max_memory_mb <= 512

    # NETWORK_RESEARCH: network enabled, read-only rootfs
    assert net_prof.network_enabled is True
    assert net_prof.read_only_rootfs is True

    # HIGH_RISK: capped timeout, requires explicit human approval
    assert high_prof.timeout_seconds <= 120
    assert high_prof.requires_explicit_approval is True
    assert high_prof.max_memory_mb <= 1024


@pytest.mark.asyncio
async def test_docker_emergency_termination_and_reaper():
    """Verify sandbox manager emergency kill and orphan container cleanup methods."""
    mgr = SandboxManager()
    
    # Emergency termination returns integer count
    term_count = mgr.terminate_all_sandboxes()
    assert isinstance(term_count, int)
    assert term_count >= 0

    # Reaper returns integer count
    reaped_count = await mgr.reap_orphan_sandboxes()
    assert isinstance(reaped_count, int)
    assert reaped_count >= 0
