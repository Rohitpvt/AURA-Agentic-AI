"""Add persistent revoked_tokens table for distributed and crash-resilient JWT blacklist

Revision ID: 003
Revises: 002
Create Date: 2026-09-30 23:10:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '003'
down_revision: Union[str, None] = '002'
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'revoked_tokens',
        sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('jti', sa.String(length=64), nullable=True),
        sa.Column('user_id', sa.Uuid(), nullable=True),
        sa.Column('reason', sa.String(length=100), server_default='revoked', nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token_hash', name='uq_revoked_token_hash')
    )
    op.create_index('idx_revoked_tokens_hash', 'revoked_tokens', ['token_hash'], unique=True)
    op.create_index('idx_revoked_tokens_jti', 'revoked_tokens', ['jti'], unique=False)
    op.create_index('idx_revoked_tokens_user', 'revoked_tokens', ['user_id'], unique=False)
    op.create_index('idx_revoked_tokens_expires', 'revoked_tokens', ['expires_at'], unique=False)


def downgrade() -> None:
    op.drop_index('idx_revoked_tokens_expires', table_name='revoked_tokens')
    op.drop_index('idx_revoked_tokens_user', table_name='revoked_tokens')
    op.drop_index('idx_revoked_tokens_jti', table_name='revoked_tokens')
    op.drop_index('idx_revoked_tokens_hash', table_name='revoked_tokens')
    op.drop_table('revoked_tokens')
