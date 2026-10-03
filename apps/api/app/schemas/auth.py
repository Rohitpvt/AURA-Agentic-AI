"""Pydantic schemas for authentication and user management."""

import uuid
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, EmailStr, Field


class UserRegisterRequest(BaseModel):
    """Payload for user registration."""
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(default="AURA User", max_length=255)
    username: Optional[str] = Field(default=None, max_length=50)
    workspace_name: Optional[str] = Field(default=None, description="Initial workspace name (defaults to personal)")


class UserLoginRequest(BaseModel):
    """Payload for user login."""
    email: EmailStr
    password: str


class TokenRefreshRequest(BaseModel):
    """Payload for refreshing an access token."""
    refresh_token: str


class TokenResponse(BaseModel):
    """Token response payload."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class UserProfileResponse(BaseModel):
    """User profile response."""
    id: uuid.UUID
    email: str
    full_name: str
    username: Optional[str] = None
    is_active: bool
    created_at: datetime
    workspaces: List[dict] = []
