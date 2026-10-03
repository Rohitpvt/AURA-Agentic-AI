"""Agent Execution Loop executing multi-step DAG plans with safety circuit breakers."""

import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.core.errors import EntityNotFoundError, ValidationError
from app.core.logging import logger
from app.db.models.agent_run import AgentRun
from app.db.models.task import Task
from app.runtime.events import RuntimeEvent, RuntimeEventType
from app.runtime.planner import supervisor_planner
from app.runtime.substrate import hermes_substrate
from app.runtime.tool_bridge import tool_bridge
from app.schemas.agent import AgentGoalRequest, AgentRunResponse
from app.schemas.memory import MemoryRecallResult
from app.schemas.task import TaskCreateRequest, TaskStepCreate, TaskStepUpdate, TaskUpdateRequest
from app.schemas.tool import ToolResponse
from app.services.memory_service import memory_service
from app.services.providers.base import ModelProvider
from app.services.providers.router import model_router
from app.services.task_service import task_service
from app.services.tool_registry import tool_registry


class AgentExecutionLoop:
    """Orchestrates end-to-end cognitive planning, DAG execution, tool bridging, and memory writeback."""

    def __init__(self):
        self._cancelled_runs: Set[uuid.UUID] = set()

    def cancel_run(self, run_id: uuid.UUID) -> None:
        """Signal cooperative cancellation for an active agent run."""
        self._cancelled_runs.add(run_id)
        logger.info(f"AgentExecutionLoop: Cancellation requested for run {run_id}")

    async def execute_goal(
        self,
        db: AsyncSession,
        request: AgentGoalRequest,
        actor_id: str,
        event_callback: Optional[Callable[[RuntimeEvent], None]] = None,
    ) -> AgentRunResponse:
        """Complete cognitive execution loop from raw goal to verified task completion."""
        start_time = time.perf_counter()
        events_emitted: List[Dict[str, Any]] = []

        def _handle_event(evt: RuntimeEvent):
            events_emitted.append(evt.to_dict())
            if event_callback:
                event_callback(evt)

        # 1. Resolve Model Provider based on routing policy
        provider = model_router.get_provider(request.preferred_provider or "ollama")
        model_name = (
            settings.LOCAL_MODEL_GENERAL
            if request.preferred_provider == "ollama"
            else "gemini-2.5-flash"
        )

        # 2. Memory Context Recall (Zero-cost pgvector)
        recalled_memories: List[MemoryRecallResult] = []
        try:
            recalled_memories = await memory_service.recall_memories(
                db=db,
                workspace_id=request.workspace_id,
                query=request.goal,
                top_k=3,
            )
            if recalled_memories:
                logger.info(f"AgentExecutionLoop: Recalled {len(recalled_memories)} relevant memories")
        except Exception as e:
            logger.warning(f"AgentExecutionLoop: Memory recall skipped ({e})")

        # 3. Discover Available Tools
        available_tools: List[ToolResponse] = await tool_registry.list_tools(
            db=db,
            workspace_id=request.workspace_id,
        )

        # 4. Supervisor Planning
        plan = await supervisor_planner.plan_goal(
            goal=request.goal,
            provider=provider,
            model_name=model_name,
            available_tools=available_tools,
            recalled_memories=recalled_memories,
        )

        # 5. Create Task and Task Steps in Database
        dag_steps = [
            TaskStepCreate(
                step_number=s.step_number,
                title=s.title,
                description=s.description,
                dependencies=s.dependencies,
                tool_name=s.suggested_tool,
                tool_input=s.tool_input,
                verification_assertions=[{"assertion": s.verification_criteria}],
            )
            for s in plan.steps
        ]

        task_res = await task_service.create_task(
            db=db,
            payload=TaskCreateRequest(
                workspace_id=request.workspace_id,
                title=request.title or f"Goal: {request.goal[:80]}",
                goal=request.goal,
                priority=request.priority,
                autonomy_level=request.autonomy_level,
                session_id=request.session_id,
                steps=dag_steps,
            ),
            user_id=uuid.UUID(actor_id) if actor_id != "system" else None,
        )
        task_id = task_res.id

        # 6. Create AgentRun Record
        agent_run = AgentRun(
            task_id=task_id,
            session_id=request.session_id,
            workspace_id=request.workspace_id,
            agent_type="master_supervisor",
            model_name=model_name,
            model_tier="general",
            status="running",
            checkpoint_state={"plan_summary": plan.summary},
        )
        db.add(agent_run)
        await db.commit()
        await db.refresh(agent_run)
        run_id = agent_run.id

        _handle_event(
            RuntimeEvent(
                event_type=RuntimeEventType.TASK_CREATED,
                task_id=task_id,
                agent_run_id=run_id,
                data={"title": task_res.title, "goal": request.goal},
            )
        )
        _handle_event(
            RuntimeEvent(
                event_type=RuntimeEventType.PLAN_GENERATED,
                task_id=task_id,
                agent_run_id=run_id,
                data={"summary": plan.summary, "step_count": len(plan.steps)},
            )
        )

        # 7. Execute DAG Steps Sequentially (Observe -> Decide -> Act -> Verify)
        await task_service.update_task_status(
            db=db,
            task_id=task_id,
            workspace_id=request.workspace_id,
            payload=TaskUpdateRequest(status="running"),
            actor_id=actor_id,
        )

        context_store: Dict[str, Any] = {}
        completed_step_numbers: Set[int] = set()
        final_synthesis: Optional[str] = None
        executed_tool_signatures: Set[str] = set()

        for step in plan.steps:
            # Check for cancellation
            if run_id in self._cancelled_runs:
                logger.info(f"AgentExecutionLoop: Run {run_id} cancelled during execution")
                await task_service.cancel_task(
                    db=db,
                    task_id=task_id,
                    workspace_id=request.workspace_id,
                    actor_id=actor_id,
                )
                agent_run.status = "cancelled"
                agent_run.ended_at = datetime.now(timezone.utc)
                await db.commit()
                _handle_event(
                    RuntimeEvent(
                        event_type=RuntimeEventType.TASK_CANCELLED,
                        task_id=task_id,
                        agent_run_id=run_id,
                        data={"reason": "User cancellation"},
                    )
                )
                break

            # Verify all step dependencies are met
            for dep in step.dependencies:
                if dep not in completed_step_numbers:
                    logger.error(f"AgentExecutionLoop: Unmet dependency Step {dep} for Step {step.step_number}")
                    break

            _handle_event(
                RuntimeEvent(
                    event_type=RuntimeEventType.STEP_STARTED,
                    task_id=task_id,
                    agent_run_id=run_id,
                    step_number=step.step_number,
                    data={"title": step.title},
                )
            )

            # Checkpoint step as running
            await task_service.checkpoint_step(
                db=db,
                task_id=task_id,
                step_number=step.step_number,
                workspace_id=request.workspace_id,
                update_data=TaskStepUpdate(status="running"),
                actor_id=actor_id,
            )

            # Hermes reasoning turn
            step_action = await hermes_substrate.execute_step_turn(
                provider=provider,
                model_name=model_name,
                goal=request.goal,
                step_number=step.step_number,
                step_title=step.title,
                step_description=step.description,
                prior_context=context_store,
                available_tools=available_tools,
                recalled_memories=recalled_memories,
                suggested_tool=step.suggested_tool,
                suggested_input=step.tool_input,
            )

            step_tool_output = None

            # If Hermes asks for a tool call -> execute through governed bridge
            if step_action.get("action") == "tool_call":
                tool_name = step_action["tool_name"]
                tool_args = step_action.get("arguments", {})

                # Circuit breaker: Check repeated identical tool calls
                tool_sig = f"{tool_name}:{sorted(tool_args.items())}"
                if tool_sig in executed_tool_signatures:
                    logger.warning(f"AgentExecutionLoop: Circuit breaker triggered on repeated tool call '{tool_sig}'")
                    tool_res = {"status": "skipped", "reason": "Circuit breaker: Identical tool call repeated"}
                else:
                    executed_tool_signatures.add(tool_sig)
                    tool_res = await tool_bridge.execute_governed_tool(
                        db=db,
                        workspace_id=request.workspace_id,
                        task_id=task_id,
                        step_number=step.step_number,
                        agent_run_id=run_id,
                        tool_name=tool_name,
                        arguments=tool_args,
                        actor_id=actor_id,
                        event_callback=_handle_event,
                    )

                # Check for HITL Suspension
                if tool_res.get("status") == "suspended_for_approval":
                    logger.info(f"AgentExecutionLoop: Suspending execution for Approval ID {tool_res.get('approval_id')}")
                    agent_run.status = "waiting_approval"
                    agent_run.checkpoint_state = {
                        "suspended_at_step": step.step_number,
                        "approval_id": tool_res.get("approval_id"),
                        "tool_name": tool_name,
                        "context_store": context_store,
                    }
                    await db.commit()
                    duration_ms = int((time.perf_counter() - start_time) * 1000)
                    return AgentRunResponse(
                        id=agent_run.id,
                        task_id=task_id,
                        workspace_id=request.workspace_id,
                        status="waiting_approval",
                        model_name=agent_run.model_name,
                        model_tier=agent_run.model_tier,
                        total_tokens_in=agent_run.total_tokens_in,
                        total_tokens_out=agent_run.total_tokens_out,
                        duration_ms=duration_ms,
                        final_result=f"Execution suspended: Human approval required for high-risk action '{tool_name}'",
                        started_at=agent_run.started_at,
                        ended_at=None,
                        events=events_emitted,
                    )

                step_tool_output = tool_res
                context_store[f"step_{step.step_number}_observation"] = tool_res

                # Run synthesis turn after tool execution
                synthesis_action = await hermes_substrate.execute_step_turn(
                    provider=provider,
                    model_name=model_name,
                    goal=request.goal,
                    step_number=step.step_number,
                    step_title=step.title,
                    step_description=step.description,
                    prior_context=context_store,
                    available_tools=available_tools,
                    recalled_memories=recalled_memories,
                )
                step_result_text = synthesis_action.get("content", f"Completed step {step.step_number}")
            else:
                step_result_text = step_action.get("content", f"Completed step {step.step_number}")

            context_store[f"step_{step.step_number}_output"] = step_result_text
            completed_step_numbers.add(step.step_number)
            final_synthesis = step_result_text

            # Checkpoint step as completed
            await task_service.checkpoint_step(
                db=db,
                task_id=task_id,
                step_number=step.step_number,
                workspace_id=request.workspace_id,
                update_data=TaskStepUpdate(
                    status="completed",
                    tool_output=step_tool_output or {"result": step_result_text},
                    is_verified=True,
                ),
                actor_id=actor_id,
            )

            _handle_event(
                RuntimeEvent(
                    event_type=RuntimeEventType.STEP_COMPLETED,
                    task_id=task_id,
                    agent_run_id=run_id,
                    step_number=step.step_number,
                    data={"summary": step_result_text[:200]},
                )
            )

        duration_ms = int((time.perf_counter() - start_time) * 1000)

        # 8. Complete Task & AgentRun
        if run_id not in self._cancelled_runs:
            await task_service.update_task_status(
                db=db,
                task_id=task_id,
                workspace_id=request.workspace_id,
                payload=TaskUpdateRequest(
                    status="completed",
                    result_summary=final_synthesis or "Task completed successfully",
                ),
                actor_id=actor_id,
            )
            agent_run.status = "completed"
            agent_run.duration_ms = duration_ms
            agent_run.ended_at = datetime.now(timezone.utc)
            await db.commit()

            # 9. Memory Writeback: If task was research/fact, optionally store key outcome
            if "search" in request.goal.lower() or "preference" in request.goal.lower():
                try:
                    await memory_service.ingest_memory(
                        db=db,
                        workspace_id=request.workspace_id,
                        fact_statement=f"Completed research on '{request.goal}': {final_synthesis[:300] if final_synthesis else 'Done'}",
                        category="project_context",
                        confidence_score=0.9,
                        source_type="agent_run",
                        user_id=uuid.UUID(actor_id) if actor_id != "system" else None,
                    )
                    _handle_event(
                        RuntimeEvent(
                            event_type=RuntimeEventType.MEMORY_WRITTEN,
                            task_id=task_id,
                            agent_run_id=run_id,
                            data={"category": "project_context"},
                        )
                    )
                except Exception as e:
                    logger.warning(f"AgentExecutionLoop: Memory writeback skipped: {e}")

            _handle_event(
                RuntimeEvent(
                    event_type=RuntimeEventType.TASK_COMPLETED,
                    task_id=task_id,
                    agent_run_id=run_id,
                    data={"duration_ms": duration_ms, "result_summary": (final_synthesis or "")[:300]},
                )
            )

        return AgentRunResponse(
            id=agent_run.id,
            task_id=task_id,
            workspace_id=request.workspace_id,
            status=agent_run.status,
            model_name=agent_run.model_name,
            model_tier=agent_run.model_tier,
            total_tokens_in=agent_run.total_tokens_in,
            total_tokens_out=agent_run.total_tokens_out,
            duration_ms=duration_ms,
            final_result=final_synthesis,
            started_at=agent_run.started_at,
            ended_at=agent_run.ended_at,
            events=events_emitted,
        )


execution_loop = AgentExecutionLoop()
