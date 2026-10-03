"""Comprehensive Tests for Local OpenTelemetry Distributed Tracing & Local Exporters (AURA-505).

Verification Categories:
1. Deterministic local/offline span creation, W3C traceparent propagation, and parent-child hierarchy.
2. Async context propagation without cross-request contamination.
3. Universal secret redaction across normal attributes, error paths, and exception messages.
4. Telemetry inspection API security: authentication, RBAC, and strict workspace tenancy isolation.
5. Cross-workspace trace isolation (Workspace A cannot view or enumerate Workspace B traces).
6. Fail-safe exporter failure isolation (broken exporter never breaks agent execution or audit).
7. Trace-to-Audit correlation and cryptographic audit ledger independence.
8. Bounded in-memory ring buffer (FIFO capacity enforcement).
9. Full Real Runtime Path across 3 Representative Tiers (Low-risk, Governed/Sandboxed, HITL-required).
10. Measured performance benchmark on host hardware.
"""

import asyncio
import time
import uuid
from typing import Any, Dict, List, Optional
from unittest.mock import patch
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.redaction import secret_redactor
from opentelemetry.sdk.trace import TracerProvider
from app.core.telemetry import (
    BoundedInMemorySpanExporter,
    SafeTelemetrySanitizer,
    TelemetryManager,
    telemetry_manager,
)
from app.db.models.tool import Tool
from app.db.models.workspace import Workspace
from app.schemas.tool import ToolExecutionRequest, ToolRegisterRequest
from app.services.audit_service import AuditLedgerService, audit_service
from app.services.providers.base import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ModelInfo,
    ModelProvider,
    ProviderHealthStatus,
)
from app.services.tool_registry import tool_registry


@pytest.fixture(autouse=True)
def clean_telemetry():
    """Clear in-memory span buffer before and after each test."""
    telemetry_manager.clear_in_memory_spans()
    yield
    telemetry_manager.clear_in_memory_spans()


# Helper to register an authenticated user and provision a personal workspace
async def create_authenticated_user_and_workspace(client: AsyncClient, name_prefix: str = "user"):
    uid = uuid.uuid4().hex[:8]
    reg_res = await client.post(
        "/api/v1/auth/register",
        json={
            "email": f"{name_prefix}_{uid}@example.com",
            "username": f"{name_prefix}_{uid}",
            "password": "SecurePassword123!",
            "full_name": f"Test Operator {uid}",
        },
    )
    assert reg_res.status_code == 201
    auth_token = reg_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {auth_token}"}

    ws_res = await client.get("/api/v1/workspaces", headers=headers)
    assert ws_res.status_code == 200
    workspaces = ws_res.json()
    assert len(workspaces) > 0
    ws_id = uuid.UUID(workspaces[0]["id"])

    return headers, ws_id


# ==============================================================================
# 1. DETERMINISTIC LOCAL / OFFLINE TESTS
# ==============================================================================

def test_span_creation_and_parent_child_hierarchy():
    """Test creating parent and child spans and verifying hierarchy in local in-memory exporter."""
    with telemetry_manager.start_span("parent_operation", span_type="workflow") as parent_span:
        parent_trace_id = telemetry_manager.get_current_trace_id()
        parent_span_id = telemetry_manager.get_current_span_id()
        assert parent_trace_id is not None
        assert parent_span_id is not None

        with telemetry_manager.start_span("child_operation", span_type="tool") as child_span:
            child_trace_id = telemetry_manager.get_current_trace_id()
            child_span_id = telemetry_manager.get_current_span_id()
            assert child_trace_id == parent_trace_id
            assert child_span_id != parent_span_id

    spans = telemetry_manager.get_in_memory_spans()
    assert len(spans) == 2

    child = next(s for s in spans if s.name == "child_operation")
    parent = next(s for s in spans if s.name == "parent_operation")

    assert child.parent.span_id == parent.context.span_id
    assert child.context.trace_id == parent.context.trace_id
    assert child.attributes.get("aura.span_type") == "tool"
    assert parent.attributes.get("aura.span_type") == "workflow"


def test_w3c_traceparent_injection_and_extraction():
    """Test standard W3C traceparent context injection and extraction."""
    headers = {}
    with telemetry_manager.start_span("root_ingress", span_type="http.server"):
        telemetry_manager.inject_trace_context(headers)
        active_trace_id = telemetry_manager.get_current_trace_id()

    assert "traceparent" in headers
    parts = headers["traceparent"].split("-")
    assert len(parts) == 4
    assert parts[0] == "00"
    assert parts[1] == active_trace_id

    extracted_ctx = telemetry_manager.extract_trace_context(headers)
    with telemetry_manager.start_span("downstream_service", parent_context=extracted_ctx):
        resumed_trace_id = telemetry_manager.get_current_trace_id()
        assert resumed_trace_id == active_trace_id


@pytest.mark.asyncio
async def test_async_context_propagation_and_isolation():
    """Test async context propagation across multiple concurrent tasks without cross-contamination."""
    async def worker_task(task_num: int):
        with telemetry_manager.start_span(f"worker_{task_num}", span_type="worker"):
            trace_id = telemetry_manager.get_current_trace_id()
            await asyncio.sleep(0.01)
            with telemetry_manager.start_span(f"worker_{task_num}_step", span_type="step"):
                assert telemetry_manager.get_current_trace_id() == trace_id
            return trace_id

    trace_ids = await asyncio.gather(*[worker_task(i) for i in range(5)])
    assert len(set(trace_ids)) == 5

    spans = telemetry_manager.get_in_memory_spans()
    assert len(spans) == 10


def test_telemetry_secret_redaction_and_bounded_attributes():
    """Test that secrets, tokens, and overly long inputs are sanitized in telemetry spans."""
    raw_attrs = {
        "api_key": "AIzaSyD-Secret123456789012345",
        "authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.e30.secret",
        "telegram_bot_token": "8985234259:AAG9bxpUHxPGehxp82eqk4EGVfd6sVu0czE",
        "user_query": "Normal user query text",
        "payload_dict": {"secret_token": "hidden", "public_id": "safe_123"},
        "long_field": "A" * 500,
    }

    sanitized = SafeTelemetrySanitizer.sanitize_attributes(raw_attrs)
    assert sanitized["api_key"] == "[REDACTED]"
    assert sanitized["authorization"] == "[REDACTED]"
    assert sanitized["telegram_bot_token"] == "[REDACTED]"
    assert sanitized["user_query"] == "Normal user query text"
    assert "public_id" in sanitized["payload_dict"]
    assert "hidden" not in sanitized["payload_dict"]
    assert len(sanitized["long_field"]) <= settings.OTEL_MAX_ATTR_LENGTH


def test_error_path_exception_message_redaction():
    """Test that secrets in exception messages are redacted before reaching span status."""
    try:
        with telemetry_manager.start_span("failing_span"):
            raise ValueError("Connection failed with Gemini key AIzaSyD-SecretKey1234567890")
    except ValueError:
        pass

    spans = telemetry_manager.get_in_memory_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.status.status_code.name == "ERROR"
    # Exception description must have secret redacted
    assert "AIzaSy" not in str(span.status.description)
    assert "[REDACTED_SECRET]" in str(span.status.description) or "[REDACTED" in str(span.status.description)


def test_bounded_memory_exporter_capacity():
    """Test that BoundedInMemorySpanExporter enforces FIFO eviction when exceeding capacity."""
    exporter = BoundedInMemorySpanExporter(max_spans=100)
    provider = TracerProvider()
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    test_tracer = provider.get_tracer("test_bounded")

    # Generate 150 spans
    for i in range(150):
        with test_tracer.start_as_current_span(f"span_{i}"):
            pass

    finished = exporter.get_finished_spans()
    assert len(finished) == 100
    # Oldest 50 spans (0-49) must have been evicted; remaining are 50-149
    assert finished[0].name == "span_50"
    assert finished[-1].name == "span_149"


def test_fail_safe_exporter_isolation():
    """Test that an exporter failure never raises exceptions or alters runtime behavior."""
    mgr = TelemetryManager()
    with patch.object(mgr._in_memory_exporter, "export", side_effect=RuntimeError("Disk full / pipe broken")):
        try:
            with mgr.start_span("resilient_span"):
                pass
        except Exception as ex:
            pytest.fail(f"Telemetry exporter failure leaked to caller: {ex}")


@pytest.mark.asyncio
async def test_audit_log_trace_correlation_and_independence(db_session: AsyncSession):
    """Test bidirectional trace_id correlation and verify audit ledger remains valid when telemetry is cleared/disabled."""
    audit_svc = AuditLedgerService()
    ws_id = uuid.uuid4()

    with telemetry_manager.start_span("governed_action", span_type="governance"):
        active_trace_id = telemetry_manager.get_current_trace_id()
        assert active_trace_id is not None

        log_entry = await audit_svc.record_event(
            db=db_session,
            workspace_id=ws_id,
            actor_type="user",
            actor_id="user_123",
            action="policy.evaluate",
            resource_type="workspace",
            resource_id=str(ws_id),
            details={"policy_name": "zero_cost_lock"},
        )

        assert log_entry.details.get("trace_id") == active_trace_id

    # 1. Cryptographic ledger verification
    verify_res1 = await audit_svc.verify_ledger(db_session, ws_id)
    assert verify_res1["is_valid"] is True

    # 2. Clearing in-memory telemetry buffer must NOT affect audit validity
    telemetry_manager.clear_in_memory_spans()
    verify_res2 = await audit_svc.verify_ledger(db_session, ws_id)
    assert verify_res2["is_valid"] is True


# ==============================================================================
# 2. TELEMETRY INSPECTION API SECURITY & TENANCY TESTS
# ==============================================================================

@pytest.mark.asyncio
async def test_telemetry_endpoints_authentication_required(async_client: AsyncClient):
    """Test that all telemetry inspection endpoints reject unauthenticated requests with 401."""
    fake_ws = uuid.uuid4()

    res1 = await async_client.get("/api/v1/telemetry/status")
    assert res1.status_code == 401

    res2 = await async_client.get(f"/api/v1/telemetry/spans?workspace_id={fake_ws}")
    assert res2.status_code == 401

    res3 = await async_client.get(f"/api/v1/telemetry/traces/00000000000000000000000000000001?workspace_id={fake_ws}")
    assert res3.status_code == 401

    res4 = await async_client.post(f"/api/v1/telemetry/clear?workspace_id={fake_ws}")
    assert res4.status_code == 401


@pytest.mark.asyncio
async def test_cross_workspace_telemetry_isolation(async_client: AsyncClient):
    """Test that Workspace B cannot view, query, enumerate, or clear Workspace A's telemetry."""
    # 1. Create User A and User B with isolated workspaces
    headers_a, ws_a = await create_authenticated_user_and_workspace(async_client, "alice")
    headers_b, ws_b = await create_authenticated_user_and_workspace(async_client, "bob")

    # 2. Generate spans in Workspace A
    with telemetry_manager.start_span("workspace_a_task", attributes={"aura.workspace_id": str(ws_a)}):
        trace_a = telemetry_manager.get_current_trace_id()

    # 3. User A can list and retrieve trace_a
    res_a = await async_client.get(f"/api/v1/telemetry/spans?workspace_id={ws_a}", headers=headers_a)
    assert res_a.status_code == 200
    assert any(s["trace_id"] == trace_a for s in res_a.json()["spans"])

    res_trace_a = await async_client.get(f"/api/v1/telemetry/traces/{trace_a}?workspace_id={ws_a}", headers=headers_a)
    assert res_trace_a.status_code == 200
    assert res_trace_a.json()["trace_id"] == trace_a

    # 4. User B querying Workspace A directly is blocked with 403 Forbidden / 404
    res_b_illegal = await async_client.get(f"/api/v1/telemetry/spans?workspace_id={ws_a}", headers=headers_b)
    assert res_b_illegal.status_code in [403, 404]

    # 5. User B querying their own workspace (ws_b) cannot see Workspace A's spans
    res_b_legal = await async_client.get(f"/api/v1/telemetry/spans?workspace_id={ws_b}", headers=headers_b)
    assert res_b_legal.status_code == 200
    assert not any(s["trace_id"] == trace_a for s in res_b_legal.json()["spans"])

    # 6. User B attempting to fetch trace_a under ws_b returns 404
    res_b_trace = await async_client.get(f"/api/v1/telemetry/traces/{trace_a}?workspace_id={ws_b}", headers=headers_b)
    assert res_b_trace.status_code == 404

    # 7. User B clearing ws_b does NOT erase Workspace A's spans
    clear_b = await async_client.post(f"/api/v1/telemetry/clear?workspace_id={ws_b}", headers=headers_b)
    assert clear_b.status_code == 200

    res_a_check = await async_client.get(f"/api/v1/telemetry/spans?workspace_id={ws_a}", headers=headers_a)
    assert res_a_check.status_code == 200
    assert any(s["trace_id"] == trace_a for s in res_a_check.json()["spans"])


# ==============================================================================
# 3. REAL AURA RUNTIME INTEGRATION TESTS ACROSS 3 REPRESENTATIVE TIERS
# ==============================================================================

@pytest.mark.asyncio
async def test_real_runtime_low_risk_tool_execution(async_client: AsyncClient, db_session: AsyncSession):
    """Tier 1: Low-Risk Governed Execution (web_search).
    Real Ingress -> Real ToolRegistry -> Real Policy Check -> Real Search -> Real Audit -> Real Exporter.
    """
    headers, ws_id = await create_authenticated_user_and_workspace(async_client, "low_risk_user")

    exec_res = await async_client.post(
        "/api/v1/tools/execute",
        headers=headers,
        json={
            "workspace_id": str(ws_id),
            "tool_name": "web_search",
            "arguments": {"query": "OpenTelemetry Python distributed tracing"},
        },
    )
    assert exec_res.status_code == 200
    trace_id = exec_res.headers.get("x-trace-id")
    assert trace_id is not None

    # Verify spans in Telemetry API
    telemetry_res = await async_client.get(f"/api/v1/telemetry/traces/{trace_id}?workspace_id={ws_id}", headers=headers)
    assert telemetry_res.status_code == 200
    trace_data = telemetry_res.json()
    span_names = [s["name"] for s in trace_data["spans"]]
    assert any("http.post" in name for name in span_names)
    assert any("tool.execute" in name for name in span_names)


@pytest.mark.asyncio
async def test_real_runtime_governed_sandboxed_tool_execution(async_client: AsyncClient, db_session: AsyncSession):
    """Tier 2: Medium/Governed Sandboxed Execution (web_extract).
    Real Ingress -> Real ToolRegistry -> Real Policy Check -> Real Playwright Extractor -> Real Audit -> Real Exporter.
    """
    headers, ws_id = await create_authenticated_user_and_workspace(async_client, "sandbox_user")

    exec_res = await async_client.post(
        "/api/v1/tools/execute",
        headers=headers,
        json={
            "workspace_id": str(ws_id),
            "tool_name": "web_extract",
            "arguments": {"url": "https://example.com", "extract_mode": "markdown"},
        },
    )
    assert exec_res.status_code == 200
    trace_id = exec_res.headers.get("x-trace-id")
    assert trace_id is not None

    telemetry_res = await async_client.get(f"/api/v1/telemetry/traces/{trace_id}?workspace_id={ws_id}", headers=headers)
    assert telemetry_res.status_code == 200
    trace_data = telemetry_res.json()
    span_names = [s["name"] for s in trace_data["spans"]]
    assert any("tool.execute web_extract" in name for name in span_names)


@pytest.mark.asyncio
async def test_real_runtime_hitl_required_tool_suspension(async_client: AsyncClient, db_session: AsyncSession):
    """Tier 3: High-Risk HITL-Required Execution Gate.
    Real Ingress -> Real ToolRegistry -> Real Risk Engine -> HMAC-SHA256 Token -> Execution Suspended -> Real Exporter.
    """
    headers, ws_id = await create_authenticated_user_and_workspace(async_client, "hitl_user")

    # Register a high-risk tool requiring approval
    reg_tool = await async_client.post(
        "/api/v1/tools",
        headers=headers,
        json={
            "workspace_id": str(ws_id),
            "name": "system_wipe_test",
            "display_name": "System Wipe Tool",
            "description": "High risk destructive test tool",
            "category": "system",
            "risk_level": "high",
            "requires_approval": True,
            "input_schema": {"type": "object", "properties": {"target": {"type": "string"}}},
        },
    )
    assert reg_tool.status_code == 201

    # Execute high-risk tool -> must suspend with HITL token
    exec_res = await async_client.post(
        "/api/v1/tools/execute",
        headers=headers,
        json={
            "workspace_id": str(ws_id),
            "tool_name": "system_wipe_test",
            "arguments": {"target": "/tmp/test"},
        },
    )
    assert exec_res.status_code == 200
    data = exec_res.json()
    assert data["requires_hitl_approval"] is True
    assert data["approval_token"] is not None
    assert data["success"] is False


class MockAgentModelProvider(ModelProvider):
    """Deterministic Model Provider for simulating Agent Planner and Tool reasoning turns."""

    async def generate_chat(self, request: ChatRequest) -> ChatResponse:
        prompt_text = " ".join([m.content for m in request.messages])

        if "Supervisor Planner" in prompt_text or "Decompose the following" in prompt_text:
            content = """{
              "goal": "Research distributed tracing in AURA agent runtime",
              "summary": "OTel agent runtime trace plan",
              "estimated_complexity": "low",
              "steps": [
                {
                  "step_number": 1,
                  "title": "Search OTel Trace Patterns",
                  "description": "Query web for OpenTelemetry Python distributed tracing patterns",
                  "dependencies": [],
                  "suggested_tool": "web_search",
                  "tool_input": {"query": "OpenTelemetry Python distributed tracing", "max_results": 2},
                  "verification_criteria": "Search results retrieved"
                },
                {
                  "step_number": 2,
                  "title": "Synthesize Trace Findings",
                  "description": "Synthesize OTel findings for agent runtime",
                  "dependencies": [1],
                  "suggested_tool": null,
                  "tool_input": null,
                  "verification_criteria": "Synthesis complete"
                }
              ]
            }"""
        elif "CURRENT STEP" in prompt_text:
            if "observation" in prompt_text.lower():
                content = '{"action": "complete", "content": "OpenTelemetry context propagation verified end-to-end across agent runtime and tool bridge."}'
            else:
                content = '{"action": "tool_call", "tool_name": "web_search", "arguments": {"query": "OpenTelemetry Python distributed tracing"}}'
        else:
            content = '{"action": "complete", "content": "Done"}'

        return ChatResponse(
            content=content,
            model=request.model,
            provider="mock",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
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
            message="Mock Provider is operational",
        )

    async def list_models(self) -> List[ModelInfo]:
        return []


@pytest.mark.asyncio
async def test_real_agent_runtime_to_tool_bridge_trace_propagation(async_client: AsyncClient, db_session: AsyncSession):
    """Canonical Agent-Runtime Integration:
    Ingress (POST /api/v1/agent/run) ->
    AgentRuntime (AgentRuntimeEngine.submit_goal) ->
    AgentToolBridge (AgentToolBridge.execute_governed_tool) ->
    ToolRegistryService (ToolRegistryService.execute_tool) ->
    Policy/Risk (evaluate_risk) ->
    Tool Execution (web_search) ->
    Audit Ledger (SHA-256 with trace_id) ->
    Local Exporter (BoundedInMemorySpanExporter).
    """
    headers, ws_id = await create_authenticated_user_and_workspace(async_client, "agent_tracer")

    mock_provider = MockAgentModelProvider()

    with patch("app.services.providers.router.ModelRouter.get_provider", return_value=mock_provider):
        # 1. Real Ingress invoking real AgentRuntimeEngine
        res = await async_client.post(
            "/api/v1/agent/run",
            headers=headers,
            json={
                "workspace_id": str(ws_id),
                "goal": "Research distributed tracing in AURA agent runtime",
                "title": "Agent OTel Trace Verification",
                "priority": "medium",
            },
        )
        assert res.status_code == 200
        run_data = res.json()
        assert run_data["status"] == "completed"
        assert run_data["final_result"] is not None

        # 2. Extract Ingress Trace ID
        trace_id = res.headers.get("x-trace-id")
        assert trace_id is not None

        # 3. Retrieve Spans from Local Exporter via Secured Telemetry API
        telemetry_res = await async_client.get(
            f"/api/v1/telemetry/traces/{trace_id}?workspace_id={ws_id}",
            headers=headers,
        )
        assert telemetry_res.status_code == 200
        trace_payload = telemetry_res.json()
        spans = trace_payload["spans"]
        assert len(spans) >= 2

        # Verify all spans in the execution tree share the same trace_id
        for span in spans:
            assert span["trace_id"] == trace_id

        span_names = [s["name"] for s in spans]
        # Must contain the HTTP ingress span and the ToolRegistry execution span invoked via AgentToolBridge
        assert any("http.post" in name for name in span_names)
        assert any("tool.execute" in name for name in span_names)

        # 4. Verify Cryptographic SHA-256 Audit Record captured trace_id
        from app.db.models.audit import AuditLog
        from sqlalchemy import select
        audit_res = await db_session.execute(select(AuditLog).where(AuditLog.workspace_id == ws_id))
        audit_records = audit_res.scalars().all()
        tool_audit_entry = next((a for a in audit_records if "web_search" in str(a.action) or "tool" in str(a.resource_type)), None)
        assert tool_audit_entry is not None
        assert tool_audit_entry.details.get("trace_id") == trace_id

        # 5. Verify Cryptographic Hash Chain integrity
        await db_session.rollback()  # Refresh session view
        verify_res = await audit_service.verify_ledger(db_session, ws_id)
        assert verify_res["is_valid"] is True


# ==============================================================================
# 4. MEASURED PERFORMANCE BENCHMARK
# ==============================================================================

def test_telemetry_span_performance_benchmark():
    """Benchmark: Measures span creation, context attachment, attribute sanitization, and recording latency."""
    # Warm-up (100 iterations)
    for _ in range(100):
        with telemetry_manager.start_span("warmup", attributes={"key": "value"}):
            pass

    # Timed Benchmark (1,000 iterations)
    iterations = 1000
    start_time = time.perf_counter()
    for i in range(iterations):
        with telemetry_manager.start_span(
            name="benchmark_span",
            span_type="benchmark",
            attributes={
                "iteration": i,
                "user": "test_operator",
                "api_key": "AIzaSyD-SecretKeyToRedact123456",
            },
        ):
            pass
    total_time_s = time.perf_counter() - start_time
    avg_latency_ms = (total_time_s / iterations) * 1000.0

    print(f"\n[BENCHMARK] 1,000 Spans Executed in {total_time_s:.4f}s | Avg Latency: {avg_latency_ms:.4f} ms/span")
    # Must be bounded and fast (< 1.0 ms per span on host hardware)
    assert avg_latency_ms < 1.0
