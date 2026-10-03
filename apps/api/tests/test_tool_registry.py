"""Tests for AURA-106: Local Tool Registry, Validation Boundary, and DuckDuckGo Web Search."""

import uuid
from unittest.mock import patch
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models.tool import Tool, ToolPermission
from app.db.models.workspace import Workspace
from app.services.tool_registry import tool_registry
from app.services.tools.web_search import execute_web_search, sanitize_untrusted_snippet


@pytest.mark.asyncio
async def test_sanitize_untrusted_snippet():
    """Verify web search snippet sanitization strips nulls and replaces dangerous backticks."""
    dirty = "Normal text ```python malicious_code()``` \x00 and control chars"
    clean = sanitize_untrusted_snippet(dirty)
    assert "\x00" not in clean
    assert "```" not in clean
    assert "'''python malicious_code()'''" in clean


@pytest.mark.asyncio
async def test_builtin_web_search_discovery(client: AsyncClient):
    """Test listing tools automatically seeds and returns built-in web_search tool."""
    # 1. Register User & get Workspace
    reg_res = await client.post(
        "/api/v1/auth/register",
        json={"email": "tool_user@example.com", "password": "ToolPassword123!"},
    )
    token = reg_res.json()["access_token"]
    me_res = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    ws_id = me_res.json()["workspaces"][0]["id"]

    # 2. List tools
    tools_res = await client.get(f"/api/v1/tools?workspace_id={ws_id}", headers={"Authorization": f"Bearer {token}"})
    assert tools_res.status_code == 200
    tools = tools_res.json()
    assert len(tools) >= 1
    tool_names = [t["name"] for t in tools]
    assert "web_search" in tool_names

    web_search = next(t for t in tools if t["name"] == "web_search")
    assert web_search["risk_level"] == "low"
    assert "query" in web_search["input_schema"]["required"]


@pytest.mark.asyncio
async def test_custom_tool_registration_and_duplicate_prevention(client: AsyncClient):
    """Test registering custom workspace tool and preventing duplicate tool names."""
    reg_res = await client.post(
        "/api/v1/auth/register",
        json={"email": "tool_owner@example.com", "password": "ToolPassword123!"},
    )
    token = reg_res.json()["access_token"]
    me_res = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    ws_id = me_res.json()["workspaces"][0]["id"]

    # 1. Register valid custom tool
    tool_payload = {
        "workspace_id": ws_id,
        "name": "custom_calculator",
        "display_name": "Custom Math Calculator",
        "description": "Perform basic arithmetic calculations",
        "category": "utilities",
        "risk_level": "low",
        "input_schema": {
            "type": "object",
            "properties": {
                "operation": {"type": "string"},
                "x": {"type": "number"},
                "y": {"type": "number"},
            },
            "required": ["operation", "x", "y"],
        },
        "timeout_seconds": 10,
    }
    reg_tool = await client.post("/api/v1/tools", json=tool_payload, headers={"Authorization": f"Bearer {token}"})
    assert reg_tool.status_code == 201
    assert reg_tool.json()["name"] == "custom_calculator"

    # 2. Duplicate registration in same workspace -> 422 / 400
    dup_res = await client.post("/api/v1/tools", json=tool_payload, headers={"Authorization": f"Bearer {token}"})
    assert dup_res.status_code in [400, 422]


@pytest.mark.asyncio
async def test_tool_schema_validation_and_argument_rejection(client: AsyncClient):
    """Test invalid argument types or missing required fields are rejected by Python validator."""
    reg_res = await client.post(
        "/api/v1/auth/register",
        json={"email": "schema_val@example.com", "password": "SchemaPassword123!"},
    )
    token = reg_res.json()["access_token"]
    me_res = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    ws_id = me_res.json()["workspaces"][0]["id"]

    # 1. Missing required 'query'
    bad_req = {
        "workspace_id": ws_id,
        "tool_name": "web_search",
        "arguments": {"max_results": 5},
    }
    res = await client.post("/api/v1/tools/execute", json=bad_req, headers={"Authorization": f"Bearer {token}"})
    assert res.status_code in [400, 422]
    assert "Missing required parameter 'query'" in res.json()["error"]["message"]

    # 2. Wrong type for 'query' (int instead of string)
    bad_type = {
        "workspace_id": ws_id,
        "tool_name": "web_search",
        "arguments": {"query": 12345},
    }
    res_type = await client.post("/api/v1/tools/execute", json=bad_type, headers={"Authorization": f"Bearer {token}"})
    assert res_type.status_code in [400, 422]
    assert "must be a string" in res_type.json()["error"]["message"]


@pytest.mark.asyncio
async def test_hitl_approval_required_for_high_risk_tool(client: AsyncClient):
    """Test high-risk or approval-required tool returns HITL token instead of executing directly."""
    reg_res = await client.post(
        "/api/v1/auth/register",
        json={"email": "hitl_admin@example.com", "password": "HitlPassword123!"},
    )
    token = reg_res.json()["access_token"]
    me_res = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    ws_id = me_res.json()["workspaces"][0]["id"]

    # Register high-risk tool
    high_risk_tool = {
        "workspace_id": ws_id,
        "name": "delete_production_database",
        "display_name": "Delete Production Database",
        "description": "Destructive drop table tool",
        "category": "database",
        "risk_level": "critical",
        "requires_approval": True,
        "input_schema": {
            "type": "object",
            "properties": {"db_name": {"type": "string"}},
            "required": ["db_name"],
        },
    }
    await client.post("/api/v1/tools", json=high_risk_tool, headers={"Authorization": f"Bearer {token}"})

    # Execute high risk tool -> Suspends for HITL approval
    exec_res = await client.post(
        "/api/v1/tools/execute",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "workspace_id": ws_id,
            "tool_name": "delete_production_database",
            "arguments": {"db_name": "prod_main"},
        },
    )
    assert exec_res.status_code == 200
    data = exec_res.json()
    assert data["success"] is False
    assert data["requires_hitl_approval"] is True
    assert data["approval_token"] is not None
    assert "Human-in-the-Loop approval required" in data["error"]


@pytest.mark.asyncio
async def test_mocked_duckduckgo_web_search_execution(client: AsyncClient):
    """Test web_search execution against mocked search results returning untrusted data format."""
    reg_res = await client.post(
        "/api/v1/auth/register",
        json={"email": "searcher@example.com", "password": "SearchPassword123!"},
    )
    token = reg_res.json()["access_token"]
    me_res = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    ws_id = me_res.json()["workspaces"][0]["id"]

    mock_raw_results = [
        {
            "title": "FastAPI Framework Documentation",
            "href": "https://fastapi.tiangolo.com",
            "body": "FastAPI is a modern, fast web framework for building APIs with Python 3.8+.",
        },
        {
            "title": "PostgreSQL 16 Release Notes",
            "href": "https://www.postgresql.org/docs/16/",
            "body": "PostgreSQL 16 improves query execution and logical replication.",
        },
    ]

    with patch("duckduckgo_search.DDGS.text", return_value=mock_raw_results):
        exec_res = await client.post(
            "/api/v1/tools/execute",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "workspace_id": ws_id,
                "tool_name": "web_search",
                "arguments": {"query": "FastAPI and PostgreSQL 16", "max_results": 2},
            },
        )
        assert exec_res.status_code == 200
        data = exec_res.json()
        assert data["success"] is True
        assert data["risk_level"] == "low"
        result = data["result"]
        assert result["total_results"] == 2
        assert result["results"][0]["title"] == "FastAPI Framework Documentation"
        assert result["results"][0]["is_untrusted_content"] is True
        assert result["results"][0]["source"] == "duckduckgo"
