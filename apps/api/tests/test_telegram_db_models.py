"""Tests for Telegram database models, encryption at rest, and constraints."""

import uuid
from datetime import datetime, timezone
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decrypt_secret, encrypt_secret
from app.db.models.telegram import TelegramIntegration, TelegramPairing
from app.db.models.workspace import Workspace


@pytest.mark.asyncio
async def test_telegram_integration_crud_and_defaults(db_session: AsyncSession):
    """Verify TelegramIntegration entity creation, defaults, and relations."""
    ws = Workspace(name="Telegram WS", slug=f"tg-ws-{uuid.uuid4().hex[:6]}")
    db_session.add(ws)
    await db_session.flush()

    raw_token = "123456789:ABCdefGHIjklMNOpqrsTUVwxyz"
    token_cipher = encrypt_secret(raw_token)

    integration = TelegramIntegration(
        workspace_id=ws.id,
        display_name="Operations Bot",
        bot_token_ciphertext=token_cipher,
        bot_username="aura_ops_bot",
        bot_id="123456789",
        is_active=True,
    )
    db_session.add(integration)
    await db_session.flush()

    assert integration.id is not None
    assert integration.polling_state == "stopped"
    assert integration.last_update_id == 0
    assert integration.total_messages_received == 0
    assert integration.total_commands_processed == 0

    # Verify decryption
    assert decrypt_secret(integration.bot_token_ciphertext) == raw_token


@pytest.mark.asyncio
async def test_telegram_pairing_uniqueness_and_indexes(db_session: AsyncSession):
    """Verify unique constraint on (workspace_id, integration_id, telegram_chat_id)."""
    ws = Workspace(name="Telegram WS 2", slug=f"tg-ws2-{uuid.uuid4().hex[:6]}")
    db_session.add(ws)
    await db_session.flush()

    integration = TelegramIntegration(
        workspace_id=ws.id,
        display_name="Support Bot",
        bot_token_ciphertext=encrypt_secret("test_token_123"),
        bot_username="aura_support_bot",
        is_active=True,
    )
    db_session.add(integration)
    await db_session.flush()

    # Create Pairing 1
    p1 = TelegramPairing(
        workspace_id=ws.id,
        integration_id=integration.id,
        telegram_chat_id="987654321",
        is_active=True,
        paired_at=datetime.now(timezone.utc),
    )
    db_session.add(p1)
    await db_session.flush()

    # Attempt Duplicate Pairing with same chat_id
    p2 = TelegramPairing(
        workspace_id=ws.id,
        integration_id=integration.id,
        telegram_chat_id="987654321",
        is_active=True,
    )
    db_session.add(p2)
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_telegram_cascade_deletion(db_session: AsyncSession):
    """Verify deleting a TelegramIntegration cascades and deletes all associated TelegramPairing records."""
    ws = Workspace(name="Cascade WS", slug=f"tg-casc-{uuid.uuid4().hex[:6]}")
    db_session.add(ws)
    await db_session.flush()

    integration = TelegramIntegration(
        workspace_id=ws.id,
        display_name="Temp Bot",
        bot_token_ciphertext=encrypt_secret("temp_token"),
        is_active=True,
    )
    db_session.add(integration)
    await db_session.flush()

    pairing = TelegramPairing(
        workspace_id=ws.id,
        integration_id=integration.id,
        telegram_chat_id="11223344",
        is_active=True,
    )
    db_session.add(pairing)
    await db_session.flush()

    # Delete Integration
    await db_session.delete(integration)
    await db_session.flush()

    # Verify Pairings deleted
    res_pair = await db_session.execute(select(TelegramPairing).where(TelegramPairing.integration_id == integration.id))
    assert len(res_pair.scalars().all()) == 0
