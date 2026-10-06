"""Human-In-The-Loop Approval Request model."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict
from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, GUID, JSONB, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.db.models.agent_run import AgentRun
    from app.db.models.task import Task


class ApprovalRequest(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Cryptographically signed HITL approval request."""

    __tablename__ = "approval_requests"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_run_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    tool_params: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False, index=True)
    approval_token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    reason_requested: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    task: Mapped["Task"] = relationship("Task", back_populates="approval_requests")
    agent_run: Mapped["AgentRun"] = relationship("AgentRun", back_populates="approval_requests")
