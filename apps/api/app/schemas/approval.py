"""Pydantic schemas for Human-In-The-Loop (HITL) approval requests and resolution."""

import uuid
from datetime import datetime
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class ApprovalRequestResponse(BaseModel):
    """Details of a cryptographic HITL approval request."""
    id: uuid.UUID
    workspace_id: uuid.UUID
    task_id: uuid.UUID
    agent_run_id: uuid.UUID
    tool_name: str
    tool_params: Dict[str, Any]
    risk_level: str
    status: str
    approval_token_hash: str
    reason_requested: Optional[str] = None
    resolved_by: Optional[uuid.UUID] = None
    resolution_notes: Optional[str] = None
    expires_at: datetime
    resolved_at: Optional[datetime] = None
    created_at: datetime


class ApprovalResolveRequest(BaseModel):
    """Payload to resolve a pending approval request."""
    decision: str = Field(..., pattern="^(approve|reject)$", description="'approve' or 'reject'")
    token: str = Field(..., min_length=10, description="Cryptographic HMAC-SHA256 approval token")
    resolution_notes: Optional[str] = Field(None, description="Optional notes regarding the human decision")


class ApprovalResolveResponse(BaseModel):
    """Outcome of resolving an approval request."""
    approval_id: uuid.UUID
    status: str
    task_id: uuid.UUID
    resumed: bool
    execution_result: Optional[Dict[str, Any]] = None
    message: str
