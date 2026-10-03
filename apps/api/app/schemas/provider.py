"""Pydantic schemas for Model Providers and Encrypted BYOK Credentials."""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ProviderCreateRequest(BaseModel):
    """Payload to configure a model provider."""
    workspace_id: uuid.UUID
    provider_type: str = Field(description="Provider type: ollama, gemini, openai, anthropic")
    display_name: str = Field(min_length=2, max_length=100)
    routing_mode: str = Field(default="local_only", description="Routing mode: local_only, byok_only, auto")
    default_model: str = Field(description="Default model (e.g. qwen2.5:7b, gemini-2.5-flash)")
    api_endpoint: str = Field(description="API base endpoint")
    config_options: Dict[str, Any] = Field(default_factory=dict)
    billing_tier: str = Field(default="zero_cost_local", description="zero_cost_local, byok_free_tier, byok_potentially_billable")
    is_enabled: bool = True
    is_default: bool = False


class ProviderUpdateRequest(BaseModel):
    """Payload to update provider settings."""
    display_name: Optional[str] = None
    routing_mode: Optional[str] = None
    default_model: Optional[str] = None
    api_endpoint: Optional[str] = None
    config_options: Optional[Dict[str, Any]] = None
    billing_tier: Optional[str] = None
    is_enabled: Optional[bool] = None
    is_default: Optional[bool] = None


class ProviderResponse(BaseModel):
    """Provider configuration response."""
    id: uuid.UUID
    workspace_id: uuid.UUID
    provider_type: str
    display_name: str
    is_enabled: bool
    is_default: bool
    routing_mode: str
    default_model: str
    api_endpoint: str
    config_options: Dict[str, Any]
    billing_tier: str
    has_credentials: bool = False
    key_fingerprint: Optional[str] = None
    created_at: datetime


class CredentialCreateRequest(BaseModel):
    """Secure payload to enroll a BYOK credential."""
    workspace_id: uuid.UUID
    provider_config_id: uuid.UUID
    credential_type: str = Field(default="api_key", description="api_key, oauth_token")
    secret: str = Field(min_length=8, description="Raw API key or token (will be encrypted immediately)")


class CredentialMetadataResponse(BaseModel):
    """Safe metadata response (Plaintext secret is NEVER returned)."""
    id: uuid.UUID
    workspace_id: uuid.UUID
    provider_config_id: uuid.UUID
    credential_type: str
    key_fingerprint: str
    is_valid: bool
    last_validated_at: Optional[datetime] = None
    last_validation_error: Optional[str] = None
    created_at: datetime
