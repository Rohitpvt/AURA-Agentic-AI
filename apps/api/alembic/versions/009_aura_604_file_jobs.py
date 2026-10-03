"""009_aura_604_file_jobs

Revision ID: 009
Revises: 008
Create Date: 2026-10-02 23:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '009'
down_revision: Union[str, None] = '008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    guid_type = postgresql.UUID(as_uuid=True) if dialect == 'postgresql' else sa.String(36)
    jsonb_type = postgresql.JSONB(astext_type=sa.Text()) if dialect == 'postgresql' else sa.JSON()

    # 1. Create file_jobs table
    op.create_table(
        'file_jobs',
        sa.Column('id', guid_type, primary_key=True),
        sa.Column('workspace_id', guid_type, sa.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('file_id', guid_type, sa.ForeignKey('file_records.id', ondelete='CASCADE'), nullable=True),
        sa.Column('job_type', sa.String(50), nullable=False),
        sa.Column('status', sa.String(50), server_default='queued', nullable=False),
        sa.Column('progress_pct', sa.Integer(), server_default='0', nullable=False),
        sa.Column('error_summary', sa.Text(), nullable=True),
        sa.Column('result_metadata', jsonb_type, server_default=sa.text("'{}'::jsonb" if dialect == 'postgresql' else "'{}'"), nullable=False),
        sa.Column('created_by', guid_type, sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_index('idx_file_jobs_ws_id', 'file_jobs', ['workspace_id'])
    op.create_index('idx_file_jobs_file_id', 'file_jobs', ['file_id'])
    op.create_index('idx_file_jobs_status', 'file_jobs', ['status'])
    op.create_index('idx_file_jobs_type', 'file_jobs', ['job_type'])

    # 2. Add partial unique index for active jobs
    if dialect == 'postgresql':
        op.execute(
            """
            CREATE UNIQUE INDEX uq_active_file_job
            ON file_jobs (workspace_id, file_id, job_type)
            WHERE status IN ('queued', 'processing');
            """
        )
    else:
        # SQLite / in-memory test fallback
        op.create_index(
            'uq_active_file_job',
            'file_jobs',
            ['workspace_id', 'file_id', 'job_type'],
            unique=False
        )


def downgrade() -> None:
    op.drop_index('idx_file_jobs_type', table_name='file_jobs')
    op.drop_index('idx_file_jobs_status', table_name='file_jobs')
    op.drop_index('idx_file_jobs_file_id', table_name='file_jobs')
    op.drop_index('idx_file_jobs_ws_id', table_name='file_jobs')
    op.drop_table('file_jobs')
