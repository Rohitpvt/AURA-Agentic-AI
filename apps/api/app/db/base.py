"""SQLAlchemy 2.0 Declarative Base, Dialect Types, and Common Mixins."""

import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional
from sqlalchemy import DateTime, types
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB, UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

try:
    from pgvector.sqlalchemy import Vector as PGVector
except ImportError:
    PGVector = None

# 1. Portable UUID Type
GUID = types.Uuid(as_uuid=True)

# 2. Portable JSONB Type
JSONB = types.JSON().with_variant(PG_JSONB, "postgresql")


# 3. Portable Vector Type
class Vector(types.TypeDecorator):
    """Vector type using pgvector on PostgreSQL and JSON on SQLite."""

    impl = types.JSON
    cache_ok = True

    def __init__(self, dim: int = 768):
        super().__init__()
        self.dim = dim

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql" and PGVector is not None:
            return dialect.type_descriptor(PGVector(self.dim))
        return dialect.type_descriptor(types.JSON())

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value
        if isinstance(value, list):
            return value
        return list(value)

    def process_result_value(self, value, dialect):
        return value


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""
    pass


class UUIDPrimaryKeyMixin:
    """Mixin for UUID primary key generation."""
    id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )


class TimestampMixin:
    """Mixin for UTC timestamp tracking."""
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class SoftDeleteMixin:
    """Mixin for soft-deletion support."""
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None
