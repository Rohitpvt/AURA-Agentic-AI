"""AURA-901 Policy Decision Engine, Risk Classification & HITL Verification.

Enforces:
1. Five-tier deterministic risk classification mapping
2. Host execution partition mapping
3. Explicit Windows LOLBins denylist filter
4. Sliding-window rate limit token buckets
5. Cryptographic HMAC-SHA256 parameter-bound HITL token validation
6. Single-use replay protection
7. Anti-tamper expiration checking
"""

from __future__ import annotations

import collections
import json
import time
from typing import Any, Dict, FrozenSet, Optional, Set
import uuid

from app.core.config import settings
from app.core.security import compute_sha256_hash, verify_approval_signature
from app.services.os_guard.types import (
    HostExecutionPartition,
    OSActionRequest,
    OSActionType,
    OSRiskTier,
    PolicyDecisionResult,
    PolicyDecisionType,
)


# Canonical Phase 9 Windows LOLBins Denylist (Permanently Prohibited)
LOLBINS_DENYLIST: FrozenSet[str] = frozenset({
    "powershell.exe",
    "pwsh.exe",
    "cmd.exe",
    "wscript.exe",
    "cscript.exe",
    "mshta.exe",
    "rundll32.exe",
    "regsvr32.exe",
    "certutil.exe",
    "bitsadmin.exe",
    "msiexec.exe",
    "installutil.exe",
    "regasm.exe",
    "regsvcs.exe",
    "wmic.exe",
    "cscr.exe",
    "hh.exe",
    "schtasks.exe",
    "vssadmin.exe",
    "bash.exe",
})

# Deterministic Risk Tier Mapping
ACTION_RISK_MAP: Dict[OSActionType, OSRiskTier] = {
    OSActionType.READ_ONLY: OSRiskTier.READ_ONLY,
    OSActionType.SYSTEM_TELEMETRY: OSRiskTier.READ_ONLY,
    OSActionType.CLIPBOARD_READ: OSRiskTier.READ_ONLY,
    OSActionType.WINDOW_FOCUS: OSRiskTier.LOW_RISK_WRITE,
    OSActionType.MOUSE_MOVE: OSRiskTier.MEDIUM_RISK_INTERACTION,
    OSActionType.MOUSE_CLICK: OSRiskTier.MEDIUM_RISK_INTERACTION,
    OSActionType.KEYBOARD_INPUT: OSRiskTier.MEDIUM_RISK_INTERACTION,
    OSActionType.CLIPBOARD_WRITE: OSRiskTier.MEDIUM_RISK_INTERACTION,
    OSActionType.APPLICATION_LAUNCH: OSRiskTier.HIGH_RISK_SYSTEM_ACTION,
    OSActionType.PROCESS_TERMINATE: OSRiskTier.HIGH_RISK_SYSTEM_ACTION,
    OSActionType.HARDWARE_CONTROL: OSRiskTier.HIGH_RISK_SYSTEM_ACTION,
}

# Host Execution Partition Mapping
ACTION_PARTITION_MAP: Dict[OSActionType, HostExecutionPartition] = {
    OSActionType.READ_ONLY: HostExecutionPartition.HOST_REQUIRED_GOVERNED,
    OSActionType.SYSTEM_TELEMETRY: HostExecutionPartition.HOST_REQUIRED_GOVERNED,
    OSActionType.CLIPBOARD_READ: HostExecutionPartition.HOST_REQUIRED_GOVERNED,
    OSActionType.WINDOW_FOCUS: HostExecutionPartition.HOST_REQUIRED_GOVERNED,
    OSActionType.MOUSE_MOVE: HostExecutionPartition.HOST_REQUIRED_GOVERNED,
    OSActionType.MOUSE_CLICK: HostExecutionPartition.HOST_REQUIRED_GOVERNED,
    OSActionType.KEYBOARD_INPUT: HostExecutionPartition.HOST_REQUIRED_GOVERNED,
    OSActionType.CLIPBOARD_WRITE: HostExecutionPartition.HOST_REQUIRED_GOVERNED,
    OSActionType.APPLICATION_LAUNCH: HostExecutionPartition.PRIVILEGED_HOST,
    OSActionType.PROCESS_TERMINATE: HostExecutionPartition.PRIVILEGED_HOST,
    OSActionType.HARDWARE_CONTROL: HostExecutionPartition.PRIVILEGED_HOST,
}

# Sliding-Window Rate Limits (Operations per 60 Seconds)
RATE_LIMIT_BUCKETS: Dict[str, int] = {
    "mouse_click": 60,
    "mouse_move": 60,
    "keyboard_input": 10,
    "application_launch": 5,
    "process_terminate": 5,
    "hardware_control": 10,
    "clipboard_write": 30,
    "default": 60,
}

HITL_TOKEN_TTL_SEC: int = 120


class SlidingWindowRateLimiter:
    """In-memory sliding-window rate limiter per workspace and action category."""

    def __init__(self):
        # Map: (workspace_id, action_category) -> deque of timestamps
        self._history: Dict[str, collections.deque] = collections.defaultdict(collections.deque)

    def check_and_record(self, workspace_id: str, category: str, limit: int, window_sec: float = 60.0) -> bool:
        """Check if action is within limit and record timestamp. Returns True if allowed."""
        now = time.time()
        key = f"{workspace_id}:{category}"
        q = self._history[key]

        # Evict timestamps older than window
        while q and (now - q[0]) > window_sec:
            q.popleft()

        if len(q) >= limit:
            return False

        q.append(now)
        return True

    def clear(self) -> None:
        """Clear all rate limit history."""
        self._history.clear()


class OSPolicyEngine:
    """Authoritative deterministic policy evaluator for all OS interactions."""

    def __init__(self):
        self.rate_limiter = SlidingWindowRateLimiter()
        self._consumed_hitl_tokens: Set[str] = set()

    def get_risk_tier(self, action_type: OSActionType) -> OSRiskTier:
        """Deterministically map action type to risk tier."""
        return ACTION_RISK_MAP.get(action_type, OSRiskTier.CRITICAL_ACTION)

    def get_partition(self, action_type: OSActionType) -> HostExecutionPartition:
        """Map action type to host execution partition."""
        return ACTION_PARTITION_MAP.get(action_type, HostExecutionPartition.FORBIDDEN)

    def evaluate_action(
        self,
        request: OSActionRequest,
        autonomy_level: int = 3,
    ) -> PolicyDecisionResult:
        """Evaluate action against deterministic policy rules, rate limits, and HITL authorization."""
        risk_tier = self.get_risk_tier(request.action_type)
        partition = self.get_partition(request.action_type)

        # 1. Reject Forbidden Partition
        if partition == HostExecutionPartition.FORBIDDEN:
            return PolicyDecisionResult(
                decision=PolicyDecisionType.DENY,
                risk_tier=risk_tier,
                partition=partition,
                reason=f"Action type '{request.action_type.value}' is strictly forbidden by host security policy.",
            )

        # 2. Check Expiration
        now = time.time()
        if request.expires_at is not None and now > request.expires_at:
            return PolicyDecisionResult(
                decision=PolicyDecisionType.EXPIRED,
                risk_tier=risk_tier,
                partition=partition,
                reason="Action request has expired.",
            )

        # 3. Inspect Parameters for Shell Execution / LOLBins
        param_error = self._inspect_parameters(request.action_type, request.parameters)
        if param_error:
            return PolicyDecisionResult(
                decision=PolicyDecisionType.DENY,
                risk_tier=risk_tier,
                partition=partition,
                reason=param_error,
            )

        # 4. Enforce Sliding-Window Rate Limits
        cat_key = request.action_type.value
        limit = RATE_LIMIT_BUCKETS.get(cat_key, RATE_LIMIT_BUCKETS["default"])
        if not self.rate_limiter.check_and_record(request.workspace_id, cat_key, limit):
            return PolicyDecisionResult(
                decision=PolicyDecisionType.RATE_LIMIT,
                risk_tier=risk_tier,
                partition=partition,
                reason=f"Rate limit exceeded for action '{cat_key}' ({limit} ops/60s).",
            )

        # 5. Determine HITL Requirement based on Autonomy Level & Risk Tier
        requires_hitl = self._requires_hitl(risk_tier, autonomy_level)

        if requires_hitl:
            if not request.hitl_approval_token:
                return PolicyDecisionResult(
                    decision=PolicyDecisionType.REQUIRE_HITL,
                    risk_tier=risk_tier,
                    partition=partition,
                    reason=f"Action '{request.action_type.value}' (Risk: {risk_tier.value}) requires cryptographic HITL approval.",
                    requires_hitl=True,
                )

            # Validate cryptographic HITL token
            token_valid, token_err = self._validate_hitl_token(request)
            if not token_valid:
                return PolicyDecisionResult(
                    decision=PolicyDecisionType.DENY,
                    risk_tier=risk_tier,
                    partition=partition,
                    reason=f"HITL approval token validation failed: {token_err}",
                    requires_hitl=True,
                )

        return PolicyDecisionResult(
            decision=PolicyDecisionType.ALLOW,
            risk_tier=risk_tier,
            partition=partition,
            reason="Policy evaluation passed successfully.",
            requires_hitl=requires_hitl,
        )

    def _requires_hitl(self, risk_tier: OSRiskTier, autonomy_level: int) -> bool:
        """Determine if an action requires HITL given the autonomy level."""
        if risk_tier == OSRiskTier.READ_ONLY or risk_tier == OSRiskTier.LOW_RISK_WRITE:
            return False
        if risk_tier == OSRiskTier.MEDIUM_RISK_INTERACTION:
            # Medium risk requires HITL at L0-L2; autonomous at L3-L5
            return autonomy_level < 3
        if risk_tier in (OSRiskTier.HIGH_RISK_SYSTEM_ACTION, OSRiskTier.CRITICAL_ACTION):
            # High risk requires HITL across all standard autonomy levels
            return True
        return True

    def _inspect_parameters(self, action_type: OSActionType, params: Dict[str, Any]) -> Optional[str]:
        """Scan parameters for command injection, LOLBins, and prohibited flags."""
        # 1. Prohibit shell=True or raw shell commands
        if params.get("shell") is True or params.get("use_shell") is True:
            return "Prohibited parameter 'shell=True' detected. Arbitrary shell execution is forbidden."

        # 2. Check executable path against LOLBins for application launches
        if action_type == OSActionType.APPLICATION_LAUNCH:
            target = str(
                params.get("application_id")
                or params.get("target")
                or params.get("executable")
                or ""
            ).strip().lower()
            if not target:
                return "Application launch request missing 'application_id' or 'target' executable path."

            import os
            basename = os.path.basename(target).lower()
            if basename in LOLBINS_DENYLIST or target in LOLBINS_DENYLIST:
                return f"Prohibited binary '{target}' is in the Windows LOLBins security denylist."

        # 3. Check keyboard inputs for prohibited destructive commands
        if action_type == OSActionType.KEYBOARD_INPUT:
            shortcut = str(params.get("shortcut") or "").lower()
            if "win" in shortcut or "cmd" in shortcut or "super" in shortcut:
                return "System Windows key shortcuts are prohibited by safety policy."

        return None

    def _validate_hitl_token(self, request: OSActionRequest) -> tuple[bool, str]:
        """Verify HMAC-SHA256 signature, parameter hash, workspace match, and single-use."""
        token = request.hitl_approval_token
        if not token:
            return False, "Missing token string"

        # Check replay
        token_hash = compute_sha256_hash(token)
        if token_hash in self._consumed_hitl_tokens:
            return False, "Approval token has already been consumed (Replay denied)"

        # Parse token payload if passed as JSON structure or token dict
        try:
            # Expected format: base64/JSON encoded token structure with signature
            token_data = json.loads(token) if isinstance(token, str) and token.startswith("{") else None
            if not token_data:
                # If raw signature string, verify against canonical payload
                param_hash = compute_sha256_hash(json.dumps(request.parameters, sort_keys=True, separators=(",", ":")))
                expected_payload = {
                    "workspace_id": request.workspace_id,
                    "action_type": request.action_type.value,
                    "param_hash": param_hash,
                }
                if not verify_approval_signature(expected_payload, token):
                    return False, "Cryptographic token signature mismatch"
                self._consumed_hitl_tokens.add(token_hash)
                return True, ""

            # Verify structured token data
            sig = token_data.get("signature", "")
            payload = {k: v for k, v in token_data.items() if k != "signature"}

            # Check workspace binding
            if payload.get("workspace_id") != request.workspace_id:
                return False, f"Token workspace_id '{payload.get('workspace_id')}' does not match request workspace '{request.workspace_id}'"

            # Check action type binding
            if payload.get("action_type") != request.action_type.value:
                return False, f"Token action_type '{payload.get('action_type')}' does not match request '{request.action_type.value}'"

            # Check parameter hash binding
            actual_param_hash = compute_sha256_hash(json.dumps(request.parameters, sort_keys=True, separators=(",", ":")))
            if payload.get("param_hash") != actual_param_hash:
                return False, "Token parameter hash mismatch (Parameters were modified after approval)"

            # Check expiration
            expires_at = float(payload.get("expires_at", 0))
            if expires_at > 0 and time.time() > expires_at:
                return False, "HITL approval token has expired"

            # Verify HMAC signature
            if not verify_approval_signature(payload, sig):
                return False, "Cryptographic token signature is invalid"

            # Mark consumed
            self._consumed_hitl_tokens.add(token_hash)
            return True, ""

        except Exception as e:
            return False, f"Token decoding error: {e}"

    def reset_consumed_tokens(self) -> None:
        """Reset consumed tokens set (for testing purposes)."""
        self._consumed_hitl_tokens.clear()


os_policy_engine = OSPolicyEngine()
