"""System-level security controls, kill-switch, and sandbox status endpoints."""

from typing import Any, Dict, Optional
import uuid
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_current_user, get_db, get_workspace_membership
from app.core.errors import AuthorizationError
from app.db.models.user import User
from app.runtime.sandbox.manager import sandbox_manager
from app.services.kill_switch import kill_switch

router = APIRouter(prefix="/system", tags=["System Controls & Security"])


class KillSwitchRequest(BaseModel):
    """Payload for emergency kill-switch activation."""
    workspace_id: uuid.UUID = Field(..., description="Target workspace ID")
    target_task_id: Optional[uuid.UUID] = Field(default=None, description="Optional specific task ID to abort")
    reason: str = Field(default="Emergency kill-switch invoked by operator", description="Reason for abort")


class KillSwitchResetRequest(BaseModel):
    """Payload for resetting emergency kill-switch state (recovery)."""
    workspace_id: Optional[uuid.UUID] = Field(default=None, description="Optional workspace ID (omit for global reset)")
    reason: str = Field(default="Operator reset emergency kill state", description="Reason for recovery reset")


@router.post("/kill-switch", summary="Trigger emergency execution kill-switch")
async def trigger_kill_switch(
    payload: KillSwitchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Immediately abort active execution loops, sub-agent workers, sandboxes, and MCP subprocesses."""
    # Verify user is a member of the target workspace
    await get_workspace_membership(payload.workspace_id, user=current_user, db=db)
    
    return await kill_switch.trigger_emergency_kill(
        db=db,
        workspace_id=payload.workspace_id,
        actor_id=str(current_user.id),
        reason=payload.reason,
        target_task_id=payload.target_task_id,
    )


@router.post("/kill-switch/reset", summary="Reset emergency kill-switch state (Recovery)")
async def reset_kill_switch(
    payload: KillSwitchResetRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Explicit recovery transition restoring normal execution state."""
    # Strict RBAC authorization check for recovery
    if payload.workspace_id:
        member = await get_workspace_membership(payload.workspace_id, user=current_user, db=db)
        if member.role not in ["owner", "admin"] and getattr(current_user, "role", "member") not in ["admin", "owner", "superuser"]:
            raise AuthorizationError(
                f"Insufficient permissions: Only workspace owners and admins can reset emergency kill state (your role is '{member.role}')"
            )
    else:
        if getattr(current_user, "role", "member") not in ["admin", "owner", "superuser"]:
            raise AuthorizationError(
                "Insufficient permissions: Global emergency kill-switch reset requires administrative privileges"
            )

    return await kill_switch.reset_emergency_state(
        db=db,
        workspace_id=payload.workspace_id,
        actor_id=str(current_user.id),
        reason=payload.reason,
    )


@router.get("/kill-switch/status", summary="Get emergency kill-switch state")
async def get_kill_switch_status(
    workspace_id: Optional[uuid.UUID] = Query(default=None, description="Optional workspace ID"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Query current global and tenant-specific kill-switch status."""
    if workspace_id:
        await get_workspace_membership(workspace_id, user=current_user, db=db)
    return kill_switch.get_status(workspace_id=workspace_id)


@router.get("/sandbox/status", summary="Get container execution sandbox status")
async def get_sandbox_status(
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Inspect the status and availability of the local Docker container sandbox."""
    return await sandbox_manager.check_sandbox_health()
