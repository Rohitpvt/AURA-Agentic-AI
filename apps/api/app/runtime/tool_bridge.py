"""Agent Tool Bridge connecting Hermes runtime requests to AURA's governed Tool Registry."""

import uuid
from typing import Any, Callable, Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.errors import AuthorizationError, ValidationError
from app.core.logging import logger
from app.runtime.events import RuntimeEvent, RuntimeEventType
from app.schemas.tool import ToolExecutionRequest, ToolExecutionResponse
from app.services.tool_registry import tool_registry


class AgentToolBridge:
    """Interception and governance bridge between the Agent Runtime and AURA Control Plane."""

    def __init__(self):
        self._registry = tool_registry

    async def execute_governed_tool(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        task_id: uuid.UUID,
        step_number: int,
        agent_run_id: uuid.UUID,
        tool_name: str,
        arguments: Dict[str, Any],
        actor_id: str,
        event_callback: Optional[Callable[[RuntimeEvent], None]] = None,
    ) -> Dict[str, Any]:
        """Execute tool request strictly through AURA's validation, risk evaluation, and audit boundary."""
        logger.info(f"AgentToolBridge: Intercepted tool request '{tool_name}' for Task {task_id} Step {step_number}")

        if event_callback:
            event_callback(
                RuntimeEvent(
                    event_type=RuntimeEventType.TOOL_REQUESTED,
                    task_id=task_id,
                    agent_run_id=agent_run_id,
                    step_number=step_number,
                    data={"tool_name": tool_name, "arguments": arguments},
                )
            )

        # 1. Build governed execution request
        exec_req = ToolExecutionRequest(
            workspace_id=workspace_id,
            tool_name=tool_name,
            arguments=arguments,
        )

        # 2. Invoke AURA ToolRegistryService
        if event_callback:
            event_callback(
                RuntimeEvent(
                    event_type=RuntimeEventType.TOOL_STARTED,
                    task_id=task_id,
                    agent_run_id=agent_run_id,
                    step_number=step_number,
                    data={"tool_name": tool_name},
                )
            )

        resp: ToolExecutionResponse = await self._registry.execute_tool(
            db=db,
            request=exec_req,
            actor_id=actor_id,
            actor_type="agent",
        )

        # 3. Handle HITL Suspensions
        if resp.requires_hitl_approval:
            logger.warning(f"AgentToolBridge: Tool '{tool_name}' suspended for Human-in-the-Loop approval")
            from app.services.approval_service import approval_service

            approval_record, signed_token = await approval_service.create_approval_request(
                db=db,
                workspace_id=workspace_id,
                task_id=task_id,
                agent_run_id=agent_run_id,
                step_number=step_number,
                tool_name=tool_name,
                tool_params=arguments,
                risk_level=resp.risk_level,
                reason_requested=f"High-risk action '{tool_name}' requires human approval before execution",
            )

            if event_callback:
                event_callback(
                    RuntimeEvent(
                        event_type=RuntimeEventType.APPROVAL_REQUESTED,
                        task_id=task_id,
                        agent_run_id=agent_run_id,
                        step_number=step_number,
                        data={
                            "approval_id": str(approval_record.id),
                            "tool_name": tool_name,
                            "risk_level": resp.risk_level,
                            "approval_token": signed_token,
                        },
                    )
                )
            return {
                "status": "suspended_for_approval",
                "requires_approval": True,
                "approval_id": str(approval_record.id),
                "approval_token": signed_token,
                "error": resp.error,
            }

        # 4. Handle Execution Failure
        if not resp.success:
            logger.error(f"AgentToolBridge: Tool '{tool_name}' failed: {resp.error}")
            if event_callback:
                event_callback(
                    RuntimeEvent(
                        event_type=RuntimeEventType.TOOL_REJECTED,
                        task_id=task_id,
                        agent_run_id=agent_run_id,
                        step_number=step_number,
                        data={"tool_name": tool_name, "error": resp.error},
                    )
                )
            return {
                "status": "error",
                "error": resp.error,
                "tool_name": tool_name,
            }

        # 5. Handle Success and sanitize untrusted output
        if event_callback:
            event_callback(
                RuntimeEvent(
                    event_type=RuntimeEventType.TOOL_COMPLETED,
                    task_id=task_id,
                    agent_run_id=agent_run_id,
                    step_number=step_number,
                    data={
                        "tool_name": tool_name,
                        "duration_ms": resp.execution_time_ms,
                    },
                )
            )

        return {
            "status": "success",
            "tool_name": tool_name,
            "result": resp.result,
            "duration_ms": resp.execution_time_ms,
        }


tool_bridge = AgentToolBridge()
