"""Tool Registry API endpoints."""

import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_current_user, get_workspace_membership
from app.db.models.user import User
from app.db.models.workspace import WorkspaceMember
from app.db.session import get_db_session
from app.schemas.tool import ToolExecutionRequest, ToolExecutionResponse, ToolRegisterRequest, ToolResponse
from app.services.tool_registry import tool_registry

router = APIRouter()


@router.get("", response_model=List[ToolResponse])
async def list_tools(
    workspace_id: uuid.UUID = Query(..., description="Target workspace ID"),
    category: Optional[str] = Query(None, description="Optional category filter"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[ToolResponse]:
    """List all available tools (system-level and workspace-level)."""
    await get_workspace_membership(workspace_id=workspace_id, user_id=current_user.id, db=db)
    return await tool_registry.list_tools(db=db, workspace_id=workspace_id, category=category)


@router.post("", response_model=ToolResponse, status_code=status.HTTP_201_CREATED)
async def register_tool(
    payload: ToolRegisterRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ToolResponse:
    """Register a new workspace tool capability."""
    if not payload.workspace_id:
        from app.core.errors import ValidationError
        raise ValidationError("workspace_id is required to register a tool")

    # Authorize: Must be owner or admin to register custom tools
    membership = await get_workspace_membership(
        workspace_id=payload.workspace_id, user_id=current_user.id, db=db
    )
    if membership.role not in ["owner", "admin"]:
        from app.core.errors import AuthorizationError
        raise AuthorizationError("Only workspace owner or admin can register new tools")

    return await tool_registry.register_tool(
        db=db,
        payload=payload,
        workspace_id=payload.workspace_id,
        actor_id=str(current_user.id),
    )


@router.get("/{tool_id}", response_model=ToolResponse)
async def get_tool(
    tool_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ToolResponse:
    """Get metadata for a specific tool."""
    await get_workspace_membership(workspace_id=workspace_id, user_id=current_user.id, db=db)
    tool = await tool_registry.get_tool(db=db, tool_id=tool_id, workspace_id=workspace_id)
    return ToolResponse(
        id=tool.id,
        workspace_id=tool.workspace_id,
        integration_id=tool.integration_id,
        name=tool.name,
        display_name=tool.display_name,
        description=tool.description,
        category=tool.category,
        risk_level=tool.risk_level,
        input_schema=tool.input_schema,
        output_schema=tool.output_schema,
        timeout_seconds=tool.timeout_seconds,
        rate_limit_per_minute=tool.rate_limit_per_minute,
        requires_approval=tool.requires_approval,
        is_allowed_in_background=tool.is_allowed_in_background,
        is_active=tool.is_active,
        created_at=tool.created_at,
    )


@router.post("/execute", response_model=ToolExecutionResponse)
async def execute_tool(
    payload: ToolExecutionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ToolExecutionResponse:
    """Execute a tool through policy, validation, risk check, and audit boundaries."""
    await get_workspace_membership(workspace_id=payload.workspace_id, user_id=current_user.id, db=db)
    return await tool_registry.execute_tool(
        db=db,
        request=payload,
        actor_id=str(current_user.id),
        actor_type="user",
    )
