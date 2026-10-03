"""Pydantic schemas for Agent Runtime, Supervisor Planner, and Execution Events."""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class AgentGoalRequest(BaseModel):
    """User goal submission to the Agent Control Plane."""
    workspace_id: uuid.UUID
    goal: str = Field(min_length=3, description="Natural language goal or instruction")
    title: Optional[str] = Field(default=None, max_length=255)
    session_id: Optional[uuid.UUID] = None
    priority: str = Field(default="medium", pattern="^(low|medium|high|critical)$")
    autonomy_level: int = Field(default=2, ge=0, le=5)
    max_iterations: int = Field(default=10, ge=1, le=50)
    routing_mode: str = Field(default="local_only", pattern="^(local_only|byok_only|auto)$")
    preferred_provider: Optional[str] = Field(default="ollama", pattern="^(ollama|gemini)$")


class AgentPlanStep(BaseModel):
    """Decomposed step in a structured supervisor plan."""
    step_number: int = Field(ge=1)
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    dependencies: List[int] = Field(default_factory=list)
    suggested_tool: Optional[str] = None
    tool_input: Optional[Dict[str, Any]] = None
    verification_criteria: Optional[str] = Field(default="Step produced valid output")


class AgentPlanResponse(BaseModel):
    """Structured plan produced by Supervisor Planner."""
    goal: str
    summary: str
    steps: List[AgentPlanStep]
    estimated_complexity: str = "medium"


class AgentEventPayload(BaseModel):
    """Structured telemetry/state event emitted during agent run."""
    event_type: str
    timestamp: str
    task_id: Optional[uuid.UUID] = None
    step_number: Optional[int] = None
    agent_run_id: Optional[uuid.UUID] = None
    data: Dict[str, Any] = Field(default_factory=dict)


class AgentRunResponse(BaseModel):
    """Complete summary of an agent run execution."""
    id: uuid.UUID
    task_id: uuid.UUID
    workspace_id: uuid.UUID
    status: str
    model_name: str
    model_tier: str
    total_tokens_in: int
    total_tokens_out: int
    duration_ms: int
    final_result: Optional[str] = None
    error: Optional[str] = None
    started_at: datetime
    ended_at: Optional[datetime] = None
    events: List[Dict[str, Any]] = []
