"""Sandbox Manager and Host Execution Boundary Coordinator.

Enforces:
- Deterministic Host Execution Policy: Unsandboxed host execution is strictly prohibited for arbitrary code/shell tools.
- Fail-Closed Behavior: If secure container sandbox is unavailable on the host, sensitive tools fail closed.
- Automatic Profile Selection: Chooses profile (READ_ONLY, DEVELOPMENT, NETWORK_RESEARCH, HIGH_RISK) based on tool classification.
- Workspace Filesystem Boundary: Mounts only the validated workspace subdirectory.
- Telemetry & Audit Correlation: Emits OpenTelemetry spans with sanitized attributes and immutable SHA-256 audit records.
"""

from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Union
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AuthorizationError, ValidationError
from app.core.filesystem import filesystem_guard
from app.core.logging import logger
from app.core.redaction import secret_redactor
from app.core.telemetry import telemetry_manager
from app.runtime.sandbox.docker_sandbox import DockerExecutionSandbox
from app.runtime.sandbox.profiles import SANDBOX_PROFILES, SandboxProfile, SandboxProfileType


class SandboxManager:
    """Coordinates sandboxed code/command execution across AURA."""

    def __init__(self):
        self.docker_sandbox = DockerExecutionSandbox()

    async def check_sandbox_health(self) -> Dict[str, Any]:
        """Check if container sandbox environment is active and healthy."""
        docker_ready = await self.docker_sandbox.is_docker_available()
        return {
            "sandbox_enabled": settings.SANDBOX_ENABLED,
            "runtime": settings.SANDBOX_RUNTIME,
            "docker_available": docker_ready,
            "status": "ready" if (settings.SANDBOX_ENABLED and docker_ready) else "degraded",
            "policy": "FAIL_CLOSED (Unsandboxed host execution prohibited)",
            "profiles": list(SANDBOX_PROFILES.keys()),
        }

    async def execute_in_sandbox(
        self,
        workspace_id: Union[str, uuid.UUID],
        command: List[str],
        profile_type: SandboxProfileType = SandboxProfileType.DEVELOPMENT,
        env_vars: Optional[Dict[str, str]] = None,
        image_name: Optional[str] = None,
        db: Optional[AsyncSession] = None,
        actor_id: str = "system",
        actor_type: str = "agent",
    ) -> Dict[str, Any]:
        """Execute a structured command inside the selected sandbox profile.

        Raises AuthorizationError if sandboxing is bypassed or unavailable.
        """
        # 1. Enforce Sandbox Policy
        if not settings.SANDBOX_ENABLED:
            logger.error("SandboxManager: Sandboxing is disabled in config. Host execution is prohibited.")
            if db:
                from app.services.audit_service import audit_service
                ws_uuid = workspace_id if isinstance(workspace_id, uuid.UUID) else uuid.UUID(str(workspace_id))
                await audit_service.record_event(
                    db=db,
                    workspace_id=ws_uuid,
                    actor_type=actor_type,
                    actor_id=actor_id,
                    action="sandbox.rejected_disabled",
                    resource_type="sandbox",
                    resource_id="host_policy",
                    details={"reason": "Sandboxing disabled in configuration"},
                )
            raise AuthorizationError("Host execution disabled: Arbitrary code execution requires an active sandbox.")

        # 2. Resolve Profile
        profile = SANDBOX_PROFILES.get(profile_type)
        if not profile:
            raise ValidationError(f"Unknown sandbox profile type: '{profile_type}'")

        # 3. Resolve Workspace Directory Path
        ws_root = filesystem_guard.get_workspace_root(workspace_id)
        ws_host_path = str(ws_root.absolute())

        # 4. Filter and Sanitize Environment Variables
        safe_env = {}
        if env_vars:
            for k, v in env_vars.items():
                if k.lower() not in secret_redactor.SENSITIVE_KEY_NAMES:
                    safe_env[k] = v

        ws_str = str(workspace_id)

        # 5. Execute in Sandbox with OpenTelemetry Span
        async with telemetry_manager.start_async_span(
            name=f"sandbox.execute {profile.profile_type.value}",
            span_type="sandbox",
            attributes={
                "aura.sandbox_profile": profile.profile_type.value,
                "aura.workspace_id": ws_str,
                "aura.actor_id": actor_id,
                "aura.actor_type": actor_type,
                "aura.network_enabled": profile.network_enabled,
                "aura.read_only_rootfs": profile.read_only_rootfs,
                "aura.max_memory_mb": profile.max_memory_mb,
                "aura.cpu_quota_percent": profile.cpu_quota_percent,
                "aura.command_bin": command[0] if command else "unknown",
            },
        ) as span:
            try:
                result = await self.docker_sandbox.run_command_in_sandbox(
                    command=command,
                    profile=profile,
                    workspace_host_path=ws_host_path,
                    env_vars=safe_env,
                    image_name=image_name,
                )

                span.set_attribute("aura.exit_code", result.get("exit_code", -1))
                span.set_attribute("aura.status", result.get("status", "unknown"))
                span.set_attribute("aura.duration_ms", result.get("duration_ms", 0.0))

                # 6. Audit Trail Logging (if db session provided)
                if db:
                    from app.services.audit_service import audit_service
                    ws_uuid = workspace_id if isinstance(workspace_id, uuid.UUID) else uuid.UUID(ws_str)
                    audit_details = {
                        "profile": profile.profile_type.value,
                        "container_name": result.get("container_name"),
                        "exit_code": result.get("exit_code"),
                        "status": result.get("status"),
                        "duration_ms": result.get("duration_ms"),
                        "command_bin": command[0] if command else "unknown",
                    }
                    active_trace_id = telemetry_manager.get_current_trace_id()
                    if active_trace_id:
                        audit_details["trace_id"] = active_trace_id

                    await audit_service.record_event(
                        db=db,
                        workspace_id=ws_uuid,
                        actor_type=actor_type,
                        actor_id=actor_id,
                        action="sandbox.command_executed",
                        resource_type="sandbox",
                        resource_id=result.get("container_name") or "ephemeral_container",
                        details=audit_details,
                    )

                return result

            except AuthorizationError as auth_err:
                span.set_attribute("aura.status", "fail_closed")
                if db:
                    from app.services.audit_service import audit_service
                    ws_uuid = workspace_id if isinstance(workspace_id, uuid.UUID) else uuid.UUID(ws_str)
                    await audit_service.record_event(
                        db=db,
                        workspace_id=ws_uuid,
                        actor_type=actor_type,
                        actor_id=actor_id,
                        action="sandbox.fail_closed_rejected",
                        resource_type="sandbox",
                        resource_id="docker_runtime",
                        details={"error": str(auth_err), "profile": profile.profile_type.value},
                    )
                raise

    def terminate_all_sandboxes(self) -> int:
        """Emergency cleanup of any active sandbox containers."""
        logger.info("SandboxManager: Emergency termination requested for all active sandboxes")
        return self.docker_sandbox.terminate_all_containers()

    async def reap_orphan_sandboxes(self) -> int:
        """Reap any orphaned containers left from previous executions."""
        return await self.docker_sandbox.reap_orphans()


sandbox_manager = SandboxManager()
