"""FastAPI dependency injection utilities for Auth, Workspace, and DB."""

import uuid
from typing import AsyncGenerator, Callable, List, Optional
from fastapi import Depends, Header, HTTPException, Path, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.errors import AuthenticationError, AuthorizationError, EntityNotFoundError
from app.core.security import decode_token
from app.db.models.user import User
from app.db.models.workspace import Workspace, WorkspaceMember
from app.db.session import get_db_session

get_db = get_db_session
security_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    auth: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
    db: AsyncSession = Depends(get_db_session),
) -> User:
    """Extract and validate JWT token from Bearer header."""
    if not auth or not auth.credentials:
        raise AuthenticationError("Authorization header with Bearer token is required")

    try:
        payload = decode_token(auth.credentials)
    except Exception as e:
        raise AuthenticationError(f"Invalid or expired authentication token: {str(e)}")

    user_id_str = payload.get("sub")
    if not user_id_str:
        raise AuthenticationError("Invalid token payload: missing subject")

    try:
        user_id = uuid.UUID(user_id_str)
    except ValueError:
        raise AuthenticationError("Invalid user ID format in token")

    res = await db.execute(select(User).where(User.id == user_id, User.deleted_at.is_(None)))
    user = res.scalar_one_or_none()
    if not user:
        raise AuthenticationError("User account not found")

    if not user.is_active:
        raise AuthenticationError("User account is inactive or disabled")

    return user


async def get_workspace_membership(
    workspace_id: uuid.UUID,
    user: Optional[User] = None,
    db: Optional[AsyncSession] = None,
    user_id: Optional[uuid.UUID] = None,
) -> WorkspaceMember:
    """Verify that user is a member of the target workspace."""
    if db is None:
        raise ValueError("Database session required")

    target_user_id = user.id if user else user_id
    if not target_user_id:
        raise AuthenticationError("User identification required")

    # Check workspace exists
    ws_res = await db.execute(select(Workspace).where(Workspace.id == workspace_id, Workspace.deleted_at.is_(None)))
    ws = ws_res.scalar_one_or_none()
    if not ws:
        raise EntityNotFoundError("Workspace", str(workspace_id))

    # Check user membership
    member_res = await db.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == target_user_id,
        )
    )
    member = member_res.scalar_one_or_none()
    if not member:
        raise AuthorizationError(f"Access denied: You are not a member of workspace {workspace_id}")

    return member


def require_workspace_roles(allowed_roles: List[str]) -> Callable:
    """Factory dependency for role-based access control inside a workspace."""
    async def _role_checker(
        workspace_id: uuid.UUID = Header(..., alias="X-Workspace-ID"),
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db_session),
    ) -> WorkspaceMember:
        member = await get_workspace_membership(workspace_id, user, db)
        if member.role not in allowed_roles:
            raise AuthorizationError(
                f"Insufficient permissions: required one of {allowed_roles}, but your role is '{member.role}'"
            )
        return member

    return _role_checker
