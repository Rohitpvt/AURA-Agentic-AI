"""Sandbox Profile Specifications for AURA Container Isolation."""

from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class SandboxProfileType(str, Enum):
    """Supported sandbox execution profiles."""
    READ_ONLY = "read_only"
    DEVELOPMENT = "development"
    NETWORK_RESEARCH = "network_research"
    HIGH_RISK = "high_risk"


class SandboxProfile(BaseModel):
    """Specification of container isolation bounds and privileges."""
    profile_type: SandboxProfileType
    description: str
    network_enabled: bool = False
    read_only_rootfs: bool = True
    workspace_writeable: bool = False
    max_memory_mb: int = 512
    cpu_quota_percent: int = 100  # 100% = 1 core
    pids_limit: int = 64
    timeout_seconds: int = 30
    drop_capabilities: List[str] = Field(default_factory=lambda: ["ALL"])
    allowed_syscalls: Optional[List[str]] = None
    requires_explicit_approval: bool = False


SANDBOX_PROFILES: Dict[SandboxProfileType, SandboxProfile] = {
    SandboxProfileType.READ_ONLY: SandboxProfile(
        profile_type=SandboxProfileType.READ_ONLY,
        description="Strict read-only isolation with no network and no disk write access",
        network_enabled=False,
        read_only_rootfs=True,
        workspace_writeable=False,
        max_memory_mb=256,
        cpu_quota_percent=50,
        pids_limit=32,
        timeout_seconds=20,
    ),
    SandboxProfileType.DEVELOPMENT: SandboxProfile(
        profile_type=SandboxProfileType.DEVELOPMENT,
        description="Scoped development sandbox with workspace-scoped read/write and isolated network",
        network_enabled=False,
        read_only_rootfs=True,
        workspace_writeable=True,
        max_memory_mb=512,
        cpu_quota_percent=100,
        pids_limit=64,
        timeout_seconds=60,
    ),
    SandboxProfileType.NETWORK_RESEARCH: SandboxProfile(
        profile_type=SandboxProfileType.NETWORK_RESEARCH,
        description="Controlled network access for web extraction and research, no host write access",
        network_enabled=True,
        read_only_rootfs=True,
        workspace_writeable=False,
        max_memory_mb=512,
        cpu_quota_percent=100,
        pids_limit=64,
        timeout_seconds=45,
    ),
    SandboxProfileType.HIGH_RISK: SandboxProfile(
        profile_type=SandboxProfileType.HIGH_RISK,
        description="High-privilege development tasks requiring mandatory human authorization",
        network_enabled=True,
        read_only_rootfs=False,
        workspace_writeable=True,
        max_memory_mb=1024,
        cpu_quota_percent=200,
        pids_limit=128,
        timeout_seconds=120,
        requires_explicit_approval=True,
    ),
}
