"""AURA-902 Execution Adapter Interfaces, Windows Native Adapter & Safe Mocks.

Defines:
1. BaseOSExecutionAdapter: The abstract boundary receiving only already-validated actions
2. WindowsOSExecutionAdapter: Native Windows execution adapter for application launch, inspection, and termination
3. SafeMockOSExecutionAdapter: Deterministic simulation adapter for safety testing and readiness probes
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import asyncio
import os
import subprocess
import time
from typing import Any, Dict, List, Optional
import psutil

from app.core.logging import logger
from app.services.os_guard.app_registry import application_registry
from app.services.os_guard.process_service import process_service
from app.services.os_guard.types import OSActionRequest, OSActionType


class BaseOSExecutionAdapter(ABC):
    """Abstract Base Execution Adapter.
    
    Receives only already-validated, policy-authorized actions.
    Has no public unsafe execution methods.
    """

    @abstractmethod
    async def execute_validated_action(self, action: OSActionRequest) -> Dict[str, Any]:
        """Execute the validated action on the host platform."""
        pass


class WindowsOSExecutionAdapter(BaseOSExecutionAdapter):
    """Native Windows Execution Adapter executing governed host operations."""

    async def execute_validated_action(self, action: OSActionRequest) -> Dict[str, Any]:
        """Execute validated OS action on Windows."""
        if action.action_type == OSActionType.APPLICATION_LAUNCH:
            return await self._execute_application_launch(action)
        elif action.action_type == OSActionType.PROCESS_TERMINATE:
            return await self._execute_process_terminate(action)
        elif action.action_type in (OSActionType.READ_ONLY, OSActionType.SYSTEM_TELEMETRY):
            return await self._execute_inspection_or_telemetry(action)
        else:
            raise NotImplementedError(f"Action type '{action.action_type.value}' is not implemented in WindowsOSExecutionAdapter.")

    async def _execute_application_launch(self, action: OSActionRequest) -> Dict[str, Any]:
        """Launch an allowlisted Windows application with sanitized arguments."""
        app_id = str(
            action.parameters.get("application_id")
            or action.parameters.get("app_id")
            or action.parameters.get("target")
            or ""
        ).strip().lower()
        args = action.parameters.get("arguments") or action.parameters.get("args") or []
        working_dir = action.parameters.get("working_directory") or action.parameters.get("cwd")
        workspace_root = action.parameters.get("workspace_root")

        # 1. Validate Launch Request via Application Registry
        is_valid, err, app_def, clean_args, clean_wd = application_registry.validate_launch_request(
            application_id=app_id,
            arguments=args,
            working_directory=working_dir,
            workspace_root=workspace_root,
        )
        if not is_valid or not app_def:
            raise ValueError(f"Application launch validation failed: {err}")

        # 2. Check that the canonical executable exists on disk
        if not os.path.exists(app_def.canonical_executable_path):
            raise FileNotFoundError(f"Allowlisted executable not found on host: {app_def.canonical_executable_path}")

        # 3. Construct Clean Subprocess Argument Array (shell=False)
        cmd_array = [app_def.canonical_executable_path] + clean_args

        # 4. Prepare Clean Environment (Sanitize secret environment variables)
        clean_env = os.environ.copy()
        sensitive_env_keys = [
            "AURA_SECRET_KEY",
            "AURA_MASTER_ENCRYPTION_KEY",
            "DATABASE_URL",
            "GEMINI_API_KEY",
            "TELEGRAM_BOT_TOKEN",
        ]
        for s_key in sensitive_env_keys:
            clean_env.pop(s_key, None)

        t_start = time.time()
        logger.info(f"WindowsOSExecutionAdapter: Spawning allowlisted application '{app_def.application_id}' (args: {clean_args})")

        # 5. Spawn Process
        proc = subprocess.Popen(
            cmd_array,
            cwd=clean_wd,
            env=clean_env,
            shell=False,
        )

        # 6. Capture create_time from psutil
        create_time = 0.0
        try:
            p_obj = psutil.Process(proc.pid)
            create_time = p_obj.create_time()
        except Exception:
            create_time = time.time()

        return {
            "status": "success",
            "application_id": app_def.application_id,
            "display_name": app_def.display_name,
            "executable_path": app_def.canonical_executable_path,
            "pid": proc.pid,
            "create_time": create_time,
            "start_timestamp": t_start,
            "arguments": clean_args,
            "working_directory": clean_wd,
        }

    async def _execute_process_terminate(self, action: OSActionRequest) -> Dict[str, Any]:
        """Terminate a specific validated process."""
        pid = int(action.parameters.get("pid", 0))
        expected_create_time = float(action.parameters.get("expected_create_time", 0.0))
        expected_name = str(action.parameters.get("expected_name", ""))

        result = process_service.terminate_process(
            pid=pid,
            expected_create_time=expected_create_time,
            expected_name=expected_name,
        )

        if result.get("outcome") not in ("TERMINATED", "ALREADY_EXITED"):
            err_msg = result.get("error") or f"Termination failed with outcome '{result.get('outcome')}'"
            raise RuntimeError(err_msg)

        return result

    async def _execute_inspection_or_telemetry(self, action: OSActionRequest) -> Dict[str, Any]:
        """Inspect processes or retrieve system telemetry."""
        params = action.parameters

        # If process inspection query
        if "inspect_processes" in params or "filter_name" in params or "pid" in params or action.parameters.get("query_type") == "processes":
            filter_name = params.get("filter_name")
            pid = params.get("pid")
            limit = int(params.get("limit", 50))
            proc_list = process_service.inspect_processes(filter_name=filter_name, pid=pid, limit=limit)
            return {
                "status": "success",
                "total_processes": len(proc_list),
                "processes": proc_list,
            }

        # Otherwise system telemetry
        return {
            "status": "success",
            "telemetry": {
                "cpu_percent": psutil.cpu_percent(interval=0.0),
                "ram_percent": psutil.virtual_memory().percent,
                "disk_free_gb": round(psutil.disk_usage(os.path.abspath(os.sep)).free / (1024.0**3), 2),
            },
        }


class SafeMockOSExecutionAdapter(BaseOSExecutionAdapter):
    """Deterministic Mock Execution Adapter for Unit Testing and Safe Validation."""

    def __init__(self, simulated_delay_sec: float = 0.0, simulate_error: Optional[str] = None):
        self.simulated_delay_sec = simulated_delay_sec
        self.simulate_error = simulate_error
        self.executed_actions: List[OSActionRequest] = []

    async def execute_validated_action(self, action: OSActionRequest) -> Dict[str, Any]:
        """Record and simulate execution safely without mutating host OS."""
        if self.simulated_delay_sec > 0:
            await asyncio.sleep(self.simulated_delay_sec)

        if self.simulate_error:
            raise RuntimeError(self.simulate_error)

        self.executed_actions.append(action)

        # Return mock structured observation based on action type
        if action.action_type in (OSActionType.READ_ONLY, OSActionType.SYSTEM_TELEMETRY):
            params = action.parameters
            if "filter_name" in params or "pid" in params or params.get("query_type") == "processes":
                return {
                    "status": "success",
                    "total_processes": 1,
                    "processes": [
                        {
                            "pid": 1234,
                            "name": "notepad.exe",
                            "status": "running",
                            "create_time": 1728000000.0,
                            "cpu_percent": 0.0,
                            "memory_mb": 15.2,
                            "is_protected": False,
                        }
                    ],
                }
            return {
                "status": "success",
                "telemetry": {
                    "cpu_percent": 12.5,
                    "ram_percent": 45.0,
                    "gpu_vram_used_mb": 0.0,
                    "disk_free_gb": 120.4,
                },
            }
        elif action.action_type == OSActionType.APPLICATION_LAUNCH:
            return {
                "status": "success",
                "application_id": action.parameters.get("application_id", "notepad"),
                "pid": 48200,
                "process_name": action.parameters.get("application_id", "notepad") + ".exe",
                "create_time": 1728000000.0,
                "start_timestamp": time.time(),
            }
        elif action.action_type == OSActionType.PROCESS_TERMINATE:
            return {
                "status": "success",
                "pid": action.parameters.get("pid", 0),
                "process_name": action.parameters.get("expected_name", "app.exe"),
                "create_time": action.parameters.get("expected_create_time", 1728000000.0),
                "outcome": "TERMINATED",
            }
        elif action.action_type in (OSActionType.MOUSE_MOVE, OSActionType.MOUSE_CLICK):
            return {
                "status": "success",
                "coordinates": (action.parameters.get("x", 0), action.parameters.get("y", 0)),
            }
        elif action.action_type == OSActionType.KEYBOARD_INPUT:
            return {
                "status": "success",
                "typed_length": len(str(action.parameters.get("text", ""))),
            }
        else:
            return {
                "status": "success",
                "action_type": action.action_type.value,
            }

    def clear(self) -> None:
        """Clear recorded actions."""
        self.executed_actions.clear()
