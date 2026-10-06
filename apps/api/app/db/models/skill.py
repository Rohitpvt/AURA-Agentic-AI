"""Procedural Skill and Skill Version models."""

import uuid
from typing import Any, Dict, List
from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, GUID, JSONB, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Skill(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """Procedural multi-step skill entity."""

    __tablename__ = "skills"
    __table_args__ = (UniqueConstraint("slug", "workspace_id", name="uq_skill_slug_workspace"),)

    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    is_system_skill: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    versions: Mapped[List["SkillVersion"]] = relationship(
        "SkillVersion", back_populates="skill", cascade="all, delete-orphan", order_by="SkillVersion.created_at.desc()"
    )


class SkillVersion(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Immutable version of a procedural skill recipe."""

    __tablename__ = "skill_versions"
    __table_args__ = (UniqueConstraint("skill_id", "version_semver", name="uq_skill_version"),)

    skill_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("skills.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_semver: Mapped[str] = mapped_column(String(20), nullable=False)
    instruction_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    required_tools: Mapped[List[str]] = mapped_column(JSONB, default=list, nullable=False)
    preconditions: Mapped[List[str]] = mapped_column(JSONB, default=list, nullable=False)
    trigger_phrases: Mapped[List[str]] = mapped_column(JSONB, default=list, nullable=False)
    is_published: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    skill: Mapped["Skill"] = relationship("Skill", back_populates="versions")
