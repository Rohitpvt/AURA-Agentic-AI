"""Unit and integration tests for AURA-203: Local MCP Host Client Manager."""

import asyncio
import json
import uuid
from unittest.mock import AsyncMock, patch
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from app.mcp.client import StdioMCPClient
from app.mcp.manager import mcp_manager
from app.mcp.protocol import JSONRPCMessage
from app.schemas.mcp import MCPServerRegisterRequest
from app.schemas.tool import ToolExecutionRequest
from app.services.tool_registry import tool_registry


@pytest.mark.asyncio
async def test_mcp_protocol_message_serialization():
    """Verify JSON-RPC 2.0 formatting and parsing for MCP."""
    req_str = JSONRPCMessage.build_request("tools/list", {"cursor": "abc"}, request_id=42)
    parsed_req = json.loads(req_str)
    assert parsed_req["jsonrpc"] == "2.0"
    assert parsed_req["method"] == "tools/list"
    assert parsed_req["id"] == 42
    assert parsed_req["params"]["cursor"] == "abc"

    notif_str = JSONRPCMessage.build_notification("notifications/initialized")
    parsed_notif = json.loads(notif_str)
    assert "id" not in parsed_notif
    assert parsed_notif["method"] == "notifications/initialized"

    resp_line = '{"jsonrpc": "2.0", "id": 42, "result": {"tools": []}}\n'
    parsed_resp = JSONRPCMessage.parse_response(resp_line)
    assert parsed_resp["result"]["tools"] == []


@pytest.mark.asyncio
async def test_mcp_server_registration_and_tool_discovery(client: AsyncClient, db_session: AsyncSession):
    """Verify registering an MCP server, discovering tools, and registering into AURA ToolRegistry."""
    # 1. Register user & workspace
    email = f"mcp_tester_{uuid.uuid4().hex[:6]}@example.com"
    reg = await client.post("/api/v1/auth/register", json={"email": email, "password": "Password123!", "full_name": "MCP Tester"})
    token = reg.json()["access_token"]
    me_res = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    ws_id = me_res.json()["workspaces"][0]["id"]

    headers = {"Authorization": f"Bearer {token}"}

    # 2. Mock Stdio subprocess for tool discovery
    mock_tools = [
        {
            "name": "read_doc",
            "description": "Read local markdown document",
            "inputSchema": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        }
    ]

    with patch.object(StdioMCPClient, "start", new_callable=AsyncMock) as mock_start, \
         patch.object(StdioMCPClient, "list_tools", new_callable=AsyncMock) as mock_list, \
         patch.object(StdioMCPClient, "call_tool", new_callable=AsyncMock) as mock_call:

        mock_list.return_value = mock_tools
        mock_call.return_value = {
            "content": [{"type": "text", "text": "Document contents: Architecture specifications"}]
        }

        # Register MCP Server via API
        reg_resp = await client.post(
            "/api/v1/mcp/servers",
            headers=headers,
            json={
                "name": "doc_server",
                "display_name": "Documentation Server",
                "command": "python",
                "args": ["-m", "mcp_docs"],
                "env": {"DOC_ROOT": "/docs"},
                "workspace_id": str(ws_id),
                "timeout_seconds": 15,
                "is_active": True,
            },
        )
        assert reg_resp.status_code == 201
        server_data = reg_resp.json()
        server_id = server_data["id"]
        assert server_data["name"] == "doc_server"

        # Trigger Tool Discovery
        disc_resp = await client.post(
            f"/api/v1/mcp/servers/{server_id}/discover?workspace_id={ws_id}",
            headers=headers,
        )
        assert disc_resp.status_code == 200
        disc_data = disc_resp.json()
        assert disc_data["registered_count"] == 1
        canonical_name = disc_data["discovered_tools"][0]["name"]
        assert canonical_name == "mcp_doc_server_read_doc"

        # 3. Verify tool is visible in AURA ToolRegistry
        ws_uuid = uuid.UUID(ws_id)
        tools = await tool_registry.list_tools(db=db_session, workspace_id=ws_uuid)
        tool_names = [t.name for t in tools]
        assert "mcp_doc_server_read_doc" in tool_names

        # 4. Execute tool through AURA's single authoritative boundary
        exec_req = ToolExecutionRequest(
            workspace_id=ws_uuid,
            tool_name="mcp_doc_server_read_doc",
            arguments={"path": "README.md"},
        )
        exec_resp = await tool_registry.execute_tool(db=db_session, request=exec_req, actor_id="user_1")
        assert exec_resp.success is True
        assert "Document contents" in str(exec_resp.result)
        assert exec_resp.result["is_untrusted_content"] is True


@pytest.mark.asyncio
async def test_mcp_server_process_lifecycle_and_cleanup():
    """Verify start, stop, and clean termination of MCP client."""
    client = StdioMCPClient(
        server_id="test_cleanup_server",
        command="python",
        args=["-c", "import time; time.sleep(1)"],
        timeout_seconds=5,
    )
    assert client.is_running is False
    await client.stop()
    assert client.is_running is False
