"""Task and Task Step DAG control-plane API endpoints."""

import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_current_user, get_workspace_membership
from app.db.models.user import User
from app.db.session import get_db_session
from app.schemas.task import (
    TaskCreateRequest,
    TaskResponse,
    TaskStepCreate,
    TaskStepResponse,
    TaskStepUpdate,
    TaskUpdateRequest,
)
from app.services.task_recovery_service import task_recovery_service
from app.services.task_service import task_service

router = APIRouter()


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(
    payload: TaskCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> TaskResponse:
    """Create a new autonomous task goal with optional initial DAG steps."""
    await get_workspace_membership(workspace_id=payload.workspace_id, user_id=current_user.id, db=db)
    return await task_service.create_task(db=db, payload=payload, user_id=current_user.id)


@router.get("", response_model=List[TaskResponse])
async def list_tasks(
    workspace_id: uuid.UUID = Query(..., description="Target workspace ID"),
    status: Optional[str] = Query(None, description="Optional status filter"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[TaskResponse]:
    """List tasks for a workspace."""
    await get_workspace_membership(workspace_id=workspace_id, user_id=current_user.id, db=db)
    return await task_service.list_tasks(
        db=db, workspace_id=workspace_id, status=status, limit=limit, offset=offset
    )


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> TaskResponse:
    """Retrieve task details and complete DAG step list."""
    await get_workspace_membership(workspace_id=workspace_id, user_id=current_user.id, db=db)
    return await task_service.get_task(db=db, task_id=task_id, workspace_id=workspace_id)


@router.patch("/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: uuid.UUID,
    payload: TaskUpdateRequest,
    workspace_id: uuid.UUID = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> TaskResponse:
    """Transition high-level task state."""
    await get_workspace_membership(workspace_id=workspace_id, user_id=current_user.id, db=db)
    return await task_service.update_task_status(
        db=db,
        task_id=task_id,
        workspace_id=workspace_id,
        payload=payload,
        actor_id=str(current_user.id),
    )


@router.post("/{task_id}/steps", response_model=List[TaskStepResponse], status_code=status.HTTP_201_CREATED)
async def add_task_steps(
    task_id: uuid.UUID,
    steps: List[TaskStepCreate],
    workspace_id: uuid.UUID = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[TaskStepResponse]:
    """Append DAG steps to an active task."""
    await get_workspace_membership(workspace_id=workspace_id, user_id=current_user.id, db=db)
    return await task_service.add_task_steps(
        db=db, task_id=task_id, workspace_id=workspace_id, new_steps=steps
    )


@router.patch("/{task_id}/steps/{step_number}", response_model=TaskStepResponse)
async def checkpoint_step(
    task_id: uuid.UUID,
    step_number: int,
    payload: TaskStepUpdate,
    workspace_id: uuid.UUID = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> TaskStepResponse:
    """Update execution checkpoint for a specific step."""
    await get_workspace_membership(workspace_id=workspace_id, user_id=current_user.id, db=db)
    return await task_service.checkpoint_step(
        db=db,
        task_id=task_id,
        step_number=step_number,
        workspace_id=workspace_id,
        update_data=payload,
        actor_id=str(current_user.id),
    )


@router.post("/{task_id}/cancel", response_model=TaskResponse)
async def cancel_task(
    task_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> TaskResponse:
    """Cancel a task and propagate cancellation to pending/running steps."""
    await get_workspace_membership(workspace_id=workspace_id, user_id=current_user.id, db=db)
    return await task_service.cancel_task(
        db=db, task_id=task_id, workspace_id=workspace_id, actor_id=str(current_user.id)
    )


@router.post("/{task_id}/resume", response_model=TaskResponse)
async def resume_task(
    task_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> TaskResponse:
    """Deterministically resume a suspended, orphaned, or HITL-resolved task."""
    await get_workspace_membership(workspace_id=workspace_id, user_id=current_user.id, db=db)
    return await task_recovery_service.resume_task(
        db=db,
        task_id=task_id,
        workspace_id=workspace_id,
        actor_id=str(current_user.id),
    )

