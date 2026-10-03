"""Database model and constraint test suite for Webhook models."""

import uuid
from datetime import datetime, timezone
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.user import User
from app.db.models.webhook import WebhookDelivery, WebhookEndpoint
from app.db.models.workspace import Workspace


@pytest.mark.asyncio
async def test_webhook_endpoint_crud_and_defaults(db_session: AsyncSession):
    """Verify WebhookEndpoint entity creation, defaults, and relationships."""
    ws = Workspace(name="Webhook Workspace", slug=f"wh-ws-{uuid.uuid4().hex[:6]}")
    user = User(email=f"wh_owner_{uuid.uuid4().hex[:6]}@example.com", password_hash="hash123", full_name="WH Owner")
    db_session.add_all([ws, user])
    await db_session.flush()

    ep = WebhookEndpoint(
        workspace_id=ws.id,
        created_by=user.id,
        public_id=f"whk_{uuid.uuid4().hex[:16]}",
        name="GitHub CI Ingress",
        description="Receives GitHub push and workflow events",
        secret_ciphertext="encrypted_dummy_secret_b64",
        prompt_template="Analyze deployment failure for commit {payload.head_commit.id}",
        autonomy_level=4,
        is_active=True,
    )
    db_session.add(ep)
    await db_session.flush()

    assert ep.id is not None
    assert ep.max_payload_bytes == 1048576
    assert ep.rate_limit_per_minute == 60
    assert ep.total_received == 0
    assert ep.total_failed == 0
    assert ep.created_at is not None


@pytest.mark.asyncio
async def test_webhook_delivery_uniqueness_constraint(db_session: AsyncSession):
    """Verify unique constraint on (workspace_id, webhook_endpoint_id, idempotency_key)."""
    ws = Workspace(name="Delivery WS", slug=f"del-ws-{uuid.uuid4().hex[:6]}")
    db_session.add(ws)
    await db_session.flush()

    ep = WebhookEndpoint(
        workspace_id=ws.id,
        public_id=f"whk_{uuid.uuid4().hex[:16]}",
        name="Jira Issues",
        secret_ciphertext="encrypted_secret",
        prompt_template="Handle Jira issue",
        autonomy_level=3,
        is_active=True,
    )
    db_session.add(ep)
    await db_session.flush()

    d1 = WebhookDelivery(
        webhook_endpoint_id=ep.id,
        workspace_id=ws.id,
        idempotency_key="deliv_key_12345",
        status="dispatched",
        payload_hash="sha256_dummy_hash_1",
    )
    db_session.add(d1)
    await db_session.flush()

    # Attempt duplicate insert with same (workspace_id, webhook_endpoint_id, idempotency_key)
    d2 = WebhookDelivery(
        webhook_endpoint_id=ep.id,
        workspace_id=ws.id,
        idempotency_key="deliv_key_12345",
        status="dispatched",
        payload_hash="sha256_dummy_hash_2",
    )
    db_session.add(d2)
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_webhook_cascade_deletion(db_session: AsyncSession):
    """Verify deleting a WebhookEndpoint cascades and deletes all associated WebhookDelivery records."""
    ws = Workspace(name="Cascade WS", slug=f"casc-ws-{uuid.uuid4().hex[:6]}")
    db_session.add(ws)
    await db_session.flush()

    ep = WebhookEndpoint(
        workspace_id=ws.id,
        public_id=f"whk_{uuid.uuid4().hex[:16]}",
        name="PagerDuty Ingress",
        secret_ciphertext="encrypted_secret",
        prompt_template="Triage incident",
        autonomy_level=4,
    )
    db_session.add(ep)
    await db_session.flush()

    d = WebhookDelivery(
        webhook_endpoint_id=ep.id,
        workspace_id=ws.id,
        idempotency_key="incident_event_1",
        status="dispatched",
        payload_hash="dummy_hash",
    )
    db_session.add(d)
    await db_session.flush()

    # Delete endpoint
    await db_session.delete(ep)
    await db_session.flush()

    # Deliveries should be gone
    deliveries = (await db_session.execute(select(WebhookDelivery).where(WebhookDelivery.webhook_endpoint_id == ep.id))).scalars().all()
    assert len(deliveries) == 0
