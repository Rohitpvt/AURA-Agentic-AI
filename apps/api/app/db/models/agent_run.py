"""AgentRun and SubAgentRun execution tracking models."""

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List
from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, GUID, JSONB, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.db.models.approval import ApprovalRequest
    from app.db.models.task import Task


class AgentRun(Base, UUIDPrimaryKeyMixin):
    """Runtime execution instance of an agent on a task."""

    __tablename__ = "agent_runs"

    task_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True, index=True
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_type: Mapped[str] = mapped_column(String(50), default="master_supervisor", nullable=False)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    model_tier: Mapped[str] = mapped_column(String(50), default="general", nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="running", nullable=False)
    total_tokens_in: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens_out: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_cost_cents: Mapped[float] = mapped_column(Numeric(10, 4), default=0.0, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    checkpoint_state: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    task: Mapped["Task"] = relationship("Task", back_populates="agent_runs")
    subagent_runs: Mapped[List["SubAgentRun"]] = relationship(
        "SubAgentRun", back_populates="parent_run", cascade="all, delete-orphan"
    )
    approval_requests: Mapped[List["ApprovalRequest"]] = relationship(
        "ApprovalRequest", back_populates="agent_run", cascade="all, delete-orphan"
    )


class SubAgentRun(Base, UUIDPrimaryKeyMixin):
    """Hierarchical sub-agent worker run instance."""

    __tablename__ = "subagent_runs"

    parent_run_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    goal: Mapped[str] = mapped_column(String(1000), nullable=False)
    assigned_budget_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    consumed_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    depth_level: Mapped[int] = mapped_column(SmallInteger, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="running", nullable=False)
    result_payload: Mapped[Dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    parent_run: Mapped["AgentRun"] = relationship("AgentRun", back_populates="subagent_runs")
