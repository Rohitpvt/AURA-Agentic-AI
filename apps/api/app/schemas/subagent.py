"""Pydantic schemas for Sub-Agent Worker Pool and execution contracts."""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class SubAgentSpec(BaseModel):
    """Specification for dispatching a bounded sub-agent worker."""
    role: str = Field(..., description="Role of the sub-agent (research_agent, analysis_agent, coding_agent, synthesis_agent)")
    goal: str = Field(..., max_length=1000, description="Focused subtask goal")
    workspace_id: uuid.UUID = Field(..., description="Workspace boundary")
    parent_task_id: uuid.UUID = Field(..., description="Parent Task ID")
    parent_run_id: uuid.UUID = Field(..., description="Parent Agent Run ID")
    assigned_budget_tokens: int = Field(default=25000, ge=1000, le=100000, description="Token budget slice")
    depth_level: int = Field(default=1, ge=1, le=2, description="Delegation depth level (max 2)")
    permitted_tools: Optional[List[str]] = Field(None, description="Explicit tool allowlist for this sub-agent")
    scoped_context: Optional[str] = Field(None, description="Focused contextual summary from supervisor")


class SubAgentResult(BaseModel):
    """Deterministic structured output contract returned by sub-agent workers."""
    role: str
    subtask: str
    status: str = Field(..., description="'completed', 'failed', or 'cancelled'")
    findings: str = Field(..., description="Consolidated findings or summary produced by worker")
    artifacts: List[Dict[str, Any]] = Field(default_factory=list, description="Structured data artifacts produced")
    tool_summaries: List[str] = Field(default_factory=list, description="Summary of tools invoked during work")
    verification_result: Dict[str, Any] = Field(default_factory=dict, description="Output verification status")
    consumed_tokens: int = 0
    duration_ms: float = 0.0
    error: Optional[str] = None


class SubAgentRunResponse(BaseModel):
    """Database record representation of a sub-agent execution instance."""
    id: uuid.UUID
    parent_run_id: uuid.UUID
    task_id: uuid.UUID
    role: str
    goal: str
    assigned_budget_tokens: int
    consumed_tokens: int
    depth_level: int
    status: str
    result_payload: Optional[Dict[str, Any]] = None
    started_at: datetime
    ended_at: Optional[datetime] = None
