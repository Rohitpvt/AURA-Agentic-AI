"""Conversational session model."""

import uuid
from typing import TYPE_CHECKING, Any, Dict, List
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, GUID, JSONB, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.db.models.message import Message


class Session(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """Conversational ingress session entity."""

    __tablename__ = "sessions"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), default="New Conversation", nullable=False)
    channel: Mapped[str] = mapped_column(String(50), default="web", nullable=False)
    channel_session_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="active", nullable=False)
    metadata_: Mapped[Dict[str, Any]] = mapped_column("metadata", JSONB, default=dict, nullable=False)

    # Relationships
    messages: Mapped[List["Message"]] = relationship(
        "Message", back_populates="session", cascade="all, delete-orphan", order_by="Message.created_at"
    )
