"""Workspace and tenancy models."""

import uuid
from typing import TYPE_CHECKING, Any, Dict, List
from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, GUID, JSONB, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.db.models.user import User
    from app.db.models.provider import ProviderConfiguration


class Workspace(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """Multi-tenancy boundary entity."""

    __tablename__ = "workspaces"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    settings: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    # Relationships
    members: Mapped[List["WorkspaceMember"]] = relationship(
        "WorkspaceMember", back_populates="workspace", cascade="all, delete-orphan"
    )
    provider_configurations: Mapped[List["ProviderConfiguration"]] = relationship(
        "ProviderConfiguration", back_populates="workspace", cascade="all, delete-orphan"
    )


class WorkspaceMember(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Association between User and Workspace with RBAC."""

    __tablename__ = "workspace_members"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id", name="uq_workspace_user"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(50), default="member", nullable=False)
    permissions: Mapped[List[str]] = mapped_column(JSONB, default=list, nullable=False)

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace", back_populates="members")
    user: Mapped["User"] = relationship("User", back_populates="workspace_memberships")
