"""MCP server management endpoints."""

import uuid
from typing import List
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_current_user
from app.core.errors import AuthorizationError, EntityNotFoundError
from app.db.models.tool import Integration
from app.db.models.user import User
from app.db.session import get_db_session
from app.mcp.manager import mcp_manager
from app.schemas.mcp import MCPDiscoveryResponse, MCPServerRegisterRequest, MCPServerResponse

router = APIRouter()


@router.post("/servers", response_model=MCPServerResponse, status_code=201)
async def register_mcp_server(
    payload: MCPServerRegisterRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Register a local MCP server integration for the workspace."""
    return await mcp_manager.register_server(
        db=db,
        request=payload,
        actor_id=str(current_user.id),
    )


@router.get("/servers", response_model=List[MCPServerResponse])
async def list_mcp_servers(
    workspace_id: uuid.UUID = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """List all registered MCP servers for a workspace."""
    res = await db.execute(
        select(Integration).where(
            Integration.workspace_id == workspace_id,
            Integration.provider_type == "mcp",
            Integration.deleted_at.is_(None),
        )
    )
    servers = res.scalars().all()
    out = []
    for s in servers:
        config = s.config or {}
        client = mcp_manager.get_client(str(s.id))
        status = "running" if client and client.is_running else s.status
        out.append(
            MCPServerResponse(
                id=s.id,
                workspace_id=s.workspace_id,
                name=s.name,
                command=config.get("command", ""),
                args=config.get("args", []),
                status=status,
                tools_count=0,
                discovered_tools=[],
                created_at=s.created_at,
            )
        )
    return out


@router.post("/servers/{server_id}/discover", response_model=MCPDiscoveryResponse)
async def discover_mcp_tools(
    server_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Discover tools exposed by the MCP server and register them into AURA ToolRegistry."""
    return await mcp_manager.discover_and_register_tools(
        db=db,
        server_id=server_id,
        workspace_id=workspace_id,
        actor_id=str(current_user.id),
    )


@router.post("/servers/{server_id}/stop")
async def stop_mcp_server(
    server_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
):
    """Stop an active MCP server process."""
    await mcp_manager.stop_server(str(server_id))
    return {"status": "stopped", "server_id": str(server_id)}
