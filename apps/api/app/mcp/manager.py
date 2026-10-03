"""MCP Host Manager supervising local MCP servers and bridging tools to AURA ToolRegistry."""

import json
import uuid
from typing import Any, Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.errors import EntityNotFoundError, ValidationError
from app.core.logging import logger
from app.db.models.tool import Integration, Tool
from app.mcp.client import StdioMCPClient
from app.schemas.mcp import MCPDiscoveryResponse, MCPServerRegisterRequest, MCPServerResponse
from app.schemas.tool import ToolRegisterRequest
from app.services.tool_registry import tool_registry


class MCPHostManager:
    """Manages active MCP subprocess clients and registers discovered tools into AURA."""

    def __init__(self):
        self._clients: Dict[str, StdioMCPClient] = {}

    def get_client(self, server_id: str) -> Optional[StdioMCPClient]:
        """Retrieve active stdio client by server ID."""
        return self._clients.get(server_id)

    async def register_server(
        self,
        db: AsyncSession,
        request: MCPServerRegisterRequest,
        actor_id: str,
    ) -> MCPServerResponse:
        """Register an MCP server configuration in PostgreSQL and initialize host client."""
        # Check duplicate integration name in workspace
        res = await db.execute(
            select(Integration).where(
                Integration.workspace_id == request.workspace_id,
                Integration.name == request.name,
                Integration.deleted_at.is_(None),
            )
        )
        if res.scalar_one_or_none():
            raise ValidationError(f"MCP Server '{request.name}' already registered in workspace")

        integration = Integration(
            workspace_id=request.workspace_id,
            name=request.name,
            provider_type="mcp",
            transport="stdio",
            config={
                "command": request.command,
                "args": request.args,
                "env": request.env,
                "timeout_seconds": request.timeout_seconds,
                "allowed_tools": request.allowed_tools,
            },
            status="active" if request.is_active else "disabled",
        )
        db.add(integration)
        await db.commit()
        await db.refresh(integration)

        server_id_str = str(integration.id)
        # Instantiate client
        client = StdioMCPClient(
            server_id=server_id_str,
            command=request.command,
            args=request.args,
            env=request.env,
            timeout_seconds=request.timeout_seconds,
        )
        self._clients[server_id_str] = client

        return MCPServerResponse(
            id=integration.id,
            workspace_id=integration.workspace_id,
            name=integration.name,
            command=request.command,
            args=request.args,
            status=integration.status,
            tools_count=0,
            discovered_tools=[],
            created_at=integration.created_at,
        )

    async def discover_and_register_tools(
        self,
        db: AsyncSession,
        server_id: uuid.UUID,
        workspace_id: uuid.UUID,
        actor_id: str,
    ) -> MCPDiscoveryResponse:
        """Connect to MCP server, discover tools, validate schemas, and register into AURA ToolRegistry."""
        res = await db.execute(
            select(Integration).where(
                Integration.id == server_id,
                Integration.workspace_id == workspace_id,
                Integration.deleted_at.is_(None),
            )
        )
        integration = res.scalar_one_or_none()
        if not integration:
            raise EntityNotFoundError("MCPServer", str(server_id))

        server_id_str = str(server_id)
        config = integration.config or {}
        command = config.get("command", "")
        args = config.get("args", [])
        env = config.get("env", {})
        timeout_seconds = config.get("timeout_seconds", 30)
        allowed_tools = config.get("allowed_tools")

        # Get or create client
        client = self._clients.get(server_id_str)
        if not client:
            client = StdioMCPClient(
                server_id=server_id_str,
                command=command,
                args=args,
                env=env,
                timeout_seconds=timeout_seconds,
            )
            self._clients[server_id_str] = client

        # Ensure server process is started
        if not client.is_running:
            await client.start()

        # Fetch tools from MCP server
        raw_tools = await client.list_tools()
        registered_tools: List[Dict[str, Any]] = []

        for t in raw_tools:
            name = t.get("name")
            if not name:
                continue

            # Check allowlist
            if allowed_tools and name not in allowed_tools:
                logger.info(f"MCPHostManager: Skipping tool '{name}' (not in allowed_tools filter)")
                continue

            description = t.get("description", f"MCP Tool from {integration.name}")
            input_schema = t.get("inputSchema", {"type": "object", "properties": {}})

            # Canonical normalized tool name prefixed by server name to avoid collisions
            canonical_tool_name = f"mcp_{integration.name}_{name}"

            # Register dynamic execution handler with AURA Tool Registry
            async def _mcp_handler(current_tool_name=name, target_client=client, **kwargs):
                result = await target_client.call_tool(current_tool_name, kwargs)
                # Extract text content from MCP content block
                content_items = result.get("content", [])
                texts = [c.get("text", "") for c in content_items if isinstance(c, dict) and c.get("type") == "text"]
                return {
                    "mcp_server": integration.name,
                    "tool": current_tool_name,
                    "output": "\n".join(texts) if texts else result,
                    "is_untrusted_content": True,
                }

            tool_registry.register_handler(canonical_tool_name, _mcp_handler)

            # Persist or update in database via ToolRegistry
            existing_tool_res = await db.execute(
                select(Tool).where(
                    Tool.name == canonical_tool_name,
                    Tool.workspace_id == workspace_id,
                )
            )
            existing_tool = existing_tool_res.scalar_one_or_none()

            if existing_tool:
                existing_tool.description = description
                existing_tool.input_schema = input_schema
                existing_tool.is_active = True
                await db.flush()
            else:
                new_tool = Tool(
                    workspace_id=workspace_id,
                    integration_id=integration.id,
                    name=canonical_tool_name,
                    display_name=f"MCP: {name} ({integration.name})",
                    description=description,
                    category="mcp",
                    risk_level="low",  # Default MCP tools to low risk; user can override in ToolPermissions
                    input_schema=input_schema,
                    output_schema={"type": "object"},
                    timeout_seconds=timeout_seconds,
                    rate_limit_per_minute=60,
                    requires_approval=False,
                    is_allowed_in_background=True,
                    is_active=True,
                )
                db.add(new_tool)
                await db.flush()

            registered_tools.append({
                "name": canonical_tool_name,
                "original_name": name,
                "description": description,
            })

        await db.commit()

        return MCPDiscoveryResponse(
            server_id=integration.id,
            server_name=integration.name,
            discovered_tools=registered_tools,
            registered_count=len(registered_tools),
            status="success",
        )

    async def stop_server(self, server_id: str) -> None:
        """Stop an active MCP server process."""
        client = self._clients.get(server_id)
        if client:
            await client.stop()

    async def cleanup_all(self) -> None:
        """Terminate all active MCP subprocesses on shutdown."""
        logger.info("MCPHostManager: Cleaning up all active MCP subprocesses")
        for server_id, client in list(self._clients.items()):
            await client.stop()
        self._clients.clear()

    async def stop_all_servers(self) -> None:
        """Alias for cleanup_all."""
        await self.cleanup_all()


mcp_manager = MCPHostManager()
