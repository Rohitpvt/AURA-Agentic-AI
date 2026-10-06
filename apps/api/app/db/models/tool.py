"""Tool, Integration, and Tool Permission models."""

import uuid
from typing import Any, Dict
from sqlalchemy import Boolean, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, GUID, JSONB, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Integration(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """External provider connection / MCP server registration."""

    __tablename__ = "integrations"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(50), nullable=False)
    transport: Mapped[str] = mapped_column(String(50), default="native", nullable=False)
    endpoint_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    config: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    encrypted_credentials: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="active", nullable=False)


class Tool(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Registered atomic tool capability."""

    __tablename__ = "tools"

    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True, index=True
    )
    integration_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("integrations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(20), default="low", nullable=False, index=True)
    input_schema: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)
    output_schema: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_allowed_in_background: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class ToolPermission(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Workspace / User policy rule governing tool access."""

    __tablename__ = "tool_permissions"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tool_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("tools.id", ondelete="CASCADE"), nullable=False, index=True
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    max_autonomy_level: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    override_requires_approval: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
