"""Cognitive Memory Record model with vector support."""

import uuid
from sqlalchemy import Boolean, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, GUID, JSONB, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin, Vector


class MemoryRecord(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """Cognitive user modeling and semantic memory record."""

    __tablename__ = "memory_records"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    category: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(50), default="user_directive", nullable=False)
    fact_statement: Mapped[str] = mapped_column(Text, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Numeric(4, 3), default=1.0, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(768), nullable=True)
    provenance: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    is_tombstoned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    tombstoned_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
