"""Pydantic schemas for Automations and Scheduled Runs."""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator
from croniter import croniter


class AutomationCreateRequest(BaseModel):
    """Payload for creating a new scheduled automation."""

    name: str = Field(..., min_length=1, max_length=255, description="Human-readable automation title")
    description: Optional[str] = Field(default=None, max_length=2000, description="Detailed explanation of automation")
    trigger_type: str = Field(default="cron", description="Trigger mechanism: cron, webhook, delayed")
    cron_expression: str = Field(..., min_length=1, max_length=100, description="Standard 5-field cron expression")
    timezone: str = Field(default="UTC", max_length=100, description="IANA timezone name")
    prompt_template: str = Field(..., min_length=1, max_length=10000, description="Prompt/objective template to execute")
    assigned_skill_id: Optional[uuid.UUID] = Field(default=None, description="Optional bound procedural skill ID")
    autonomy_level: int = Field(default=3, ge=0, le=4, description="Autonomy ceiling (L0-L4)")
    is_active: bool = Field(default=True, description="Whether schedule is active")

    @field_validator("cron_expression")
    @classmethod
    def validate_cron(cls, v: str) -> str:
        clean = v.strip()
        parts = clean.split()
        if len(parts) != 5:
            raise ValueError("Cron expression must consist of exactly 5 fields: 'minute hour day-of-month month day-of-week'")
        if not croniter.is_valid(clean):
            raise ValueError(f"Invalid cron expression syntax: '{clean}'")
        return clean

    @field_validator("timezone")
    @classmethod
    def validate_tz(cls, v: str) -> str:
        import zoneinfo
        try:
            zoneinfo.ZoneInfo(v.strip())
            return v.strip()
        except Exception:
            raise ValueError(f"Invalid IANA timezone string: '{v}'")


class AutomationUpdateRequest(BaseModel):
    """Payload for updating an existing automation."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=2000)
    cron_expression: Optional[str] = Field(default=None, min_length=1, max_length=100)
    timezone: Optional[str] = Field(default=None, max_length=100)
    prompt_template: Optional[str] = Field(default=None, min_length=1, max_length=10000)
    assigned_skill_id: Optional[uuid.UUID] = None
    autonomy_level: Optional[int] = Field(default=None, ge=0, le=4)
    is_active: Optional[bool] = None

    @field_validator("cron_expression")
    @classmethod
    def validate_cron(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        clean = v.strip()
        parts = clean.split()
        if len(parts) != 5:
            raise ValueError("Cron expression must consist of exactly 5 fields: 'minute hour day-of-month month day-of-week'")
        if not croniter.is_valid(clean):
            raise ValueError(f"Invalid cron expression syntax: '{clean}'")
        return clean

    @field_validator("timezone")
    @classmethod
    def validate_tz(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        import zoneinfo
        try:
            zoneinfo.ZoneInfo(v.strip())
            return v.strip()
        except Exception:
            raise ValueError(f"Invalid IANA timezone string: '{v}'")


class AutomationResponse(BaseModel):
    """Public representation of an automation."""

    id: uuid.UUID
    workspace_id: uuid.UUID
    created_by: Optional[uuid.UUID] = None
    name: str
    description: Optional[str] = None
    trigger_type: str
    cron_expression: Optional[str] = None
    timezone: str
    prompt_template: str
    assigned_skill_id: Optional[uuid.UUID] = None
    autonomy_level: int
    is_active: bool
    next_run_at: Optional[datetime] = None
    last_run_at: Optional[datetime] = None
    last_success_at: Optional[datetime] = None
    last_failure_at: Optional[datetime] = None
    failure_streak: int
    circuit_state: str
    circuit_opened_at: Optional[datetime] = None
    total_runs: int
    total_failures: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AutomationRunResponse(BaseModel):
    """Public representation of an individual automation run."""

    id: uuid.UUID
    automation_id: uuid.UUID
    workspace_id: uuid.UUID
    scheduled_for: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    status: str
    attempt: int
    retry_count: int
    max_retries: int
    claimed_at: Optional[datetime] = None
    claim_expires_at: Optional[datetime] = None
    claimed_by: Optional[str] = None
    task_id: Optional[uuid.UUID] = None
    idempotency_key: str
    error_code: Optional[str] = None
    error_summary: Optional[str] = None
    output_summary: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
