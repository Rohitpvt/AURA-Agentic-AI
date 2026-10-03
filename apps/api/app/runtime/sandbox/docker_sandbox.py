"""Docker-based Ephemeral Container Execution Sandbox."""

import asyncio
import json
import shutil
import time
from typing import Any, Dict, List, Optional, Set
import uuid

from app.core.config import settings
from app.core.errors import AuthorizationError, ValidationError
from app.core.logging import logger
from app.runtime.sandbox.profiles import SandboxProfile, SandboxProfileType


# Maximum allowed output size in bytes (512 KB) to prevent memory exhaustion
MAX_OUTPUT_BYTES = 512 * 1024


class DockerExecutionSandbox:
    """Manages ephemeral Docker containers for executing code and shell commands in isolation."""

    def __init__(self):
        self._docker_bin: Optional[str] = shutil.which("docker")
        self._active_containers: Set[str] = set()

    async def is_docker_available(self) -> bool:
        """Check if Docker CLI and daemon are reachable."""
        # Refresh binary location in case it was installed/added to PATH
        self._docker_bin = shutil.which("docker")
        if not self._docker_bin:
            return False
        try:
            proc = await asyncio.create_subprocess_exec(
                self._docker_bin, "info",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=3.0)
            return proc.returncode == 0
        except Exception:
            return False

    async def run_command_in_sandbox(
        self,
        command: List[str],
        profile: SandboxProfile,
        workspace_host_path: str,
        env_vars: Optional[Dict[str, str]] = None,
        image_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute a structured command inside an isolated ephemeral Docker container.

        Enforces:
        - fail-closed validation (prohibits unsandboxed host fallback)
        - ephemeral container lifecycle (--rm)
        - read-only rootfs (--read-only with ephemeral /tmp tmpfs)
        - dropped capabilities (--cap-drop ALL)
        - memory, CPU, and PID limits
        - no privileged mode (--security-opt no-new-privileges)
        - network isolation (--network none or bridge)
        - volume mount strictly scoped to workspace
        - execution timeout
        - bounded output capture
        """
        if not await self.is_docker_available():
            logger.error("DockerSandbox: Docker daemon is not running or unavailable. Fails closed.")
            raise AuthorizationError("Secure sandbox unavailable: Unsandboxed host execution is strictly prohibited.")

        container_name = f"aura_sbx_{uuid.uuid4().hex[:12]}"
        target_image = image_name or settings.SANDBOX_DEFAULT_IMAGE
        target_timeout = profile.timeout_seconds or settings.SANDBOX_TIMEOUT_SECONDS

        # Build docker run arguments
        docker_args = [
            self._docker_bin, "run",
            "--name", container_name,
            "--rm",
            "--interactive",
            "--security-opt", "no-new-privileges",
            "--label", "aura.managed=true",
            "--label", f"aura.profile={profile.profile_type.value}",
            "--pids-limit", str(profile.pids_limit),
            "--memory", f"{profile.max_memory_mb}m",
            "--memory-swap", f"{profile.max_memory_mb}m",
            "--cpus", str(profile.cpu_quota_percent / 100.0),
        ]

        # Capabilities
        for cap in profile.drop_capabilities:
            docker_args.extend(["--cap-drop", cap])

        # Network
        if profile.network_enabled:
            docker_args.extend(["--network", "bridge"])
        else:
            docker_args.extend(["--network", "none"])

        # Read-only root filesystem
        if profile.read_only_rootfs:
            docker_args.append("--read-only")
            # Provide strictly bounded ephemeral /tmp
            docker_args.extend(["--tmpfs", "/tmp:rw,noexec,nosuid,size=64m"])

        # Workspace mount
        mount_mode = "rw" if profile.workspace_writeable else "ro"
        docker_args.extend(["-v", f"{workspace_host_path}:/workspace:{mount_mode}"])
        docker_args.extend(["-w", "/workspace"])

        # Environment variables (sanitized)
        if env_vars:
            for k, v in env_vars.items():
                docker_args.extend(["-e", f"{k}={v}"])

        # Image & Command
        docker_args.append(target_image)
        docker_args.extend(command)

        start_time = time.perf_counter()
        logger.info(f"DockerSandbox: Spawning container {container_name} (Profile: {profile.profile_type.value})")

        # Track active container
        self._active_containers.add(container_name)

        try:
            proc = await asyncio.create_subprocess_exec(
                *docker_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=float(target_timeout)
            )
            duration_ms = (time.perf_counter() - start_time) * 1000.0

            # Bounded output truncation
            truncated = False
            if len(stdout_bytes) > MAX_OUTPUT_BYTES:
                stdout_bytes = stdout_bytes[:MAX_OUTPUT_BYTES]
                truncated = True
            if len(stderr_bytes) > MAX_OUTPUT_BYTES:
                stderr_bytes = stderr_bytes[:MAX_OUTPUT_BYTES]
                truncated = True

            stdout_str = stdout_bytes.decode("utf-8", errors="replace")
            stderr_str = stderr_bytes.decode("utf-8", errors="replace")
            if truncated:
                stdout_str += "\n[AURA_SANDBOX_OUTPUT_TRUNCATED]"

            # Categorize exit code
            status = "success" if proc.returncode == 0 else "error"
            if proc.returncode == 137:
                status = "oom_killed"
                stderr_str = (stderr_str + "\nContainer terminated by OOM killer (exit code 137)").strip()

            return {
                "exit_code": proc.returncode,
                "stdout": stdout_str,
                "stderr": stderr_str,
                "duration_ms": round(duration_ms, 2),
                "status": status,
                "container_name": container_name,
                "profile": profile.profile_type.value,
                "truncated": truncated,
                "is_untrusted_content": True,
            }

        except asyncio.TimeoutError:
            logger.warning(f"DockerSandbox: Container {container_name} timed out after {target_timeout}s; killing")
            await self.terminate_container(container_name)
            return {
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Execution timed out after {target_timeout} seconds",
                "duration_ms": round(target_timeout * 1000.0, 2),
                "status": "timeout",
                "container_name": container_name,
                "profile": profile.profile_type.value,
                "truncated": False,
                "is_untrusted_content": True,
            }
        except Exception as e:
            logger.error(f"DockerSandbox: Unexpected failure in container execution: {e}")
            return {
                "exit_code": -1,
                "stdout": "",
                "stderr": str(e),
                "duration_ms": round((time.perf_counter() - start_time) * 1000.0, 2),
                "status": "failed",
                "container_name": container_name,
                "profile": profile.profile_type.value,
                "truncated": False,
                "is_untrusted_content": True,
            }
        finally:
            self._active_containers.discard(container_name)

    async def terminate_container(self, container_name: str) -> bool:
        """Forcefully terminate and remove a container by name."""
        if not self._docker_bin:
            return False
        try:
            kill_proc = await asyncio.create_subprocess_exec(
                self._docker_bin, "rm", "-f", container_name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(kill_proc.communicate(), timeout=5.0)
            return kill_proc.returncode == 0
        except Exception as e:
            logger.warning(f"DockerSandbox: Failed to terminate container {container_name}: {e}")
            return False

    def terminate_all_containers(self) -> int:
        """Synchronously kill and remove all active containers tracked in this process."""
        if not self._docker_bin or not self._active_containers:
            self._active_containers.clear()
            return 0

        import subprocess
        count = 0
        for container_name in list(self._active_containers):
            try:
                subprocess.run(
                    [self._docker_bin, "rm", "-f", container_name],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                )
                count += 1
            except Exception:
                pass
        self._active_containers.clear()
        return count

    async def reap_orphans(self) -> int:
        """Reap any orphaned AURA sandbox containers still lingering on the host."""
        if not await self.is_docker_available():
            return 0
        try:
            proc = await asyncio.create_subprocess_exec(
                self._docker_bin, "ps", "-aq", "--filter", "label=aura.managed=true",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
            container_ids = stdout.decode().strip().split()
            if not container_ids:
                return 0

            reap_proc = await asyncio.create_subprocess_exec(
                self._docker_bin, "rm", "-f", *container_ids,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(reap_proc.communicate(), timeout=10.0)
            logger.info(f"DockerSandbox: Reaped {len(container_ids)} orphaned sandbox container(s)")
            return len(container_ids)
        except Exception as e:
            logger.warning(f"DockerSandbox: Orphan reaper failed: {e}")
            return 0
