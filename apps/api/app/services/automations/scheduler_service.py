"""PostgreSQL Transactional Scheduler and Automation Engine for AURA."""

import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AuthorizationError, ConflictError, EntityNotFoundError, ValidationError
from app.core.logging import logger
from app.db.models.automation import Automation, AutomationRun
from app.db.models.task import Task
from app.schemas.automation import AutomationCreateRequest, AutomationResponse, AutomationRunResponse, AutomationUpdateRequest
from app.schemas.task import TaskCreateRequest
from app.services.audit_service import audit_service
from app.services.automations.cron_engine import calculate_next_run, validate_cron_expression
from app.services.task_service import TaskService


# Canonical retry delays in seconds (base) + random jitter bounds
RETRY_BASE_DELAYS = [30, 120, 480]


class SchedulerService:
    """Provides transactional cron scheduling, row-locked job claiming, and automation execution."""

    def __init__(self, task_service: Optional[TaskService] = None):
        self.task_service = task_service or TaskService()

    # ==========================================
    # 1. Automation CRUD Operations
    # ==========================================

    async def create_automation(
        self,
        db: AsyncSession,
        payload: AutomationCreateRequest,
        workspace_id: uuid.UUID,
        user_id: Optional[uuid.UUID],
    ) -> AutomationResponse:
        """Create a new automation with validated cron schedule."""
        validate_cron_expression(payload.cron_expression)
        now = datetime.now(timezone.utc)
        initial_next_run = calculate_next_run(
            payload.cron_expression, base_time=now, timezone_str=payload.timezone
        )

        automation = Automation(
            workspace_id=workspace_id,
            created_by=user_id,
            name=payload.name,
            description=payload.description,
            trigger_type=payload.trigger_type,
            cron_expression=payload.cron_expression,
            timezone=payload.timezone,
            prompt_template=payload.prompt_template,
            assigned_skill_id=payload.assigned_skill_id,
            autonomy_level=payload.autonomy_level,
            is_active=payload.is_active,
            next_run_at=initial_next_run,
            circuit_state="CLOSED",
            failure_streak=0,
            total_runs=0,
            total_failures=0,
        )
        db.add(automation)
        await db.flush()

        await audit_service.record_event(
            db=db,
            workspace_id=workspace_id,
            actor_type="user" if user_id else "system",
            actor_id=str(user_id) if user_id else "system",
            action="automation.created",
            resource_type="automation",
            resource_id=str(automation.id),
            details={
                "name": automation.name,
                "cron_expression": automation.cron_expression,
                "timezone": automation.timezone,
                "next_run_at": initial_next_run.isoformat() if initial_next_run else None,
            },
        )
        return AutomationResponse.model_validate(automation)

    async def get_automation(
        self,
        db: AsyncSession,
        automation_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> AutomationResponse:
        """Retrieve automation details ensuring workspace isolation."""
        automation = await self._get_automation_entity(db, automation_id, workspace_id)
        return AutomationResponse.model_validate(automation)

    async def list_automations(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        is_active: Optional[bool] = None,
    ) -> List[AutomationResponse]:
        """List automations in workspace."""
        stmt = select(Automation).where(
            Automation.workspace_id == workspace_id,
            Automation.deleted_at.is_(None),
        )
        if is_active is not None:
            stmt = stmt.where(Automation.is_active == is_active)
        stmt = stmt.order_by(Automation.created_at.desc())
        res = await db.execute(stmt)
        return [AutomationResponse.model_validate(a) for a in res.scalars().all()]

    async def update_automation(
        self,
        db: AsyncSession,
        automation_id: uuid.UUID,
        payload: AutomationUpdateRequest,
        workspace_id: uuid.UUID,
        user_id: Optional[uuid.UUID] = None,
    ) -> AutomationResponse:
        """Update automation fields and recalculate schedule if cron expression changed."""
        automation = await self._get_automation_entity(db, automation_id, workspace_id)

        if payload.name is not None:
            automation.name = payload.name
        if payload.description is not None:
            automation.description = payload.description
        if payload.prompt_template is not None:
            automation.prompt_template = payload.prompt_template
        if payload.assigned_skill_id is not None:
            automation.assigned_skill_id = payload.assigned_skill_id
        if payload.autonomy_level is not None:
            automation.autonomy_level = payload.autonomy_level
        if payload.is_active is not None:
            automation.is_active = payload.is_active

        cron_changed = payload.cron_expression is not None and payload.cron_expression != automation.cron_expression
        tz_changed = payload.timezone is not None and payload.timezone != automation.timezone

        if cron_changed:
            validate_cron_expression(payload.cron_expression)
            automation.cron_expression = payload.cron_expression
        if tz_changed:
            automation.timezone = payload.timezone

        if (cron_changed or tz_changed) and automation.cron_expression:
            now = datetime.now(timezone.utc)
            automation.next_run_at = calculate_next_run(
                automation.cron_expression, base_time=now, timezone_str=automation.timezone
            )

        await db.flush()
        await audit_service.record_event(
            db=db,
            workspace_id=workspace_id,
            actor_type="user" if user_id else "system",
            actor_id=str(user_id) if user_id else "system",
            action="automation.updated",
            resource_type="automation",
            resource_id=str(automation.id),
            details={"name": automation.name, "is_active": automation.is_active},
        )
        return AutomationResponse.model_validate(automation)

    async def toggle_automation(
        self,
        db: AsyncSession,
        automation_id: uuid.UUID,
        workspace_id: uuid.UUID,
        is_active: bool,
        user_id: Optional[uuid.UUID] = None,
    ) -> AutomationResponse:
        """Enable or disable an automation schedule."""
        automation = await self._get_automation_entity(db, automation_id, workspace_id)
        automation.is_active = is_active
        if is_active and automation.cron_expression:
            now = datetime.now(timezone.utc)
            automation.next_run_at = calculate_next_run(
                automation.cron_expression, base_time=now, timezone_str=automation.timezone
            )
        await db.flush()
        await audit_service.record_event(
            db=db,
            workspace_id=workspace_id,
            actor_type="user" if user_id else "system",
            actor_id=str(user_id) if user_id else "system",
            action="automation.enabled" if is_active else "automation.disabled",
            resource_type="automation",
            resource_id=str(automation.id),
            details={"is_active": is_active},
        )
        return AutomationResponse.model_validate(automation)

    async def delete_automation(
        self,
        db: AsyncSession,
        automation_id: uuid.UUID,
        workspace_id: uuid.UUID,
        user_id: Optional[uuid.UUID] = None,
    ) -> None:
        """Soft-delete an automation."""
        automation = await self._get_automation_entity(db, automation_id, workspace_id)
        automation.deleted_at = datetime.now(timezone.utc)
        automation.is_active = False
        await db.flush()
        await audit_service.record_event(
            db=db,
            workspace_id=workspace_id,
            actor_type="user" if user_id else "system",
            actor_id=str(user_id) if user_id else "system",
            action="automation.deleted",
            resource_type="automation",
            resource_id=str(automation.id),
            details={"name": automation.name},
        )

    async def reset_circuit_breaker(
        self,
        db: AsyncSession,
        automation_id: uuid.UUID,
        workspace_id: uuid.UUID,
        user_id: Optional[uuid.UUID] = None,
    ) -> AutomationResponse:
        """Reset an OPEN circuit breaker to CLOSED and resume scheduling."""
        automation = await self._get_automation_entity(db, automation_id, workspace_id)
        automation.circuit_state = "CLOSED"
        automation.circuit_opened_at = None
        automation.failure_streak = 0
        if automation.is_active and automation.cron_expression:
            now = datetime.now(timezone.utc)
            automation.next_run_at = calculate_next_run(
                automation.cron_expression, base_time=now, timezone_str=automation.timezone
            )
        await db.flush()
        await audit_service.record_event(
            db=db,
            workspace_id=workspace_id,
            actor_type="user" if user_id else "system",
            actor_id=str(user_id) if user_id else "system",
            action="automation.circuit_reset",
            resource_type="automation",
            resource_id=str(automation.id),
            details={"circuit_state": "CLOSED"},
        )
        return AutomationResponse.model_validate(automation)

    # ==========================================
    # 2. Transactional Claiming & Scheduling
    # ==========================================

    async def claim_due_automations(
        self,
        db: AsyncSession,
        worker_id: str,
        limit: int = 10,
    ) -> List[AutomationRun]:
        """Claim due automations using PostgreSQL FOR UPDATE SKIP LOCKED.

        Atomically transitions due automations, advances schedule timestamp, and creates claimed runs.
        """
        from app.services.kill_switch import kill_switch
        if kill_switch.is_active():
            logger.warning("SchedulerService: Claiming suspended because Emergency Kill Switch is active")
            return []

        now = datetime.now(timezone.utc)

        # 1. Select Due Automations with Row-Level Lock
        stmt = (
            select(Automation)
            .where(
                Automation.is_active.is_(True),
                Automation.circuit_state == "CLOSED",
                Automation.next_run_at <= now,
                Automation.deleted_at.is_(None),
            )
            .order_by(Automation.next_run_at.asc())
            .limit(limit)
        )

        # PostgreSQL FOR UPDATE SKIP LOCKED
        if db.bind and db.bind.dialect.name == "postgresql":
            stmt = stmt.with_for_update(skip_locked=True)

        res = await db.execute(stmt)
        due_automations = res.scalars().all()
        claimed_runs: List[AutomationRun] = []

        for auto in due_automations:
            scheduled_for = auto.next_run_at or now
            # Canonical Idempotency Key
            idempotency_key = f"auto_{auto.id}_{int(scheduled_for.timestamp())}"

            # Check if run already exists for this exact slot
            existing_run = await db.execute(
                select(AutomationRun).where(AutomationRun.idempotency_key == idempotency_key)
            )
            if existing_run.scalar_one_or_none() is not None:
                # Advance next_run_at and skip to prevent duplicate pickup
                if auto.cron_expression:
                    auto.next_run_at = calculate_next_run(
                        auto.cron_expression, base_time=now, timezone_str=auto.timezone
                    )
                continue

            # Calculate next scheduled execution
            if auto.cron_expression:
                auto.next_run_at = calculate_next_run(
                    auto.cron_expression, base_time=now, timezone_str=auto.timezone
                )
            auto.last_run_at = now
            auto.total_runs += 1

            # Create Claimed AutomationRun entity
            claim_expiry = now + timedelta(minutes=15)
            run = AutomationRun(
                automation_id=auto.id,
                workspace_id=auto.workspace_id,
                scheduled_for=scheduled_for,
                status="claimed",
                attempt=1,
                retry_count=0,
                max_retries=3,
                claimed_at=now,
                claim_expires_at=claim_expiry,
                claimed_by=worker_id,
                idempotency_key=idempotency_key,
            )
            db.add(run)
            claimed_runs.append(run)

        if claimed_runs:
            await db.flush()
            logger.info(f"Scheduler: Worker {worker_id} claimed {len(claimed_runs)} due automation runs")

        return claimed_runs

    async def recover_expired_leases(
        self,
        db: AsyncSession,
        worker_id: str,
        limit: int = 10,
    ) -> List[AutomationRun]:
        """Recover orphaned or crashed automation runs whose leases have expired."""
        now = datetime.now(timezone.utc)
        stmt = (
            select(AutomationRun)
            .where(
                AutomationRun.status.in_(["claimed", "running"]),
                AutomationRun.claim_expires_at < now,
            )
            .order_by(AutomationRun.claim_expires_at.asc())
            .limit(limit)
        )
        if db.bind and db.bind.dialect.name == "postgresql":
            stmt = stmt.with_for_update(skip_locked=True)

        res = await db.execute(stmt)
        expired_runs = res.scalars().all()
        recovered: List[AutomationRun] = []

        for run in expired_runs:
            # Re-lease run
            run.status = "claimed"
            run.claimed_at = now
            run.claim_expires_at = now + timedelta(minutes=15)
            run.claimed_by = worker_id
            recovered.append(run)
            logger.warning(
                f"Scheduler: Recovered expired lease on AutomationRun {run.id} (Automation: {run.automation_id})"
            )

        if recovered:
            await db.flush()
        return recovered

    # ==========================================
    # 3. Execution & Governed Task Dispatching
    # ==========================================

    async def execute_claimed_run(
        self,
        db: AsyncSession,
        run_id: uuid.UUID,
        worker_id: str,
    ) -> AutomationRunResponse:
        """Execute a claimed run by creating and dispatching a governed AURA Task."""
        stmt = (
            select(AutomationRun)
            .options(selectinload(AutomationRun.automation))
            .where(AutomationRun.id == run_id)
        )
        res = await db.execute(stmt)
        run = res.scalar_one_or_none()
        if not run:
            raise EntityNotFoundError("AutomationRun", str(run_id))

        auto = run.automation
        if not auto or not auto.is_active or auto.circuit_state == "OPEN" or auto.deleted_at is not None:
            now = datetime.now(timezone.utc)
            run.status = "cancelled"
            run.completed_at = now
            run.error_code = "AUTOMATION_INACTIVE"
            run.error_summary = "Parent automation is disabled, deleted, or circuit-breaker is open."
            await db.flush()
            logger.warning(
                f"Scheduler: Cancelled run {run.id} because parent automation {run.automation_id} is inactive/open/deleted"
            )
            return AutomationRunResponse.model_validate(run)

        now = datetime.now(timezone.utc)
        run.status = "running"
        run.started_at = now

        try:
            # Create downstream Governed Task via TaskService
            task_payload = TaskCreateRequest(
                workspace_id=run.workspace_id,
                title=f"Automation: {auto.name}",
                goal=auto.prompt_template,
                autonomy_level=min(auto.autonomy_level, 4),
                idempotency_key=run.idempotency_key,
                timeout_seconds=900,  # 15 minutes timeout ceiling
            )
            task_resp = await self.task_service.create_task(
                db=db,
                payload=task_payload,
                user_id=auto.created_by,
            )
            run.task_id = task_resp.id

            # Mark Run Succeeded
            run.status = "succeeded"
            run.completed_at = datetime.now(timezone.utc)
            run.output_summary = f"Task {task_resp.id} initiated successfully in state '{task_resp.status}'"
            auto.last_success_at = datetime.now(timezone.utc)
            auto.failure_streak = 0

            await audit_service.record_event(
                db=db,
                workspace_id=run.workspace_id,
                actor_type="scheduler",
                actor_id=worker_id,
                action="automation.run_succeeded",
                resource_type="automation_run",
                resource_id=str(run.id),
                details={"automation_id": str(auto.id), "task_id": str(task_resp.id)},
            )
        except Exception as exc:
            logger.error(f"Scheduler: Failed executing run {run.id} for automation {auto.id}: {exc}")
            await self._handle_run_failure(db, run, auto, str(exc), worker_id)

        await db.flush()
        return AutomationRunResponse.model_validate(run)

    async def trigger_manual_run(
        self,
        db: AsyncSession,
        automation_id: uuid.UUID,
        workspace_id: uuid.UUID,
        user_id: Optional[uuid.UUID] = None,
    ) -> AutomationRunResponse:
        """Trigger an authorized immediate manual run of an automation."""
        auto = await self._get_automation_entity(db, automation_id, workspace_id)
        now = datetime.now(timezone.utc)
        idempotency_key = f"manual_{auto.id}_{int(now.timestamp())}_{random.randint(100, 999)}"

        run = AutomationRun(
            automation_id=auto.id,
            workspace_id=auto.workspace_id,
            scheduled_for=now,
            status="claimed",
            attempt=1,
            retry_count=0,
            max_retries=3,
            claimed_at=now,
            claim_expires_at=now + timedelta(minutes=15),
            claimed_by=f"manual_{user_id or 'admin'}",
            idempotency_key=idempotency_key,
        )
        db.add(run)
        await db.flush()

        # Execute run
        return await self.execute_claimed_run(db, run.id, worker_id=f"manual_{user_id or 'admin'}")

    async def _handle_run_failure(
        self,
        db: AsyncSession,
        run: AutomationRun,
        auto: Automation,
        error_msg: str,
        worker_id: str,
    ) -> None:
        """Handle execution failure, apply exponential retry sequence, and manage circuit breaker."""
        now = datetime.now(timezone.utc)
        run.error_code = "TASK_DISPATCH_FAILED"
        run.error_summary = error_msg

        if run.retry_count < run.max_retries:
            base_delay = RETRY_BASE_DELAYS[min(run.retry_count, len(RETRY_BASE_DELAYS) - 1)]
            jitter = random.uniform(1.0, 5.0)
            backoff_seconds = base_delay + jitter
            run.status = "retrying"
            run.retry_count += 1
            run.attempt += 1
            run.claim_expires_at = now + timedelta(seconds=backoff_seconds)
            logger.info(
                f"Scheduler: Scheduling Retry {run.retry_count}/{run.max_retries} for Run {run.id} in {backoff_seconds:.1f}s"
            )
            await audit_service.record_event(
                db=db,
                workspace_id=run.workspace_id,
                actor_type="scheduler",
                actor_id=worker_id,
                action="automation.retry_scheduled",
                resource_type="automation_run",
                resource_id=str(run.id),
                details={"retry_count": run.retry_count, "backoff_seconds": backoff_seconds},
            )
        else:
            run.status = "failed"
            run.completed_at = now
            auto.total_failures += 1
            auto.failure_streak += 1
            auto.last_failure_at = now

            # 3-Strike Circuit Breaker
            if auto.failure_streak >= 3:
                auto.circuit_state = "OPEN"
                auto.circuit_opened_at = now
                logger.error(
                    f"Scheduler: Circuit Breaker OPENED for Automation {auto.id} after {auto.failure_streak} consecutive failures"
                )
                await audit_service.record_event(
                    db=db,
                    workspace_id=run.workspace_id,
                    actor_type="scheduler",
                    actor_id=worker_id,
                    action="automation.circuit_opened",
                    resource_type="automation",
                    resource_id=str(auto.id),
                    details={"failure_streak": auto.failure_streak, "error": error_msg},
                )

    # ==========================================
    # 4. Runs Telemetry & Query
    # ==========================================

    async def list_runs(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        automation_id: Optional[uuid.UUID] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[AutomationRunResponse]:
        """List execution runs for an automation or workspace."""
        if automation_id:
            # Enforce that parent automation exists in this workspace
            await self._get_automation_entity(db, automation_id, workspace_id)

        stmt = select(AutomationRun).where(AutomationRun.workspace_id == workspace_id)
        if automation_id:
            stmt = stmt.where(AutomationRun.automation_id == automation_id)
        if status:
            stmt = stmt.where(AutomationRun.status == status)
        stmt = stmt.order_by(AutomationRun.scheduled_for.desc()).limit(limit).offset(offset)
        res = await db.execute(stmt)
        return [AutomationRunResponse.model_validate(r) for r in res.scalars().all()]

    async def get_run(
        self,
        db: AsyncSession,
        run_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> AutomationRunResponse:
        """Retrieve individual run details."""
        stmt = select(AutomationRun).where(
            AutomationRun.id == run_id,
            AutomationRun.workspace_id == workspace_id,
        )
        res = await db.execute(stmt)
        run = res.scalar_one_or_none()
        if not run:
            raise EntityNotFoundError("AutomationRun", str(run_id))
        return AutomationRunResponse.model_validate(run)

    async def _get_automation_entity(
        self,
        db: AsyncSession,
        automation_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> Automation:
        """Fetch internal entity enforcing workspace isolation."""
        stmt = select(Automation).where(
            Automation.id == automation_id,
            Automation.workspace_id == workspace_id,
            Automation.deleted_at.is_(None),
        )
        res = await db.execute(stmt)
        auto = res.scalar_one_or_none()
        if not auto:
            raise EntityNotFoundError("Automation", str(automation_id))
        return auto


scheduler_service = SchedulerService()
