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
from app.services.os_guard.app_registry import (
    ApplicationDefinition,
    ApplicationRegistry,
    application_registry,
    CANONICAL_ALLOWLIST,
)
from app.services.os_guard.clipboard_service import (
    GovernedClipboardAdapter,
    governed_clipboard_adapter,
)
from app.services.os_guard.hardware_service import (
    BrightnessControlNotSupportedError,
    CapabilityDiscoveryService,
    capability_discovery_service,
    CoreAudioVolumeAdapter,
    core_audio_volume_adapter,
    WmiDisplayBrightnessAdapter,
    wmi_display_brightness_adapter,
)
from app.services.os_guard.process_service import ProcessService, process_service
from app.services.os_guard.telemetry_service import (
    GPUTelemetryAdapter,
    SystemTelemetryAdapter,
    system_telemetry_adapter,
)
from app.services.os_guard.validators import (
    CoordinateSafetyValidator,
    KeyboardInputValidator,
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
    "KeyboardInputValidator",
    "ApplicationDefinition",
    "ApplicationRegistry",
    "application_registry",
    "CANONICAL_ALLOWLIST",
    "GovernedClipboardAdapter",
    "governed_clipboard_adapter",
    "CoreAudioVolumeAdapter",
    "core_audio_volume_adapter",
    "WmiDisplayBrightnessAdapter",
    "wmi_display_brightness_adapter",
    "CapabilityDiscoveryService",
    "capability_discovery_service",
    "BrightnessControlNotSupportedError",
    "ProcessService",
    "process_service",
    "SystemTelemetryAdapter",
    "system_telemetry_adapter",
    "GPUTelemetryAdapter",
    "LOLBINS_DENYLIST",
    "PROTECTED_PROCESS_NAMES",
    "ACTION_RISK_MAP",
    "ACTION_PARTITION_MAP",
    "RATE_LIMIT_BUCKETS",
]

