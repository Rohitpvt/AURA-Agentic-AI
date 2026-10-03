"""006_phase4_telegram

Revision ID: 006
Revises: 005
Create Date: 2026-10-01 18:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '006'
down_revision: Union[str, None] = '005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. telegram_integrations Table
    op.create_table(
        'telegram_integrations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('workspace_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('display_name', sa.String(length=255), server_default='Telegram Bot', nullable=False),
        sa.Column('bot_token_ciphertext', sa.Text(), nullable=False),
        sa.Column('bot_username', sa.String(length=255), nullable=True),
        sa.Column('bot_id', sa.String(length=64), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('polling_state', sa.String(length=50), server_default='stopped', nullable=False),
        sa.Column('last_update_id', sa.BigInteger(), server_default='0', nullable=False),
        sa.Column('poller_lease_id', sa.String(length=255), nullable=True),
        sa.Column('poller_lease_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_successful_poll_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error_code', sa.String(length=100), nullable=True),
        sa.Column('last_error_summary', sa.Text(), nullable=True),
        sa.Column('total_messages_received', sa.Integer(), server_default='0', nullable=False),
        sa.Column('total_commands_processed', sa.Integer(), server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_telegram_integrations_workspace_id', 'telegram_integrations', ['workspace_id'])
    op.create_index('ix_telegram_integrations_is_active', 'telegram_integrations', ['is_active'])
    op.create_index('ix_telegram_integrations_workspace_active', 'telegram_integrations', ['workspace_id', 'is_active'])
    op.create_index('ix_telegram_integrations_lease', 'telegram_integrations', ['is_active', 'poller_lease_expires_at'])

    # 2. telegram_pairings Table
    op.create_table(
        'telegram_pairings',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('workspace_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('integration_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('telegram_integrations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('telegram_chat_id', sa.String(length=64), nullable=False),
        sa.Column('telegram_user_id', sa.String(length=64), nullable=True),
        sa.Column('telegram_username', sa.String(length=255), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('pairing_token_hash', sa.String(length=64), nullable=True),
        sa.Column('pairing_token_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('paired_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.UniqueConstraint('workspace_id', 'integration_id', 'telegram_chat_id', name='uq_telegram_pairing_chat'),
    )
    op.create_index('ix_telegram_pairings_workspace_id', 'telegram_pairings', ['workspace_id'])
    op.create_index('ix_telegram_pairings_integration_id', 'telegram_pairings', ['integration_id'])
    op.create_index('ix_telegram_pairings_chat_id', 'telegram_pairings', ['telegram_chat_id'])
    op.create_index('ix_telegram_pairings_is_active', 'telegram_pairings', ['is_active'])
    op.create_index('ix_telegram_pairings_token_hash', 'telegram_pairings', ['pairing_token_hash'])
    op.create_index('ix_telegram_pairings_lookup', 'telegram_pairings', ['integration_id', 'telegram_chat_id', 'is_active'])


def downgrade() -> None:
    op.drop_table('telegram_pairings')
    op.drop_table('telegram_integrations')
