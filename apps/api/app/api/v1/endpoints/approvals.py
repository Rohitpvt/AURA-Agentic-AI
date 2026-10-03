"""Human-In-The-Loop Approval Endpoints."""

import uuid
from typing import List
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_current_user
from app.db.models.user import User
from app.db.session import get_db_session
from app.schemas.approval import ApprovalRequestResponse, ApprovalResolveRequest, ApprovalResolveResponse
from app.services.approval_service import approval_service

router = APIRouter()


@router.get("", response_model=List[ApprovalRequestResponse])
async def list_pending_approvals(
    workspace_id: uuid.UUID = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """List all pending approval requests in the workspace."""
    return await approval_service.list_pending_approvals(db=db, workspace_id=workspace_id)


@router.get("/{approval_id}", response_model=ApprovalRequestResponse)
async def get_approval(
    approval_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Retrieve details of a specific approval request."""
    approval = await approval_service.get_approval(db=db, approval_id=approval_id, workspace_id=workspace_id)
    return approval_service._to_response(approval)


@router.post("/{approval_id}/resolve", response_model=ApprovalResolveResponse)
async def resolve_approval(
    approval_id: uuid.UUID,
    payload: ApprovalResolveRequest,
    workspace_id: uuid.UUID = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Resolve a pending approval request with cryptographic token verification."""
    return await approval_service.resolve_approval(
        db=db,
        approval_id=approval_id,
        workspace_id=workspace_id,
        user_id=current_user.id,
        payload=payload,
    )
