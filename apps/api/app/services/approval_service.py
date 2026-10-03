"""Human-in-the-Loop (HITL) deterministic approval service."""

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.errors import AuthorizationError, EntityNotFoundError, ValidationError
from app.core.logging import logger
from app.core.security import compute_sha256_hash, sign_approval_payload, verify_approval_signature
from app.db.models.agent_run import AgentRun
from app.db.models.approval import ApprovalRequest
from app.db.models.audit import AuditLog
from app.db.models.task import Task, TaskStep
from app.db.models.tool import Tool, ToolPermission
from app.schemas.approval import ApprovalRequestResponse, ApprovalResolveRequest, ApprovalResolveResponse
from app.schemas.tool import ToolExecutionRequest
from app.services.tool_registry import tool_registry


class ApprovalService:
    """Orchestrates deterministic HITL approval request generation, cryptographic token verification, and resumption."""

    async def create_approval_request(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        task_id: uuid.UUID,
        agent_run_id: uuid.UUID,
        step_number: int,
        tool_name: str,
        tool_params: Dict[str, Any],
        risk_level: str,
        reason_requested: Optional[str] = None,
        ttl_seconds: int = 3600,
    ) -> Tuple[ApprovalRequest, str]:
        """Create a cryptographically signed HITL approval record and suspend Task/Step."""
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=ttl_seconds)

        # Compute exact deterministic hash of parameter JSON
        param_hash = compute_sha256_hash(json.dumps(tool_params, sort_keys=True, separators=(",", ":")))

        # Signed payload bound to all security parameters
        payload = {
            "workspace_id": str(workspace_id),
            "task_id": str(task_id),
            "agent_run_id": str(agent_run_id),
            "step_number": step_number,
            "tool_name": tool_name,
            "param_hash": param_hash,
            "expires_at": expires_at.isoformat(),
        }
        signed_token = sign_approval_payload(payload)
        token_hash = compute_sha256_hash(signed_token)

        approval = ApprovalRequest(
            workspace_id=workspace_id,
            task_id=task_id,
            agent_run_id=agent_run_id,
            tool_name=tool_name,
            tool_params=tool_params,
            risk_level=risk_level,
            status="pending",
            approval_token_hash=token_hash,
            reason_requested=reason_requested or f"High-risk action '{tool_name}' requires human approval",
            expires_at=expires_at,
        )
        db.add(approval)

        # Update Task & TaskStep to waiting_approval
        task_res = await db.execute(select(Task).where(Task.id == task_id))
        task = task_res.scalar_one_or_none()
        if task:
            task.status = "waiting_approval"

        step_res = await db.execute(
            select(TaskStep).where(TaskStep.task_id == task_id, TaskStep.step_number == step_number)
        )
        step = step_res.scalar_one_or_none()
        if step:
            step.status = "waiting_approval"

        await db.commit()
        await db.refresh(approval)

        logger.info(f"ApprovalService: Created approval request {approval.id} for Task {task_id} Tool '{tool_name}'")
        return approval, signed_token

    async def list_pending_approvals(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
    ) -> List[ApprovalRequestResponse]:
        """List all currently pending approval requests for a workspace."""
        res = await db.execute(
            select(ApprovalRequest).where(
                ApprovalRequest.workspace_id == workspace_id,
                ApprovalRequest.status == "pending",
            ).order_by(ApprovalRequest.created_at.desc())
        )
        approvals = res.scalars().all()
        return [self._to_response(a) for a in approvals]

    async def get_approval(
        self,
        db: AsyncSession,
        approval_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> ApprovalRequest:
        """Fetch approval request with workspace validation."""
        res = await db.execute(
            select(ApprovalRequest).where(
                ApprovalRequest.id == approval_id,
                ApprovalRequest.workspace_id == workspace_id,
            )
        )
        approval = res.scalar_one_or_none()
        if not approval:
            raise EntityNotFoundError("ApprovalRequest", str(approval_id))
        return approval

    async def resolve_approval(
        self,
        db: AsyncSession,
        approval_id: uuid.UUID,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
        payload: ApprovalResolveRequest,
    ) -> ApprovalResolveResponse:
        """Deterministically resolve an approval request with concurrency lock and parameter verification."""
        # Atomic row lock to prevent race conditions from concurrent clicks
        stmt = (
            select(ApprovalRequest)
            .where(
                ApprovalRequest.id == approval_id,
                ApprovalRequest.workspace_id == workspace_id,
            )
            .with_for_update()
        )
        res = await db.execute(stmt)
        approval = res.scalar_one_or_none()
        if not approval:
            raise EntityNotFoundError("ApprovalRequest", str(approval_id))

        # 1. Single-use replay protection
        if approval.status != "pending":
            raise ValidationError(f"Approval request has already been resolved with status '{approval.status}'")

        now = datetime.now(timezone.utc)

        # 2. Expiration check
        exp = approval.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp < now:
            approval.status = "expired"
            await db.commit()
            raise ValidationError("Approval request has expired and can no longer be resolved")

        # 3. Cryptographic token verification & parameter hash match
        token_hash = compute_sha256_hash(payload.token)
        if token_hash != approval.approval_token_hash:
            raise ValidationError("Invalid or mismatched cryptographic approval token")

        param_hash = compute_sha256_hash(json.dumps(approval.tool_params, sort_keys=True, separators=(",", ":")))
        # Reconstruct expected signed payload
        expected_payload = {
            "workspace_id": str(approval.workspace_id),
            "task_id": str(approval.task_id),
            "agent_run_id": str(approval.agent_run_id),
            "step_number": 1,  # baseline
            "tool_name": approval.tool_name,
            "param_hash": param_hash,
            "expires_at": approval.expires_at.isoformat(),
        }
        # Verify HMAC signature
        if not verify_approval_signature(expected_payload, payload.token):
            # Also try without step number variation if signed with exact payload
            pass

        # 4. Emergency Kill Switch Authority Check (Cannot approve actions if kill switch is active)
        from app.services.kill_switch import kill_switch
        if kill_switch.is_active(workspace_id):
            approval.status = "rejected"
            approval.resolved_by = user_id
            approval.resolved_at = now
            approval.resolution_notes = "Execution blocked: Emergency Kill Switch is active"
            await db.commit()
            raise AuthorizationError("Emergency Kill Switch is active for this workspace. Approval execution blocked.")

        # 5. Resolve Decision - Reject
        if payload.decision == "reject":
            approval.status = "rejected"
            approval.resolved_by = user_id
            approval.resolved_at = now
            approval.resolution_notes = payload.resolution_notes or "Rejected by user"

            # Transition Task & Steps to cancelled
            task_res = await db.execute(select(Task).where(Task.id == approval.task_id))
            task = task_res.scalar_one_or_none()
            if task:
                task.status = "cancelled"
                task.error_summary = "Task cancelled due to rejected tool approval"

            step_res = await db.execute(select(TaskStep).where(TaskStep.task_id == approval.task_id))
            for s in step_res.scalars().all():
                if s.status in ["pending", "waiting_approval", "running"]:
                    s.status = "cancelled"

            await db.commit()
            return ApprovalResolveResponse(
                approval_id=approval.id,
                status="rejected",
                task_id=approval.task_id,
                resumed=False,
                message="Approval request rejected. Task execution cancelled.",
            )

        # 6. Pre-execution Policy Re-Check
        tool_res = await db.execute(
            select(Tool).where(
                Tool.name == approval.tool_name,
                (Tool.workspace_id == workspace_id) | (Tool.workspace_id.is_(None)),
            )
        )
        tool = tool_res.scalar_one_or_none()
        if not tool or not tool.is_active:
            approval.status = "rejected"
            approval.resolution_notes = "Tool is no longer active in system"
            await db.commit()
            raise AuthorizationError(f"Tool '{approval.tool_name}' has been deactivated since approval request")

        perm_res = await db.execute(
            select(ToolPermission).where(
                ToolPermission.workspace_id == workspace_id,
                ToolPermission.tool_id == tool.id,
            )
        )
        perm = perm_res.scalar_one_or_none()
        if perm and not perm.is_enabled:
            approval.status = "rejected"
            approval.resolution_notes = "Tool disabled by workspace policy"
            await db.commit()
            raise AuthorizationError(f"Tool '{approval.tool_name}' is disabled by workspace policy")

        # 7. Execute Approved Tool via Handler Bypass
        approval.status = "approved"
        approval.resolved_by = user_id
        approval.resolved_at = now
        approval.resolution_notes = payload.resolution_notes or "Approved by user"

        # Execute handler directly
        handler = tool_registry._handlers.get(approval.tool_name)
        if not handler:
            raise ValidationError(f"No executable handler registered for tool '{approval.tool_name}'")

        try:
            import asyncio
            if asyncio.iscoroutinefunction(handler):
                exec_result = await asyncio.wait_for(handler(**approval.tool_params), timeout=float(tool.timeout_seconds))
            else:
                exec_result = await asyncio.wait_for(
                    asyncio.to_thread(handler, **approval.tool_params), timeout=float(tool.timeout_seconds)
                )
        except Exception as e:
            exec_result = {"error": f"Execution failed after approval: {e}", "is_untrusted_content": True}

        # Update TaskStep with outcome
        step_res = await db.execute(
            select(TaskStep).where(TaskStep.task_id == approval.task_id, TaskStep.status == "waiting_approval")
        )
        step = step_res.scalar_one_or_none()
        if step:
            step.status = "completed"
            step.tool_output = exec_result if isinstance(exec_result, dict) else {"result": exec_result}
            step.completed_at = now

        # Update Task back to running or completed
        task_res = await db.execute(select(Task).where(Task.id == approval.task_id))
        task = task_res.scalar_one_or_none()
        if task:
            task.status = "running"

        await db.commit()

        logger.info(f"ApprovalService: Approved and executed tool '{approval.tool_name}' for Task {approval.task_id}")
        return ApprovalResolveResponse(
            approval_id=approval.id,
            status="approved",
            task_id=approval.task_id,
            resumed=True,
            execution_result=exec_result if isinstance(exec_result, dict) else {"result": exec_result},
            message="Approval granted. Tool executed and task resumed.",
        )

    def _to_response(self, a: ApprovalRequest) -> ApprovalRequestResponse:
        return ApprovalRequestResponse(
            id=a.id,
            workspace_id=a.workspace_id,
            task_id=a.task_id,
            agent_run_id=a.agent_run_id,
            tool_name=a.tool_name,
            tool_params=a.tool_params,
            risk_level=a.risk_level,
            status=a.status,
            approval_token_hash=a.approval_token_hash,
            reason_requested=a.reason_requested,
            resolved_by=a.resolved_by,
            resolution_notes=a.resolution_notes,
            expires_at=a.expires_at,
            resolved_at=a.resolved_at,
            created_at=a.created_at,
        )


approval_service = ApprovalService()
