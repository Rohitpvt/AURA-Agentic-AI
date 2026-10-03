"""Pydantic schemas for Task DAG and Step Checkpoint management."""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class TaskStepCreate(BaseModel):
    """Schema for defining a step within a task DAG."""
    step_number: int = Field(ge=1, description="1-indexed step number")
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1)
    dependencies: List[int] = Field(default_factory=list, description="List of step_numbers this step depends on")
    tool_name: Optional[str] = Field(default=None, max_length=100)
    tool_input: Optional[Dict[str, Any]] = None
    verification_assertions: List[Dict[str, Any]] = Field(default_factory=list)


class TaskStepUpdate(BaseModel):
    """Schema for updating/checkpointing a step during execution."""
    status: Optional[str] = Field(None, pattern="^(pending|running|completed|failed|skipped|cancelled)$")
    tool_output: Optional[Dict[str, Any]] = None
    is_verified: Optional[bool] = None
    error_message: Optional[str] = None


class TaskStepResponse(BaseModel):
    """Task Step metadata response."""
    id: uuid.UUID
    task_id: uuid.UUID
    step_number: int
    title: str
    description: str
    dependencies: List[int]
    status: str
    tool_name: Optional[str] = None
    tool_input: Optional[Dict[str, Any]] = None
    tool_output: Optional[Dict[str, Any]] = None
    verification_assertions: List[Dict[str, Any]] = []
    is_verified: bool
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None


class TaskCreateRequest(BaseModel):
    """Payload to create a new high-level task/goal."""
    workspace_id: uuid.UUID
    title: str = Field(min_length=1, max_length=255)
    goal: str = Field(min_length=1)
    priority: str = Field(default="medium", pattern="^(low|medium|high|critical)$")
    autonomy_level: int = Field(default=2, ge=0, le=5)
    budget_max_tokens: int = Field(default=100000, ge=1000)
    budget_max_cost_cents: int = Field(default=500, ge=0)
    timeout_seconds: int = Field(default=1800, ge=10)
    session_id: Optional[uuid.UUID] = None
    idempotency_key: Optional[str] = Field(default=None, max_length=255)
    steps: Optional[List[TaskStepCreate]] = Field(default_factory=list, description="Optional initial DAG steps")


class TaskUpdateRequest(BaseModel):
    """Payload to update high-level task state."""
    status: Optional[str] = Field(None, pattern="^(pending|planning|running|completed|failed|cancelled|blocked)$")
    result_summary: Optional[str] = None
    error_summary: Optional[str] = None


class TaskResponse(BaseModel):
    """Task response model."""
    id: uuid.UUID
    workspace_id: uuid.UUID
    created_by: Optional[uuid.UUID] = None
    session_id: Optional[uuid.UUID] = None
    title: str
    goal: str
    status: str
    priority: str
    autonomy_level: int
    budget_max_tokens: int
    budget_max_cost_cents: int
    timeout_seconds: int
    idempotency_key: Optional[str] = None
    error_summary: Optional[str] = None
    result_summary: Optional[str] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    steps: List[TaskStepResponse] = []
