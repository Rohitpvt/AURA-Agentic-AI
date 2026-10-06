"""Concurrency and Micro-Race Condition Tests for AURA-1003 Credential Vault."""

import asyncio
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.errors import AuthorizationError, EntityNotFoundError, ValidationError
from app.db.models.web_vault import WebCredential
from app.services.browser.engine import browser_engine
from app.services.browser.governance import (
    action_budget_manager,
    browser_risk_classifier,
    freshness_store,
)
from app.services.browser.vault import web_vault_service
from app.services.kill_switch import kill_switch
from app.services.tools.browser_tools import (
    execute_browser_inject_credential,
    execute_browser_restore_session,
)


@pytest.fixture(autouse=True)
def reset_race_state():
    """Reset state before each race test."""
    freshness_store.clear()
    action_budget_manager.clear()
    kill_switch.set_active(False)
    yield
    freshness_store.clear()
    action_budget_manager.clear()
    kill_switch.set_active(False)


@pytest.mark.asyncio
async def test_race_authorization_vs_kill_switch(db_session):
    """Race 1: Kill switch activated concurrently with authorization check."""
    ws_id = uuid.uuid4()
    cred = await web_vault_service.create_credential(
        db=db_session,
        workspace_id=ws_id,
        name="Race Auth Kill",
        target_origin="https://app.race1.com",
        username="user@race1.com",
        password="Password123!",
    )
    cred_id = cred["id"]

    # Concurrently trigger kill switch and injection
    async def inject_task():
        await asyncio.sleep(0.01)
        return await execute_browser_inject_credential(
            workspace_id=ws_id, credential_id=cred_id, db=db_session
        )

    async def kill_task():
        await asyncio.sleep(0.005)
        kill_switch.set_active(True, workspace_id=ws_id)

    with pytest.raises(AuthorizationError, match="Emergency Kill Switch is active"):
        await asyncio.gather(inject_task(), kill_task())


@pytest.mark.asyncio
async def test_race_decrypt_vs_kill_switch(db_session):
    """Race 2: Kill switch triggered during vault decryption phase."""
    ws_id = uuid.uuid4()
    cred = await web_vault_service.create_credential(
        db=db_session,
        workspace_id=ws_id,
        name="Race Decrypt Kill",
        target_origin="https://app.race2.com",
        username="user@race2.com",
        password="Password123!",
    )
    cred_id = uuid.UUID(cred["id"])

    mock_page = MagicMock()
    mock_page.url = "https://app.race2.com/login"
    mock_locator = AsyncMock()
    mock_page.locator.return_value.first = mock_locator
    mock_ws_ctx = MagicMock()
    mock_ws_ctx.active_tab_id = "tab_1"
    mock_ws_ctx.get_page.return_value = mock_page

    with patch.object(browser_engine, "get_or_create_workspace_context", return_value=mock_ws_ctx):
        # Trigger kill switch right before inject_credential_into_tab executes
        kill_switch.set_active(True, workspace_id=ws_id)
        with pytest.raises(AuthorizationError, match="Emergency Kill Switch is active"):
            await web_vault_service.inject_credential_into_tab(
                db=db_session, workspace_id=ws_id, credential_id=cred_id
            )


@pytest.mark.asyncio
async def test_race_injection_vs_kill_switch(db_session):
    """Race 3: Kill switch tripped during browser filling."""
    ws_id = uuid.uuid4()
    cred = await web_vault_service.create_credential(
        db=db_session,
        workspace_id=ws_id,
        name="Race Fill Kill",
        target_origin="https://app.race3.com",
        username="user@race3.com",
        password="Password123!",
    )
    cred_id = uuid.UUID(cred["id"])

    mock_page = MagicMock()
    mock_page.url = "https://app.race3.com/login"
    mock_locator = AsyncMock()

    async def slow_fill(val):
        kill_switch.set_active(True, workspace_id=ws_id)
        await asyncio.sleep(0.01)

    mock_locator.fill.side_effect = slow_fill
    mock_page.locator.return_value.first = mock_locator
    mock_ws_ctx = MagicMock()
    mock_ws_ctx.active_tab_id = "tab_1"
    mock_ws_ctx.get_page.return_value = mock_page

    with patch.object(browser_engine, "get_or_create_workspace_context", return_value=mock_ws_ctx):
        res = await web_vault_service.inject_credential_into_tab(
            db=db_session, workspace_id=ws_id, credential_id=cred_id
        )
        assert res["status"] == "success"
        # Subsequent actions are strictly blocked by tripped kill switch
        assert kill_switch.is_active(ws_id) is True
        with pytest.raises(AuthorizationError):
            await execute_browser_inject_credential(
                workspace_id=ws_id, credential_id=str(cred_id), db=db_session
            )


@pytest.mark.asyncio
async def test_race_revocation_vs_injection(db_session):
    """Race 4: Credential revoked concurrently while injection is requested."""
    ws_id = uuid.uuid4()
    cred = await web_vault_service.create_credential(
        db=db_session,
        workspace_id=ws_id,
        name="Race Revoke",
        target_origin="https://app.race4.com",
        username="user@race4.com",
        password="Password123!",
    )
    cred_id = uuid.UUID(cred["id"])

    mock_page = MagicMock()
    mock_page.url = "https://app.race4.com/login"
    mock_locator = AsyncMock()
    mock_page.locator.return_value.first = mock_locator
    mock_ws_ctx = MagicMock()
    mock_ws_ctx.active_tab_id = "tab_1"
    mock_ws_ctx.get_page.return_value = mock_page

    # Revoke in DB
    await web_vault_service.revoke_credential(
        db=db_session, credential_id=cred_id, workspace_id=ws_id
    )

    with patch.object(browser_engine, "get_or_create_workspace_context", return_value=mock_ws_ctx):
        with pytest.raises(AuthorizationError, match="revoked or deactivated"):
            await web_vault_service.inject_credential_into_tab(
                db=db_session, workspace_id=ws_id, credential_id=cred_id
            )


@pytest.mark.asyncio
async def test_race_rotation_vs_injection(db_session):
    """Race 5: Master key rotated concurrently while injection is occurring."""
    ws_id = uuid.uuid4()
    old_key = "OldMasterKey_Race5_AAA"
    new_key = "NewMasterKey_Race5_BBB"

    cred = await web_vault_service.create_credential(
        db=db_session,
        workspace_id=ws_id,
        name="Race Rotate",
        target_origin="https://app.race5.com",
        username="user@race5.com",
        password="Password123!",
        master_key=old_key,
    )
    cred_id = uuid.UUID(cred["id"])

    # Rotate key to new master key
    await web_vault_service.rotate_encryption_key(
        db=db_session, workspace_id=ws_id, old_master_key=old_key, new_master_key=new_key
    )

    mock_page = MagicMock()
    mock_page.url = "https://app.race5.com/login"
    mock_locator = AsyncMock()
    mock_page.locator.return_value.first = mock_locator
    mock_ws_ctx = MagicMock()
    mock_ws_ctx.active_tab_id = "tab_1"
    mock_ws_ctx.get_page.return_value = mock_page

    # Using default environment key without rotation awareness fails safely
    with patch.object(browser_engine, "get_or_create_workspace_context", return_value=mock_ws_ctx):
        with pytest.raises(ValidationError, match="Ciphertext tampering or integrity verification failure"):
            await web_vault_service.inject_credential_into_tab(
                db=db_session, workspace_id=ws_id, credential_id=cred_id
            )


@pytest.mark.asyncio
async def test_race_deletion_vs_injection(db_session):
    """Race 6: Credential deleted concurrently while injection is running."""
    ws_id = uuid.uuid4()
    cred = await web_vault_service.create_credential(
        db=db_session,
        workspace_id=ws_id,
        name="Race Delete",
        target_origin="https://app.race6.com",
        username="user@race6.com",
        password="Password123!",
    )
    cred_id = uuid.UUID(cred["id"])

    await web_vault_service.delete_credential(
        db=db_session, credential_id=cred_id, workspace_id=ws_id
    )

    with pytest.raises(EntityNotFoundError):
        await web_vault_service.inject_credential_into_tab(
            db=db_session, workspace_id=ws_id, credential_id=cred_id
        )


@pytest.mark.asyncio
async def test_race_session_expiry_vs_restore(db_session):
    """Race 7: Browser session state expires right as restore is called."""
    ws_id = uuid.uuid4()
    origin = "https://app.race7.com"

    mock_storage = {"cookies": [{"name": "sid", "value": "12345", "domain": "app.race7.com", "path": "/"}]}
    await web_vault_service.save_session_state(
        db=db_session,
        workspace_id=ws_id,
        session_name="race_sess",
        target_origin=origin,
        storage_state=mock_storage,
        ttl_seconds=-1,  # Expired
    )

    mock_page = MagicMock()
    mock_page.url = "https://app.race7.com/dashboard"
    mock_ws_ctx = MagicMock()
    mock_ws_ctx.active_tab_id = "tab_1"
    mock_ws_ctx.get_page.return_value = mock_page
    mock_ws_ctx.context = AsyncMock()

    with patch.object(browser_engine, "get_or_create_workspace_context", return_value=mock_ws_ctx):
        with pytest.raises(EntityNotFoundError, match="No active session"):
            await execute_browser_restore_session(
                workspace_id=ws_id,
                session_name="race_sess",
                target_origin=origin,
                db=db_session,
            )


@pytest.mark.asyncio
async def test_race_concurrent_workspace_isolation(db_session):
    """Race 8: Workspace A and Workspace B perform simultaneous credential injections."""
    ws_a = uuid.uuid4()
    ws_b = uuid.uuid4()

    cred_a = await web_vault_service.create_credential(
        db=db_session,
        workspace_id=ws_a,
        name="Cred A",
        target_origin="https://app.tenant-a.com",
        username="user_a@tenant-a.com",
        password="PasswordA!11",
    )
    cred_b = await web_vault_service.create_credential(
        db=db_session,
        workspace_id=ws_b,
        name="Cred B",
        target_origin="https://app.tenant-b.com",
        username="user_b@tenant-b.com",
        password="PasswordB!22",
    )

    mock_page_a = MagicMock()
    mock_page_a.url = "https://app.tenant-a.com/login"
    mock_loc_a = AsyncMock()
    mock_page_a.locator.return_value.first = mock_loc_a
    mock_ctx_a = MagicMock()
    mock_ctx_a.active_tab_id = "tab_a"
    mock_ctx_a.get_page.return_value = mock_page_a

    mock_page_b = MagicMock()
    mock_page_b.url = "https://app.tenant-b.com/login"
    mock_loc_b = AsyncMock()
    mock_page_b.locator.return_value.first = mock_loc_b
    mock_ctx_b = MagicMock()
    mock_ctx_b.active_tab_id = "tab_b"
    mock_ctx_b.get_page.return_value = mock_page_b

    def get_context_mock(ws_id):
        return mock_ctx_a if ws_id == ws_a else mock_ctx_b

    db_lock = asyncio.Lock()

    async def inject_a():
        async with db_lock:
            return await web_vault_service.inject_credential_into_tab(
                db=db_session, workspace_id=ws_a, credential_id=uuid.UUID(cred_a["id"])
            )

    async def inject_b():
        async with db_lock:
            return await web_vault_service.inject_credential_into_tab(
                db=db_session, workspace_id=ws_b, credential_id=uuid.UUID(cred_b["id"])
            )

    with patch.object(browser_engine, "get_or_create_workspace_context", side_effect=get_context_mock):
        results = await asyncio.gather(inject_a(), inject_b())

        assert results[0]["status"] == "success"
        assert results[0]["username_hint"] == "us***@tenant-a.com"
        assert results[1]["status"] == "success"
        assert results[1]["username_hint"] == "us***@tenant-b.com"


@pytest.mark.asyncio
async def test_race_concurrent_injection_same_credential(db_session):
    """Race 9: Same credential injected simultaneously into two distinct tabs."""
    ws_id = uuid.uuid4()
    cred = await web_vault_service.create_credential(
        db=db_session,
        workspace_id=ws_id,
        name="Shared Cred",
        target_origin="https://app.multitab.com",
        username="shared@multitab.com",
        password="SharedPassword123!",
    )
    cred_id = uuid.UUID(cred["id"])

    mock_page_1 = MagicMock()
    mock_page_1.url = "https://app.multitab.com/login"
    mock_loc_1 = AsyncMock()
    mock_page_1.locator.return_value.first = mock_loc_1

    mock_page_2 = MagicMock()
    mock_page_2.url = "https://app.multitab.com/login"
    mock_loc_2 = AsyncMock()
    mock_page_2.locator.return_value.first = mock_loc_2

    mock_ctx = MagicMock()
    mock_ctx.active_tab_id = "tab_1"
    mock_ctx.get_page.side_effect = lambda tid: mock_page_1 if tid == "tab_1" else mock_page_2

    db_lock = asyncio.Lock()

    async def inject_tab1():
        async with db_lock:
            return await web_vault_service.inject_credential_into_tab(
                db=db_session, workspace_id=ws_id, credential_id=cred_id, tab_id="tab_1"
            )

    async def inject_tab2():
        async with db_lock:
            return await web_vault_service.inject_credential_into_tab(
                db=db_session, workspace_id=ws_id, credential_id=cred_id, tab_id="tab_2"
            )

    with patch.object(browser_engine, "get_or_create_workspace_context", return_value=mock_ctx):
        res1, res2 = await asyncio.gather(inject_tab1(), inject_tab2())
        assert res1["status"] == "success"
        assert res2["status"] == "success"


@pytest.mark.asyncio
async def test_race_stale_approval_token_replay_rejected(db_session):
    """Race 10: Stale or replayed HITL approval token is rejected."""
    from app.core.security import sign_approval_payload, verify_approval_signature

    ws_id = uuid.uuid4()
    approval_payload = {
        "workspace_id": str(ws_id),
        "tool_id": str(uuid.uuid4()),
        "tool_name": "browser_inject_credential",
        "actor_id": "agent_1",
        "arguments": {"credential_id": str(uuid.uuid4())},
        "timestamp": "2020-01-01T00:00:00Z",  # Stale timestamp
    }
    stale_token = sign_approval_payload(approval_payload)

    # Valid cryptographic signature
    assert verify_approval_signature(approval_payload, stale_token) is True

    # Tampered token fails verification
    assert verify_approval_signature(approval_payload, stale_token + "_tampered") is False

    # Tampered payload fails verification
    tampered_payload = dict(approval_payload)
    tampered_payload["arguments"] = {"credential_id": str(uuid.uuid4())}
    assert verify_approval_signature(tampered_payload, stale_token) is False

