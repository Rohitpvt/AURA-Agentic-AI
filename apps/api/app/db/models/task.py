"""Task and TaskStep models representing multi-step agent plans."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, GUID, JSONB, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.db.models.agent_run import AgentRun
    from app.db.models.approval import ApprovalRequest


class Task(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """High-level user goal / autonomous task entity."""

    __tablename__ = "tasks"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False, index=True)
    priority: Mapped[str] = mapped_column(String(20), default="medium", nullable=False)
    autonomy_level: Mapped[int] = mapped_column(SmallInteger, default=2, nullable=False)
    budget_max_tokens: Mapped[int] = mapped_column(Integer, default=100000, nullable=False)
    budget_max_cost_cents: Mapped[int] = mapped_column(Integer, default=500, nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=1800, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    steps: Mapped[List["TaskStep"]] = relationship(
        "TaskStep", back_populates="task", cascade="all, delete-orphan", order_by="TaskStep.step_number"
    )
    agent_runs: Mapped[List["AgentRun"]] = relationship(
        "AgentRun", back_populates="task", cascade="all, delete-orphan"
    )
    approval_requests: Mapped[List["ApprovalRequest"]] = relationship(
        "ApprovalRequest", back_populates="task", cascade="all, delete-orphan"
    )


class TaskStep(Base, UUIDPrimaryKeyMixin):
    """Discrete step within a task execution DAG."""

    __tablename__ = "task_steps"
    __table_args__ = (UniqueConstraint("task_id", "step_number", name="uq_task_step_number"),)

    task_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    step_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    dependencies: Mapped[List[int]] = mapped_column(JSONB, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False)
    tool_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tool_input: Mapped[Dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    tool_output: Mapped[Dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    verification_assertions: Mapped[List[Dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    task: Mapped["Task"] = relationship("Task", back_populates="steps")
