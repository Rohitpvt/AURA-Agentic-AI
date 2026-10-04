"""AURA-901 Windows OS Control Foundation & Policy Boundary Types.

Defines:
1. Canonical OSActionType enumeration
2. Five-tier OSRiskTier taxonomy
3. Strict OSActionLifecycleState state machine
4. HostExecutionPartition classification
5. PolicyDecisionType enum
6. Pydantic request and response models
"""

from __future__ import annotations

from enum import Enum
import time
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field, field_validator


class OSActionType(str, Enum):
    """Canonical Phase 9 OS Action Types."""

    READ_ONLY = "read_only"
    APPLICATION_LAUNCH = "application_launch"
    PROCESS_TERMINATE = "process_terminate"
    WINDOW_FOCUS = "window_focus"
    MOUSE_MOVE = "mouse_move"
    MOUSE_CLICK = "mouse_click"
    KEYBOARD_INPUT = "keyboard_input"
    CLIPBOARD_READ = "clipboard_read"
    CLIPBOARD_WRITE = "clipboard_write"
    SYSTEM_TELEMETRY = "system_telemetry"
    HARDWARE_CONTROL = "hardware_control"


class OSRiskTier(str, Enum):
    """Canonical Phase 9 Five-Tier Risk Taxonomy."""

    READ_ONLY = "read_only"
    LOW_RISK_WRITE = "low_risk_write"
    MEDIUM_RISK_INTERACTION = "medium_risk_interaction"
    HIGH_RISK_SYSTEM_ACTION = "high_risk_system_action"
    CRITICAL_ACTION = "critical_action"


class OSActionLifecycleState(str, Enum):
    """Strict OS Action State Machine Lifecycle."""

    CREATED = "created"
    VALIDATING = "validating"
    POLICY_CHECK = "policy_check"
    WAITING_HITL = "waiting_hitl"
    AUTHORIZED = "authorized"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    KILL_SWITCHED = "kill_switched"
    EXPIRED = "expired"


class HostExecutionPartition(str, Enum):
    """Execution Partition Boundaries."""

    CONTAINER_SAFE = "container_safe"
    HOST_REQUIRED_GOVERNED = "host_required_governed"
    PRIVILEGED_HOST = "privileged_host"
    FORBIDDEN = "forbidden"


class PolicyDecisionType(str, Enum):
    """Policy Decision Outcomes."""

    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_HITL = "require_hitl"
    RATE_LIMIT = "rate_limit"
    KILL_SWITCHED = "kill_switched"
    EXPIRED = "expired"
    INVALID = "invalid"


class OSActionRequest(BaseModel):
    """Strict Governed Host Action Request Contract."""

    action_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    workspace_id: str
    actor_type: str = "agent"
    actor_id: str = "system"
    action_type: OSActionType
    parameters: Dict[str, Any] = Field(default_factory=dict)
    hitl_approval_token: Optional[str] = None
    created_at: float = Field(default_factory=time.time)
    expires_at: Optional[float] = None
    timeout_seconds: float = 5.0
    correlation_id: Optional[str] = None
    trace_id: Optional[str] = None

    @field_validator("timeout_seconds")
    @classmethod
    def validate_timeout_bounds(cls, v: float) -> float:
        """Enforce hard maximum timeout of 5.0 seconds."""
        if v <= 0:
            raise ValueError("Timeout must be strictly positive (> 0.0s)")
        if v > 5.0:
            # Hard clamp / reject oversized timeout bypass attempts
            return 5.0
        return v

    @field_validator("workspace_id")
    @classmethod
    def validate_workspace_id(cls, v: str) -> str:
        """Validate workspace string is non-empty."""
        if not v or not v.strip():
            raise ValueError("workspace_id must be a valid non-empty string")
        return v.strip()


class PolicyDecisionResult(BaseModel):
    """Deterministic Outcome of Policy Evaluation."""

    decision: PolicyDecisionType
    risk_tier: OSRiskTier
    partition: HostExecutionPartition
    reason: str
    requires_hitl: bool = False
    hitl_token_id: Optional[str] = None


class OSActionResponse(BaseModel):
    """Governed OS Action Execution Response."""

    action_id: str
    workspace_id: str
    action_type: OSActionType
    state: OSActionLifecycleState
    policy_decision: PolicyDecisionType
    risk_tier: OSRiskTier
    duration_ms: float = 0.0
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    trace_id: Optional[str] = None
