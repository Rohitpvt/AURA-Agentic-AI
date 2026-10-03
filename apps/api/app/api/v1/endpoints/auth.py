"""Authentication API endpoints (Registration, Login, Refresh, Logout, Profile)."""

import uuid
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.api.deps import get_current_user
from app.core.config import settings
from app.core.errors import AuthenticationError, ConflictError
from app.core.security import (
    compute_token_hash,
    create_access_token,
    create_refresh_token,
    decode_token,
    get_password_hash,
    revoke_token,
    verify_password,
)
from app.db.models.token import RevokedToken
from app.db.models.user import User
from app.db.models.workspace import Workspace, WorkspaceMember
from app.db.session import get_db_session
from app.schemas.auth import (
    TokenRefreshRequest,
    TokenResponse,
    UserLoginRequest,
    UserProfileResponse,
    UserRegisterRequest,
)

router = APIRouter()


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: UserRegisterRequest, db: AsyncSession = Depends(get_db_session)) -> TokenResponse:
    """Register a new user and create an initial default personal workspace."""
    # Check duplicate email
    res = await db.execute(select(User).where(User.email == payload.email))
    if res.scalar_one_or_none():
        raise ConflictError(f"User with email '{payload.email}' already exists")

    # Create User
    user = User(
        email=payload.email,
        password_hash=get_password_hash(payload.password),
        full_name=payload.full_name,
        is_active=True,
    )
    db.add(user)
    await db.flush()

    # Create Personal Default Workspace
    safe_name = payload.full_name.split()[0].lower() if payload.full_name else "personal"
    ws_name = payload.workspace_name or f"{payload.full_name}'s Workspace"
    ws_slug = f"{safe_name}-personal-{uuid.uuid4().hex[:6]}"
    workspace = Workspace(
        name=ws_name,
        slug=ws_slug,
        description="Default personal workspace",
    )
    db.add(workspace)
    await db.flush()

    # Add user as Workspace Owner
    member = WorkspaceMember(
        workspace_id=workspace.id,
        user_id=user.id,
        role="owner",
        permissions=["*"],
    )
    db.add(member)
    await db.commit()

    token_data = {"sub": str(user.id), "email": user.email, "full_name": user.full_name}
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/login", response_model=TokenResponse)
async def login(payload: UserLoginRequest, db: AsyncSession = Depends(get_db_session)) -> TokenResponse:
    """Authenticate user credentials and issue JWT tokens."""
    res = await db.execute(select(User).where(User.email == payload.email, User.deleted_at.is_(None)))
    user = res.scalar_one_or_none()
    if not user or not verify_password(payload.password, user.password_hash):
        raise AuthenticationError("Invalid email or password")

    if not user.is_active:
        raise AuthenticationError("Account is inactive or disabled")

    token_data = {"sub": str(user.id), "email": user.email, "full_name": user.full_name}
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(payload: TokenRefreshRequest, db: AsyncSession = Depends(get_db_session)) -> TokenResponse:
    """Rotate refresh token and issue new access token with crash-resilient DB persistence."""
    try:
        decoded = decode_token(payload.refresh_token)
    except Exception as e:
        raise AuthenticationError(f"Invalid refresh token: {str(e)}")

    if decoded.get("type") != "refresh":
        raise AuthenticationError("Provided token is not a refresh token")

    token_hash = compute_token_hash(payload.refresh_token)

    # Check database for persistent revocation across crashes/restarts
    rev_check = await db.execute(select(RevokedToken).where(RevokedToken.token_hash == token_hash))
    if rev_check.scalar_one_or_none():
        revoke_token(payload.refresh_token)
        raise AuthenticationError("Refresh token has been revoked or already rotated")

    user_id_str = decoded.get("sub")
    res = await db.execute(select(User).where(User.id == uuid.UUID(user_id_str), User.deleted_at.is_(None)))
    user = res.scalar_one_or_none()
    if not user or not user.is_active:
        raise AuthenticationError("User account no longer active")

    exp_ts = decoded.get("exp")
    expires_at = (
        datetime.fromtimestamp(exp_ts, tz=timezone.utc)
        if exp_ts
        else datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    )

    # Persist revocation in DB atomically to prevent race condition
    try:
        rev_entry = RevokedToken(
            token_hash=token_hash,
            jti=decoded.get("jti"),
            user_id=user.id,
            reason="rotation",
            expires_at=expires_at,
        )
        db.add(rev_entry)
        await db.flush()
    except IntegrityError:
        await db.rollback()
        revoke_token(payload.refresh_token)
        raise AuthenticationError("Refresh token has already been rotated (concurrent race detected)")

    revoke_token(payload.refresh_token)

    token_data = {"sub": str(user.id), "email": user.email, "full_name": user.full_name}
    access_token = create_access_token(token_data)
    new_refresh = create_refresh_token(token_data)

    await db.commit()

    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/logout", status_code=status.HTTP_200_OK)
async def logout(
    payload: TokenRefreshRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """Revoke refresh token on logout with DB persistence."""
    token_hash = compute_token_hash(payload.refresh_token)
    try:
        decoded = decode_token(payload.refresh_token)
        exp_ts = decoded.get("exp")
        expires_at = (
            datetime.fromtimestamp(exp_ts, tz=timezone.utc)
            if exp_ts
            else datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
        )
        jti = decoded.get("jti")
    except Exception:
        expires_at = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
        jti = None

    try:
        rev_entry = RevokedToken(
            token_hash=token_hash,
            jti=jti,
            user_id=current_user.id,
            reason="logout",
            expires_at=expires_at,
        )
        db.add(rev_entry)
        await db.commit()
    except Exception:
        await db.rollback()

    revoke_token(payload.refresh_token)
    return {"success": True, "message": "Logged out successfully"}


@router.get("/me", response_model=UserProfileResponse)
async def get_my_profile(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db_session)
) -> UserProfileResponse:
    """Retrieve profile and workspace memberships for the authenticated user."""
    res = await db.execute(
        select(WorkspaceMember)
        .options(selectinload(WorkspaceMember.workspace))
        .where(WorkspaceMember.user_id == current_user.id)
    )
    memberships = res.scalars().all()

    workspaces = [
        {
            "id": str(m.workspace.id),
            "name": m.workspace.name,
            "slug": m.workspace.slug,
            "role": m.role,
        }
        for m in memberships
        if m.workspace and not m.workspace.deleted_at
    ]

    return UserProfileResponse(
        id=current_user.id,
        email=current_user.email,
        full_name=current_user.full_name,
        is_active=current_user.is_active,
        created_at=current_user.created_at,
        workspaces=workspaces,
    )
