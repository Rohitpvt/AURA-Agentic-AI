"""Pydantic schemas for workspaces and memberships."""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class WorkspaceCreateRequest(BaseModel):
    """Payload to create a workspace."""
    name: str = Field(min_length=2, max_length=255)
    slug: Optional[str] = Field(default=None, max_length=100)
    description: Optional[str] = None
    settings: Dict[str, Any] = Field(default_factory=dict)


class WorkspaceResponse(BaseModel):
    """Workspace response payload."""
    id: uuid.UUID
    name: str
    slug: str
    description: Optional[str] = None
    settings: Dict[str, Any] = Field(default_factory=dict)
    role: Optional[str] = None
    created_at: datetime


class AddMemberRequest(BaseModel):
    """Payload to add a user to a workspace."""
    user_id: uuid.UUID
    role: str = Field(default="member", description="Role: owner, admin, member, guest")
    permissions: List[str] = Field(default_factory=list)


class MemberResponse(BaseModel):
    """Workspace member response."""
    id: uuid.UUID
    workspace_id: uuid.UUID
    user_id: uuid.UUID
    role: str
    permissions: List[str]
    email: Optional[str] = None
    full_name: Optional[str] = None
    created_at: datetime
