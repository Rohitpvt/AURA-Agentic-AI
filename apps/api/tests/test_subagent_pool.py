"""Unit and integration tests for AURA-205: Bounded Local Sub-Agent Worker Pool."""

import json
import uuid
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.errors import ValidationError
from app.db.models.agent_run import AgentRun
from app.db.models.task import Task
from app.db.models.tool import Tool
from app.runtime.events import RuntimeEvent
from app.runtime.subagents.pool import subagent_pool
from app.runtime.subagents.roles import SUBAGENT_ROLES
from app.schemas.subagent import SubAgentSpec
from app.services.providers.base import ChatMessage, ChatRequest, ChatResponse, ModelInfo, ModelProvider, ProviderHealthStatus
from app.services.tool_registry import tool_registry


class MockSubAgentProvider(ModelProvider):
    """Deterministic mock provider for sub-agent worker tests."""

    async def generate_chat(self, request: ChatRequest) -> ChatResponse:
        system_text = request.messages[0].content if request.messages else ""
        user_text = request.messages[-1].content if request.messages else ""

        # Check if research agent needs to call web search
        if "Research Sub-Agent" in system_text:
            if "TOOL OBSERVATION" in user_text:
                return ChatResponse(
                    content=json.dumps({
                        "action": "complete",
                        "findings": "Research findings on FastAPI 2026 security: Found 3 CVE mitigations and TLS 1.3 requirement.",
                        "artifacts": [{"type": "source_link", "url": "https://fastapi.tiangolo.com"}],
                        "verification": {"factual_basis": "verified"},
                    }),
                    total_tokens=150,
                    prompt_tokens=100,
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

        # Analysis agent
        if "Analysis Sub-Agent" in system_text:
            return ChatResponse(
                content=json.dumps({
                    "action": "complete",
                    "findings": "Technical Analysis: Security posture is robust. No architectural contradictions detected.",
                    "artifacts": [{"type": "analysis_summary", "score": 95}],
                    "verification": {"consistency_score": "high"},
                }),
                total_tokens=120,
                prompt_tokens=80,
                completion_tokens=40,
                model="mock_model",
                provider="mock",
            )

        # Default synthesis
        return ChatResponse(
            content=json.dumps({
                "action": "complete",
                "findings": "Synthesized executive outcome.",
                "artifacts": [],
                "verification": {"status": "complete"},
            }),
            total_tokens=100,
            prompt_tokens=60,
            completion_tokens=40,
            model="mock_model",
            provider="mock",
        )

    async def generate_stream(self, request: ChatRequest):
        yield "mock stream"

    async def generate_structured(self, request: ChatRequest, response_model: Any) -> Any:
        return {}

    async def validate_credentials(self) -> bool:
        return True

    async def health_check(self) -> ProviderHealthStatus:
        return ProviderHealthStatus(
            provider_type="mock",
            is_available=True,
            status="healthy",
            message="Mock SubAgent Provider is operational",
        )

    async def list_models(self) -> List[ModelInfo]:
        return [
            ModelInfo(
                id="mock-model",
                name="Mock Model",
                provider="mock",
                context_window=8192,
                is_local=True,
            )
        ]



@pytest.mark.asyncio
async def test_subagent_dispatch_and_governed_tool_execution(db_session: AsyncSession):
    """Verify research sub-agent executes governed tool, observes result, and returns structured contract."""
    mock_prov = MockSubAgentProvider()
    ws_id = uuid.uuid4()
    task_id = uuid.uuid4()
    parent_run_id = uuid.uuid4()

    # Create task & parent run records
    task = Task(id=task_id, workspace_id=ws_id, title="Multi-Agent Task", goal="Research & analyze topic", status="running")
    parent_run = AgentRun(id=parent_run_id, task_id=task_id, workspace_id=ws_id, agent_type="master_supervisor", model_name="qwen2.5:7b-instruct-q4_K_M", status="running")
    db_session.add(task)
    db_session.add(parent_run)
    await db_session.commit()

    events = []
    def record_event(e: RuntimeEvent):
        events.append(e)

    # Dispatch Research Agent
    spec = SubAgentSpec(
        role="research_agent",
        goal="Gather latest FastAPI security standards",
        workspace_id=ws_id,
        parent_task_id=task_id,
        parent_run_id=parent_run_id,
        assigned_budget_tokens=10000,
        depth_level=1,
    )

    with patch("app.services.tools.web_search.execute_web_search") as mock_search:
        mock_search.return_value = {
            "query": "FastAPI 2026 security benchmarks",
            "total_results": 1,
            "results": [{"title": "FastAPI Security 2026", "url": "https://fastapi.tiangolo.com", "snippet": "Latest benchmarks"}],
            "status": "success",
        }

        result = await subagent_pool.dispatch_worker(
            db=db_session,
            spec=spec,
            provider=mock_prov,
            model_name="mock_model",
            actor_id="user_1",
            event_callback=record_event,
        )

        assert result.status == "completed"
        assert "FastAPI 2026 security" in result.findings
        assert len(result.artifacts) >= 1
        assert result.consumed_tokens > 0


@pytest.mark.asyncio
async def test_subagent_recursion_depth_limit(db_session: AsyncSession):
    """Verify that attempting to dispatch a sub-agent at depth > 2 is rejected."""
    mock_prov = MockSubAgentProvider()
    spec = SubAgentSpec(
        role="research_agent",
        goal="Test depth limit",
        workspace_id=uuid.uuid4(),
        parent_task_id=uuid.uuid4(),
        parent_run_id=uuid.uuid4(),
    )

    with pytest.raises(Exception) as exc:
        SubAgentSpec(
            role="research_agent",
            goal="Test depth limit",
            workspace_id=uuid.uuid4(),
            parent_task_id=uuid.uuid4(),
            parent_run_id=uuid.uuid4(),
            depth_level=3,  # Exceeds max depth of 2
        )
    assert "less than or equal to 2" in str(exc.value)


@pytest.mark.asyncio
async def test_subagent_tool_allowlist_enforcement(db_session: AsyncSession):
    """Verify that a sub-agent attempting to use an unpermitted tool is blocked."""
    class MaliciousToolSubAgentProvider(ModelProvider):
        async def generate_chat(self, request: ChatRequest) -> ChatResponse:
            return ChatResponse(
                content=json.dumps({
                    "action": "tool_call",
                    "tool_name": "delete_all_files",  # Unpermitted tool
                    "arguments": {"path": "/"},
                }),
                total_tokens=50,
                prompt_tokens=30,
                completion_tokens=20,
                model="mock_model",
                provider="mock",
            )
        async def generate_stream(self, request: ChatRequest):
            yield ""
        async def generate_structured(self, request: ChatRequest, response_model: Any) -> Any:
            return {}
        async def validate_credentials(self) -> bool:
            return True
        async def health_check(self) -> ProviderHealthStatus:
            return ProviderHealthStatus(provider_type="mock", is_available=True, status="healthy", message="ok")
        async def list_models(self) -> List[ModelInfo]:
            return [ModelInfo(id="mock", name="mock", provider="mock", context_window=8192, is_local=True)]


    mock_prov = MaliciousToolSubAgentProvider()
    ws_id = uuid.uuid4()
    task_id = uuid.uuid4()
    parent_run_id = uuid.uuid4()

    db_session.add(Task(id=task_id, workspace_id=ws_id, title="Test", goal="Test", status="running"))
    db_session.add(AgentRun(id=parent_run_id, task_id=task_id, workspace_id=ws_id, agent_type="master_supervisor", model_name="qwen", status="running"))
    await db_session.commit()

    spec = SubAgentSpec(
        role="analysis_agent",  # Analysis agent has no default tool permissions
        goal="Analyze data",
        workspace_id=ws_id,
        parent_task_id=task_id,
        parent_run_id=parent_run_id,
        permitted_tools=[],  # Empty allowlist
    )

    result = await subagent_pool.dispatch_worker(db=db_session, spec=spec, provider=mock_prov)
    assert result.status == "failed"
    assert "not permitted" in str(result.error)

