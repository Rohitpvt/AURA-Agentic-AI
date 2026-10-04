"""AURA-901 Windows OS Control Foundation & Policy Boundary Package."""

from app.services.os_guard.adapters import BaseOSExecutionAdapter, SafeMockOSExecutionAdapter
from app.services.os_guard.os_guard_service import OSGuardService, os_guard_service
from app.services.os_guard.policy import (
    ACTION_PARTITION_MAP,
    ACTION_RISK_MAP,
    LOLBINS_DENYLIST,
    OSPolicyEngine,
    RATE_LIMIT_BUCKETS,
    os_policy_engine,
)
from app.services.os_guard.types import (
    HostExecutionPartition,
    OSActionLifecycleState,
    OSActionRequest,
    OSActionResponse,
    OSActionType,
    OSRiskTier,
    PolicyDecisionResult,
    PolicyDecisionType,
)
from app.services.os_guard.validators import (
    CoordinateSafetyValidator,
    PathValidator,
    ProcessIdentityValidator,
    PROTECTED_PROCESS_NAMES,
)

__all__ = [
    "BaseOSExecutionAdapter",
    "SafeMockOSExecutionAdapter",
    "OSGuardService",
    "os_guard_service",
    "OSPolicyEngine",
    "os_policy_engine",
    "OSActionType",
    "OSRiskTier",
    "OSActionLifecycleState",
    "HostExecutionPartition",
    "PolicyDecisionType",
    "OSActionRequest",
    "OSActionResponse",
    "PolicyDecisionResult",
    "PathValidator",
    "ProcessIdentityValidator",
    "CoordinateSafetyValidator",
    "LOLBINS_DENYLIST",
    "PROTECTED_PROCESS_NAMES",
    "ACTION_RISK_MAP",
    "ACTION_PARTITION_MAP",
    "RATE_LIMIT_BUCKETS",
]
