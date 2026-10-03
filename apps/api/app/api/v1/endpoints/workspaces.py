"""Workspaces and multi-tenancy management endpoints."""

import uuid
from typing import List
from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.api.deps import get_current_user, get_workspace_membership
from app.core.errors import AuthorizationError, ConflictError, EntityNotFoundError
from app.db.models.user import User
from app.db.models.workspace import Workspace, WorkspaceMember
from app.db.session import get_db_session
from app.schemas.workspace import (
    AddMemberRequest,
    MemberResponse,
    WorkspaceCreateRequest,
    WorkspaceResponse,
)

router = APIRouter()


@router.get("", response_model=List[WorkspaceResponse])
async def list_workspaces(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db_session)
) -> List[WorkspaceResponse]:
    """List all workspaces the authenticated user is a member of."""
    res = await db.execute(
        select(WorkspaceMember)
        .options(selectinload(WorkspaceMember.workspace))
        .where(WorkspaceMember.user_id == current_user.id)
    )
    memberships = res.scalars().all()

    return [
        WorkspaceResponse(
            id=m.workspace.id,
            name=m.workspace.name,
            slug=m.workspace.slug,
            description=m.workspace.description,
            settings=m.workspace.settings,
            role=m.role,
            created_at=m.workspace.created_at,
        )
        for m in memberships
        if m.workspace and not m.workspace.deleted_at
    ]


@router.post("", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    payload: WorkspaceCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> WorkspaceResponse:
    """Create a new workspace and assign the creator as the Owner."""
    slug = payload.slug or f"{payload.name.lower().replace(' ', '-')}-{uuid.uuid4().hex[:6]}"

    # Verify unique slug
    res = await db.execute(select(Workspace).where(Workspace.slug == slug))
    if res.scalar_one_or_none():
        raise ConflictError(f"Workspace with slug '{slug}' already exists")

    workspace = Workspace(
        name=payload.name,
        slug=slug,
        description=payload.description,
        settings=payload.settings,
    )
    db.add(workspace)
    await db.flush()

    member = WorkspaceMember(
        workspace_id=workspace.id,
        user_id=current_user.id,
        role="owner",
        permissions=["*"],
    )
    db.add(member)
    await db.commit()

    return WorkspaceResponse(
        id=workspace.id,
        name=workspace.name,
        slug=workspace.slug,
        description=workspace.description,
        settings=workspace.settings,
        role="owner",
        created_at=workspace.created_at,
    )


@router.get("/{id}", response_model=WorkspaceResponse)
async def get_workspace(
    id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> WorkspaceResponse:
    """Get single workspace details after verifying user membership."""
    member = await get_workspace_membership(id, current_user, db)
    res = await db.execute(select(Workspace).where(Workspace.id == id, Workspace.deleted_at.is_(None)))
    ws = res.scalar_one()

    return WorkspaceResponse(
        id=ws.id,
        name=ws.name,
        slug=ws.slug,
        description=ws.description,
        settings=ws.settings,
        role=member.role,
        created_at=ws.created_at,
    )


@router.get("/{id}/members", response_model=List[MemberResponse])
async def list_workspace_members(
    id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[MemberResponse]:
    """List all members of a workspace."""
    await get_workspace_membership(id, current_user, db)

    res = await db.execute(
        select(WorkspaceMember).options(selectinload(WorkspaceMember.user)).where(WorkspaceMember.workspace_id == id)
    )
    members = res.scalars().all()

    return [
        MemberResponse(
            id=m.id,
            workspace_id=m.workspace_id,
            user_id=m.user_id,
            role=m.role,
            permissions=m.permissions,
            email=m.user.email if m.user else None,
            full_name=m.user.full_name if m.user else None,
            created_at=m.created_at,
        )
        for m in members
    ]


@router.post("/{id}/members", response_model=MemberResponse, status_code=status.HTTP_201_CREATED)
async def add_workspace_member(
    id: uuid.UUID,
    payload: AddMemberRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> MemberResponse:
    """Add a member to a workspace (Requires Owner or Admin role)."""
    current_member = await get_workspace_membership(id, current_user, db)
    if current_member.role not in ["owner", "admin"]:
        raise AuthorizationError("Only workspace Owners and Admins can invite new members")

    # Check target user exists
    user_res = await db.execute(select(User).where(User.id == payload.user_id, User.deleted_at.is_(None)))
    target_user = user_res.scalar_one_or_none()
    if not target_user:
        raise EntityNotFoundError("User", str(payload.user_id))

    # Check if already a member
    exist_res = await db.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == id,
            WorkspaceMember.user_id == payload.user_id,
        )
    )
    if exist_res.scalar_one_or_none():
        raise ConflictError(f"User is already a member of workspace {id}")

    new_member = WorkspaceMember(
        workspace_id=id,
        user_id=payload.user_id,
        role=payload.role,
        permissions=payload.permissions,
    )
    db.add(new_member)
    await db.commit()

    return MemberResponse(
        id=new_member.id,
        workspace_id=new_member.workspace_id,
        user_id=new_member.user_id,
        role=new_member.role,
        permissions=new_member.permissions,
        email=target_user.email,
        full_name=target_user.full_name,
        created_at=new_member.created_at,
    )
