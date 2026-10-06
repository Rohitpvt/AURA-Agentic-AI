"""Inbound Webhook Gateway database models for AURA."""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, GUID, JSONB, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class WebhookEndpoint(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """Secure inbound webhook endpoint configuration."""

    __tablename__ = "webhook_endpoints"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    public_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    secret_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_template: Mapped[str] = mapped_column(Text, nullable=False)
    autonomy_level: Mapped[int] = mapped_column(SmallInteger, default=4, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    max_payload_bytes: Mapped[int] = mapped_column(Integer, default=1048576, nullable=False)  # 1 MB max
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    last_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_received: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Relationships
    deliveries: Mapped[list["WebhookDelivery"]] = relationship(
        "WebhookDelivery", back_populates="endpoint", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_webhook_endpoints_workspace_active", "workspace_id", "is_active"),
    )


class WebhookDelivery(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Receipt and audit record for an incoming webhook delivery."""

    __tablename__ = "webhook_deliveries"

    webhook_endpoint_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("webhook_endpoints.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    status: Mapped[str] = mapped_column(String(50), default="accepted", nullable=False, index=True)
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    endpoint: Mapped["WebhookEndpoint"] = relationship("WebhookEndpoint", back_populates="deliveries")

    __table_args__ = (
        UniqueConstraint("workspace_id", "webhook_endpoint_id", "idempotency_key", name="uq_webhook_delivery_idempotency"),
        Index("ix_webhook_deliveries_lookup", "webhook_endpoint_id", "received_at"),
    )
