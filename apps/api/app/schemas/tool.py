"""Pydantic schemas for Tool Registry and execution boundary."""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ToolRegisterRequest(BaseModel):
    """Payload to register a new tool in the workspace/system."""
    name: str = Field(min_length=2, max_length=100, description="Unique identifier (e.g. web_search)")
    display_name: str = Field(min_length=2, max_length=255)
    description: str = Field(min_length=5, description="Semantic description of tool capability")
    category: str = Field(default="system", max_length=50)
    risk_level: str = Field(default="low", pattern="^(low|medium|high|critical)$")
    input_schema: Dict[str, Any] = Field(description="JSON Schema for input parameters")
    output_schema: Optional[Dict[str, Any]] = Field(default_factory=dict, description="JSON Schema for output data")
    timeout_seconds: int = Field(default=30, ge=1, le=600)
    rate_limit_per_minute: int = Field(default=60, ge=1, le=1000)
    requires_approval: bool = False
    is_allowed_in_background: bool = True
    workspace_id: Optional[uuid.UUID] = None


class ToolResponse(BaseModel):
    """Tool metadata response model."""
    id: uuid.UUID
    workspace_id: Optional[uuid.UUID] = None
    integration_id: Optional[uuid.UUID] = None
    name: str
    display_name: str
    description: str
    category: str
    risk_level: str
    input_schema: Dict[str, Any]
    output_schema: Dict[str, Any]
    timeout_seconds: int
    rate_limit_per_minute: int
    requires_approval: bool
    is_allowed_in_background: bool
    is_active: bool
    created_at: datetime


class ToolExecutionRequest(BaseModel):
    """Payload to invoke a tool through the security boundary."""
    workspace_id: uuid.UUID
    tool_name: Optional[str] = None
    tool_id: Optional[uuid.UUID] = None
    arguments: Dict[str, Any] = Field(default_factory=dict)


class ToolExecutionResponse(BaseModel):
    """Result of tool execution."""
    success: bool
    tool_name: str
    result: Optional[Any] = None
    error: Optional[str] = None
    risk_level: str
    execution_time_ms: float
    requires_hitl_approval: bool = False
    approval_token: Optional[str] = None
