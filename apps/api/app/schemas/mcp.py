"""Pydantic schemas for Model Context Protocol (MCP) server management and tool discovery."""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class MCPServerRegisterRequest(BaseModel):
    """Payload to register a new local MCP server."""
    name: str = Field(..., min_length=2, max_length=100, description="Unique identifier for the MCP server")
    display_name: Optional[str] = Field(None, max_length=255, description="Human-readable server name")
    command: str = Field(..., description="Executable command to run (e.g. 'python', 'node', 'uvx')")
    args: List[str] = Field(default_factory=list, description="Command line arguments")
    env: Dict[str, str] = Field(default_factory=dict, description="Environment variables for the server process")
    workspace_id: uuid.UUID = Field(..., description="Workspace owning this MCP integration")
    timeout_seconds: int = Field(default=30, ge=5, le=300, description="Process communication timeout")
    allowed_tools: Optional[List[str]] = Field(None, description="Optional allowlist of tool names to register")
    is_active: bool = Field(default=True, description="Whether the server is enabled")


class MCPServerResponse(BaseModel):
    """Information and lifecycle status of a registered MCP server."""
    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    command: str
    args: List[str]
    status: str
    tools_count: int = 0
    discovered_tools: List[str] = Field(default_factory=list)
    created_at: datetime


class MCPDiscoveryResponse(BaseModel):
    """Result of tool discovery on an MCP server."""
    server_id: uuid.UUID
    server_name: str
    discovered_tools: List[Dict[str, Any]]
    registered_count: int
    status: str
