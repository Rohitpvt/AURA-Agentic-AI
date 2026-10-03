"""008_aura_603_vector_indexing

Revision ID: 008
Revises: 007
Create Date: 2026-10-02 22:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

try:
    from pgvector.sqlalchemy import Vector as PGVector
except ImportError:
    PGVector = None

revision: str = '008'
down_revision: Union[str, None] = '007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    # 1. Unique constraint on file_chunks (workspace_id, file_id, chunk_index)
    op.create_unique_constraint(
        'uq_file_chunks_ws_file_idx',
        'file_chunks',
        ['workspace_id', 'file_id', 'chunk_index']
    )

    # 2. Add HNSW cosine index on file_chunks(embedding) if PostgreSQL
    if dialect == 'postgresql':
        op.execute('CREATE EXTENSION IF NOT EXISTS vector;')
        op.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_file_chunks_embedding_hnsw
            ON file_chunks USING hnsw (embedding vector_cosine_ops)
            WITH (m = 16, ef_construction = 64)
            WHERE embedding IS NOT NULL;

            CREATE INDEX IF NOT EXISTS idx_file_chunks_fts
            ON file_chunks USING gin (to_tsvector('english', chunk_text));
            """
        )


    # 3. Add provenance column to memory_records
    jsonb_type = postgresql.JSONB(astext_type=sa.Text()) if dialect == 'postgresql' else sa.JSON()
    op.add_column(
        'memory_records',
        sa.Column('provenance', jsonb_type, server_default=sa.text("'{}'::jsonb" if dialect == 'postgresql' else "'{}'"), nullable=False)
    )

    if dialect == 'postgresql':
        op.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_memory_records_provenance_file
            ON memory_records ((provenance->>'file_id'))
            WHERE provenance->>'file_id' IS NOT NULL;
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == 'postgresql':
        op.execute('DROP INDEX IF EXISTS idx_memory_records_provenance_file;')
        op.execute('DROP INDEX IF EXISTS idx_file_chunks_fts;')
        op.execute('DROP INDEX IF EXISTS idx_file_chunks_embedding_hnsw;')


    op.drop_column('memory_records', 'provenance')
    op.drop_constraint('uq_file_chunks_ws_file_idx', 'file_chunks', type_='unique')
