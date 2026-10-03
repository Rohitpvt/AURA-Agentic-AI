"""Comprehensive integration tests for AURA-403 Telegram Bot Long-Polling."""

import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import compute_sha256_hash, encrypt_secret
from app.db.models.approval import ApprovalRequest
from app.db.models.task import Task
from app.db.models.telegram import TelegramIntegration, TelegramPairing
from app.db.models.workspace import Workspace
from app.schemas.telegram import TelegramIntegrationCreateRequest, TelegramPairingGenerateRequest
from app.services.approval_service import approval_service
from app.services.integrations.telegram_service import telegram_service
from app.services.kill_switch import kill_switch


# ==============================================================================
# 1. Bot Token Validation Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_telegram_bot_token_validation():
    """Verify Telegram getMe validation accepts valid tokens and rejects invalid ones."""
    # 1. Valid Token Mock
    valid_resp = httpx.Response(
        200,
        json={"ok": True, "result": {"id": 123456789, "is_bot": True, "first_name": "AURA Bot", "username": "aura_test_bot"}},
        request=httpx.Request("GET", "https://api.telegram.org/bot123/getMe"),
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = valid_resp
        val = await telegram_service.validate_bot_token("123456789:ABCdefGHIjklMNOpqrsTUVwxyz_valid")
        assert val.is_valid is True
        assert val.bot_username == "aura_test_bot"
        assert val.bot_id == "123456789"

    # 2. Invalid Token Mock
    invalid_resp = httpx.Response(
        401,
        json={"ok": False, "error_code": 401, "description": "Unauthorized"},
        request=httpx.Request("GET", "https://api.telegram.org/bot123/getMe"),
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = invalid_resp
        val_bad = await telegram_service.validate_bot_token("invalid_bot_token")
        assert val_bad.is_valid is False
        assert "rejected token" in (val_bad.error_message or "")


# ==============================================================================
# 2. Pairing Lifecycle & Single-Use Invalidation Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_telegram_pairing_flow_and_token_invalidation(db_session: AsyncSession):
    """Verify one-time pairing token generation, /start <token> binding, and revocation."""
    ws = Workspace(name="Pairing WS", slug=f"tg-pair-{uuid.uuid4().hex[:6]}")
    db_session.add(ws)
    await db_session.flush()

    integration = TelegramIntegration(
        workspace_id=ws.id,
        display_name="Pairing Test Bot",
        bot_token_ciphertext=encrypt_secret("valid_token_123"),
        bot_username="aura_pair_bot",
        is_active=True,
    )
    db_session.add(integration)
    await db_session.flush()

    # Step 1: Generate 15-minute pairing token
    token_resp = await telegram_service.generate_pairing_token(
        db=db_session,
        integration_id=integration.id,
        workspace_id=ws.id,
        ttl_seconds=900,
    )
    raw_token = token_resp.pairing_token
    assert raw_token.startswith("aurapair_")

    # Step 2: Unpaired user sends /start with valid token -> Pairing succeeds
    success, msg = await telegram_service.resolve_pairing_token(
        db=db_session,
        integration=integration,
        chat_id="100200300",
        user_id="555",
        username="operator_alice",
        raw_token=raw_token,
    )
    assert success is True
    assert "Pairing successful" in msg

    # Verify pairing record in DB is now active and token hash is cleared
    stmt = select(TelegramPairing).where(
        TelegramPairing.integration_id == integration.id,
        TelegramPairing.telegram_chat_id == "100200300",
    )
    pairing = (await db_session.execute(stmt)).scalar_one_or_none()
    assert pairing is not None
    assert pairing.is_active is True
    assert pairing.telegram_username == "operator_alice"
    assert pairing.pairing_token_hash is None  # Single-use revocation

    # Step 3: Attempting to reuse the same token must fail
    success_reuse, msg_reuse = await telegram_service.resolve_pairing_token(
        db=db_session,
        integration=integration,
        chat_id="999888777",
        user_id="777",
        username="attacker_bob",
        raw_token=raw_token,
    )
    assert success_reuse is False
    assert "Invalid or previously used" in msg_reuse

    # Step 4: Expired token test
    tok_exp = await telegram_service.generate_pairing_token(
        db=db_session,
        integration_id=integration.id,
        workspace_id=ws.id,
        ttl_seconds=-10,  # Expired immediately
    )
    success_exp, msg_exp = await telegram_service.resolve_pairing_token(
        db=db_session,
        integration=integration,
        chat_id="444333222",
        user_id="222",
        username="late_user",
        raw_token=tok_exp.pairing_token,
    )
    assert success_exp is False
    assert "expired" in msg_exp


# ==============================================================================
# 3. Chat Authorization & Command Handling Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_telegram_unauthorized_chat_rejection(db_session: AsyncSession):
    """Verify unpaired chats cannot execute commands or query status."""
    ws = Workspace(name="Auth WS", slug=f"tg-auth-{uuid.uuid4().hex[:6]}")
    db_session.add(ws)
    await db_session.flush()

    integration = TelegramIntegration(
        workspace_id=ws.id,
        display_name="Auth Test Bot",
        bot_token_ciphertext=encrypt_secret("valid_token_123"),
        bot_username="aura_auth_bot",
        is_active=True,
    )
    db_session.add(integration)
    await db_session.flush()

    # 1. Unpaired chat sends /status
    res_status = await telegram_service.handle_command(
        db=db_session,
        integration=integration,
        chat_id="unauthorized_chat_999",
        user_id=None,
        username="stranger",
        raw_text="/status",
        update_id=1,
    )
    assert "Unauthorized chat" in res_status

    # 2. Unpaired chat sends /goal
    res_goal = await telegram_service.handle_command(
        db=db_session,
        integration=integration,
        chat_id="unauthorized_chat_999",
        user_id=None,
        username="stranger",
        raw_text="/goal do something malicious",
        update_id=2,
    )
    assert "Unauthorized chat" in res_goal

    # 3. Unpaired chat sends plain /start
    res_start = await telegram_service.handle_command(
        db=db_session,
        integration=integration,
        chat_id="unauthorized_chat_999",
        user_id=None,
        username="stranger",
        raw_text="/start",
        update_id=3,
    )
    assert "Welcome to AURA" in res_start
    assert "not currently paired" in res_start


@pytest.mark.asyncio
async def test_telegram_goal_command_and_governance(db_session: AsyncSession):
    """Verify /goal command creates a governed task bounded to Autonomy L4 with untrusted framing."""
    ws = Workspace(name="Goal WS", slug=f"tg-goal-{uuid.uuid4().hex[:6]}")
    db_session.add(ws)
    await db_session.flush()

    integration = TelegramIntegration(
        workspace_id=ws.id,
        display_name="Goal Bot",
        bot_token_ciphertext=encrypt_secret("valid_token_123"),
        is_active=True,
    )
    db_session.add(integration)
    await db_session.flush()

    # Pair Chat
    pairing = TelegramPairing(
        workspace_id=ws.id,
        integration_id=integration.id,
        telegram_chat_id="paired_chat_101",
        telegram_username="operator_dan",
        is_active=True,
        paired_at=datetime.now(timezone.utc),
    )
    db_session.add(pairing)
    await db_session.flush()

    # Execute /goal
    goal_res = await telegram_service.handle_command(
        db=db_session,
        integration=integration,
        chat_id="paired_chat_101",
        user_id="101",
        username="operator_dan",
        raw_text="/goal Research PostgreSQL 17 logical replication enhancements",
        update_id=42,
    )
    assert "Governed Task Dispatched" in goal_res
    assert "Level 4" in goal_res

    # Invariant: Verify task created in database
    stmt = select(Task).where(Task.workspace_id == ws.id, Task.idempotency_key == f"tg_{integration.id}_42")
    task = (await db_session.execute(stmt)).scalar_one_or_none()
    assert task is not None
    assert task.autonomy_level == 4
    assert task.timeout_seconds == 300
    assert task.budget_max_tokens == 4000
    assert "[SYSTEM: UNTRUSTED TELEGRAM INGRESS EVENT]" in task.goal
    assert "UNTRUSTED_EXTERNAL_INPUT (is_untrusted_content = True)" in task.goal


@pytest.mark.asyncio
async def test_telegram_status_command(db_session: AsyncSession):
    """Verify /status command returns safe workspace summaries."""
    ws = Workspace(name="Status WS", slug=f"tg-status-{uuid.uuid4().hex[:6]}")
    db_session.add(ws)
    await db_session.flush()

    integration = TelegramIntegration(
        workspace_id=ws.id,
        display_name="Status Bot",
        bot_token_ciphertext=encrypt_secret("valid_token_123"),
        is_active=True,
    )
    db_session.add(integration)
    await db_session.flush()

    pairing = TelegramPairing(
        workspace_id=ws.id,
        integration_id=integration.id,
        telegram_chat_id="chat_status_202",
        is_active=True,
    )
    db_session.add(pairing)

    # Create dummy task in workspace
    dummy_task = Task(
        workspace_id=ws.id,
        title="Sample Background Task",
        goal="Run checks",
        status="running",
    )
    db_session.add(dummy_task)
    await db_session.flush()

    status_res = await telegram_service.handle_command(
        db=db_session,
        integration=integration,
        chat_id="chat_status_202",
        user_id="202",
        username="operator",
        raw_text="/status",
        update_id=10,
    )
    assert "AURA Workspace Status" in status_res
    assert "Sample Background Task" in status_res
    assert "Emergency Kill Switch" in status_res


@pytest.mark.asyncio
async def test_telegram_cancel_command_workspace_isolation(db_session: AsyncSession):
    """Verify /cancel command cancels task in paired workspace and rejects cross-workspace task cancellation."""
    ws1 = Workspace(name="WS 1", slug=f"tg-c1-{uuid.uuid4().hex[:6]}")
    ws2 = Workspace(name="WS 2", slug=f"tg-c2-{uuid.uuid4().hex[:6]}")
    db_session.add_all([ws1, ws2])
    await db_session.flush()

    integration1 = TelegramIntegration(workspace_id=ws1.id, bot_token_ciphertext=encrypt_secret("t1"), is_active=True)
    db_session.add(integration1)
    await db_session.flush()

    pairing1 = TelegramPairing(workspace_id=ws1.id, integration_id=integration1.id, telegram_chat_id="chat_c1", is_active=True)
    db_session.add(pairing1)

    task_ws1 = Task(workspace_id=ws1.id, title="WS1 Task", goal="Goal 1", status="running")
    task_ws2 = Task(workspace_id=ws2.id, title="WS2 Task", goal="Goal 2", status="running")
    db_session.add_all([task_ws1, task_ws2])
    await db_session.flush()

    # 1. Cancel own task -> Success
    res_cancel_own = await telegram_service.handle_command(
        db=db_session,
        integration=integration1,
        chat_id="chat_c1",
        user_id="1",
        username="op",
        raw_text=f"/cancel {task_ws1.id}",
        update_id=1,
    )
    assert "has been cancelled" in res_cancel_own
    assert task_ws1.status == "cancelled"

    # 2. Attempt to cancel task from another workspace -> Rejection
    res_cancel_other = await telegram_service.handle_command(
        db=db_session,
        integration=integration1,
        chat_id="chat_c1",
        user_id="1",
        username="op",
        raw_text=f"/cancel {task_ws2.id}",
        update_id=2,
    )
    assert "not found in this workspace" in res_cancel_other
    assert task_ws2.status == "running"  # Invariant: WS2 task unaffected


@pytest.mark.asyncio
async def test_telegram_approve_command_hitl_resumption(db_session: AsyncSession):
    """Verify /approve command resolves pending HITL request and resumes task."""
    ws = Workspace(name="Approve WS", slug=f"tg-app-{uuid.uuid4().hex[:6]}")
    db_session.add(ws)
    await db_session.flush()

    integration = TelegramIntegration(workspace_id=ws.id, bot_token_ciphertext=encrypt_secret("tok"), is_active=True)
    db_session.add(integration)
    await db_session.flush()

    pairing = TelegramPairing(workspace_id=ws.id, integration_id=integration.id, telegram_chat_id="chat_app_1", is_active=True)
    db_session.add(pairing)

    task = Task(workspace_id=ws.id, title="Task Needing Approval", goal="High risk", status="waiting_approval")
    db_session.add(task)
    await db_session.flush()

    from app.db.models.agent_run import AgentRun
    from app.db.models.tool import Tool
    from app.services.tool_registry import tool_registry

    tool = Tool(
        workspace_id=ws.id,
        name="telegram_approval_tool",
        display_name="Telegram Approval Tool",
        description="A tool for testing Telegram HITL approval",
        category="general",
        risk_level="high",
        input_schema={"type": "object", "properties": {"action": {"type": "string"}}},
        is_active=True,
    )
    db_session.add(tool)

    async def mock_action(action: str = "", **kwargs):
        return {"result": f"Executed action {action}"}
    tool_registry.register_handler("telegram_approval_tool", mock_action)

    agent_run = AgentRun(
        task_id=task.id,
        workspace_id=ws.id,
        model_name="qwen2.5:7b-instruct",
        status="running",
    )
    db_session.add(agent_run)
    await db_session.flush()

    # Create ApprovalRequest
    approval, token = await approval_service.create_approval_request(
        db=db_session,
        workspace_id=ws.id,
        task_id=task.id,
        agent_run_id=agent_run.id,
        step_number=1,
        tool_name="telegram_approval_tool",
        tool_params={"action": "deploy_staging"},
        risk_level="HIGH",
    )

    # Approve via Telegram command
    res_approve = await telegram_service.handle_command(
        db=db_session,
        integration=integration,
        chat_id="chat_app_1",
        user_id="101",
        username="operator_dan",
        raw_text=f"/approve {approval.id}",
        update_id=15,
    )
    assert "Approval granted" in res_approve

    # Verify approval state in DB
    await db_session.refresh(approval)
    assert approval.status == "approved"


@pytest.mark.asyncio
async def test_telegram_emergency_kill_switch_suspension(db_session: AsyncSession):
    """Verify that when emergency kill switch is active, /goal and /approve commands are suspended."""
    ws = Workspace(name="KS WS", slug=f"tg-ks-{uuid.uuid4().hex[:6]}")
    db_session.add(ws)
    await db_session.flush()

    integration = TelegramIntegration(workspace_id=ws.id, bot_token_ciphertext=encrypt_secret("tok"), is_active=True)
    db_session.add(integration)
    await db_session.flush()

    pairing = TelegramPairing(workspace_id=ws.id, integration_id=integration.id, telegram_chat_id="chat_ks", is_active=True)
    db_session.add(pairing)
    await db_session.flush()

    # Engage Kill Switch
    kill_switch.set_active(True, workspace_id=ws.id)
    try:
        # /goal under kill switch
        res_goal = await telegram_service.handle_command(
            db=db_session,
            integration=integration,
            chat_id="chat_ks",
            user_id="1",
            username="op",
            raw_text="/goal try running task",
            update_id=1,
        )
        assert "Emergency Kill Switch is active" in res_goal

        # /approve under kill switch
        res_app = await telegram_service.handle_command(
            db=db_session,
            integration=integration,
            chat_id="chat_ks",
            user_id="1",
            username="op",
            raw_text=f"/approve {uuid.uuid4()}",
            update_id=2,
        )
        assert "Emergency Kill Switch is active" in res_app
    finally:
        kill_switch.set_active(False)


# ==============================================================================
# 4. Long-Polling Worker & Offset Advancement Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_telegram_long_polling_offset_advancement(db_session: AsyncSession):
    """Verify long-polling advances and persists update_id offset after processing."""
    ws = Workspace(name="Poll WS", slug=f"tg-poll-{uuid.uuid4().hex[:6]}")
    db_session.add(ws)
    await db_session.flush()

    raw_token = "valid_poll_token_xyz"
    integration = TelegramIntegration(
        workspace_id=ws.id,
        display_name="Poll Bot",
        bot_token_ciphertext=encrypt_secret(raw_token),
        is_active=True,
        last_update_id=100,
    )
    db_session.add(integration)
    await db_session.flush()

    # Mock getUpdates response with 2 updates
    mock_updates = {
        "ok": True,
        "result": [
            {
                "update_id": 101,
                "message": {
                    "message_id": 1,
                    "chat": {"id": 888777},
                    "from": {"id": 888777, "username": "test_user"},
                    "text": "/help",
                },
            },
            {
                "update_id": 102,
                "message": {
                    "message_id": 2,
                    "chat": {"id": 888777},
                    "from": {"id": 888777, "username": "test_user"},
                    "text": "/start",
                },
            },
        ],
    }

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get, \
         patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_get.return_value = httpx.Response(200, json=mock_updates, request=httpx.Request("GET", "https://api.telegram.org"))
        mock_post.return_value = httpx.Response(200, json={"ok": True}, request=httpx.Request("POST", "https://api.telegram.org"))

        processed = await telegram_service.poll_integration_updates(
            db=db_session,
            integration_id=integration.id,
            worker_id="test_worker_1",
            timeout_seconds=0,
        )
        assert processed == 2

    # Invariant: offset must be persisted as 102
    await db_session.refresh(integration)
    assert integration.last_update_id == 102
    assert integration.polling_state == "polling"


# ==============================================================================
# 5. Authenticated REST API Lifecycle Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_telegram_management_api_lifecycle(client: AsyncClient):
    """Verify authenticated management API for Telegram Bot integrations and pairing tokens."""
    # 1. Register User & Workspace
    reg = await client.post(
        "/api/v1/auth/register",
        json={"email": "tg_admin@example.com", "username": "tg_admin", "password": "StrongPassword123!", "full_name": "TG Admin"},
    )
    assert reg.status_code == 201
    token = reg.json()["access_token"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    ws_id = me.json()["workspaces"][0]["id"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Configure Telegram Integration (Mock getMe)
    valid_getme = httpx.Response(
        200,
        json={"ok": True, "result": {"id": 999888, "is_bot": True, "username": "managed_aura_bot"}},
        request=httpx.Request("GET", "https://api.telegram.org"),
    )
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = valid_getme
        create_res = await client.post(
            f"/api/v1/telegram/integrations?workspace_id={ws_id}",
            json={"display_name": "Production Alert Bot", "bot_token": "999888:ValidTelegramBotTokenSecret123"},
            headers=headers,
        )
        assert create_res.status_code == 201
        data = create_res.json()
        int_id = data["id"]
        assert data["bot_username"] == "managed_aura_bot"
        assert "bot_token" not in data  # Token must never leak

    # 3. List Integrations
    list_res = await client.get(f"/api/v1/telegram/integrations?workspace_id={ws_id}", headers=headers)
    assert list_res.status_code == 200
    assert len(list_res.json()) >= 1
    assert "bot_token" not in list_res.json()[0]

    # 4. Generate Pairing Token
    pair_res = await client.post(f"/api/v1/telegram/integrations/{int_id}/pairings?workspace_id={ws_id}", json={"ttl_seconds": 900}, headers=headers)
    assert pair_res.status_code == 200
    pair_data = pair_res.json()
    assert pair_data["pairing_token"].startswith("aurapair_")
    assert "/start aurapair_" in pair_data["instructions"]

    # 5. List Pairings
    pair_list = await client.get(f"/api/v1/telegram/integrations/{int_id}/pairings?workspace_id={ws_id}", headers=headers)
    assert pair_list.status_code == 200

    # 6. Delete Integration
    del_res = await client.delete(f"/api/v1/telegram/integrations/{int_id}?workspace_id={ws_id}", headers=headers)
    assert del_res.status_code == 204
