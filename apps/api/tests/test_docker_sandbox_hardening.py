"""Comprehensive Tests for Production Docker / WSL2 Sandbox Operational Hardening (AURA-506).

Verification Categories:
1. Fail-Closed Contract & Host Execution Fallback Prevention.
2. Multi-Tenant Workspace Filesystem Boundary & Traversal Defense.
3. Network Policy Isolation & SSRF Defense Guard.
4. Container Security Flags, Profiles, and Resource Constraints.
5. Process Lifecycle, Timeout Handling, Output Bounding, and OOM Detection.
6. Kill-Switch Integration and Orphan Container Reaping.
7. OpenTelemetry Tracing and SHA-256 Cryptographic Audit Ledger Integration.
"""

import asyncio
from pathlib import Path
import time
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AuthorizationError, ValidationError
from app.core.filesystem import filesystem_guard
from app.core.network import ssrf_guard
from app.core.telemetry import telemetry_manager
from app.db.models.audit import AuditLog
from app.runtime.sandbox.docker_sandbox import DockerExecutionSandbox, MAX_OUTPUT_BYTES
from app.runtime.sandbox.manager import sandbox_manager
from app.runtime.sandbox.profiles import SANDBOX_PROFILES, SandboxProfile, SandboxProfileType
from app.services.audit_service import audit_service
from app.services.kill_switch import kill_switch


@pytest.fixture(autouse=True)
def clean_telemetry():
    """Ensure in-memory telemetry is cleared before and after each test."""
    telemetry_manager.clear_in_memory_spans()
    yield
    telemetry_manager.clear_in_memory_spans()


# ==============================================================================
# 1. FAIL-CLOSED CONTRACT TESTS
# ==============================================================================

@pytest.mark.asyncio
async def test_fail_closed_when_docker_binary_unavailable():
    """Verify execution fails closed with AuthorizationError when Docker is not installed."""
    with patch.object(DockerExecutionSandbox, "is_docker_available", return_value=False):
        with pytest.raises(AuthorizationError) as exc_info:
            await sandbox_manager.execute_in_sandbox(
                workspace_id=uuid.uuid4(),
                command=["python3", "-c", "print('hello')"],
                profile_type=SandboxProfileType.DEVELOPMENT,
            )
        assert "Unsandboxed host execution is strictly prohibited" in str(exc_info.value)


@pytest.mark.asyncio
async def test_fail_closed_when_sandbox_disabled_in_config():
    """Verify execution fails closed with AuthorizationError when SANDBOX_ENABLED is False."""
    with patch.object(settings, "SANDBOX_ENABLED", False):
        with pytest.raises(AuthorizationError) as exc_info:
            await sandbox_manager.execute_in_sandbox(
                workspace_id=uuid.uuid4(),
                command=["echo", "untrusted"],
                profile_type=SandboxProfileType.READ_ONLY,
            )
        assert "Arbitrary code execution requires an active sandbox" in str(exc_info.value)


@pytest.mark.asyncio
async def test_invalid_sandbox_profile_rejected():
    """Verify requesting an invalid/unknown sandbox profile raises ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        await sandbox_manager.execute_in_sandbox(
            workspace_id=uuid.uuid4(),
            command=["echo", "test"],
            profile_type="invalid_profile_type",  # type: ignore
        )
    assert "Unknown sandbox profile type" in str(exc_info.value)


# ==============================================================================
# 2. MULTI-TENANT WORKSPACE FILESYSTEM BOUNDARY & TRAVERSAL TESTS
# ==============================================================================

def test_workspace_filesystem_boundary_multi_tenant_isolation():
    """Verify that Workspace A cannot access Workspace B or host filesystem paths."""
    ws_a = uuid.uuid4()
    ws_b = uuid.uuid4()

    ws_a_root = filesystem_guard.get_workspace_root(ws_a)
    ws_b_root = filesystem_guard.get_workspace_root(ws_b)

    assert ws_a_root != ws_b_root
    assert ws_a_root.exists()
    assert ws_b_root.exists()

    # Valid file in Workspace A
    safe_file_a = filesystem_guard.validate_and_resolve_path(ws_a, "data/output.json")
    assert str(safe_file_a).startswith(str(ws_a_root))

    # Cross-workspace breakout attempt from Workspace A targeting Workspace B
    with pytest.raises(AuthorizationError):
        filesystem_guard.validate_and_resolve_path(ws_a, f"../{ws_b}/secret.txt")

    # Host root breakout attempt
    with pytest.raises(AuthorizationError):
        filesystem_guard.validate_and_resolve_path(ws_a, "../../../../../Windows/System32/config/SAM")


def test_filesystem_guard_rejects_dangerous_patterns():
    """Verify that UNC network shares, drive letters, and null bytes are rejected."""
    ws_id = uuid.uuid4()

    # UNC path
    with pytest.raises(AuthorizationError):
        filesystem_guard.validate_and_resolve_path(ws_id, "\\\\attacker.share\\payload.exe")

    # Windows Drive letter
    with pytest.raises(AuthorizationError):
        filesystem_guard.validate_and_resolve_path(ws_id, "C:\\Users\\Administrator\\secrets.txt")

    # Null byte injection
    with pytest.raises(ValidationError):
        filesystem_guard.validate_and_resolve_path(ws_id, "safe_file.txt\x00.exe")


# ==============================================================================
# 3. NETWORK POLICY ISOLATION & SSRF DEFENSE TESTS
# ==============================================================================

def test_sandbox_profile_network_isolation_policies():
    """Verify network isolation flags across all sandbox profile specifications."""
    read_only = SANDBOX_PROFILES[SandboxProfileType.READ_ONLY]
    development = SANDBOX_PROFILES[SandboxProfileType.DEVELOPMENT]
    research = SANDBOX_PROFILES[SandboxProfileType.NETWORK_RESEARCH]
    high_risk = SANDBOX_PROFILES[SandboxProfileType.HIGH_RISK]

    # Offline profiles
    assert read_only.network_enabled is False
    assert development.network_enabled is False

    # Controlled online profiles
    assert research.network_enabled is True
    assert high_risk.network_enabled is True


def test_ssrf_guard_blocks_private_and_metadata_targets():
    """Verify that SSRF guard blocks localhost, loopback, private RFC 1918, and AWS metadata."""
    # Loopback targets
    with pytest.raises(AuthorizationError):
        ssrf_guard.validate_url("http://127.0.0.1:8000/api/v1/keys")

    with pytest.raises(AuthorizationError):
        ssrf_guard.validate_url("http://localhost:3000")

    # Cloud metadata target
    with pytest.raises(AuthorizationError):
        ssrf_guard.validate_url("http://169.254.169.254/latest/meta-data/")

    # Private network ranges
    with pytest.raises(AuthorizationError):
        ssrf_guard.validate_url("http://10.0.0.5:9000/admin")

    with pytest.raises(AuthorizationError):
        ssrf_guard.validate_url("http://192.168.1.1/router")

    # Dangerous URL schemes
    with pytest.raises(AuthorizationError):
        ssrf_guard.validate_url("file:///etc/passwd")

    with pytest.raises(AuthorizationError):
        ssrf_guard.validate_url("gopher://127.0.0.1:6379")


# ==============================================================================
# 4. CONTAINER SECURITY FLAGS & RESOURCE CONSTRAINTS
# ==============================================================================

@pytest.mark.asyncio
async def test_docker_sandbox_argument_construction():
    """Verify that DockerExecutionSandbox constructs secure arguments with all hardening flags."""
    sandbox = DockerExecutionSandbox()
    profile = SANDBOX_PROFILES[SandboxProfileType.DEVELOPMENT]

    with patch.object(sandbox, "is_docker_available", return_value=True):
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.communicate.return_value = (b"hello sandbox\n", b"")
            mock_exec.return_value = mock_proc

            res = await sandbox.run_command_in_sandbox(
                command=["python3", "-c", "print('hello')"],
                profile=profile,
                workspace_host_path="/tmp/aura_ws_test",
                env_vars={"SAFE_VAR": "value123"},
            )

            assert res["status"] == "success"
            assert "hello sandbox" in res["stdout"]

            # Inspect constructed docker args
            called_args = list(mock_exec.call_args[0])
            assert "run" in called_args
            assert "--security-opt" in called_args
            assert "no-new-privileges" in called_args
            assert "--rm" in called_args
            assert "--read-only" in called_args
            assert "--tmpfs" in called_args
            assert "--cap-drop" in called_args
            assert "ALL" in called_args
            assert "--network" in called_args
            assert "none" in called_args  # Development profile is offline
            assert "--memory" in called_args
            assert "512m" in called_args
            assert "--pids-limit" in called_args
            assert "64" in called_args
            assert "-v" in called_args
            assert "/tmp/aura_ws_test:/workspace:rw" in called_args


# ==============================================================================
# 5. PROCESS LIFECYCLE, TIMEOUT, OUTPUT BOUNDS & OOM HANDLING
# ==============================================================================

@pytest.mark.asyncio
async def test_docker_sandbox_timeout_handling():
    """Verify that a timeout triggers force-kill cleanup and returns status 'timeout'."""
    sandbox = DockerExecutionSandbox()
    profile = SANDBOX_PROFILES[SandboxProfileType.READ_ONLY]

    with patch.object(sandbox, "is_docker_available", return_value=True):
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.communicate.side_effect = asyncio.TimeoutError()
            mock_exec.return_value = mock_proc

            with patch.object(sandbox, "terminate_container", return_value=True) as mock_term:
                res = await sandbox.run_command_in_sandbox(
                    command=["sleep", "100"],
                    profile=profile,
                    workspace_host_path="/tmp/test",
                )

                assert res["status"] == "timeout"
                assert res["exit_code"] == -1
                assert "timed out" in res["stderr"]
                mock_term.assert_called_once()


@pytest.mark.asyncio
async def test_docker_sandbox_oom_termination_detection():
    """Verify that an exit code of 137 is correctly identified as OOM termination."""
    sandbox = DockerExecutionSandbox()
    profile = SANDBOX_PROFILES[SandboxProfileType.DEVELOPMENT]

    with patch.object(sandbox, "is_docker_available", return_value=True):
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.returncode = 137
            mock_proc.communicate.return_value = (b"", b"Killed")
            mock_exec.return_value = mock_proc

            res = await sandbox.run_command_in_sandbox(
                command=["python3", "-c", "a = 'x' * 10**9"],
                profile=profile,
                workspace_host_path="/tmp/test",
            )

            assert res["status"] == "oom_killed"
            assert res["exit_code"] == 137
            assert "OOM killer" in res["stderr"]


@pytest.mark.asyncio
async def test_docker_sandbox_output_buffer_truncation():
    """Verify that stdout/stderr exceeding MAX_OUTPUT_BYTES is safely truncated."""
    sandbox = DockerExecutionSandbox()
    profile = SANDBOX_PROFILES[SandboxProfileType.DEVELOPMENT]
    huge_output = b"A" * (MAX_OUTPUT_BYTES + 2048)

    with patch.object(sandbox, "is_docker_available", return_value=True):
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.communicate.return_value = (huge_output, b"")
            mock_exec.return_value = mock_proc

            res = await sandbox.run_command_in_sandbox(
                command=["cat", "/dev/zero"],
                profile=profile,
                workspace_host_path="/tmp/test",
            )

            assert res["status"] == "success"
            assert res["truncated"] is True
            assert len(res["stdout"].encode("utf-8")) <= MAX_OUTPUT_BYTES + 100
            assert "[AURA_SANDBOX_OUTPUT_TRUNCATED]" in res["stdout"]


# ==============================================================================
# 6. KILL-SWITCH INTEGRATION & ORPHAN CONTAINER REAPING
# ==============================================================================

def test_kill_switch_terminates_all_active_sandboxes():
    """Verify that kill switch triggers emergency termination of active sandbox containers."""
    sandbox = sandbox_manager.docker_sandbox
    sandbox._active_containers.add("aura_sbx_mock_container_1")
    sandbox._active_containers.add("aura_sbx_mock_container_2")

    with patch("subprocess.run") as mock_run:
        terminated_count = sandbox_manager.terminate_all_sandboxes()
        assert len(sandbox._active_containers) == 0
        if sandbox._docker_bin:
            assert terminated_count == 2


@pytest.mark.asyncio
async def test_orphan_sandbox_reaper():
    """Verify that orphan container reaper queries and cleans lingering containers."""
    sandbox = DockerExecutionSandbox()

    with patch.object(sandbox, "is_docker_available", return_value=True):
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            # First call: ps list; Second call: rm -f
            proc_ps = AsyncMock()
            proc_ps.communicate.return_value = (b"aura_sbx_123 aura_sbx_456\n", b"")
            proc_rm = AsyncMock()
            proc_rm.communicate.return_value = (b"", b"")

            mock_exec.side_effect = [proc_ps, proc_rm]

            reaped = await sandbox.reap_orphans()
            assert reaped == 2


# ==============================================================================
# 7. OPENTELEMETRY & AUDIT LEDGER INTEGRATION
# ==============================================================================

@pytest.mark.asyncio
async def test_sandbox_execution_emits_telemetry_span_and_audit_record(db_session: AsyncSession):
    """Verify that sandboxed command execution creates an OpenTelemetry span and audit record."""
    ws_id = uuid.uuid4()
    profile = SandboxProfileType.DEVELOPMENT

    with patch.object(DockerExecutionSandbox, "is_docker_available", return_value=True):
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.communicate.return_value = (b"execution complete", b"")
            mock_exec.return_value = mock_proc

            res = await sandbox_manager.execute_in_sandbox(
                workspace_id=ws_id,
                command=["pytest", "--version"],
                profile_type=profile,
                db=db_session,
                actor_id="test_runner",
            )

            assert res["status"] == "success"

            # 1. Verify OpenTelemetry span
            spans = telemetry_manager.get_in_memory_spans()
            sbx_span = next((s for s in spans if "sandbox.execute" in s.name), None)
            assert sbx_span is not None
            assert sbx_span.attributes.get("aura.sandbox_profile") == "development"
            assert sbx_span.attributes.get("aura.workspace_id") == str(ws_id)
            assert sbx_span.attributes.get("aura.status") == "success"

            # 2. Verify Audit Record
            audit_res = await db_session.execute(
                select(AuditLog).where(AuditLog.workspace_id == ws_id)
            )
            audit_logs = audit_res.scalars().all()
            assert len(audit_logs) >= 1
            sbx_audit = next((a for a in audit_logs if a.action == "sandbox.command_executed"), None)
            assert sbx_audit is not None
            assert sbx_audit.details.get("profile") == "development"
            assert sbx_audit.details.get("status") == "success"

            # 3. Verify Audit Chain Integrity
            verify_res = await audit_service.verify_ledger(db_session, ws_id)
            assert verify_res["is_valid"] is True
