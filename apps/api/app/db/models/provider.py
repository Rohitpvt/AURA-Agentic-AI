"""Model Provider Configurations and Encrypted BYOK Credentials models."""

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, Optional
from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, GUID, JSONB, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.db.models.workspace import Workspace


class ProviderConfiguration(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Model provider configuration (Ollama Local, Gemini BYOK, OpenAI, Anthropic)."""

    __tablename__ = "provider_configurations"
    __table_args__ = (
        UniqueConstraint("workspace_id", "provider_type", name="uq_workspace_provider_type"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider_type: Mapped[str] = mapped_column(String(50), nullable=False)  # 'ollama', 'gemini', 'openai', 'anthropic'
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    routing_mode: Mapped[str] = mapped_column(String(30), default="local_only", nullable=False)  # 'local_only', 'byok_only', 'auto'
    default_model: Mapped[str] = mapped_column(String(100), nullable=False)
    api_endpoint: Mapped[str] = mapped_column(String(255), nullable=False)
    config_options: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    billing_tier: Mapped[str] = mapped_column(String(50), default="zero_cost_local", nullable=False)  # 'zero_cost_local', 'byok_free_tier', 'byok_potentially_billable'
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace", back_populates="provider_configurations")
    credentials: Mapped[list["Credential"]] = relationship(
        "Credential", back_populates="provider_config", cascade="all, delete-orphan"
    )


class Credential(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Encrypted credential vault. Plaintext secrets are NEVER stored in the database."""

    __tablename__ = "credentials"
    __table_args__ = (
        UniqueConstraint("provider_config_id", "credential_type", name="uq_provider_credential"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider_config_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("provider_configurations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    credential_type: Mapped[str] = mapped_column(String(50), default="api_key", nullable=False)  # 'api_key', 'oauth_token', 'service_account_json'
    encrypted_secret: Mapped[str] = mapped_column(Text, nullable=False)  # AES-256-GCM / Fernet ciphertext
    key_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)  # SHA-256 digest prefix (e.g. 'AIza...4f8a')
    is_valid: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_validated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_validation_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    provider_config: Mapped["ProviderConfiguration"] = relationship(
        "ProviderConfiguration", back_populates="credentials"
    )
