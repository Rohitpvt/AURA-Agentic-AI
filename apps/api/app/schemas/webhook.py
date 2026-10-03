"""Pydantic schemas for Webhook Ingress and Management."""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class WebhookEndpointCreateRequest(BaseModel):
    """Payload to configure a new inbound webhook endpoint."""
    name: str = Field(min_length=1, max_length=255, description="Human-readable webhook endpoint name")
    description: Optional[str] = Field(default=None, max_length=2000)
    prompt_template: str = Field(
        min_length=1,
        max_length=5000,
        description="Prompt template hydrated with webhook payload data (e.g., 'Process issue {payload.issue.id}: {payload.issue.title}')",
    )
    autonomy_level: int = Field(default=4, ge=1, le=4, description="Maximum autonomy level bound (1 to 4)")
    is_active: bool = Field(default=True)
    rate_limit_per_minute: int = Field(default=60, ge=1, le=300)


class WebhookEndpointUpdateRequest(BaseModel):
    """Payload to update an existing webhook endpoint."""
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    prompt_template: Optional[str] = Field(default=None, min_length=1, max_length=5000)
    autonomy_level: Optional[int] = Field(default=None, ge=1, le=4)
    is_active: Optional[bool] = None
    rate_limit_per_minute: Optional[int] = Field(default=None, ge=1, le=300)


class WebhookEndpointResponse(BaseModel):
    """Public metadata representation of a webhook endpoint (secret is masked)."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    public_id: str
    name: str
    description: Optional[str] = None
    prompt_template: str
    autonomy_level: int
    is_active: bool
    rate_limit_per_minute: int
    last_received_at: Optional[datetime] = None
    total_received: int = 0
    total_failed: int = 0
    created_at: datetime
    updated_at: datetime


class WebhookEndpointCreatedResponse(WebhookEndpointResponse):
    """Response returned upon creation or secret rotation containing the plaintext secret ONCE."""
    secret: str = Field(description="Cryptographic HMAC secret (displayed only once)")


class WebhookDeliveryResponse(BaseModel):
    """Telemetry representation of a webhook delivery receipt."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    webhook_endpoint_id: uuid.UUID
    workspace_id: uuid.UUID
    idempotency_key: str
    received_at: datetime
    status: str
    task_id: Optional[uuid.UUID] = None
    payload_hash: str
    error_code: Optional[str] = None
    error_summary: Optional[str] = None


class WebhookIngressResult(BaseModel):
    """Public minimal acknowledgement returned to external webhook sender."""
    status: str = Field(description="Outcome: 'accepted', 'duplicate', 'rejected', 'blocked'")
    message: str
    idempotency_key: str
    task_id: Optional[uuid.UUID] = None
