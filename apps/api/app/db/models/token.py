"""Revoked Token persistent blacklist model for distributed and crash-resilient JWT revocation."""

import uuid
from datetime import datetime, timezone
from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, GUID, TimestampMixin, UUIDPrimaryKeyMixin


class RevokedToken(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Persistent blacklist ledger for revoked access and refresh tokens."""

    __tablename__ = "revoked_tokens"

    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    jti: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    reason: Mapped[str] = mapped_column(String(100), default="revoked", nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
