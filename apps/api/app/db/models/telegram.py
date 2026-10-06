"""Database models for Telegram Bot integration and operator pairing."""

import uuid
from datetime import datetime
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, GUID, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class TelegramIntegration(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """Telegram Bot integration configuration scoped to a workspace."""

    __tablename__ = "telegram_integrations"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    display_name: Mapped[str] = mapped_column(String(255), default="Telegram Bot", nullable=False)
    bot_token_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    bot_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bot_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    
    # Polling state and offset persistence
    polling_state: Mapped[str] = mapped_column(String(50), default="stopped", nullable=False)  # stopped, polling, backoff, error
    last_update_id: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    
    # Single-poller ownership lease
    poller_lease_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    poller_lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    
    # Health and telemetry
    last_successful_poll_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_messages_received: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_commands_processed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Relationships
    pairings: Mapped[list["TelegramPairing"]] = relationship(
        "TelegramPairing", back_populates="integration", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_telegram_integrations_workspace_active", "workspace_id", "is_active"),
        Index("ix_telegram_integrations_lease", "is_active", "poller_lease_expires_at"),
    )


class TelegramPairing(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Authorized pairing between an external Telegram chat and an AURA workspace."""

    __tablename__ = "telegram_pairings"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    integration_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("telegram_integrations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    telegram_chat_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    telegram_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    telegram_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    
    # One-time pairing token (15-min TTL)
    pairing_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    pairing_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    
    paired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    integration: Mapped["TelegramIntegration"] = relationship("TelegramIntegration", back_populates="pairings")

    __table_args__ = (
        UniqueConstraint("workspace_id", "integration_id", "telegram_chat_id", name="uq_telegram_pairing_chat"),
        Index("ix_telegram_pairings_lookup", "integration_id", "telegram_chat_id", "is_active"),
    )
