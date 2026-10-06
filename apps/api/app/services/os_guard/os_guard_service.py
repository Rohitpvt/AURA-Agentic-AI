"""AURA-901 Master OS Guard Service and Governance Coordinator.

Orchestrates:
1. Single-worker concurrency serialization lock (MAX_ACTIVE_ACTIONS = 1)
2. Authoritative sub-15ms Emergency Kill Switch probing
3. Hard 5.0-second action timeout enforcement
4. Deterministic policy evaluation & HITL verification
5. Adapter execution boundary
6. Tamper-evident audit ledger logging with secret redaction
7. OpenTelemetry distributed tracing
8. Strict lifecycle state machine transitions with replay immunity
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.core.redaction import secret_redactor
from app.core.telemetry import telemetry_manager
from app.services.audit_service import audit_service
from app.services.kill_switch import EmergencyKillSwitchService
from app.services.os_guard.adapters import BaseOSExecutionAdapter, SafeMockOSExecutionAdapter
from app.services.os_guard.policy import OSPolicyEngine, os_policy_engine
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


class OSGuardService:
    """Master Governed OS Execution Coordinator."""

    MAX_ACTION_TIMEOUT_SEC: float = 5.0

    def __init__(
        self,
        policy_engine: Optional[OSPolicyEngine] = None,
        default_adapter: Optional[BaseOSExecutionAdapter] = None,
        kill_switch: Optional[EmergencyKillSwitchService] = None,
    ):
        self._lock = asyncio.Lock()
        self.policy_engine = policy_engine or os_policy_engine
        self.default_adapter = default_adapter or SafeMockOSExecutionAdapter()
        
        # Kill switch integration
        if kill_switch is not None:
            self.kill_switch = kill_switch
        else:
            from app.services.kill_switch import EmergencyKillSwitchService
            # Default instance from app
            self.kill_switch = EmergencyKillSwitchService()

    async def execute_os_action(
        self,
        request: OSActionRequest,
        db: Optional[AsyncSession] = None,
        autonomy_level: int = 3,
        adapter: Optional[BaseOSExecutionAdapter] = None,
    ) -> OSActionResponse:
        """Execute host action strictly through governance, policy, kill switch, and timeout gates."""
        t0 = time.perf_counter()
        target_adapter = adapter or self.default_adapter
        trace_id = telemetry_manager.get_current_trace_id() or request.trace_id

        # 1. Probe Kill Switch (Pre-Lock Check)
        if self.kill_switch.is_active(request.workspace_id):
            return self._build_terminal_response(
                request=request,
                state=OSActionLifecycleState.KILL_SWITCHED,
                decision=PolicyDecisionType.KILL_SWITCHED,
                duration_ms=(time.perf_counter() - t0) * 1000.0,
                error="Emergency kill switch is active. Host OS action permanently blocked.",
                trace_id=trace_id,
            )

        # 2. Concurrency Gate: Single Active Action Lock
        async with self._lock:
            # 3. Probe Kill Switch (Inside Lock Check - Race Prevention)
            if self.kill_switch.is_active(request.workspace_id):
                return self._build_terminal_response(
                    request=request,
                    state=OSActionLifecycleState.KILL_SWITCHED,
                    decision=PolicyDecisionType.KILL_SWITCHED,
                    duration_ms=(time.perf_counter() - t0) * 1000.0,
                    error="Emergency kill switch is active. Host OS action permanently blocked.",
                    trace_id=trace_id,
                )

            # 4. Enforce Hard 5.0-Second Action Timeout Ceiling
            timeout = min(max(0.1, request.timeout_seconds), self.MAX_ACTION_TIMEOUT_SEC)

            # 5. Policy & Governance Evaluation
            policy_res: PolicyDecisionResult = self.policy_engine.evaluate_action(request, autonomy_level)

            if policy_res.decision != PolicyDecisionType.ALLOW:
                state = OSActionLifecycleState.FAILED
                if policy_res.decision == PolicyDecisionType.REQUIRE_HITL:
                    state = OSActionLifecycleState.WAITING_HITL
                elif policy_res.decision == PolicyDecisionType.EXPIRED:
                    state = OSActionLifecycleState.EXPIRED

                resp = self._build_terminal_response(
                    request=request,
                    state=state,
                    decision=policy_res.decision,
                    duration_ms=(time.perf_counter() - t0) * 1000.0,
                    error=policy_res.reason,
                    trace_id=trace_id,
                )
                await self._record_audit_event(db, request, resp)
                return resp

            # 6. Pre-Execution Kill Switch Check
            if self.kill_switch.is_active(request.workspace_id):
                return self._build_terminal_response(
                    request=request,
                    state=OSActionLifecycleState.KILL_SWITCHED,
                    decision=PolicyDecisionType.KILL_SWITCHED,
                    duration_ms=(time.perf_counter() - t0) * 1000.0,
                    error="Emergency kill switch is active. Host OS action permanently blocked.",
                    trace_id=trace_id,
                )

            # 7. Execution Boundary with Enforced Timeout
            try:
                with telemetry_manager.start_span(
                    name=f"os_guard.execute {request.action_type.value}",
                    span_type="os_guard",
                    attributes={
                        "aura.os_action": request.action_type.value,
                        "aura.workspace_id": request.workspace_id,
                        "aura.risk_tier": policy_res.risk_tier.value,
                        "aura.partition": policy_res.partition.value,
                        "aura.timeout_sec": timeout,
                    },
                ):
                    raw_result = await asyncio.wait_for(
                        target_adapter.execute_validated_action(request),
                        timeout=timeout,
                    )

                # Check if kill switch was triggered during execution
                if self.kill_switch.is_active(request.workspace_id):
                    resp = self._build_terminal_response(
                        request=request,
                        state=OSActionLifecycleState.KILL_SWITCHED,
                        decision=PolicyDecisionType.KILL_SWITCHED,
                        duration_ms=(time.perf_counter() - t0) * 1000.0,
                        error="Emergency kill switch was triggered during action execution.",
                        trace_id=trace_id,
                    )
                else:
                    duration_ms = (time.perf_counter() - t0) * 1000.0
                    resp = OSActionResponse(
                        action_id=request.action_id,
                        workspace_id=request.workspace_id,
                        action_type=request.action_type,
                        state=OSActionLifecycleState.COMPLETED,
                        policy_decision=PolicyDecisionType.ALLOW,
                        risk_tier=policy_res.risk_tier,
                        duration_ms=duration_ms,
                        result=raw_result,
                        trace_id=trace_id,
                    )

            except asyncio.TimeoutError:
                duration_ms = (time.perf_counter() - t0) * 1000.0
                resp = self._build_terminal_response(
                    request=request,
                    state=OSActionLifecycleState.TIMED_OUT,
                    decision=PolicyDecisionType.ALLOW,
                    duration_ms=duration_ms,
                    error=f"OS action timed out after {timeout:.2f} seconds.",
                    trace_id=trace_id,
                )
            except Exception as ex:
                duration_ms = (time.perf_counter() - t0) * 1000.0
                resp = self._build_terminal_response(
                    request=request,
                    state=OSActionLifecycleState.FAILED,
                    decision=PolicyDecisionType.ALLOW,
                    duration_ms=duration_ms,
                    error=f"OS action execution failed: {ex}",
                    trace_id=trace_id,
                )

            # 8. Record Audit Ledger Event
            await self._record_audit_event(db, request, resp)
            return resp

    def _build_terminal_response(
        self,
        request: OSActionRequest,
        state: OSActionLifecycleState,
        decision: PolicyDecisionType,
        duration_ms: float,
        error: str,
        trace_id: Optional[str] = None,
    ) -> OSActionResponse:
        """Build deterministic terminal response."""
        return OSActionResponse(
            action_id=request.action_id,
            workspace_id=request.workspace_id,
            action_type=request.action_type,
            state=state,
            policy_decision=decision,
            risk_tier=self.policy_engine.get_risk_tier(request.action_type),
            duration_ms=duration_ms,
            error=error,
            trace_id=trace_id,
        )

    async def _record_audit_event(
        self,
        db: Optional[AsyncSession],
        request: OSActionRequest,
        response: OSActionResponse,
    ) -> None:
        """Record sanitized audit event in database if session available."""
        if not db:
            return

        try:
            ws_id = uuid.UUID(request.workspace_id) if isinstance(request.workspace_id, str) else request.workspace_id
            clean_params = secret_redactor.redact_structure(request.parameters)

            # Explicit privacy protection for typed text content and clipboard payload
            if "text" in clean_params:
                payload_len = len(str(request.parameters.get("text", "")))
                if request.action_type == OSActionType.CLIPBOARD_WRITE:
                    clean_params["text"] = "[REDACTED_CLIPBOARD_CONTENT]"
                    clean_params["character_count"] = payload_len
                else:
                    clean_params["text"] = "[REDACTED_TYPED_CONTENT]"
                    clean_params["typed_character_count"] = payload_len

            details = {
                "action_id": request.action_id,
                "action_type": request.action_type.value,
                "risk_tier": response.risk_tier.value,
                "lifecycle_state": response.state.value,
                "policy_decision": response.policy_decision.value,
                "duration_ms": response.duration_ms,
                "parameters_redacted": clean_params,
                "error": response.error,
                "trace_id": response.trace_id,
            }

            await audit_service.record_event(
                db=db,
                workspace_id=ws_id,
                actor_type=request.actor_type,
                actor_id=request.actor_id,
                action=f"os_action.{request.action_type.value}",
                resource_type="host_os",
                resource_id=request.action_id,
                details=details,
            )
        except Exception as audit_err:
            logger.warning(f"OSGuardService: Failed recording audit event ({audit_err})")


os_guard_service = OSGuardService()
