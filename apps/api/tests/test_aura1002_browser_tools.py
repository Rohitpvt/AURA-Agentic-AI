"""Unit and Functional Tests for AURA-1002 Governed Browser Interaction Tools."""

import asyncio
import time
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.errors import AuthorizationError, EntityNotFoundError, ValidationError
from app.db.models.tool import Tool
from app.schemas.tool import ToolExecutionRequest, ToolExecutionResponse
from app.services.browser.engine import PlaywrightBrowserEngine, browser_engine
from app.services.browser.governance import (
    ALLOWED_BROWSER_KEYS,
    MAX_BROWSER_ACTIONS_PER_TASK,
    BrowserActionBudgetManager,
    BrowserRiskClassifier,
    ObservationFreshnessStore,
    action_budget_manager,
    browser_risk_classifier,
    freshness_store,
)
from app.services.browser.models import AXTreeNode, PageObservation, TabInfo
from app.services.kill_switch import kill_switch
from app.services.tool_registry import BUILTIN_TOOLS, ToolRegistryService, tool_registry
from app.services.tools.browser_tools import (
    execute_browser_click,
    execute_browser_get_page_state,
    execute_browser_navigate,
    execute_browser_press_key,
    execute_browser_screenshot,
    execute_browser_scroll,
    execute_browser_select,
    execute_browser_tab_manage,
    execute_browser_type,
)


@pytest.fixture(autouse=True)
def reset_governance_stores():
    """Reset budget and observation stores before each test."""
    freshness_store.clear()
    action_budget_manager.clear()
    yield
    freshness_store.clear()
    action_budget_manager.clear()


@pytest.mark.asyncio
async def test_builtin_browser_tools_registration():
    """Verify all 9 browser interaction tools are registered in BUILTIN_TOOLS with schemas."""
    expected_tools = [
        "browser_navigate",
        "browser_get_page_state",
        "browser_screenshot",
        "browser_click",
        "browser_type",
        "browser_select",
        "browser_scroll",
        "browser_press_key",
        "browser_tab_manage",
    ]
    for tool_name in expected_tools:
        assert tool_name in BUILTIN_TOOLS, f"Tool '{tool_name}' missing from BUILTIN_TOOLS"
        spec = BUILTIN_TOOLS[tool_name]
        assert spec["category"] == "browser"
        assert "input_schema" in spec
        assert "output_schema" in spec
        assert "handler" in spec
        assert spec["timeout_seconds"] > 0
        assert spec["rate_limit_per_minute"] > 0


@pytest.mark.asyncio
async def test_browser_action_budget_enforcement():
    """Verify hard enforcement of 30 browser actions per task."""
    ws_id = uuid.uuid4()
    task_id = "task-budget-101"

    # Consume up to 30 actions
    for i in range(MAX_BROWSER_ACTIONS_PER_TASK):
        count = action_budget_manager.consume_action(ws_id, task_id, f"action_{i}")
        assert count == i + 1

    # 31st action must raise ValidationError
    with pytest.raises(ValidationError, match="Browser action budget exceeded"):
        action_budget_manager.consume_action(ws_id, task_id, "action_31")


@pytest.mark.asyncio
async def test_observation_freshness_ttl():
    """Verify observation freshness TTL expiration and element retrieval."""
    ws_id = uuid.uuid4()
    tab_id = "tab-freshness-01"

    node = AXTreeNode(
        node_id=1,
        role="button",
        name="Submit Form",
        bounding_box={"x": 100, "y": 100, "width": 80, "height": 30},
    )

    # 1. Fresh observation
    freshness_store.record_observation(
        workspace_id=ws_id,
        tab_id=tab_id,
        url="https://aura.local/form",
        title="Form",
        nodes=[node],
        ttl_seconds=1.0,
    )

    retrieved = freshness_store.get_element(ws_id, tab_id, 1)
    assert retrieved.name == "Submit Form"

    # 2. Non-existent node_id
    with pytest.raises(ValidationError, match="Element ID 99 does not exist"):
        freshness_store.get_element(ws_id, tab_id, 99)

    # 3. Observation expiration (simulate passage of time)
    obs = freshness_store.get_observation(ws_id, tab_id)
    assert obs is not None
    obs.captured_at = time.time() - 2.0  # 2.0s ago > 1.0s TTL

    with pytest.raises(ValidationError, match="Page observation is stale"):
        freshness_store.get_element(ws_id, tab_id, 1)


@pytest.mark.asyncio
async def test_browser_risk_classifier_semantics():
    """Verify deterministic semantic risk classification for varied browser actions."""
    ws_id = uuid.uuid4()
    tab_id = "tab-risk-01"

    safe_btn = AXTreeNode(node_id=1, role="button", name="Next Page")
    destructive_btn = AXTreeNode(node_id=2, role="button", name="Delete Account Forever")
    submit_btn = AXTreeNode(node_id=3, role="button", name="Submit Order")
    password_input = AXTreeNode(node_id=4, role="textbox", name="User Password")
    search_input = AXTreeNode(node_id=5, role="textbox", name="Search Query")

    freshness_store.record_observation(
        workspace_id=ws_id,
        tab_id=tab_id,
        url="https://aura.local/app",
        title="App",
        nodes=[safe_btn, destructive_btn, submit_btn, password_input, search_input],
    )

    # 1. Read-only navigation / observe
    assert browser_risk_classifier.evaluate_risk("browser_navigate", {"url": "https://example.com"}, ws_id) == "low"
    assert browser_risk_classifier.evaluate_risk("browser_get_page_state", {}, ws_id) == "low"
    assert browser_risk_classifier.evaluate_risk("browser_screenshot", {}, ws_id) == "low"

    # 2. Safe click vs Consequential vs Critical click
    assert browser_risk_classifier.evaluate_risk("browser_click", {"tab_id": tab_id, "element_id": 1}, ws_id) == "low"
    assert browser_risk_classifier.evaluate_risk("browser_click", {"tab_id": tab_id, "element_id": 3}, ws_id) == "high"
    assert browser_risk_classifier.evaluate_risk("browser_click", {"tab_id": tab_id, "element_id": 2}, ws_id) == "critical"

    # 3. Normal typing vs Sensitive password field
    assert browser_risk_classifier.evaluate_risk("browser_type", {"tab_id": tab_id, "element_id": 5, "text": "cats"}, ws_id) == "medium"
    assert browser_risk_classifier.evaluate_risk("browser_type", {"tab_id": tab_id, "element_id": 4, "text": "secret123"}, ws_id) == "high"


@pytest.mark.asyncio
async def test_browser_press_key_allowlist_and_forbidden():
    """Verify governed press_key rejects forbidden shortcuts and unsupported keys."""
    ws_id = uuid.uuid4()

    # Allowed keys
    assert browser_risk_classifier.evaluate_risk("browser_press_key", {"key": "Tab"}, ws_id) == "low"
    assert browser_risk_classifier.evaluate_risk("browser_press_key", {"key": "Enter"}, ws_id) == "medium"

    # Forbidden OS shortcuts
    with pytest.raises(ValidationError, match="Forbidden browser keyboard combination"):
        browser_risk_classifier.evaluate_risk("browser_press_key", {"key": "Control+Alt+Delete"}, ws_id)

    with pytest.raises(ValidationError, match="Forbidden browser keyboard combination"):
        browser_risk_classifier.evaluate_risk("browser_press_key", {"key": "Alt+F4"}, ws_id)

    # Unsupported key
    with pytest.raises(ValidationError, match="Disallowed browser key"):
        browser_risk_classifier.evaluate_risk("browser_press_key", {"key": "F12"}, ws_id)


@pytest.mark.asyncio
async def test_browser_type_sanitization_and_masking():
    """Verify NUL byte rejection, length bounds, and sensitive text masking."""
    ws_id = uuid.uuid4()
    tab_id = "tab-type-01"

    # 1. NUL byte rejection
    with pytest.raises(ValidationError, match="NUL"):
        browser_risk_classifier.evaluate_risk("browser_type", {"text": "hello\x00world"}, ws_id)

    # 2. Oversized text rejection (>2000 chars)
    with pytest.raises(ValidationError, match="exceeds maximum"):
        browser_risk_classifier.evaluate_risk("browser_type", {"text": "A" * 2001}, ws_id)

    # 3. Sensitive masking
    masked = browser_risk_classifier.mask_sensitive_value("MySecretPassword123!", role="password")
    assert "MySecretPassword123!" not in masked
    assert "REDACTED_PASSWORD" in masked
    assert "20 chars" in masked


@pytest.mark.asyncio
async def test_kill_switch_blocks_browser_tools(db_session):
    """Verify active kill switch immediately halts all browser tool executions."""
    ws_id = uuid.uuid4()
    kill_switch.activate(ws_id, triggered_by="test", reason="Security Breach")

    try:
        req = ToolExecutionRequest(
            workspace_id=ws_id,
            tool_name="browser_navigate",
            arguments={"url": "https://example.com"},
        )
        with pytest.raises(AuthorizationError, match="Emergency Kill Switch is active"):
            await tool_registry.execute_tool(db=db_session, request=req, actor_id="user1")

        # Click also blocked
        req_click = ToolExecutionRequest(
            workspace_id=ws_id,
            tool_name="browser_click",
            arguments={"element_id": 1},
        )
        with pytest.raises(AuthorizationError, match="Emergency Kill Switch is active"):
            await tool_registry.execute_tool(db=db_session, request=req_click, actor_id="user1")

    finally:
        kill_switch.deactivate(ws_id, reactivated_by="test")


@pytest.mark.asyncio
async def test_dynamic_hitl_approval_generation_for_high_risk(db_session):
    """Verify tool_registry suspends high-risk browser clicks and produces cryptographic approval tokens."""
    ws_id = uuid.uuid4()
    tab_id = "tab-hitl-01"

    btn = AXTreeNode(node_id=1, role="button", name="Delete Workspace Database")
    freshness_store.record_observation(
        workspace_id=ws_id,
        tab_id=tab_id,
        url="https://aura.local/settings",
        title="Settings",
        nodes=[btn],
    )

    req = ToolExecutionRequest(
        workspace_id=ws_id,
        tool_name="browser_click",
        arguments={"element_id": 1, "tab_id": tab_id},
    )

    resp: ToolExecutionResponse = await tool_registry.execute_tool(
        db=db_session,
        request=req,
        actor_id="agent-007",
        actor_type="agent",
    )

    assert resp.success is False
    assert resp.requires_hitl_approval is True
    assert resp.risk_level in ["high", "critical"]
    assert resp.approval_token is not None
    assert len(resp.approval_token) > 32
    assert "Human-in-the-Loop approval required" in resp.error


@pytest.mark.asyncio
async def test_browser_disabled_element_rejection():
    """Verify clicking or typing into disabled element raises ValidationError."""
    ws_id = uuid.uuid4()
    tab_id = "tab-disabled-01"

    disabled_btn = AXTreeNode(node_id=1, role="button", name="Inactive Action", disabled=True)
    freshness_store.record_observation(
        workspace_id=ws_id,
        tab_id=tab_id,
        url="https://aura.local/page",
        title="Page",
        nodes=[disabled_btn],
    )

    with pytest.raises(ValidationError, match="is disabled and cannot be clicked"):
        await execute_browser_click(workspace_id=ws_id, element_id=1, tab_id=tab_id)

    with pytest.raises(ValidationError, match="is disabled and cannot receive text input"):
        await execute_browser_type(workspace_id=ws_id, element_id=1, text="test", tab_id=tab_id)
