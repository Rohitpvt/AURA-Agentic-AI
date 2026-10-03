"""004_phase4_automations

Revision ID: 004
Revises: 003
Create Date: 2026-10-01 14:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '004'
down_revision: Union[str, None] = '003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. automations Table
    op.create_table(
        'automations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('workspace_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('trigger_type', sa.String(length=50), server_default='cron', nullable=False),
        sa.Column('cron_expression', sa.String(length=100), nullable=True),
        sa.Column('timezone', sa.String(length=100), server_default='UTC', nullable=False),
        sa.Column('webhook_secret', sa.String(length=255), nullable=True),
        sa.Column('event_pattern', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('prompt_template', sa.Text(), nullable=False),
        sa.Column('assigned_skill_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('skills.id', ondelete='SET NULL'), nullable=True),
        sa.Column('autonomy_level', sa.SmallInteger(), server_default='3', nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('next_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_success_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_failure_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('failure_streak', sa.Integer(), server_default='0', nullable=False),
        sa.Column('circuit_state', sa.String(length=50), server_default='CLOSED', nullable=False),
        sa.Column('circuit_opened_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('total_runs', sa.Integer(), server_default='0', nullable=False),
        sa.Column('total_failures', sa.Integer(), server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_automations_workspace_id', 'automations', ['workspace_id'])
    op.create_index('ix_automations_next_run_at', 'automations', ['next_run_at'])
    op.create_index('ix_automations_due_lookup', 'automations', ['is_active', 'circuit_state', 'next_run_at'])
    op.create_index('ix_automations_workspace_active', 'automations', ['workspace_id', 'is_active'])

    # 2. automation_runs Table
    op.create_table(
        'automation_runs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('automation_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('automations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('workspace_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('scheduled_for', sa.DateTime(timezone=True), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(length=50), server_default='pending', nullable=False),
        sa.Column('attempt', sa.Integer(), server_default='1', nullable=False),
        sa.Column('retry_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('max_retries', sa.Integer(), server_default='3', nullable=False),
        sa.Column('claimed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('claim_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('claimed_by', sa.String(length=255), nullable=True),
        sa.Column('task_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tasks.id', ondelete='SET NULL'), nullable=True),
        sa.Column('idempotency_key', sa.String(length=255), unique=True, nullable=False),
        sa.Column('error_code', sa.String(length=100), nullable=True),
        sa.Column('error_summary', sa.Text(), nullable=True),
        sa.Column('output_summary', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    )
    op.create_index('ix_automation_runs_automation_id', 'automation_runs', ['automation_id'])
    op.create_index('ix_automation_runs_workspace_id', 'automation_runs', ['workspace_id'])
    op.create_index('ix_automation_runs_scheduled_for', 'automation_runs', ['scheduled_for'])
    op.create_index('ix_automation_runs_idempotency_key', 'automation_runs', ['idempotency_key'], unique=True)
    op.create_index('ix_automation_runs_status_claim', 'automation_runs', ['status', 'claim_expires_at'])
    op.create_index('ix_automation_runs_workspace_scheduled', 'automation_runs', ['workspace_id', 'scheduled_for'])


def downgrade() -> None:
    op.drop_table('automation_runs')
    op.drop_table('automations')
