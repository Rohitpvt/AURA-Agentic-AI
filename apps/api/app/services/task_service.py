"""Task and Task Step DAG State Management Service."""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.core.errors import AuthorizationError, ConflictError, EntityNotFoundError, ValidationError
from app.core.logging import logger
from app.core.security import compute_sha256_hash
from app.db.models.audit import AuditLog
from app.db.models.task import Task, TaskStep
from app.schemas.task import (
    TaskCreateRequest,
    TaskResponse,
    TaskStepCreate,
    TaskStepResponse,
    TaskStepUpdate,
    TaskUpdateRequest,
)


# Canonical State Transitions
VALID_TASK_TRANSITIONS = {
    "pending": {"planning", "running", "cancelled"},
    "planning": {"running", "blocked", "cancelled", "failed"},
    "running": {"completed", "failed", "blocked", "cancelled"},
    "blocked": {"running", "cancelled", "failed"},
    "completed": set(),
    "failed": set(),
    "cancelled": set(),
}

VALID_STEP_TRANSITIONS = {
    "pending": {"running", "skipped", "cancelled"},
    "running": {"completed", "failed", "cancelled"},
    "skipped": set(),
    "completed": set(),
    "failed": set(),
    "cancelled": set(),
}


def validate_dag_structure(steps: List[Any]) -> None:
    """Validate that task steps form a valid, non-cyclic Directed Acyclic Graph (DAG)."""
    step_numbers = set()
    for s in steps:
        num = s.step_number if hasattr(s, "step_number") else s["step_number"]
        if num in step_numbers:
            raise ValidationError(f"Duplicate step number {num} detected in task DAG")
        step_numbers.add(num)

    # Dependency existence and self-dependency check
    adj: Dict[int, List[int]] = {num: [] for num in step_numbers}
    in_degree: Dict[int, int] = {num: 0 for num in step_numbers}

    for s in steps:
        num = s.step_number if hasattr(s, "step_number") else s["step_number"]
        deps = s.dependencies if hasattr(s, "dependencies") else s.get("dependencies", [])
        for dep in deps:
            if dep == num:
                raise ValidationError(f"Step {num} cannot depend on itself (self-dependency)")
            if dep not in step_numbers:
                raise ValidationError(f"Step {num} depends on non-existent step {dep}")
            adj[dep].append(num)
            in_degree[num] += 1

    # Cycle detection via topological sort (Kahn's algorithm)
    queue = [n for n in step_numbers if in_degree[n] == 0]
    visited_count = 0

    while queue:
        curr = queue.pop(0)
        visited_count += 1
        for neighbor in adj[curr]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if visited_count != len(step_numbers):
        raise ValidationError("Cyclic dependency detected in task step DAG")


class TaskService:
    """Service managing Task lifecycle, DAG step validation, checkpoints, and cancellation."""

    async def create_task(
        self,
        db: AsyncSession,
        payload: TaskCreateRequest,
        user_id: Optional[uuid.UUID],
    ) -> TaskResponse:
        """Create a new Task with optional initial DAG steps, with idempotency protection."""
        # 1. Check Idempotency Key
        if payload.idempotency_key:
            res = await db.execute(
                select(Task)
                .options(selectinload(Task.steps))
                .where(
                    Task.workspace_id == payload.workspace_id,
                    Task.idempotency_key == payload.idempotency_key,
                    Task.deleted_at.is_(None),
                )
            )
            existing = res.scalar_one_or_none()
            if existing:
                logger.info(f"Returning idempotent task {existing.id} for key '{payload.idempotency_key}'")
                return self._to_task_response(existing)

        # 2. Validate Initial Steps DAG if present
        if payload.steps:
            validate_dag_structure(payload.steps)

        # 3. Create Task Entity
        task = Task(
            workspace_id=payload.workspace_id,
            created_by=user_id,
            session_id=payload.session_id,
            title=payload.title,
            goal=payload.goal,
            status="pending",
            priority=payload.priority,
            autonomy_level=payload.autonomy_level,
            budget_max_tokens=payload.budget_max_tokens,
            budget_max_cost_cents=payload.budget_max_cost_cents,
            timeout_seconds=payload.timeout_seconds,
            idempotency_key=payload.idempotency_key,
        )
        db.add(task)
        await db.flush()

        # 4. Attach Steps
        if payload.steps:
            for s in payload.steps:
                step_entity = TaskStep(
                    task_id=task.id,
                    step_number=s.step_number,
                    title=s.title,
                    description=s.description,
                    dependencies=s.dependencies,
                    status="pending",
                    tool_name=s.tool_name,
                    tool_input=s.tool_input,
                    verification_assertions=s.verification_assertions,
                )
                db.add(step_entity)
            await db.flush()

        # 5. Audit Logging
        await self._log_audit(
            db=db,
            workspace_id=payload.workspace_id,
            actor_type="user" if user_id else "system",
            actor_id=str(user_id) if user_id else "system",
            action="task.created",
            resource_type="task",
            resource_id=str(task.id),
            details={"title": task.title, "step_count": len(payload.steps or [])},
        )
        await db.commit()

        # Reload with steps
        return await self.get_task(db=db, task_id=task.id, workspace_id=payload.workspace_id)

    async def get_task(
        self,
        db: AsyncSession,
        task_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> TaskResponse:
        """Fetch a task and its steps, verifying workspace isolation."""
        res = await db.execute(
            select(Task)
            .options(selectinload(Task.steps))
            .where(
                Task.id == task_id,
                Task.workspace_id == workspace_id,
                Task.deleted_at.is_(None),
            )
        )
        task = res.scalar_one_or_none()
        if not task:
            raise EntityNotFoundError("Task", str(task_id))
        return self._to_task_response(task)

    async def list_tasks(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[TaskResponse]:
        """List tasks within a workspace."""
        stmt = (
            select(Task)
            .options(selectinload(Task.steps))
            .where(Task.workspace_id == workspace_id, Task.deleted_at.is_(None))
            .order_by(Task.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        if status:
            stmt = stmt.where(Task.status == status)

        res = await db.execute(stmt)
        tasks = res.scalars().all()
        return [self._to_task_response(t) for t in tasks]

    async def add_task_steps(
        self,
        db: AsyncSession,
        task_id: uuid.UUID,
        workspace_id: uuid.UUID,
        new_steps: List[TaskStepCreate],
    ) -> List[TaskStepResponse]:
        """Add new DAG steps to an existing task."""
        res = await db.execute(
            select(Task)
            .options(selectinload(Task.steps))
            .where(Task.id == task_id, Task.workspace_id == workspace_id, Task.deleted_at.is_(None))
        )
        task = res.scalar_one_or_none()
        if not task:
            raise EntityNotFoundError("Task", str(task_id))

        if task.status in ["completed", "cancelled", "failed"]:
            raise ValidationError(f"Cannot add steps to task in '{task.status}' state")

        # Combine existing and new steps to validate complete DAG
        combined = list(task.steps) + new_steps
        validate_dag_structure(combined)

        for s in new_steps:
            step_entity = TaskStep(
                task_id=task.id,
                step_number=s.step_number,
                title=s.title,
                description=s.description,
                dependencies=s.dependencies,
                status="pending",
                tool_name=s.tool_name,
                tool_input=s.tool_input,
                verification_assertions=s.verification_assertions,
            )
            db.add(step_entity)

        await db.commit()
        refreshed = await self.get_task(db=db, task_id=task_id, workspace_id=workspace_id)
        return refreshed.steps

    async def update_task_status(
        self,
        db: AsyncSession,
        task_id: uuid.UUID,
        workspace_id: uuid.UUID,
        payload: TaskUpdateRequest,
        actor_id: str,
    ) -> TaskResponse:
        """Transition task status adhering to canonical state machine."""
        res = await db.execute(
            select(Task)
            .options(selectinload(Task.steps))
            .where(Task.id == task_id, Task.workspace_id == workspace_id, Task.deleted_at.is_(None))
        )
        task = res.scalar_one_or_none()
        if not task:
            raise EntityNotFoundError("Task", str(task_id))

        if payload.status:
            allowed = VALID_TASK_TRANSITIONS.get(task.status, set())
            if payload.status != task.status and payload.status not in allowed:
                raise ValidationError(
                    f"Invalid task transition from '{task.status}' to '{payload.status}'. Allowed: {list(allowed)}"
                )
            task.status = payload.status
            if payload.status in ["completed", "failed", "cancelled"]:
                task.completed_at = datetime.now(timezone.utc)

        if payload.result_summary is not None:
            task.result_summary = payload.result_summary
        if payload.error_summary is not None:
            task.error_summary = payload.error_summary

        await self._log_audit(
            db=db,
            workspace_id=workspace_id,
            actor_type="user",
            actor_id=actor_id,
            action="task.status_updated",
            resource_type="task",
            resource_id=str(task.id),
            details={"old_status": task.status, "new_status": payload.status},
        )
        await db.commit()
        return self._to_task_response(task)

    async def checkpoint_step(
        self,
        db: AsyncSession,
        task_id: uuid.UUID,
        step_number: int,
        workspace_id: uuid.UUID,
        update_data: TaskStepUpdate,
        actor_id: str,
    ) -> TaskStepResponse:
        """Update/checkpoint step execution state, outputs, and completion."""
        res = await db.execute(
            select(TaskStep)
            .join(Task, TaskStep.task_id == Task.id)
            .where(
                TaskStep.task_id == task_id,
                TaskStep.step_number == step_number,
                Task.workspace_id == workspace_id,
                Task.deleted_at.is_(None),
            )
        )
        step = res.scalar_one_or_none()
        if not step:
            raise EntityNotFoundError("TaskStep", f"Task {task_id} Step {step_number}")

        if update_data.status:
            allowed = VALID_STEP_TRANSITIONS.get(step.status, set())
            if update_data.status != step.status and update_data.status not in allowed:
                raise ValidationError(
                    f"Invalid step transition from '{step.status}' to '{update_data.status}'. Allowed: {list(allowed)}"
                )
            step.status = update_data.status
            if update_data.status == "running" and not step.started_at:
                step.started_at = datetime.now(timezone.utc)
            elif update_data.status in ["completed", "failed", "skipped", "cancelled"]:
                step.completed_at = datetime.now(timezone.utc)

        if update_data.tool_output is not None:
            step.tool_output = update_data.tool_output
        if update_data.is_verified is not None:
            step.is_verified = update_data.is_verified
        if update_data.error_message is not None:
            step.error_message = update_data.error_message

        await db.commit()
        await db.refresh(step)
        return self._to_step_response(step)

    async def cancel_task(
        self,
        db: AsyncSession,
        task_id: uuid.UUID,
        workspace_id: uuid.UUID,
        actor_id: str,
    ) -> TaskResponse:
        """Cancel task and cascade cancellation to all pending/running steps."""
        res = await db.execute(
            select(Task)
            .options(selectinload(Task.steps))
            .where(Task.id == task_id, Task.workspace_id == workspace_id, Task.deleted_at.is_(None))
        )
        task = res.scalar_one_or_none()
        if not task:
            raise EntityNotFoundError("Task", str(task_id))

        if task.status in ["completed", "cancelled"]:
            raise ValidationError(f"Task {task_id} is already in '{task.status}' state and cannot be cancelled")

        task.status = "cancelled"
        task.completed_at = datetime.now(timezone.utc)

        for step in task.steps:
            if step.status in ["pending", "running"]:
                step.status = "cancelled"
                step.completed_at = datetime.now(timezone.utc)

        await self._log_audit(
            db=db,
            workspace_id=workspace_id,
            actor_type="user",
            actor_id=actor_id,
            action="task.cancelled",
            resource_type="task",
            resource_id=str(task.id),
            details={"previous_status": task.status},
        )
        await db.commit()
        return self._to_task_response(task)

    def _to_task_response(self, task: Task) -> TaskResponse:
        return TaskResponse(
            id=task.id,
            workspace_id=task.workspace_id,
            created_by=task.created_by,
            session_id=task.session_id,
            title=task.title,
            goal=task.goal,
            status=task.status,
            priority=task.priority,
            autonomy_level=task.autonomy_level,
            budget_max_tokens=task.budget_max_tokens,
            budget_max_cost_cents=task.budget_max_cost_cents,
            timeout_seconds=task.timeout_seconds,
            idempotency_key=task.idempotency_key,
            error_summary=task.error_summary,
            result_summary=task.result_summary,
            completed_at=task.completed_at,
            created_at=task.created_at,
            updated_at=task.updated_at,
            steps=[self._to_step_response(s) for s in (task.steps or [])],
        )

    def _to_step_response(self, step: TaskStep) -> TaskStepResponse:
        return TaskStepResponse(
            id=step.id,
            task_id=step.task_id,
            step_number=step.step_number,
            title=step.title,
            description=step.description,
            dependencies=step.dependencies or [],
            status=step.status,
            tool_name=step.tool_name,
            tool_input=step.tool_input,
            tool_output=step.tool_output,
            verification_assertions=step.verification_assertions or [],
            is_verified=step.is_verified,
            started_at=step.started_at,
            completed_at=step.completed_at,
            error_message=step.error_message,
        )

    async def _log_audit(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        actor_type: str,
        actor_id: str,
        action: str,
        resource_type: str,
        resource_id: str,
        details: Dict[str, Any],
    ) -> None:
        """Emit tamper-evident SHA-256 hashed audit log record."""
        from app.services.audit_service import audit_service
        await audit_service.record_event(
            db=db,
            workspace_id=workspace_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
        )


task_service = TaskService()
