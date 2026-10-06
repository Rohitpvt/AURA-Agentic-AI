"""File Registry and Document Chunk Database Models."""

from datetime import datetime, timezone
import enum
import uuid
from sqlalchemy import BigInteger, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, GUID, JSONB, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin, Vector


class FileStatus(str, enum.Enum):
    """File ingestion and lifecycle states.
    
    Semantic Invariants:
    - UPLOADED: Intake stored, SHA-256 verified, registered in database.
    - PARSING: Extraction pass actively in progress.
    - INDEXED: Extraction completed successfully and file registry / structural metadata
               catalog updated. (Note: does NOT mean FileChunk generation, FastEmbed vectors,
               pgvector indexing, or cognitive memory linking, which are Phase 6.3 capabilities).
    - FAILED: Parsing or extraction error encountered.
    - QUARANTINED: High-risk executable disguise or payload blocked.
    - DELETE_REQUESTED -> STORAGE_PURGED -> VECTORS_PURGED -> MEMORY_TOMBSTONED -> AUDITED -> DELETED:
      Idempotent deletion lifecycle state machine.
    """
    UPLOADED = "uploaded"
    PARSING = "parsing"
    INDEXED = "indexed"
    FAILED = "failed"
    QUARANTINED = "quarantined"
    DELETE_REQUESTED = "delete_requested"
    STORAGE_PURGED = "storage_purged"
    VECTORS_PURGED = "vectors_purged"
    MEMORY_TOMBSTONED = "memory_tombstoned"
    AUDITED = "audited"
    DELETED = "deleted"


class FileRecord(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """Canonical file registry entity representing an uploaded user document."""

    __tablename__ = "file_records"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    safe_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_extension: Mapped[str] = mapped_column(String(20), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default=FileStatus.UPLOADED.value, nullable=False, index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)
    security_flags: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)


class FileChunk(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Structural chunk with 768-dimensional FastEmbed vector embedding."""

    __tablename__ = "file_chunks"
    __table_args__ = (
        UniqueConstraint("workspace_id", "file_id", "chunk_index", name="uq_file_chunks_ws_file_idx"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("file_records.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(768), nullable=True)
    source_location: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
