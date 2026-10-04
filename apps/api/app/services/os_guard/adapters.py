"""AURA-901 Execution Adapter Interfaces and Safe Mocks.

Defines:
1. BaseOSExecutionAdapter: The abstract boundary receiving only already-validated actions
2. SafeMockOSExecutionAdapter: Deterministic simulation adapter for safety testing and readiness probes
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import asyncio
from typing import Any, Dict, List, Optional

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
        if action.action_type == OSActionType.READ_ONLY or action.action_type == OSActionType.SYSTEM_TELEMETRY:
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
                "pid": 48200,
                "process_name": action.parameters.get("target", "app.exe"),
                "create_time": 1728000000.0,
            }
        elif action.action_type == OSActionType.PROCESS_TERMINATE:
            return {
                "status": "success",
                "terminated_pid": action.parameters.get("pid", 0),
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
