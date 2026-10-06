"""Security Red Team and Attack Mitigation Tests for AURA-1003 Credential Vault."""

import asyncio
import base64
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.errors import AuthorizationError, EntityNotFoundError, ValidationError
from app.db.models.web_vault import WebCredential, WebSessionState
from app.schemas.tool import ToolExecutionRequest
from app.services.browser.engine import PlaywrightBrowserEngine, browser_engine
from app.services.browser.governance import (
    action_budget_manager,
    browser_risk_classifier,
    freshness_store,
)
from app.services.browser.models import AXTreeNode, PageObservation
from app.services.browser.vault import web_vault_service
from app.services.kill_switch import kill_switch
from app.services.tool_registry import tool_registry
from app.services.tools.browser_tools import (
    execute_browser_inject_credential,
    execute_browser_list_credentials,
    execute_browser_restore_session,
    execute_browser_save_session,
)


@pytest.fixture(autouse=True)
def reset_state():
    """Reset governance, kill switch, and freshness stores before each test."""
    freshness_store.clear()
    action_budget_manager.clear()
    kill_switch.set_active(False)
    yield
    freshness_store.clear()
    action_budget_manager.clear()
    kill_switch.set_active(False)


@pytest.mark.asyncio
async def test_security_zero_plaintext_in_tool_outputs_and_metadata(db_session):
    """Verify tool execution outputs never expose plaintext passwords or session tokens."""
    ws_id = uuid.uuid4()
    canary_pass = "CANARY_SECRET_PASS_9874135"
    canary_user = "canary_user@securecorp.com"

    cred_meta = await web_vault_service.create_credential(
        db=db_session,
        workspace_id=ws_id,
        name="Target Site",
        target_origin="https://target.corp.com",
        username=canary_user,
        password=canary_pass,
    )
    cred_id = cred_meta["id"]

    # 1. List credentials tool output check
    list_res = await execute_browser_list_credentials(
        workspace_id=ws_id,
        db=db_session,
    )
    assert canary_pass not in str(list_res)
    assert canary_user not in str(list_res)  # only masked hint
    assert "ca***@securecorp.com" in str(list_res)

    # 2. Inspect DB columns directly
    stmt = await db_session.get(WebCredential, uuid.UUID(cred_id))
    assert stmt is not None
    assert canary_pass not in stmt.password_ciphertext
    assert canary_user not in stmt.username_ciphertext
    assert "ciphertext" in stmt.password_ciphertext or len(stmt.password_ciphertext) > 20


@pytest.mark.asyncio
async def test_security_workspace_isolation_cross_tenant_block(db_session):
    """Verify Tenant B cannot list, get, revoke, delete, or inject Tenant A credentials."""
    ws_a = uuid.uuid4()
    ws_b = uuid.uuid4()

    cred_a = await web_vault_service.create_credential(
        db=db_session,
        workspace_id=ws_a,
        name="Workspace A Secret Site",
        target_origin="https://vault.internal.com",
        username="admin_a@corp.com",
        password="PasswordA!@#11",
    )
    cred_a_id = uuid.UUID(cred_a["id"])

    # Tenant B listing credentials sees 0 items
    list_b = await execute_browser_list_credentials(
        workspace_id=ws_b,
        db=db_session,
    )
    assert list_b["total"] == 0
    assert len(list_b["credentials"]) == 0

    # Tenant B metadata request fails with EntityNotFoundError
    with pytest.raises(EntityNotFoundError):
        await web_vault_service.get_credential_metadata(
            db=db_session, credential_id=cred_a_id, workspace_id=ws_b
        )

    # Tenant B revocation request fails with EntityNotFoundError
    with pytest.raises(EntityNotFoundError):
        await web_vault_service.revoke_credential(
            db=db_session, credential_id=cred_a_id, workspace_id=ws_b
        )

    # Tenant B deletion request fails with EntityNotFoundError
    with pytest.raises(EntityNotFoundError):
        await web_vault_service.delete_credential(
            db=db_session, credential_id=cred_a_id, workspace_id=ws_b
        )

    # Tenant B injection attempt fails with EntityNotFoundError
    with pytest.raises(EntityNotFoundError):
        await execute_browser_inject_credential(
            workspace_id=ws_b,
            credential_id=str(cred_a_id),
            db=db_session,
        )


@pytest.mark.asyncio
async def test_security_phishing_and_lookalike_domain_defense(db_session):
    """Verify credential bound to https://secure.bank.com cannot be injected into lookalike domains."""
    ws_id = uuid.uuid4()

    cred = await web_vault_service.create_credential(
        db=db_session,
        workspace_id=ws_id,
        name="Bank Online",
        target_origin="https://secure.bank.com",
        username="bank_user@bank.com",
        password="BankPassSecure9900!",
        allow_subdomains=False,
    )
    cred_id = uuid.UUID(cred["id"])

    # Mock browser engine context with phishing pages
    mock_page = AsyncMock()
    mock_ws_ctx = MagicMock()
    mock_ws_ctx.active_tab_id = "tab_1"
    mock_ws_ctx.get_page.return_value = mock_page

    phishing_urls = [
        "https://secure.bank.com.attacker.net/login",
        "https://secure-bank.com/login",
        "https://fake-secure.bank.com/login",
        "http://secure.bank.com/login",  # Insecure HTTP scheme
        "https://secure.bank.com:8443/login",  # Unauthorized port
        "https://evilcorp.org/phishing?target=https://secure.bank.com",
    ]

    for fake_url in phishing_urls:
        mock_page.url = fake_url
        with patch.object(browser_engine, "get_or_create_workspace_context", return_value=mock_ws_ctx):
            with pytest.raises(AuthorizationError, match="Phishing/Origin mismatch"):
                await web_vault_service.inject_credential_into_tab(
                    db=db_session,
                    workspace_id=ws_id,
                    credential_id=cred_id,
                )


@pytest.mark.asyncio
async def test_security_subdomain_enforcement_boundary(db_session):
    """Verify subdomain access is rejected unless explicitly enabled."""
    ws_id = uuid.uuid4()

    # Credential with allow_subdomains=False
    cred_strict = await web_vault_service.create_credential(
        db=db_session,
        workspace_id=ws_id,
        name="Strict Domain",
        target_origin="https://example.com",
        username="user@example.com",
        password="ExamplePass123!",
        allow_subdomains=False,
    )
    cred_strict_id = uuid.UUID(cred_strict["id"])

    mock_page = AsyncMock()
    mock_page.url = "https://subdomain.example.com/login"
    mock_ws_ctx = MagicMock()
    mock_ws_ctx.active_tab_id = "tab_1"
    mock_ws_ctx.get_page.return_value = mock_page

    with patch.object(browser_engine, "get_or_create_workspace_context", return_value=mock_ws_ctx):
        with pytest.raises(AuthorizationError, match="Phishing/Origin mismatch"):
            await web_vault_service.inject_credential_into_tab(
                db=db_session,
                workspace_id=ws_id,
                credential_id=cred_strict_id,
            )

    # Credential with allow_subdomains=True
    cred_sub = await web_vault_service.create_credential(
        db=db_session,
        workspace_id=ws_id,
        name="Permissive Subdomains",
        target_origin="https://example.org",
        username="user@example.org",
        password="ExamplePassOrg123!",
        allow_subdomains=True,
    )
    cred_sub_id = uuid.UUID(cred_sub["id"])

    mock_page.url = "https://api.example.org/login"
    mock_locator = AsyncMock()
    mock_locator.fill = AsyncMock()
    mock_page.locator = MagicMock()
    mock_page.locator.return_value.first = mock_locator

    with patch.object(browser_engine, "get_or_create_workspace_context", return_value=mock_ws_ctx):
        res = await web_vault_service.inject_credential_into_tab(
            db=db_session,
            workspace_id=ws_id,
            credential_id=cred_sub_id,
        )
        assert res["status"] == "success"
        assert res["action"] == "credential_injected"


@pytest.mark.asyncio
async def test_security_tampered_ciphertext_fails_closed(db_session):
    """Verify tampering with encrypted password in DB fails injection closed."""
    ws_id = uuid.uuid4()

    cred = await web_vault_service.create_credential(
        db=db_session,
        workspace_id=ws_id,
        name="Tamper Target",
        target_origin="https://app.tamper.com",
        username="admin@tamper.com",
        password="OriginalValidPassword99!",
    )
    cred_id = uuid.UUID(cred["id"])

    # Directly tamper with ciphertext in database
    db_cred = await db_session.get(WebCredential, cred_id)
    raw_bytes = bytearray(base64.b64decode(db_cred.password_ciphertext.encode("ascii")))
    raw_bytes[-2] ^= 0x55  # Modify ciphertext bit
    db_cred.password_ciphertext = base64.b64encode(raw_bytes).decode("ascii")
    await db_session.commit()

    mock_page = AsyncMock()
    mock_page.url = "https://app.tamper.com/login"
    mock_ws_ctx = MagicMock()
    mock_ws_ctx.active_tab_id = "tab_1"
    mock_ws_ctx.get_page.return_value = mock_page

    with patch.object(browser_engine, "get_or_create_workspace_context", return_value=mock_ws_ctx):
        with pytest.raises(ValidationError, match="Ciphertext tampering or integrity verification failure"):
            await web_vault_service.inject_credential_into_tab(
                db=db_session,
                workspace_id=ws_id,
                credential_id=cred_id,
            )


@pytest.mark.asyncio
async def test_security_revoked_credential_fails_closed(db_session):
    """Verify injection fails immediately if credential is revoked or inactive."""
    ws_id = uuid.uuid4()

    cred = await web_vault_service.create_credential(
        db=db_session,
        workspace_id=ws_id,
        name="Revoke Target",
        target_origin="https://app.revoked.com",
        username="user@revoked.com",
        password="RevokedPass123!",
    )
    cred_id = uuid.UUID(cred["id"])

    # Revoke
    await web_vault_service.revoke_credential(
        db=db_session, credential_id=cred_id, workspace_id=ws_id, reason="Compromise suspected"
    )

    mock_page = AsyncMock()
    mock_page.url = "https://app.revoked.com/login"
    mock_ws_ctx = MagicMock()
    mock_ws_ctx.active_tab_id = "tab_1"
    mock_ws_ctx.get_page.return_value = mock_page

    with patch.object(browser_engine, "get_or_create_workspace_context", return_value=mock_ws_ctx):
        with pytest.raises(AuthorizationError, match="revoked or deactivated"):
            await web_vault_service.inject_credential_into_tab(
                db=db_session,
                workspace_id=ws_id,
                credential_id=cred_id,
            )


@pytest.mark.asyncio
async def test_security_emergency_kill_switch_blocks_all_vault_operations(db_session):
    """Verify active kill switch immediately aborts all credential and session operations."""
    ws_id = uuid.uuid4()

    cred = await web_vault_service.create_credential(
        db=db_session,
        workspace_id=ws_id,
        name="Kill Switch Target",
        target_origin="https://secure.service.com",
        username="user@service.com",
        password="ValidPassword123!",
    )
    cred_id = cred["id"]

    # Activate Kill Switch for workspace
    kill_switch.set_active(True, workspace_id=ws_id)

    # 1. Inject credential blocked
    with pytest.raises(AuthorizationError, match="Emergency Kill Switch is active"):
        await execute_browser_inject_credential(
            workspace_id=ws_id,
            credential_id=cred_id,
            db=db_session,
        )

    # 2. List credentials blocked
    with pytest.raises(AuthorizationError, match="Emergency Kill Switch is active"):
        await execute_browser_list_credentials(
            workspace_id=ws_id,
            db=db_session,
        )

    # 3. Save session blocked
    with pytest.raises(AuthorizationError, match="Emergency Kill Switch is active"):
        await execute_browser_save_session(
            workspace_id=ws_id,
            session_name="emergency_save",
            db=db_session,
        )

    # 4. Restore session blocked
    with pytest.raises(AuthorizationError, match="Emergency Kill Switch is active"):
        await execute_browser_restore_session(
            workspace_id=ws_id,
            session_name="emergency_restore",
            db=db_session,
        )


@pytest.mark.asyncio
async def test_security_hitl_approval_gate_on_credential_injection(db_session):
    """Verify tool execution requests for browser_inject_credential enforce High-Risk HITL approval."""
    ws_id = uuid.uuid4()
    req = ToolExecutionRequest(
        workspace_id=ws_id,
        tool_name="browser_inject_credential",
        arguments={"credential_id": str(uuid.uuid4())},
    )

    # Calling tool_registry.execute_tool without approval token returns suspended response
    resp = await tool_registry.execute_tool(
        db=db_session,
        request=req,
        actor_id="agent_1",
    )
    assert resp.success is False
    assert resp.requires_hitl_approval is True
    assert resp.risk_level == "high"
    assert resp.approval_token is not None
    assert "Human-in-the-Loop approval required" in resp.error
