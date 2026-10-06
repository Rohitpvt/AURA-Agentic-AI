"""Automation and Cron task models for AURA."""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, GUID, JSONB, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Automation(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """Scheduled and reactive event-triggered automation entity."""

    __tablename__ = "automations"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    trigger_type: Mapped[str] = mapped_column(String(50), default="cron", nullable=False)  # cron, webhook, delayed
    cron_expression: Mapped[str | None] = mapped_column(String(100), nullable=True)
    timezone: Mapped[str] = mapped_column(String(100), default="UTC", nullable=False)
    webhook_secret: Mapped[str | None] = mapped_column(String(255), nullable=True)
    event_pattern: Mapped[Dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    prompt_template: Mapped[str] = mapped_column(Text, nullable=False)
    assigned_skill_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("skills.id", ondelete="SET NULL"), nullable=True
    )
    autonomy_level: Mapped[int] = mapped_column(SmallInteger, default=3, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    
    # Scheduling and health timestamps
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # Circuit breaker and statistics
    failure_streak: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    circuit_state: Mapped[str] = mapped_column(String(50), default="CLOSED", nullable=False, index=True)  # CLOSED, OPEN, HALF_OPEN
    circuit_opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_runs: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Relationship
    runs: Mapped[list["AutomationRun"]] = relationship("AutomationRun", back_populates="automation", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_automations_due_lookup", "is_active", "circuit_state", "next_run_at"),
        Index("ix_automations_workspace_active", "workspace_id", "is_active"),
    )


class AutomationRun(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Execution record for an automated scheduled run."""

    __tablename__ = "automation_runs"

    automation_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("automations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False, index=True)  # pending, claimed, running, succeeded, failed, retrying, cancelled
    attempt: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_retries: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    
    # Claim and lease management
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claim_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    claimed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)  # worker / process identifier
    
    # Associated task DAG
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    
    # Output and error telemetry
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    automation: Mapped["Automation"] = relationship("Automation", back_populates="runs")

    __table_args__ = (
        Index("ix_automation_runs_status_claim", "status", "claim_expires_at"),
        Index("ix_automation_runs_workspace_scheduled", "workspace_id", "scheduled_for"),
    )
