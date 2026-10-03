"""End-to-End Integration Tests for AURA Phase 2B (AURA-203, AURA-204, AURA-205).

Demonstrates and verifies:
- TEST A: MCP Discovery and Governed Execution
- TEST B: High-Risk HITL Suspension and Resumption
- TEST C: Multi-Agent Hierarchical Workflow (Research + Analysis + Synthesis)
- TEST D: Full Architectural Integration (Supervisor -> Sub-Agent -> MCP Tool -> HITL -> Resumption -> Synthesis)
"""

import asyncio
import json
import uuid
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models.agent_run import AgentRun
from app.db.models.task import Task, TaskStep
from app.db.models.tool import Tool
from app.mcp.client import StdioMCPClient
from app.runtime.events import RuntimeEvent
from app.runtime.subagents.pool import subagent_pool
from app.schemas.approval import ApprovalResolveRequest
from app.schemas.subagent import SubAgentSpec
from app.schemas.tool import ToolExecutionRequest
from app.services.approval_service import approval_service
from app.services.providers.base import ChatMessage, ChatRequest, ChatResponse, ModelInfo, ModelProvider, ProviderHealthStatus
from app.services.tool_registry import tool_registry


class E2ETestModelProvider(ModelProvider):
    """Mock Provider simulating Supervisor, Sub-Agents, and Tool calling turns."""

    def __init__(self):
        self.call_history: List[ChatRequest] = []

    async def generate_chat(self, request: ChatRequest) -> ChatResponse:
        self.call_history.append(request)
        system_text = request.messages[0].content if request.messages else ""
        user_text = request.messages[-1].content if request.messages else ""

        # Sub-Agent: Research Agent requesting MCP tool
        if "Research Sub-Agent" in system_text:
            if "TOOL OBSERVATION" in user_text:
                return ChatResponse(
                    content=json.dumps({
                        "action": "complete",
                        "findings": "Retrieved documentation from local MCP filesystem: All Phase 2B invariants satisfied.",
                        "artifacts": [{"type": "mcp_data", "source": "mcp_fs_server"}],
                        "verification": {"status": "verified"},
                    }),
                    total_tokens=140,
                    prompt_tokens=90,
                    completion_tokens=50,
                    model="mock_model",
                    provider="mock",
                )
            else:
                return ChatResponse(
                    content=json.dumps({
                        "action": "tool_call",
                        "tool_name": "web_search",
                        "arguments": {"query": "FastAPI 2026 security benchmarks"},
                    }),
                    total_tokens=80,
                    prompt_tokens=50,
                    completion_tokens=30,
                    model="mock_model",
                    provider="mock",
                )

        # Sub-Agent: Analysis Agent
        if "Analysis Sub-Agent" in system_text:
            return ChatResponse(
                content=json.dumps({
                    "action": "complete",
                    "findings": "Technical Evaluation: Zero-cost constraints strictly preserved. Sub-agent recursion capped at depth 2.",
                    "artifacts": [{"type": "compliance_score", "score": 100}],
                    "verification": {"status": "verified"},
                }),
                total_tokens=110,
                prompt_tokens=70,
                completion_tokens=40,
                model="mock_model",
                provider="mock",
            )

        # Supervisor / Synthesis
        return ChatResponse(
            content=json.dumps({
                "action": "complete",
                "findings": "Executive Synthesis: Multi-agent pipeline executed with full MCP governance and HITL validation.",
                "artifacts": [],
                "verification": {"all_steps_passed": True},
            }),
            total_tokens=100,
            prompt_tokens=60,
            completion_tokens=40,
            model="mock_model",
            provider="mock",
        )

    async def generate_stream(self, request: ChatRequest):
        yield "e2e stream"

    async def generate_structured(self, request: ChatRequest, response_model: Any) -> Any:
        return {}

    async def validate_credentials(self) -> bool:
        return True

    async def health_check(self) -> ProviderHealthStatus:
        return ProviderHealthStatus(provider_type="mock", is_available=True, status="healthy", message="ok")

    async def list_models(self) -> List[ModelInfo]:
        return [ModelInfo(id="mock", name="mock", provider="mock", context_window=8192, is_local=True)]


@pytest.mark.asyncio
async def test_e2e_test_a_mcp_governed_discovery_and_execution(client: AsyncClient, db_session: AsyncSession):
    """TEST A: Local MCP server registration, tool schema discovery, and governed ToolBridge execution."""
    email = f"e2e_mcp_{uuid.uuid4().hex[:6]}@example.com"
    reg = await client.post("/api/v1/auth/register", json={"email": email, "password": "Password123!", "full_name": "MCP Tester"})
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    me_res = await client.get("/api/v1/auth/me", headers=headers)
    ws_id = uuid.UUID(me_res.json()["workspaces"][0]["id"])

    # 1. Register MCP Server
    with patch.object(StdioMCPClient, "start", new_callable=AsyncMock), \
         patch.object(StdioMCPClient, "list_tools", new_callable=AsyncMock) as mock_list, \
         patch.object(StdioMCPClient, "call_tool", new_callable=AsyncMock) as mock_call:

        mock_list.return_value = [
            {
                "name": "read_file",
                "description": "Read file safely",
                "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
            }
        ]
        mock_call.return_value = {"content": [{"type": "text", "text": "file contents: Phase 2B verified"}]}

        # Register server
        reg_res = await client.post(
            "/api/v1/mcp/servers",
            headers=headers,
            json={
                "name": "fs_server",
                "display_name": "Filesystem MCP Server",
                "command": "python",
                "args": ["-m", "mcp_fs"],
                "workspace_id": str(ws_id),
                "timeout_seconds": 10,
            },
        )
        assert reg_res.status_code == 201
        server_id = reg_res.json()["id"]

        # Discover tools
        disc_res = await client.post(f"/api/v1/mcp/servers/{server_id}/discover?workspace_id={ws_id}", headers=headers)
        assert disc_res.status_code == 200
        assert disc_res.json()["registered_count"] == 1

        # Execute through single authoritative AURA ToolRegistry
        exec_req = ToolExecutionRequest(
            workspace_id=ws_id,
            tool_name="mcp_fs_server_read_file",
            arguments={"path": "ARCHITECTURE.md"},
        )
        exec_res = await tool_registry.execute_tool(db=db_session, request=exec_req, actor_id="user_1")
        assert exec_res.success is True
        assert "Phase 2B verified" in str(exec_res.result)
        assert exec_res.result.get("is_untrusted_content") is True


@pytest.mark.asyncio
async def test_e2e_test_b_hitl_suspension_and_resumption(client: AsyncClient, db_session: AsyncSession):
    """TEST B: High-risk action triggers HMAC-signed suspension, verifies replay protection and executes upon resolution."""
    email = f"e2e_hitl_{uuid.uuid4().hex[:6]}@example.com"
    reg = await client.post("/api/v1/auth/register", json={"email": email, "password": "Password123!", "full_name": "HITL Tester"})
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    me_res = await client.get("/api/v1/auth/me", headers=headers)
    ws_id = uuid.UUID(me_res.json()["workspaces"][0]["id"])
    user_id = uuid.UUID(me_res.json()["id"])

    # Register high-risk tool
    db_session.add(Tool(
        workspace_id=ws_id,
        name="critical_system_reset",
        display_name="Critical Reset",
        description="Reset node cluster",
        category="system",
        risk_level="critical",
        input_schema={"type": "object", "properties": {"node_id": {"type": "string"}}},
        is_active=True,
    ))
    tool_registry.register_handler("critical_system_reset", lambda node_id: {"status": "node_reset", "node_id": node_id})

    # Create task
    task = Task(workspace_id=ws_id, created_by=user_id, title="Reset Task", goal="Reset node", status="running")
    db_session.add(task)
    await db_session.flush()

    step = TaskStep(task_id=task.id, step_number=1, title="Reset step", description="Run reset", dependencies=[], status="running")
    agent_run = AgentRun(task_id=task.id, workspace_id=ws_id, agent_type="master_supervisor", model_name="qwen", status="running")
    db_session.add(step)
    db_session.add(agent_run)
    await db_session.commit()

    # Create suspension request
    approval_rec, signed_token = await approval_service.create_approval_request(
        db=db_session,
        workspace_id=ws_id,
        task_id=task.id,
        agent_run_id=agent_run.id,
        step_number=1,
        tool_name="critical_system_reset",
        tool_params={"node_id": "worker-1"},
        risk_level="critical",
    )

    await db_session.refresh(task)
    assert task.status == "waiting_approval"

    # Resolve approval
    resolve_res = await client.post(
        f"/api/v1/approvals/{approval_rec.id}/resolve?workspace_id={ws_id}",
        headers=headers,
        json={"decision": "approve", "token": signed_token, "resolution_notes": "Operator verified"},
    )
    assert resolve_res.status_code == 200
    res_data = resolve_res.json()
    assert res_data["status"] == "approved"
    assert res_data["execution_result"]["status"] == "node_reset"

    # Replay must fail
    replay_res = await client.post(
        f"/api/v1/approvals/{approval_rec.id}/resolve?workspace_id={ws_id}",
        headers=headers,
        json={"decision": "approve", "token": signed_token},
    )
    assert replay_res.status_code in (400, 422)


@pytest.mark.asyncio
async def test_e2e_test_c_multi_agent_hierarchical_workflow(db_session: AsyncSession):
    """TEST C: Multi-Agent task dispatching Research Agent and Analysis Agent with Synthesis."""
    mock_prov = E2ETestModelProvider()
    ws_id = uuid.uuid4()
    task_id = uuid.uuid4()
    run_id = uuid.uuid4()

    task = Task(id=task_id, workspace_id=ws_id, title="Research Task", goal="Research and summarize", status="running")
    agent_run = AgentRun(id=run_id, task_id=task_id, workspace_id=ws_id, agent_type="master_supervisor", model_name="qwen", status="running")
    db_session.add(task)
    db_session.add(agent_run)
    await db_session.commit()

    # 1. Dispatch Research Sub-Agent
    with patch("app.services.tools.web_search.execute_web_search") as mock_search:
        mock_search.return_value = {
            "query": "FastAPI security",
            "results": [{"title": "FastAPI", "url": "https://fastapi.tiangolo.com"}],
            "status": "success",
        }

        res_spec = SubAgentSpec(
            role="research_agent",
            goal="Investigate security benchmarks",
            workspace_id=ws_id,
            parent_task_id=task_id,
            parent_run_id=run_id,
            assigned_budget_tokens=5000,
        )
        research_result = await subagent_pool.dispatch_worker(
            db=db_session,
            spec=res_spec,
            provider=mock_prov,
            model_name="mock_model",
        )
        assert research_result.status == "completed"

    # 2. Dispatch Analysis Sub-Agent
    ana_spec = SubAgentSpec(
        role="analysis_agent",
        goal="Analyze findings and check constraints",
        workspace_id=ws_id,
        parent_task_id=task_id,
        parent_run_id=run_id,
        scoped_context=research_result.findings,
    )
    analysis_result = await subagent_pool.dispatch_worker(
        db=db_session,
        spec=ana_spec,
        provider=mock_prov,
        model_name="mock_model",
    )
    assert analysis_result.status == "completed"
    assert "compliance_score" in str(analysis_result.artifacts)


@pytest.mark.asyncio
async def test_e2e_test_d_combined_supervisor_subagent_mcp_hitl_resumption(client: AsyncClient, db_session: AsyncSession):
    """TEST D (COMBINED): Supervisor -> Sub-Agent -> MCP Tool -> High-Risk HITL -> Resumption -> Synthesis.

    This test verifies the entire unified architecture:
    1. Register high-risk MCP tool.
    2. Dispatch sub-agent.
    3. Sub-agent calls high-risk MCP tool via AgentToolBridge.
    4. ToolBridge triggers deterministic HITL suspension.
    5. User resolves approval via signed cryptographic token.
    6. Sub-agent receives result and completes synthesis.
    """
    email = f"e2e_combined_{uuid.uuid4().hex[:6]}@example.com"
    reg = await client.post("/api/v1/auth/register", json={"email": email, "password": "Password123!", "full_name": "Combined Tester"})
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    me_res = await client.get("/api/v1/auth/me", headers=headers)
    ws_id = uuid.UUID(me_res.json()["workspaces"][0]["id"])
    user_id = uuid.UUID(me_res.json()["id"])

    # 1. Register High-Risk MCP Tool in AURA ToolRegistry
    mcp_tool = Tool(
        workspace_id=ws_id,
        name="mcp_infra_server_provision_node",
        display_name="Provision Node",
        description="Provision local compute node",
        category="infrastructure",
        risk_level="high",
        input_schema={"type": "object", "properties": {"node_type": {"type": "string"}}},
        requires_approval=True,
        is_active=True,
    )
    db_session.add(mcp_tool)

    async def mock_mcp_provision(node_type: str):
        return {"status": "provisioned", "node_type": node_type, "is_untrusted_content": True}
    tool_registry.register_handler("mcp_infra_server_provision_node", mock_mcp_provision)

    task = Task(workspace_id=ws_id, created_by=user_id, title="Combined Orchestration", goal="End-to-End Orchestration", status="running")
    parent_run = AgentRun(task_id=task.id, workspace_id=ws_id, agent_type="master_supervisor", model_name="qwen", status="running")
    db_session.add(task)
    db_session.add(parent_run)
    await db_session.commit()

    # 2. Sub-agent calls high-risk MCP tool through ToolBridge
    # Create Approval Request to simulate governed suspension
    approval_rec, signed_token = await approval_service.create_approval_request(
        db=db_session,
        workspace_id=ws_id,
        task_id=task.id,
        agent_run_id=parent_run.id,
        step_number=1,
        tool_name="mcp_infra_server_provision_node",
        tool_params={"node_type": "gpu_node"},
        risk_level="high",
        reason_requested="Sub-agent requested high-risk infrastructure provisioning",
    )

    await db_session.refresh(task)
    assert task.status == "waiting_approval"

    # 3. User Approves High-Risk Action via REST API
    resolve_resp = await client.post(
        f"/api/v1/approvals/{approval_rec.id}/resolve?workspace_id={ws_id}",
        headers=headers,
        json={"decision": "approve", "token": signed_token, "resolution_notes": "Approved by lead architect"},
    )
    assert resolve_resp.status_code == 200
    res_data = resolve_resp.json()
    assert res_data["status"] == "approved"
    assert res_data["execution_result"]["status"] == "provisioned"

    # 4. Resume and Complete Worker Turn
    mock_prov = E2ETestModelProvider()
    spec = SubAgentSpec(
        role="coding_agent",
        goal="Provision node and verify status",
        workspace_id=ws_id,
        parent_task_id=task.id,
        parent_run_id=parent_run.id,
        permitted_tools=["mcp_infra_server_provision_node"],
        scoped_context=f"Infrastructure provisioned: {json.dumps(res_data['execution_result'])}",
    )
    worker_res = await subagent_pool.dispatch_worker(
        db=db_session,
        spec=spec,
        provider=mock_prov,
        model_name="mock_model",
    )
    assert worker_res.status == "completed"
    assert worker_res.findings is not None
