"""File Intelligence Background Job Model."""

from datetime import datetime, timezone
import enum
import uuid
from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, GUID, JSONB, TimestampMixin, UUIDPrimaryKeyMixin


class FileJobType(str, enum.Enum):
    """File intelligence job types."""
    EXTRACT = "file_extract"
    INDEX = "file_index"
    SUMMARY = "file_summary"
    RECONCILE = "file_reconcile"


class FileJobStatus(str, enum.Enum):
    """Deterministic states for file intelligence jobs."""
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class FileJob(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Dedicated persistent authority for asynchronous file intelligence operations."""

    __tablename__ = "file_jobs"
    __table_args__ = (
        Index(
            "uq_active_file_job",
            "workspace_id",
            "file_id",
            "job_type",
            unique=True,
            postgresql_where=Column("status").in_(["queued", "processing"]),
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    file_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("file_records.id", ondelete="CASCADE"), nullable=True, index=True
    )
    job_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(50), default=FileJobStatus.QUEUED.value, nullable=False, index=True
    )
    progress_pct: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
