"""Bounded Local Sub-Agent Worker Pool for hierarchical delegation."""

import asyncio
import json
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.core.errors import AuthorizationError, EntityNotFoundError, ValidationError
from app.core.logging import logger
from app.db.models.agent_run import SubAgentRun
from app.runtime.events import RuntimeEvent, RuntimeEventType
from app.runtime.subagents.roles import SUBAGENT_ROLES
from app.runtime.tool_bridge import tool_bridge
from app.schemas.subagent import SubAgentResult, SubAgentSpec
from app.services.providers.base import ChatMessage, ChatRequest, ModelProvider
from app.services.providers.router import model_router


class SubAgentWorkerPool:
    """Manages execution of bounded sub-agent workers with depth, concurrency, and tool constraints."""

    def __init__(self, max_concurrency: int = 4):
        self.max_concurrency = min(max_concurrency, 4)
        self._semaphore = asyncio.Semaphore(self.max_concurrency)
        self._active_workers: Dict[uuid.UUID, asyncio.Task] = {}

    async def dispatch_worker(
        self,
        db: AsyncSession,
        spec: SubAgentSpec,
        provider: Optional[ModelProvider] = None,
        model_name: Optional[str] = None,
        actor_id: str = "system",
        event_callback: Optional[Callable[[RuntimeEvent], None]] = None,
    ) -> SubAgentResult:
        """Dispatch a single bounded sub-agent worker under strict concurrency and depth limits."""
        start_time = time.perf_counter()

        # 0. Emergency Kill Switch Check
        from app.services.kill_switch import kill_switch
        if kill_switch.is_active(spec.workspace_id):
            logger.warning(f"SubAgentWorkerPool: Dispatch blocked - Emergency Kill Switch is active for workspace {spec.workspace_id}")
            raise AuthorizationError(f"Emergency Kill Switch is active in workspace '{spec.workspace_id}'. Sub-agent dispatch is suspended.")

        # 1. Enforce Hard Recursion Depth Ceiling (Max Depth = 2)
        if spec.depth_level > 2:
            logger.error(f"SubAgentWorkerPool: Recursion depth limit exceeded (attempted depth {spec.depth_level})")
            raise ValidationError(f"Sub-agent recursion depth {spec.depth_level} exceeds maximum allowed depth of 2")

        # 2. Validate Role
        role_cfg = SUBAGENT_ROLES.get(spec.role)
        if not role_cfg:
            raise ValidationError(f"Unknown sub-agent role '{spec.role}'. Available roles: {list(SUBAGENT_ROLES.keys())}")

        # 3. Create SubAgentRun DB Record
        subagent_run = SubAgentRun(
            parent_run_id=spec.parent_run_id,
            task_id=spec.parent_task_id,
            role=spec.role,
            goal=spec.goal[:1000],
            assigned_budget_tokens=spec.assigned_budget_tokens,
            consumed_tokens=0,
            depth_level=spec.depth_level,
            status="running",
        )
        db.add(subagent_run)
        await db.commit()
        await db.refresh(subagent_run)

        run_id = subagent_run.id
        logger.info(f"SubAgentWorkerPool: Dispatched {spec.role} (Run ID: {run_id}, Depth: {spec.depth_level})")

        if event_callback:
            event_callback(
                RuntimeEvent(
                    event_type=RuntimeEventType.SUBAGENT_STARTED,
                    task_id=spec.parent_task_id,
                    agent_run_id=spec.parent_run_id,
                    data={"subagent_run_id": str(run_id), "role": spec.role, "goal": spec.goal},
                )
            )

        # 4. Resolve Model Provider
        prov = provider or model_router.get_provider("ollama")
        target_model = model_name or settings.LOCAL_MODEL_GENERAL

        # 5. Acquire Concurrency Semaphore
        async with self._semaphore:
            worker_coro = self._run_worker_turn(
                db=db,
                subagent_run=subagent_run,
                spec=spec,
                role_cfg=role_cfg,
                provider=prov,
                model_name=target_model,
                actor_id=actor_id,
                event_callback=event_callback,
            )
            worker_task = asyncio.create_task(worker_coro)
            self._active_workers[run_id] = worker_task

            try:
                result = await worker_task
            except asyncio.CancelledError:
                logger.warning(f"SubAgentWorkerPool: Worker {run_id} cancelled")
                subagent_run.status = "cancelled"
                subagent_run.ended_at = datetime.now(timezone.utc)
                await db.commit()
                if event_callback:
                    event_callback(
                        RuntimeEvent(
                            event_type=RuntimeEventType.SUBAGENT_CANCELLED,
                            task_id=spec.parent_task_id,
                            agent_run_id=spec.parent_run_id,
                            data={"subagent_run_id": str(run_id), "role": spec.role},
                        )
                    )
                return SubAgentResult(
                    role=spec.role,
                    subtask=spec.goal,
                    status="cancelled",
                    findings="Worker cancelled by supervisor",
                    error="Task cancelled",
                )
            except Exception as e:
                logger.error(f"SubAgentWorkerPool: Worker {run_id} failed ({e})")
                subagent_run.status = "failed"
                subagent_run.ended_at = datetime.now(timezone.utc)
                await db.commit()
                if event_callback:
                    event_callback(
                        RuntimeEvent(
                            event_type=RuntimeEventType.SUBAGENT_FAILED,
                            task_id=spec.parent_task_id,
                            agent_run_id=spec.parent_run_id,
                            data={"subagent_run_id": str(run_id), "role": spec.role, "error": str(e)},
                        )
                    )
                return SubAgentResult(
                    role=spec.role,
                    subtask=spec.goal,
                    status="failed",
                    findings="Worker execution encountered an unhandled error",
                    error=str(e),
                )
            finally:
                self._active_workers.pop(run_id, None)

        duration_ms = (time.perf_counter() - start_time) * 1000.0
        result.duration_ms = duration_ms

        # Update DB record with outcome
        subagent_run.status = result.status
        subagent_run.consumed_tokens = result.consumed_tokens
        subagent_run.result_payload = result.model_dump()
        subagent_run.ended_at = datetime.now(timezone.utc)
        await db.commit()

        if event_callback:
            event_callback(
                RuntimeEvent(
                    event_type=RuntimeEventType.SUBAGENT_COMPLETED,
                    task_id=spec.parent_task_id,
                    agent_run_id=spec.parent_run_id,
                    data={
                        "subagent_run_id": str(run_id),
                        "role": spec.role,
                        "status": result.status,
                        "duration_ms": duration_ms,
                    },
                )
            )

        return result

    async def _run_worker_turn(
        self,
        db: AsyncSession,
        subagent_run: SubAgentRun,
        spec: SubAgentSpec,
        role_cfg: Dict[str, Any],
        provider: ModelProvider,
        model_name: str,
        actor_id: str,
        event_callback: Optional[Callable[[RuntimeEvent], None]],
    ) -> SubAgentResult:
        """Internal execution loop for a sub-agent worker."""
        permitted_tools = spec.permitted_tools or role_cfg.get("default_permitted_tools", [])
        tool_summaries = []
        artifacts = []

        # Construct prompt
        context_str = spec.scoped_context or "No extra context provided."
        user_prompt = f"""ASSIGNED SUBTASK GOAL:
{spec.goal}

SCOPED CONTEXT:
{context_str}

PERMITTED TOOLS:
{json.dumps(permitted_tools)}

Perform your task and provide structured JSON completion output.
"""
        messages = [
            ChatMessage(role="system", content=role_cfg["system_prompt"]),
            ChatMessage(role="user", content=user_prompt),
        ]

        req = ChatRequest(
            model=model_name,
            messages=messages,
            temperature=0.2,
            max_tokens=min(spec.assigned_budget_tokens, 2048),
            json_mode=True,
        )

        resp = await provider.generate_chat(req)
        raw_output = resp.content.strip()

        # Parse output
        cleaned = raw_output
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\n", "", cleaned)
            cleaned = re.sub(r"\n```$", "", cleaned)

        try:
            parsed = json.loads(cleaned)
        except Exception:
            parsed = {"action": "complete", "findings": cleaned}

        # Check if sub-agent requested a tool call
        if isinstance(parsed, dict) and parsed.get("action") == "tool_call":
            requested_tool = parsed.get("tool_name")
            tool_args = parsed.get("arguments", {})

            # Enforce Sub-Agent Tool Allowlist
            if requested_tool not in permitted_tools:
                logger.warning(f"SubAgent[{spec.role}]: Attempted to call unauthorized tool '{requested_tool}'")
                return SubAgentResult(
                    role=spec.role,
                    subtask=spec.goal,
                    status="failed",
                    findings=f"Sub-agent attempted to call unauthorized tool '{requested_tool}'",
                    error=f"Tool '{requested_tool}' not permitted for role '{spec.role}'",
                )

            # Route through AURA's single authoritative ToolBridge boundary
            tool_res = await tool_bridge.execute_governed_tool(
                db=db,
                workspace_id=spec.workspace_id,
                task_id=spec.parent_task_id,
                step_number=1,
                agent_run_id=spec.parent_run_id,
                tool_name=requested_tool,
                arguments=tool_args,
                actor_id=actor_id,
                event_callback=event_callback,
            )
            tool_summaries.append(f"{requested_tool}: {tool_res.get('status')}")

            # Second turn for synthesis based on tool observation
            messages.append(ChatMessage(role="assistant", content=raw_output))
            obs_str = json.dumps(tool_res.get("result", tool_res), indent=2)
            messages.append(ChatMessage(role="user", content=f"TOOL OBSERVATION:\n{obs_str}\n\nSynthesize final findings JSON."))

            synth_req = ChatRequest(
                model=model_name,
                messages=messages,
                temperature=0.2,
                max_tokens=2048,
                json_mode=True,
            )
            synth_resp = await provider.generate_chat(synth_req)
            synth_cleaned = synth_resp.content.strip()
            if synth_cleaned.startswith("```"):
                synth_cleaned = re.sub(r"^```(?:json)?\n", "", synth_cleaned)
                synth_cleaned = re.sub(r"\n```$", "", synth_cleaned)

            try:
                final_parsed = json.loads(synth_cleaned)
                findings = final_parsed.get("findings", synth_cleaned)
                artifacts = final_parsed.get("artifacts", [])
                verification = final_parsed.get("verification", {"status": "verified"})
            except Exception:
                findings = synth_cleaned
                verification = {"status": "unstructured_synthesis"}

            return SubAgentResult(
                role=spec.role,
                subtask=spec.goal,
                status="completed",
                findings=findings,
                artifacts=artifacts,
                tool_summaries=tool_summaries,
                verification_result=verification,
                consumed_tokens=resp.total_tokens + synth_resp.total_tokens,
            )

        # Direct completion
        findings = parsed.get("findings", cleaned) if isinstance(parsed, dict) else cleaned
        artifacts = parsed.get("artifacts", []) if isinstance(parsed, dict) else []
        verification = parsed.get("verification", {"status": "completed"}) if isinstance(parsed, dict) else {}

        return SubAgentResult(
            role=spec.role,
            subtask=spec.goal,
            status="completed",
            findings=findings,
            artifacts=artifacts,
            tool_summaries=tool_summaries,
            verification_result=verification,
            consumed_tokens=resp.total_tokens,
        )

    def cancel_task_workers(self, task_id: uuid.UUID) -> None:
        """Cancel all running sub-agent workers for a given parent task."""
        logger.info(f"SubAgentWorkerPool: Cancelling all active workers for Task {task_id}")
        for run_id, task in list(self._active_workers.items()):
            if not task.done():
                task.cancel()


subagent_pool = SubAgentWorkerPool(max_concurrency=4)
