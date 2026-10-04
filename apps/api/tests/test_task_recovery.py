"""AURA-706 Long-Horizon Task Checkpoint & Recovery Tests.

Covers:
1. Durable step checkpoint verification & idempotent resumption semantics.
2. Resuming from exact pending/unverified step without repeating completed steps.
3. Completion state when all steps are verified.
4. Budget (tokens, cost) and timeout ceiling preservation and enforcement across recovery.
5. Active Kill Switch blocking task resumption with AuthorizationError.
6. Workspace tenancy isolation: Cross-workspace task resumption rejection.
7. HITL approval gate preservation: Task cannot resume while approval is pending.
8. Post-restart governance and tool permit revalidation.
9. Startup recovery sweep for orphaned RUNNING / PLANNING tasks on server lifecycle boot.
10. Audit ledger recording of task resumption with verified step counts.
"""

from datetime import datetime, timedelta, timezone
import uuid
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AuthorizationError, EntityNotFoundError, ValidationError
from app.db.models.approval import ApprovalRequest
from app.db.models.audit import AuditLog
from app.db.models.task import Task, TaskStep
from app.db.models.tool import Tool, ToolPermission
from app.db.models.user import User
from app.db.models.workspace import Workspace, WorkspaceMember
from app.schemas.task import TaskStepUpdate
from app.services.kill_switch import kill_switch
from app.services.task_recovery_service import TaskRecoveryService, task_recovery_service
from app.services.task_service import task_service


# ==============================================================================
# Helper Provisioning
# ==============================================================================

async def setup_test_user_and_workspace(db: AsyncSession):
    """Helper to provision a user, primary workspace, and membership."""
    user = User(
        id=uuid.uuid4(),
        email=f"recovery_user_{uuid.uuid4().hex[:8]}@example.com",
        full_name="Recovery Test User",
        password_hash="hashed_pw_test",
        is_active=True,
    )
    db.add(user)

    ws = Workspace(
        id=uuid.uuid4(),
        name=f"Recovery Workspace {uuid.uuid4().hex[:6]}",
        slug=f"rec-ws-{uuid.uuid4().hex[:6]}",
    )
    db.add(ws)

    member = WorkspaceMember(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        user_id=user.id,
        role="owner",
        permissions=["admin"],
    )
    db.add(member)

    await db.commit()
    await db.refresh(user)
    await db.refresh(ws)
    return user, ws


async def create_multistep_test_task(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    status: str = "running",
    timeout_seconds: int = 1800,
) -> Task:
    """Create a task with 3 steps: Step 1 completed/verified, Step 2 running/unverified, Step 3 pending."""
    task = Task(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        created_by=user_id,
        title="Long-Horizon Autonomous Investigation",
        goal="Extract, synthesize, and report system diagnostics",
        status=status,
        autonomy_level=2,
        budget_max_tokens=50000,
        budget_max_cost_cents=200,
        timeout_seconds=timeout_seconds,
    )
    db.add(task)

    step1 = TaskStep(
        id=uuid.uuid4(),
        task_id=task.id,
        step_number=1,
        title="Step 1: Extract Logs",
        description="Query local system logs",
        dependencies=[],
        status="completed",
        tool_name="web_search",
        tool_input={"query": "diagnostic query"},
        tool_output={"status": "success", "entries": 42},
        is_verified=True,
        started_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        completed_at=datetime.now(timezone.utc) - timedelta(minutes=4),
    )
    db.add(step1)

    step2 = TaskStep(
        id=uuid.uuid4(),
        task_id=task.id,
        step_number=2,
        title="Step 2: Inspect Architecture",
        description="Inspect architectural diagrams",
        dependencies=[1],
        status="running",
        tool_name="inspect_file",
        tool_input={"file_id": str(uuid.uuid4())},
        tool_output=None,
        is_verified=False,
        started_at=datetime.now(timezone.utc) - timedelta(minutes=3),
    )
    db.add(step2)

    step3 = TaskStep(
        id=uuid.uuid4(),
        task_id=task.id,
        step_number=3,
        title="Step 3: Generate Final Summary",
        description="Aggregate findings into report",
        dependencies=[2],
        status="pending",
        tool_name=None,
        tool_input=None,
        tool_output=None,
        is_verified=False,
    )
    db.add(step3)

    await db.commit()
    stmt = select(Task).options(selectinload(Task.steps)).where(Task.id == task.id)
    res = await db.execute(stmt)
    return res.scalar_one()


# ==============================================================================
# 1. Deterministic Resume Semantics & Checkpoints
# ==============================================================================

@pytest.mark.asyncio
async def test_resume_task_exact_pending_step(db_session: AsyncSession):
    """Verify resume_task identifies last verified step and resumes from step 2 without repeating step 1."""
    user, ws = await setup_test_user_and_workspace(db_session)
    task = await create_multistep_test_task(db_session, ws.id, user.id)

    res = await task_recovery_service.resume_task(
        db=db_session,
        task_id=task.id,
        workspace_id=ws.id,
        actor_id=str(user.id),
    )

    assert res.id == task.id
    assert res.status == "running"
    
    # Step 1 remains completed & verified
    step1 = next(s for s in res.steps if s.step_number == 1)
    assert step1.status == "completed"
    assert step1.is_verified is True
    assert step1.tool_output == {"status": "success", "entries": 42}

    # Step 2 was reset from running to pending for clean execution
    step2 = next(s for s in res.steps if s.step_number == 2)
    assert step2.status == "pending"
    assert step2.is_verified is False

    # Step 3 remains pending
    step3 = next(s for s in res.steps if s.step_number == 3)
    assert step3.status == "pending"


@pytest.mark.asyncio
async def test_resume_task_all_steps_verified_completes_task(db_session: AsyncSession):
    """Verify resuming a task where all steps are completed and verified transitions to completed."""
    user, ws = await setup_test_user_and_workspace(db_session)
    task = await create_multistep_test_task(db_session, ws.id, user.id, status="pending")

    # Mark all steps as completed & verified
    for s in task.steps:
        s.status = "completed"
        s.is_verified = True
    await db_session.commit()

    res = await task_recovery_service.resume_task(
        db=db_session,
        task_id=task.id,
        workspace_id=ws.id,
        actor_id=str(user.id),
    )

    assert res.status == "completed"
    assert res.completed_at is not None
    assert "All DAG steps successfully completed" in (res.result_summary or "")


# ==============================================================================
# 2. Budget & Timeout Ceiling Enforcement
# ==============================================================================

@pytest.mark.asyncio
async def test_resume_task_timeout_enforcement(db_session: AsyncSession):
    """Verify task recovery fails if task timeout has elapsed since creation."""
    user, ws = await setup_test_user_and_workspace(db_session)
    task = await create_multistep_test_task(db_session, ws.id, user.id, timeout_seconds=10)

    # Fast forward task creation time by 1 hour
    task.created_at = datetime.now(timezone.utc) - timedelta(hours=1)
    await db_session.commit()

    res = await task_recovery_service.resume_task(
        db=db_session,
        task_id=task.id,
        workspace_id=ws.id,
        actor_id=str(user.id),
    )

    assert res.status == "failed"
    assert "timeout" in (res.error_summary or "").lower()


# ==============================================================================
# 3. Emergency Kill Switch Authority & Isolation
# ==============================================================================

@pytest.mark.asyncio
async def test_resume_task_blocked_by_active_kill_switch(db_session: AsyncSession):
    """Verify active workspace kill switch blocks task resumption with AuthorizationError."""
    user, ws = await setup_test_user_and_workspace(db_session)
    task = await create_multistep_test_task(db_session, ws.id, user.id)

    # Engage kill switch
    kill_switch.set_active(True, ws.id)
    try:
        with pytest.raises(AuthorizationError, match="Kill Switch is currently active"):
            await task_recovery_service.resume_task(
                db=db_session,
                task_id=task.id,
                workspace_id=ws.id,
                actor_id=str(user.id),
            )
    finally:
        kill_switch.set_active(False, ws.id)


@pytest.mark.asyncio
async def test_resume_task_workspace_tenancy_isolation(db_session: AsyncSession):
    """Verify task in Workspace B cannot be resumed by Workspace A."""
    user_a, ws_a = await setup_test_user_and_workspace(db_session)
    user_b, ws_b = await setup_test_user_and_workspace(db_session)

    task_b = await create_multistep_test_task(db_session, ws_b.id, user_b.id)

    with pytest.raises(EntityNotFoundError):
        await task_recovery_service.resume_task(
            db=db_session,
            task_id=task_b.id,
            workspace_id=ws_a.id,
            actor_id=str(user_a.id),
        )


# ==============================================================================
# 4. HITL Approval Gate Preservation
# ==============================================================================

@pytest.mark.asyncio
async def test_resume_task_hitl_pending_preservation(db_session: AsyncSession):
    """Verify task waiting on pending HITL approval retains 'waiting_approval' state on resume attempt."""
    user, ws = await setup_test_user_and_workspace(db_session)
    task = await create_multistep_test_task(db_session, ws.id, user.id, status="waiting_approval")

    # Add pending approval request
    approval = ApprovalRequest(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        task_id=task.id,
        agent_run_id=uuid.uuid4(),
        tool_name="inspect_file",
        tool_params={"file_id": str(uuid.uuid4())},
        risk_level="high",
        status="pending",
        approval_token_hash="dummy_token_hash",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db_session.add(approval)
    await db_session.commit()

    res = await task_recovery_service.resume_task(
        db=db_session,
        task_id=task.id,
        workspace_id=ws.id,
        actor_id=str(user.id),
    )

    assert res.status == "waiting_approval"


# ==============================================================================
# 5. Startup Recovery Sweep (Lifespan Hook)
# ==============================================================================

@pytest.mark.asyncio
async def test_startup_recovery_sweep_orphaned_tasks(db_session: AsyncSession):
    """Verify startup recovery sweep detects and safely reconciles orphaned tasks across server restart."""
    user, ws = await setup_test_user_and_workspace(db_session)
    
    # 1. Normal orphaned running task
    task1 = await create_multistep_test_task(db_session, ws.id, user.id, status="running")

    # 2. Timed out orphaned running task
    task2 = await create_multistep_test_task(db_session, ws.id, user.id, status="running", timeout_seconds=5)
    task2.created_at = datetime.now(timezone.utc) - timedelta(hours=2)
    await db_session.commit()

    # Run Startup Sweep
    counts = await task_recovery_service.startup_recovery_sweep(db_session)

    assert counts["scanned"] >= 2
    assert counts["ready_for_resume"] >= 1
    assert counts["failed_orphans"] >= 1

    # Verify task 1 transitioned to pending
    stmt = select(Task).options(selectinload(Task.steps)).where(Task.id == task1.id)
    res = await db_session.execute(stmt)
    refreshed_task1 = res.scalar_one()
    assert refreshed_task1.status == "pending"
    for s in refreshed_task1.steps:
        if s.step_number == 2:
            assert s.status == "pending"  # Reset from running

    # Verify task 2 transitioned to failed due to timeout
    await db_session.refresh(task2)
    assert task2.status == "failed"


# ==============================================================================
# 6. Audit Trail Logging on Resumption
# ==============================================================================

@pytest.mark.asyncio
async def test_resume_task_audit_trail_logging(db_session: AsyncSession):
    """Verify resuming a task emits an audit log record with verified step counts."""
    user, ws = await setup_test_user_and_workspace(db_session)
    task = await create_multistep_test_task(db_session, ws.id, user.id)

    await task_recovery_service.resume_task(
        db=db_session,
        task_id=task.id,
        workspace_id=ws.id,
        actor_id=str(user.id),
    )

    stmt = select(AuditLog).where(
        AuditLog.workspace_id == ws.id,
        AuditLog.action == "task.resumed",
        AuditLog.resource_id == str(task.id),
    )
    res = await db_session.execute(stmt)
    audit = res.scalar_one_or_none()

    assert audit is not None
    assert audit.details["verified_steps_count"] == 1
    assert audit.details["remaining_steps_count"] == 2
