"""Tests for Automation and AutomationRun database models."""

import uuid
from datetime import datetime, timezone
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.automation import Automation, AutomationRun
from app.db.models.user import User
from app.db.models.workspace import Workspace


@pytest.mark.asyncio
async def test_automation_model_crud_and_defaults(db_session: AsyncSession):
    """Test creating, reading, updating, and soft-deleting an Automation entity."""
    # 1. Create Workspace and User
    ws = Workspace(name="Test Automations WS", slug="test-auto-ws")
    user = User(email="scheduler@aura.local", password_hash="hash123", full_name="Scheduler Tester")
    db_session.add_all([ws, user])
    await db_session.flush()

    # 2. Create Automation
    now = datetime.now(timezone.utc)
    auto = Automation(
        workspace_id=ws.id,
        created_by=user.id,
        name="Daily System Cleanup",
        description="Scans and cleans temporary artifacts daily at midnight",
        trigger_type="cron",
        cron_expression="0 0 * * *",
        timezone="UTC",
        prompt_template="Scan workspace artifacts and prune temporary cache files.",
        autonomy_level=3,
        is_active=True,
        next_run_at=now,
    )
    db_session.add(auto)
    await db_session.flush()

    assert auto.id is not None
    assert auto.circuit_state == "CLOSED"
    assert auto.failure_streak == 0
    assert auto.total_runs == 0
    assert auto.total_failures == 0
    assert auto.created_at is not None

    # 3. Read
    res = await db_session.execute(select(Automation).where(Automation.id == auto.id))
    fetched = res.scalar_one()
    assert fetched.name == "Daily System Cleanup"
    assert fetched.cron_expression == "0 0 * * *"

    # 4. Soft Delete
    auto.deleted_at = datetime.now(timezone.utc)
    auto.is_active = False
    await db_session.flush()

    res_deleted = await db_session.execute(
        select(Automation).where(Automation.id == auto.id, Automation.deleted_at.is_(None))
    )
    assert res_deleted.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_automation_run_model_and_idempotency_constraint(db_session: AsyncSession):
    """Test creating AutomationRun records and enforcing uniqueness on idempotency_key."""
    ws = Workspace(name="Runs WS", slug="runs-ws")
    db_session.add(ws)
    await db_session.flush()

    auto = Automation(
        workspace_id=ws.id,
        name="Hourly Health Pulse",
        trigger_type="cron",
        cron_expression="0 * * * *",
        timezone="UTC",
        prompt_template="Check system health and resource metrics.",
    )
    db_session.add(auto)
    await db_session.flush()

    now = datetime.now(timezone.utc)
    idem_key = f"auto_{auto.id}_{int(now.timestamp())}"

    # 1. Create Run
    run1 = AutomationRun(
        automation_id=auto.id,
        workspace_id=ws.id,
        scheduled_for=now,
        status="claimed",
        attempt=1,
        retry_count=0,
        idempotency_key=idem_key,
    )
    db_session.add(run1)
    await db_session.flush()
    assert run1.id is not None
    assert run1.status == "claimed"

    # 2. Attempt Duplicate Idempotency Key Insertion
    run_duplicate = AutomationRun(
        automation_id=auto.id,
        workspace_id=ws.id,
        scheduled_for=now,
        status="claimed",
        attempt=1,
        idempotency_key=idem_key,
    )
    db_session.add(run_duplicate)
    with pytest.raises(Exception):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_cascade_deletion_of_runs_on_automation_delete(db_session: AsyncSession):
    """Test that deleting an automation cascades deletion to its associated runs."""
    ws = Workspace(name="Cascade WS", slug="cascade-ws")
    db_session.add(ws)
    await db_session.flush()

    auto = Automation(
        workspace_id=ws.id,
        name="Ephemeral Cron",
        trigger_type="cron",
        cron_expression="*/5 * * * *",
        timezone="UTC",
        prompt_template="Log ping.",
    )
    db_session.add(auto)
    await db_session.flush()

    run = AutomationRun(
        automation_id=auto.id,
        workspace_id=ws.id,
        scheduled_for=datetime.now(timezone.utc),
        status="succeeded",
        idempotency_key=f"auto_{auto.id}_100",
    )
    db_session.add(run)
    await db_session.flush()

    # Hard delete automation
    await db_session.delete(auto)
    await db_session.flush()

    res = await db_session.execute(select(AutomationRun).where(AutomationRun.id == run.id))
    assert res.scalar_one_or_none() is None
