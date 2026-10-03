"""007_phase6_files

Revision ID: 007
Revises: 006
Create Date: 2026-10-02 18:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
try:
    from pgvector.sqlalchemy import Vector as PGVector
except ImportError:
    PGVector = None

revision: str = '007'
down_revision: Union[str, None] = '006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. file_records Table
    op.create_table(
        'file_records',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('workspace_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('uploaded_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('original_filename', sa.String(length=255), nullable=False),
        sa.Column('safe_filename', sa.String(length=255), nullable=False),
        sa.Column('mime_type', sa.String(length=100), nullable=False),
        sa.Column('file_extension', sa.String(length=20), nullable=False),
        sa.Column('size_bytes', sa.BigInteger(), nullable=False),
        sa.Column('sha256_hash', sa.String(length=64), nullable=False),
        sa.Column('storage_path', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=50), server_default='uploaded', nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column('security_flags', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_file_records_workspace_id', 'file_records', ['workspace_id'])
    op.create_index('ix_file_records_sha256_hash', 'file_records', ['sha256_hash'])
    op.create_index('ix_file_records_status', 'file_records', ['status'])
    op.create_index('ix_file_records_ws_hash', 'file_records', ['workspace_id', 'sha256_hash'])

    # 2. file_chunks Table
    vector_col = PGVector(768) if PGVector is not None else postgresql.JSONB(astext_type=sa.Text())
    op.create_table(
        'file_chunks',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('workspace_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('file_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('file_records.id', ondelete='CASCADE'), nullable=False),
        sa.Column('chunk_index', sa.Integer(), nullable=False),
        sa.Column('chunk_text', sa.Text(), nullable=False),
        sa.Column('token_count', sa.Integer(), nullable=False),
        sa.Column('embedding', vector_col, nullable=True),
        sa.Column('source_location', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    )
    op.create_index('ix_file_chunks_workspace_id', 'file_chunks', ['workspace_id'])
    op.create_index('ix_file_chunks_file_id', 'file_chunks', ['file_id'])
    op.create_index('ix_file_chunks_ws_file', 'file_chunks', ['workspace_id', 'file_id'])


def downgrade() -> None:
    op.drop_table('file_chunks')
    op.drop_table('file_records')
