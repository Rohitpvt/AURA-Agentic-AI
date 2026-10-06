"""Encrypted Web Credential and Session Vault Database Models (AURA-1003)."""

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, Optional
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, GUID, JSONB, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.db.models.workspace import Workspace


class WebCredential(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Encrypted website credential vault. Plaintext secrets are NEVER stored."""

    __tablename__ = "web_credentials"
    __table_args__ = (
        UniqueConstraint("workspace_id", "target_origin", "name", name="uq_workspace_origin_credential_name"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    target_domain: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    target_origin: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    allow_subdomains: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # AES-256-GCM encrypted ciphertexts
    username_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    password_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    extra_secrets_ciphertext: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Privacy-preserving masked identifier (e.g. 'us***@example.com' or 'ad***')
    username_hint: Mapped[str] = mapped_column(String(100), nullable=False)
    key_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace")


class WebSessionState(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Encrypted browser session and storage state vault (cookies, localStorage, auth state)."""

    __tablename__ = "web_session_states"
    __table_args__ = (
        UniqueConstraint("workspace_id", "target_origin", "session_name", name="uq_workspace_origin_session"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_name: Mapped[str] = mapped_column(String(100), default="default", nullable=False)
    target_domain: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    target_origin: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    # AES-256-GCM encrypted Playwright storage_state JSON
    encrypted_storage_state: Mapped[str] = mapped_column(Text, nullable=False)
    key_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace")
