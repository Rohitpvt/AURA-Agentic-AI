"""Automation and Scheduled Run API Endpoints."""

import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_workspace_membership
from app.db.models.user import User
from app.db.session import get_db_session
from app.schemas.automation import (
    AutomationCreateRequest,
    AutomationResponse,
    AutomationRunResponse,
    AutomationUpdateRequest,
)
from app.services.automations.scheduler_service import scheduler_service

router = APIRouter()


class ToggleAutomationPayload(BaseModel):
    """Payload for toggling automation active state."""
    is_active: bool = Field(..., description="Target active state")


@router.post("", response_model=AutomationResponse, status_code=status.HTTP_201_CREATED)
async def create_automation(
    payload: AutomationCreateRequest,
    workspace_id: uuid.UUID = Query(..., description="Target workspace ID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> AutomationResponse:
    """Create a new scheduled automation in the specified workspace."""
    await get_workspace_membership(workspace_id=workspace_id, user_id=current_user.id, db=db)
    return await scheduler_service.create_automation(
        db=db, payload=payload, workspace_id=workspace_id, user_id=current_user.id
    )


@router.get("", response_model=List[AutomationResponse])
async def list_automations(
    workspace_id: uuid.UUID = Query(..., description="Target workspace ID"),
    is_active: Optional[bool] = Query(None, description="Filter by active state"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[AutomationResponse]:
    """List all automations within a workspace."""
    await get_workspace_membership(workspace_id=workspace_id, user_id=current_user.id, db=db)
    return await scheduler_service.list_automations(
        db=db, workspace_id=workspace_id, is_active=is_active
    )


@router.get("/{automation_id}", response_model=AutomationResponse)
async def get_automation(
    automation_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(..., description="Target workspace ID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> AutomationResponse:
    """Retrieve details of an individual automation."""
    await get_workspace_membership(workspace_id=workspace_id, user_id=current_user.id, db=db)
    return await scheduler_service.get_automation(
        db=db, automation_id=automation_id, workspace_id=workspace_id
    )


@router.patch("/{automation_id}", response_model=AutomationResponse)
async def update_automation(
    automation_id: uuid.UUID,
    payload: AutomationUpdateRequest,
    workspace_id: uuid.UUID = Query(..., description="Target workspace ID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> AutomationResponse:
    """Update automation settings, cron schedule, or prompt template."""
    await get_workspace_membership(workspace_id=workspace_id, user_id=current_user.id, db=db)
    return await scheduler_service.update_automation(
        db=db,
        automation_id=automation_id,
        payload=payload,
        workspace_id=workspace_id,
        user_id=current_user.id,
    )


@router.delete("/{automation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_automation(
    automation_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(..., description="Target workspace ID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """Soft-delete an automation."""
    await get_workspace_membership(workspace_id=workspace_id, user_id=current_user.id, db=db)
    await scheduler_service.delete_automation(
        db=db, automation_id=automation_id, workspace_id=workspace_id, user_id=current_user.id
    )


@router.post("/{automation_id}/toggle", response_model=AutomationResponse)
async def toggle_automation(
    automation_id: uuid.UUID,
    payload: ToggleAutomationPayload,
    workspace_id: uuid.UUID = Query(..., description="Target workspace ID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> AutomationResponse:
    """Enable or disable an automation schedule."""
    await get_workspace_membership(workspace_id=workspace_id, user_id=current_user.id, db=db)
    return await scheduler_service.toggle_automation(
        db=db,
        automation_id=automation_id,
        workspace_id=workspace_id,
        is_active=payload.is_active,
        user_id=current_user.id,
    )


@router.post("/{automation_id}/reset-circuit", response_model=AutomationResponse)
async def reset_circuit_breaker(
    automation_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(..., description="Target workspace ID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> AutomationResponse:
    """Reset an OPEN circuit breaker to CLOSED state."""
    await get_workspace_membership(workspace_id=workspace_id, user_id=current_user.id, db=db)
    return await scheduler_service.reset_circuit_breaker(
        db=db, automation_id=automation_id, workspace_id=workspace_id, user_id=current_user.id
    )


@router.post("/{automation_id}/run", response_model=AutomationRunResponse)
async def trigger_manual_run(
    automation_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(..., description="Target workspace ID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> AutomationRunResponse:
    """Trigger an authorized immediate manual run of an automation."""
    await get_workspace_membership(workspace_id=workspace_id, user_id=current_user.id, db=db)
    return await scheduler_service.trigger_manual_run(
        db=db, automation_id=automation_id, workspace_id=workspace_id, user_id=current_user.id
    )


@router.get("/{automation_id}/runs", response_model=List[AutomationRunResponse])
async def list_automation_runs(
    automation_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(..., description="Target workspace ID"),
    status: Optional[str] = Query(None, description="Filter by run status"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[AutomationRunResponse]:
    """List execution runs for a specific automation."""
    await get_workspace_membership(workspace_id=workspace_id, user_id=current_user.id, db=db)
    return await scheduler_service.list_runs(
        db=db,
        workspace_id=workspace_id,
        automation_id=automation_id,
        status=status,
        limit=limit,
        offset=offset,
    )


@router.get("/runs/{run_id}", response_model=AutomationRunResponse)
async def get_automation_run(
    run_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(..., description="Target workspace ID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> AutomationRunResponse:
    """Retrieve details of an individual automation run."""
    await get_workspace_membership(workspace_id=workspace_id, user_id=current_user.id, db=db)
    return await scheduler_service.get_run(db=db, run_id=run_id, workspace_id=workspace_id)
