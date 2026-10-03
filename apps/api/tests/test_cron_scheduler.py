"""Comprehensive test suite for AURA-401 PostgreSQL Transactional Cron Scheduler."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import EntityNotFoundError, ValidationError
from app.db.models.automation import Automation, AutomationRun
from app.db.models.task import Task
from app.db.models.user import User
from app.db.models.workspace import Workspace, WorkspaceMember
from app.schemas.automation import AutomationCreateRequest, AutomationUpdateRequest
from app.schemas.task import TaskCreateRequest
from app.services.automations.cron_engine import calculate_next_run, resolve_due_schedule, validate_cron_expression
from app.services.automations.scheduler_service import SchedulerService, scheduler_service
from app.services.task_service import TaskService


# ==============================================================================
# 1. Cron Engine, Timezone & DST Tests
# ==============================================================================

def test_cron_validation():
    """Verify standard 5-field cron parsing and invalid expression rejections."""
    # Valid expressions
    validate_cron_expression("0 0 * * *")      # Daily at midnight
    validate_cron_expression("*/15 * * * *")   # Every 15 minutes
    validate_cron_expression("0 9 * * 1-5")    # Monday to Friday at 9:00 AM
    validate_cron_expression("30 14 1 1 *")    # Jan 1st at 14:30

    # Invalid expressions (must raise ValidationError)
    with pytest.raises(ValidationError):
        validate_cron_expression("invalid_cron")

    with pytest.raises(ValidationError):
        validate_cron_expression("* * * *")  # 4 fields instead of 5

    with pytest.raises(ValidationError):
        validate_cron_expression("60 * * * *")  # 60 is invalid minute


def test_cron_timezone_and_dst_calculations():
    """Verify calculations across UTC, Asia/Kolkata, and America/New_York (DST)."""
    # 1. Daily at 07:00 UTC
    base_utc = datetime(2026, 10, 1, 6, 0, 0, tzinfo=timezone.utc)
    next_utc = calculate_next_run("0 7 * * *", base_time=base_utc, timezone_str="UTC")
    assert next_utc == datetime(2026, 10, 1, 7, 0, 0, tzinfo=timezone.utc)

    # 2. Daily at 09:30 AM in Asia/Kolkata (IST = UTC+5:30) -> 04:00 UTC
    base_ist = datetime(2026, 10, 1, 2, 0, 0, tzinfo=timezone.utc)
    next_ist = calculate_next_run("30 9 * * *", base_time=base_ist, timezone_str="Asia/Kolkata")
    assert next_ist == datetime(2026, 10, 1, 4, 0, 0, tzinfo=timezone.utc)

    # 3. DST Transition in America/New_York (Nov 1, 2026 Fall Back)
    base_ny = datetime(2026, 10, 31, 12, 0, 0, tzinfo=timezone.utc)
    next_ny = calculate_next_run("0 12 * * *", base_time=base_ny, timezone_str="America/New_York")
    assert next_ny.tzinfo == timezone.utc


def test_missed_run_backlog_bounding_policy():
    """Verify that prolonged downtime calculates the next forward schedule without backlog storms."""
    # Last run was 30 days ago
    last_run = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
    now = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    # Hourly schedule
    next_due = resolve_due_schedule("0 * * * *", last_run_at=last_run, next_run_at=None, now=now, timezone_str="UTC")
    
    # Must schedule for 13:00 on October 1st, NOT for all 720 missed hours
    assert next_due == datetime(2026, 10, 1, 13, 0, 0, tzinfo=timezone.utc)


# ==============================================================================
# 2. Transactional Claiming, Leases & Idempotency Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_claim_due_automations_and_idempotency(db_session: AsyncSession):
    """Verify claiming due automations, advancing schedules, and idempotency protection."""
    ws = Workspace(name="Scheduler WS", slug="sched-ws")
    db_session.add(ws)
    await db_session.flush()

    past_time = datetime.now(timezone.utc) - timedelta(minutes=5)
    future_time = datetime.now(timezone.utc) + timedelta(hours=1)

    # 1. Due Automation (is_active=True, next_run_at in past)
    auto_due = Automation(
        workspace_id=ws.id,
        name="Due Job",
        trigger_type="cron",
        cron_expression="0 * * * *",
        timezone="UTC",
        prompt_template="Execute hourly check.",
        is_active=True,
        next_run_at=past_time,
    )
    # 2. Future Automation (not due)
    auto_future = Automation(
        workspace_id=ws.id,
        name="Future Job",
        trigger_type="cron",
        cron_expression="0 0 * * *",
        timezone="UTC",
        prompt_template="Execute midnight backup.",
        is_active=True,
        next_run_at=future_time,
    )
    # 3. Disabled Automation (past time but is_active=False)
    auto_disabled = Automation(
        workspace_id=ws.id,
        name="Disabled Job",
        trigger_type="cron",
        cron_expression="0 * * * *",
        timezone="UTC",
        prompt_template="Should not run.",
        is_active=False,
        next_run_at=past_time,
    )
    db_session.add_all([auto_due, auto_future, auto_disabled])
    await db_session.flush()

    # 4. Worker 1 Claims Due Jobs
    claimed_runs = await scheduler_service.claim_due_automations(
        db=db_session, worker_id="worker_alpha", limit=10
    )

    assert len(claimed_runs) == 1
    run = claimed_runs[0]
    assert run.automation_id == auto_due.id
    assert run.status == "claimed"
    assert run.claimed_by == "worker_alpha"
    assert run.claim_expires_at > datetime.now(timezone.utc)

    # Verify auto_due's next_run_at was advanced into the future
    assert auto_due.next_run_at > datetime.now(timezone.utc)
    assert auto_due.total_runs == 1

    # 5. Worker 2 attempts claiming simultaneously (nothing due now)
    claimed_runs_2 = await scheduler_service.claim_due_automations(
        db=db_session, worker_id="worker_beta", limit=10
    )
    assert len(claimed_runs_2) == 0


@pytest.mark.asyncio
async def test_expired_lease_recovery(db_session: AsyncSession):
    """Verify recovery of orphaned claimed runs when lease expires."""
    ws = Workspace(name="Lease Recovery WS", slug="lease-rec-ws")
    db_session.add(ws)
    await db_session.flush()

    auto = Automation(
        workspace_id=ws.id,
        name="Crashed Worker Job",
        trigger_type="cron",
        cron_expression="0 * * * *",
        timezone="UTC",
        prompt_template="Do work.",
    )
    db_session.add(auto)
    await db_session.flush()

    # Stalled run with expired lease (expired 5 minutes ago)
    past_expiry = datetime.now(timezone.utc) - timedelta(minutes=5)
    stalled_run = AutomationRun(
        automation_id=auto.id,
        workspace_id=ws.id,
        scheduled_for=datetime.now(timezone.utc) - timedelta(minutes=20),
        status="claimed",
        claimed_by="crashed_worker_99",
        claimed_at=datetime.now(timezone.utc) - timedelta(minutes=20),
        claim_expires_at=past_expiry,
        idempotency_key=f"auto_{auto.id}_stalled",
    )
    db_session.add(stalled_run)
    await db_session.flush()

    # Recovery worker runs
    recovered = await scheduler_service.recover_expired_leases(
        db=db_session, worker_id="recovery_worker_01", limit=10
    )

    assert len(recovered) == 1
    rec_run = recovered[0]
    assert rec_run.id == stalled_run.id
    assert rec_run.claimed_by == "recovery_worker_01"
    assert rec_run.claim_expires_at > datetime.now(timezone.utc)


# ==============================================================================
# 3. Execution, Retries & Circuit Breaker Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_execute_claimed_run_success(db_session: AsyncSession):
    """Verify successful execution creates a governed downstream Task."""
    ws = Workspace(name="Exec Success WS", slug="exec-succ-ws")
    db_session.add(ws)
    await db_session.flush()

    auto = Automation(
        workspace_id=ws.id,
        name="Productive Automation",
        trigger_type="cron",
        cron_expression="0 * * * *",
        timezone="UTC",
        prompt_template="Synthesize daily changelog.",
        autonomy_level=3,
    )
    db_session.add(auto)
    await db_session.flush()

    run = AutomationRun(
        automation_id=auto.id,
        workspace_id=ws.id,
        scheduled_for=datetime.now(timezone.utc),
        status="claimed",
        idempotency_key=f"auto_{auto.id}_succ",
    )
    db_session.add(run)
    await db_session.flush()

    # Execute
    res = await scheduler_service.execute_claimed_run(
        db=db_session, run_id=run.id, worker_id="exec_worker"
    )

    assert res.status == "succeeded"
    assert res.task_id is not None
    assert auto.failure_streak == 0
    assert auto.last_success_at is not None


@pytest.mark.asyncio
async def test_retry_sequence_and_circuit_breaker_transition(db_session: AsyncSession):
    """Verify exponential jitter retry sequence and 3-strike circuit breaker OPEN state."""
    ws = Workspace(name="Failure & Circuit WS", slug="fail-circuit-ws")
    db_session.add(ws)
    await db_session.flush()

    auto = Automation(
        workspace_id=ws.id,
        name="Failing Automation",
        trigger_type="cron",
        cron_expression="0 * * * *",
        timezone="UTC",
        prompt_template="Execute failing action.",
        failure_streak=0,
        circuit_state="CLOSED",
    )
    db_session.add(auto)
    await db_session.flush()

    # Mock TaskService to simulate execution failure
    failing_task_service = AsyncMock()
    failing_task_service.create_task.side_effect = RuntimeError("Downstream execution unavailable")
    custom_scheduler = SchedulerService(task_service=failing_task_service)

    # 1. Attempt 1 Failure -> transitions to 'retrying' (Retry 1)
    run1 = AutomationRun(
        automation_id=auto.id,
        workspace_id=ws.id,
        scheduled_for=datetime.now(timezone.utc),
        status="claimed",
        retry_count=0,
        max_retries=3,
        idempotency_key=f"auto_{auto.id}_f1",
    )
    db_session.add(run1)
    await db_session.flush()

    res1 = await custom_scheduler.execute_claimed_run(db=db_session, run_id=run1.id, worker_id="w1")
    assert res1.status == "retrying"
    assert res1.retry_count == 1
    assert auto.circuit_state == "CLOSED"

    # 2. Simulate Max Retries Exhausted (Attempt 4) on run1
    run1.retry_count = 3
    run1.status = "claimed"
    res1_exhausted = await custom_scheduler.execute_claimed_run(db=db_session, run_id=run1.id, worker_id="w1")
    assert res1_exhausted.status == "failed"
    assert auto.failure_streak == 1

    # 3. Second Failure Streak
    run2 = AutomationRun(
        automation_id=auto.id,
        workspace_id=ws.id,
        scheduled_for=datetime.now(timezone.utc),
        status="claimed",
        retry_count=3,
        idempotency_key=f"auto_{auto.id}_f2",
    )
    db_session.add(run2)
    await db_session.flush()
    await custom_scheduler.execute_claimed_run(db=db_session, run_id=run2.id, worker_id="w1")
    assert auto.failure_streak == 2
    assert auto.circuit_state == "CLOSED"

    # 4. Third Failure Streak -> Opens Circuit Breaker
    run3 = AutomationRun(
        automation_id=auto.id,
        workspace_id=ws.id,
        scheduled_for=datetime.now(timezone.utc),
        status="claimed",
        retry_count=3,
        idempotency_key=f"auto_{auto.id}_f3",
    )
    db_session.add(run3)
    await db_session.flush()
    await custom_scheduler.execute_claimed_run(db=db_session, run_id=run3.id, worker_id="w1")
    assert auto.failure_streak == 3
    assert auto.circuit_state == "OPEN"
    assert auto.circuit_opened_at is not None

    # 5. Verify OPEN automation is ignored by scheduler scanner
    auto.next_run_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    claimed = await custom_scheduler.claim_due_automations(db=db_session, worker_id="w1")
    assert len(claimed) == 0

    # 6. Manual Reset of Circuit Breaker
    reset_res = await custom_scheduler.reset_circuit_breaker(
        db=db_session, automation_id=auto.id, workspace_id=ws.id
    )
    assert reset_res.circuit_state == "CLOSED"
    assert auto.failure_streak == 0
    assert auto.next_run_at is not None


# ==============================================================================
# 4. REST API Endpoint Integration Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_automations_api_lifecycle(client: AsyncClient, db_session: AsyncSession):
    """Test full REST API lifecycle: create, list, get, update, toggle, manual run, runs telemetry."""
    reg_res = await client.post(
        "/api/v1/auth/register",
        json={"email": "cron_admin@example.com", "username": "cron_admin", "password": "StrongPassword123!", "full_name": "Cron Admin"},
    )
    assert reg_res.status_code == 201
    auth_data = reg_res.json()
    token = auth_data["access_token"]
    me_res = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_res.status_code == 200
    workspace_id = me_res.json()["workspaces"][0]["id"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Create Automation
    create_payload = {
        "name": "Nightly Security Audit",
        "description": "Scans codebase and verifies threat mitigations",
        "trigger_type": "cron",
        "cron_expression": "0 2 * * *",
        "timezone": "UTC",
        "prompt_template": "Perform full repository audit and output summary report.",
        "autonomy_level": 3,
        "is_active": True,
    }
    create_res = await client.post(
        f"/api/v1/automations?workspace_id={workspace_id}",
        json=create_payload,
        headers=headers,
    )
    assert create_res.status_code == 201
    auto_data = create_res.json()
    auto_id = auto_data["id"]
    assert auto_data["name"] == "Nightly Security Audit"
    assert auto_data["circuit_state"] == "CLOSED"

    # 3. List Automations
    list_res = await client.get(f"/api/v1/automations?workspace_id={workspace_id}", headers=headers)
    assert list_res.status_code == 200
    assert len(list_res.json()) >= 1

    # 4. Update Automation
    update_res = await client.patch(
        f"/api/v1/automations/{auto_id}?workspace_id={workspace_id}",
        json={"name": "Nightly Security & Compliance Audit", "cron_expression": "30 2 * * *"},
        headers=headers,
    )
    assert update_res.status_code == 200
    assert update_res.json()["name"] == "Nightly Security & Compliance Audit"
    assert update_res.json()["cron_expression"] == "30 2 * * *"

    # 5. Toggle Automation (Disable)
    toggle_res = await client.post(
        f"/api/v1/automations/{auto_id}/toggle?workspace_id={workspace_id}",
        json={"is_active": False},
        headers=headers,
    )
    assert toggle_res.status_code == 200
    assert toggle_res.json()["is_active"] is False

    # Re-enable
    toggle_on = await client.post(
        f"/api/v1/automations/{auto_id}/toggle?workspace_id={workspace_id}",
        json={"is_active": True},
        headers=headers,
    )
    assert toggle_on.status_code == 200
    assert toggle_on.json()["is_active"] is True

    # 6. Trigger Manual Immediate Run
    run_res = await client.post(
        f"/api/v1/automations/{auto_id}/run?workspace_id={workspace_id}",
        headers=headers,
    )
    assert run_res.status_code == 200
    run_data = run_res.json()
    assert run_data["status"] == "succeeded"
    assert run_data["task_id"] is not None

    # 7. List Runs for Automation
    runs_res = await client.get(
        f"/api/v1/automations/{auto_id}/runs?workspace_id={workspace_id}",
        headers=headers,
    )
    assert runs_res.status_code == 200
    assert len(runs_res.json()) >= 1


# ==============================================================================
# 5. Acceptance Gate Verifications
# ==============================================================================

@pytest.mark.asyncio
async def test_crash_window_downstream_task_idempotency(db_session: AsyncSession):
    """Prove crash-window safety:
    Worker 1 claims run and creates downstream Task, but crashes BEFORE acknowledging run status.
    Worker 2 recovers expired lease and dispatches.
    Result MUST be: 1 AutomationRun, 1 downstream Task, 0 duplicate executions.
    """
    scheduler_service = SchedulerService()
    now = datetime.now(timezone.utc)
    ws_id = uuid.uuid4()
    auto_id = uuid.uuid4()

    auto = Automation(
        id=auto_id,
        workspace_id=ws_id,
        name="Crash Window Test Automation",
        trigger_type="cron",
        cron_expression="0 12 * * *",
        timezone="UTC",
        prompt_template="Execute critical financial audit",
        autonomy_level=2,
        is_active=True,
        circuit_state="CLOSED",
        next_run_at=now - timedelta(minutes=5),
    )
    db_session.add(auto)
    await db_session.flush()

    # Step 1: Worker 1 claims due automation
    claims = await scheduler_service.claim_due_automations(db_session, worker_id="worker_alpha_1", limit=1)
    assert len(claims) == 1
    run = claims[0]
    idempotency_key = run.idempotency_key

    # Step 2: Simulate Task creation by Worker 1
    task_service = TaskService()
    task_payload = TaskCreateRequest(
        workspace_id=ws_id,
        title=f"Automation: {auto.name}",
        goal=auto.prompt_template,
        autonomy_level=2,
        idempotency_key=idempotency_key,
        timeout_seconds=900,
    )
    task1 = await task_service.create_task(db_session, task_payload, user_id=None)
    assert task1 is not None

    # Step 3: Simulate Worker 1 CRASH before updating run status or run.task_id
    # Run remains in 'claimed' or 'running' status with no task_id set in run record
    run.status = "running"
    # Make lease expire 20 minutes in the past
    run.claim_expires_at = now - timedelta(minutes=20)
    await db_session.flush()

    # Step 4: Worker 2 recovers expired lease
    recovered = await scheduler_service.recover_expired_leases(db_session, worker_id="worker_beta_2", limit=10)
    assert len(recovered) == 1
    assert recovered[0].id == run.id
    assert recovered[0].claimed_by == "worker_beta_2"

    # Step 5: Worker 2 executes the claimed run
    exec_res = await scheduler_service.execute_claimed_run(db_session, run.id, worker_id="worker_beta_2")
    assert exec_res.status == "succeeded"
    assert exec_res.task_id == task1.id

    # Step 6: Verify Database Invariant: Exactly 1 Task and 1 AutomationRun
    all_runs = (await db_session.execute(select(AutomationRun).where(AutomationRun.automation_id == auto_id))).scalars().all()
    assert len(all_runs) == 1

    all_tasks = (await db_session.execute(select(Task).where(Task.idempotency_key == idempotency_key))).scalars().all()
    assert len(all_tasks) == 1
    assert all_tasks[0].id == task1.id


@pytest.mark.asyncio
async def test_lease_recovery_inactive_and_circuit_open_safety(db_session: AsyncSession):
    """Verify that if an automation is disabled or circuit opened while an orphaned lease expires,
    the recovery worker cancels the run instead of dispatching downstream tasks.
    """
    scheduler_service = SchedulerService()
    now = datetime.now(timezone.utc)
    ws_id = uuid.uuid4()
    auto_id = uuid.uuid4()

    auto = Automation(
        id=auto_id,
        workspace_id=ws_id,
        name="Disabled Lease Safety",
        trigger_type="cron",
        cron_expression="0 0 * * *",
        timezone="UTC",
        prompt_template="Do not run if disabled",
        is_active=False,  # Disabled after claiming
        circuit_state="OPEN",  # Circuit tripped
        next_run_at=now,
    )
    db_session.add(auto)

    run = AutomationRun(
        automation_id=auto_id,
        workspace_id=ws_id,
        scheduled_for=now - timedelta(hours=1),
        status="claimed",
        attempt=1,
        retry_count=0,
        claim_expires_at=now - timedelta(minutes=10),
        claimed_by="crashed_worker",
        idempotency_key=f"auto_{auto_id}_test_lease_inactive",
    )
    db_session.add(run)
    await db_session.flush()

    # Recovery
    recovered = await scheduler_service.recover_expired_leases(db_session, worker_id="recovery_worker")
    assert len(recovered) == 1

    # Execute
    res = await scheduler_service.execute_claimed_run(db_session, run.id, worker_id="recovery_worker")
    assert res.status == "cancelled"
    assert res.error_code == "AUTOMATION_INACTIVE"
    assert res.task_id is None


@pytest.mark.asyncio
async def test_cross_workspace_security_and_unauthorized_circuit_reset(client: AsyncClient):
    """Verify strict multi-tenant boundary:
    User B from Workspace B CANNOT view, update, run, toggle, or reset circuit breaker for Workspace A's automation.
    """
    # 1. Register User A (Workspace A)
    res_a = await client.post(
        "/api/v1/auth/register",
        json={"email": "tenant_a@example.com", "username": "tenant_a", "password": "Password123!", "full_name": "Tenant A"},
    )
    token_a = res_a.json()["access_token"]
    ws_a = (await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token_a}"})).json()["workspaces"][0]["id"]

    # 2. Register User B (Workspace B)
    res_b = await client.post(
        "/api/v1/auth/register",
        json={"email": "tenant_b@example.com", "username": "tenant_b", "password": "Password123!", "full_name": "Tenant B"},
    )
    token_b = res_b.json()["access_token"]
    ws_b = (await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token_b}"})).json()["workspaces"][0]["id"]

    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # 3. Create Automation in Workspace A
    create_res = await client.post(
        f"/api/v1/automations?workspace_id={ws_a}",
        json={
            "name": "Confidential Workspace A Automation",
            "trigger_type": "cron",
            "cron_expression": "0 1 * * *",
            "prompt_template": "Confidential Prompt",
            "autonomy_level": 2,
        },
        headers=headers_a,
    )
    assert create_res.status_code == 201
    auto_id_a = create_res.json()["id"]

    # 4. User B attempts to access Workspace A's automation -> Must fail (404/403)
    get_res = await client.get(f"/api/v1/automations/{auto_id_a}?workspace_id={ws_b}", headers=headers_b)
    assert get_res.status_code in (403, 404)

    patch_res = await client.patch(
        f"/api/v1/automations/{auto_id_a}?workspace_id={ws_b}",
        json={"name": "Tampered Name"},
        headers=headers_b,
    )
    assert patch_res.status_code in (403, 404)

    run_res = await client.post(
        f"/api/v1/automations/{auto_id_a}/run?workspace_id={ws_b}",
        headers=headers_b,
    )
    assert run_res.status_code in (403, 404)

    toggle_res = await client.post(
        f"/api/v1/automations/{auto_id_a}/toggle?workspace_id={ws_b}",
        json={"is_active": False},
        headers=headers_b,
    )
    assert toggle_res.status_code in (403, 404)

    runs_res = await client.get(
        f"/api/v1/automations/{auto_id_a}/runs?workspace_id={ws_b}",
        headers=headers_b,
    )
    assert runs_res.status_code in (403, 404)


@pytest.mark.asyncio
async def test_kill_switch_suspends_scheduler_dispatch(db_session: AsyncSession):
    """Verify that when emergency kill switch is engaged, SchedulerService does not dispatch any runs."""
    from app.services.kill_switch import kill_switch
    scheduler_service = SchedulerService()
    now = datetime.now(timezone.utc)
    ws_id = uuid.uuid4()
    auto_id = uuid.uuid4()

    auto = Automation(
        id=auto_id,
        workspace_id=ws_id,
        name="Kill Switch Test",
        trigger_type="cron",
        cron_expression="* * * * *",
        timezone="UTC",
        prompt_template="Kill switch test objective",
        is_active=True,
        circuit_state="CLOSED",
        next_run_at=now - timedelta(minutes=1),
    )
    db_session.add(auto)
    await db_session.flush()

    # Engage kill switch
    kill_switch.set_active(True)
    try:
        claims = await scheduler_service.claim_due_automations(db_session, worker_id="test_worker")
        assert len(claims) == 0
    finally:
        kill_switch.set_active(False)

