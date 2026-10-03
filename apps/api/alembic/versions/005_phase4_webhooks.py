"""005_phase4_webhooks

Revision ID: 005
Revises: 004
Create Date: 2026-10-01 16:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '005'
down_revision: Union[str, None] = '004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. webhook_endpoints Table
    op.create_table(
        'webhook_endpoints',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('workspace_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('public_id', sa.String(length=64), unique=True, nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('secret_ciphertext', sa.Text(), nullable=False),
        sa.Column('prompt_template', sa.Text(), nullable=False),
        sa.Column('autonomy_level', sa.SmallInteger(), server_default='4', nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('max_payload_bytes', sa.Integer(), server_default='1048576', nullable=False),
        sa.Column('rate_limit_per_minute', sa.Integer(), server_default='60', nullable=False),
        sa.Column('last_received_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('total_received', sa.Integer(), server_default='0', nullable=False),
        sa.Column('total_failed', sa.Integer(), server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_webhook_endpoints_workspace_id', 'webhook_endpoints', ['workspace_id'])
    op.create_index('ix_webhook_endpoints_public_id', 'webhook_endpoints', ['public_id'])
    op.create_index('ix_webhook_endpoints_is_active', 'webhook_endpoints', ['is_active'])
    op.create_index('ix_webhook_endpoints_workspace_active', 'webhook_endpoints', ['workspace_id', 'is_active'])

    # 2. webhook_deliveries Table
    op.create_table(
        'webhook_deliveries',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('webhook_endpoint_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('webhook_endpoints.id', ondelete='CASCADE'), nullable=False),
        sa.Column('workspace_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('idempotency_key', sa.String(length=255), nullable=False),
        sa.Column('received_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('status', sa.String(length=50), server_default='accepted', nullable=False),
        sa.Column('task_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tasks.id', ondelete='SET NULL'), nullable=True),
        sa.Column('payload_hash', sa.String(length=64), nullable=False),
        sa.Column('error_code', sa.String(length=100), nullable=True),
        sa.Column('error_summary', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.UniqueConstraint('workspace_id', 'webhook_endpoint_id', 'idempotency_key', name='uq_webhook_delivery_idempotency'),
    )
    op.create_index('ix_webhook_deliveries_webhook_endpoint_id', 'webhook_deliveries', ['webhook_endpoint_id'])
    op.create_index('ix_webhook_deliveries_workspace_id', 'webhook_deliveries', ['workspace_id'])
    op.create_index('ix_webhook_deliveries_idempotency_key', 'webhook_deliveries', ['idempotency_key'])
    op.create_index('ix_webhook_deliveries_status', 'webhook_deliveries', ['status'])
    op.create_index('ix_webhook_deliveries_lookup', 'webhook_deliveries', ['webhook_endpoint_id', 'received_at'])


def downgrade() -> None:
    op.drop_table('webhook_deliveries')
    op.drop_table('webhook_endpoints')
