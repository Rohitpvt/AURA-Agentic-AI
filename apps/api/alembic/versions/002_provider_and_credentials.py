"""Add provider configurations and encrypted credentials tables

Revision ID: 002
Revises: 001
Create Date: 2026-09-30 22:55:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '002'
down_revision: Union[str, None] = '001'
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[Sequence[str], None] = None


def upgrade() -> None:
    # 1. provider_configurations table
    op.create_table(
        'provider_configurations',
        sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('provider_type', sa.String(length=50), nullable=False),
        sa.Column('display_name', sa.String(length=100), nullable=False),
        sa.Column('is_enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('is_default', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('routing_mode', sa.String(length=30), server_default='local_only', nullable=False),
        sa.Column('default_model', sa.String(length=100), nullable=False),
        sa.Column('api_endpoint', sa.String(length=255), nullable=False),
        sa.Column('config_options', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column('billing_tier', sa.String(length=50), server_default='zero_cost_local', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('workspace_id', 'provider_type', name='uq_workspace_provider_type')
    )
    op.create_index('idx_provider_configs_ws', 'provider_configurations', ['workspace_id', 'is_enabled'], unique=False)

    # 2. credentials table
    op.create_table(
        'credentials',
        sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('provider_config_id', sa.Uuid(), nullable=False),
        sa.Column('credential_type', sa.String(length=50), server_default='api_key', nullable=False),
        sa.Column('encrypted_secret', sa.Text(), nullable=False),
        sa.Column('key_fingerprint', sa.String(length=64), nullable=False),
        sa.Column('is_valid', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('last_validated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_validation_error', sa.Text(), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['provider_config_id'], ['provider_configurations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('provider_config_id', 'credential_type', name='uq_provider_credential')
    )
    op.create_index('idx_credentials_ws', 'credentials', ['workspace_id'], unique=False)
    op.create_index('idx_credentials_provider', 'credentials', ['provider_config_id'], unique=False)


def downgrade() -> None:
    op.drop_index('idx_credentials_provider', table_name='credentials')
    op.drop_index('idx_credentials_ws', table_name='credentials')
    op.drop_table('credentials')
    op.drop_index('idx_provider_configs_ws', table_name='provider_configurations')
    op.drop_table('provider_configurations')
