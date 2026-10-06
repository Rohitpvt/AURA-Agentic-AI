"""Message entity model."""

import uuid
from typing import TYPE_CHECKING, Any, Dict
from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, GUID, JSONB, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.db.models.session import Session


class Message(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Verbatim message record."""

    __tablename__ = "messages"

    session_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sender_type: Mapped[str] = mapped_column(String(50), nullable=False)
    sender_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tokens_consumed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    metadata_: Mapped[Dict[str, Any]] = mapped_column("metadata", JSONB, default=dict, nullable=False)

    # Relationships
    session: Mapped["Session"] = relationship("Session", back_populates="messages")
