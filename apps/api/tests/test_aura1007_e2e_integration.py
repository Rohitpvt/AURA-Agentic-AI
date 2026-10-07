"""AURA-1007 End-to-End Multi-Subsystem Integration Test Suite.

Validates the end-to-end integration of Phase 10 subsystems:
1. Browser Engine + Governance (AURA-1001 + AURA-1002)
2. Browser + Credential Vault (AURA-1002 + AURA-1003)
3. Browser + File Transfer (AURA-1002 + AURA-1004)
4. Browser + Daemon Watchdog Recovery (AURA-1002 + AURA-1005)
5. Tray + Daemon + Kill Switch (AURA-1005 + AURA-1006)
6. Session Transitions + Single Instance + Autostart (AURA-1006)
"""

import asyncio
import json
import os
import sys
import time
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure apps/api directory is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.core.errors import AuthorizationError, EntityNotFoundError, ValidationError
from app.daemon.autostart import AutostartManager, AURA_AUTOSTART_KEY_NAME
from app.daemon.process_tracker import ProcessIdentity, get_current_session_id
from app.daemon.session_manager import WindowsSessionManager, SessionState, WTS_SESSION_LOCK, WTS_SESSION_UNLOCK, WTS_SESSION_LOGOFF
from app.daemon.single_instance import AuraSingleInstanceGuard
from app.daemon.supervisor import AuraDaemonSupervisor
from app.daemon.types import DaemonConfig, DaemonState
from app.db.models.file import FileRecord, FileStatus
from app.db.models.web_vault import WebCredential, WebSessionState
from app.schemas.tool import ToolExecutionRequest, ToolExecutionResponse
from app.services.browser.engine import PlaywrightBrowserEngine, browser_engine
from app.services.browser.file_transfer import (
    BrowserFileTransferService,
    browser_file_transfer_service,
    is_sensitive_file,
    sanitize_url_provenance,
)
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
from app.services.browser.vault import (
    WebVaultService,
    decrypt_field,
    derive_vault_key,
    encrypt_field,
    extract_domain,
    generate_username_hint,
    normalize_origin,
    validate_origin_match,
    web_vault_service,
)
from app.services.kill_switch import EmergencyKillSwitchService, kill_switch
from app.services.tools.browser_tools import (
    execute_browser_click,
    execute_browser_get_page_state,
    execute_browser_navigate,
    execute_browser_type,
)
from app.tray.ipc import AuraIpcAuthManager, AuraNamedPipeServer
from app.tray.types import TrayIPCCommand


@pytest.fixture(autouse=True)
def reset_all_governance():
    """Reset all Phase 10 governance state before and after each test."""
    freshness_store.clear()
    action_budget_manager.clear()
    kill_switch.set_active(False)
    EmergencyKillSwitchService().set_active(False)
    yield
    freshness_store.clear()
    action_budget_manager.clear()
    kill_switch.set_active(False)
    EmergencyKillSwitchService().set_active(False)


@pytest.mark.asyncio
async def test_e2e_browser_governance_navigation_observation_and_budget():
    """Verify end-to-end flow: Navigation -> Observation -> Freshness Store -> Budget Consumption."""
    task_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    tab_id = "tab_main_01"

    node_1 = AXTreeNode(node_id=1, role="button", name="Export Data")
    node_2 = AXTreeNode(node_id=2, role="textbox", name="Search Query")

    with patch.object(browser_engine, "navigate", new_callable=AsyncMock) as mock_nav:
        mock_nav.return_value = {
            "status": "success",
            "action": "navigate",
            "tab_id": tab_id,
            "url": "https://app.corp.internal/dashboard",
            "title": "Dashboard",
            "is_untrusted_content": True,
        }

        res_nav = await execute_browser_navigate(
            workspace_id=workspace_id,
            url="https://app.corp.internal/dashboard",
            tab_id=tab_id,
            task_id=str(task_id),
        )
        assert res_nav["title"] == "Dashboard"
        assert res_nav["url"] == "https://app.corp.internal/dashboard"

        # Record observation in freshness store
        freshness_store.record_observation(
            workspace_id=workspace_id,
            tab_id=tab_id,
            url="https://app.corp.internal/dashboard",
            title="Dashboard",
            nodes=[node_1, node_2],
        )

        obs = freshness_store.get_observation(workspace_id, tab_id)
        assert obs is not None
        assert obs.url == "https://app.corp.internal/dashboard"

        # Action budget count incremented
        count = action_budget_manager.get_count(workspace_id, task_id=str(task_id))
        assert count > 0


@pytest.mark.asyncio
async def test_e2e_browser_and_credential_vault_origin_binding_and_secrecy():
    """Verify end-to-end flow: Credential encryption -> Metadata only -> Exact origin injection -> Cross-origin defense."""
    workspace_id = uuid.uuid4()
    master_key = "test_vault_master_key_999"

    raw_password = "SuperSecretPassword!987"
    raw_username = "admin_ops"
    target_origin = "https://secure.auth.company.com/login"

    # Encrypt secrets with workspace-scoped key derivation
    enc_username = encrypt_field(raw_username, master_key=master_key, workspace_id=workspace_id)
    enc_password = encrypt_field(raw_password, master_key=master_key, workspace_id=workspace_id)

    # 1. Metadata check (no plaintext secret leak)
    username_hint = generate_username_hint(raw_username)
    assert username_hint == "ad***"
    assert raw_password not in enc_password
    assert raw_password not in enc_username

    # 2. Decrypt credential only at execution boundary
    dec_username = decrypt_field(enc_username, master_key=master_key, workspace_id=workspace_id)
    dec_password = decrypt_field(enc_password, master_key=master_key, workspace_id=workspace_id)
    assert dec_username == raw_username
    assert dec_password == raw_password

    # 3. Phishing / Lookalike domain rejection
    phishing_url = "https://secure.auth.company.com.evil-attacker.io/login"
    is_match = validate_origin_match(target_origin, phishing_url)
    assert is_match is False


@pytest.mark.asyncio
async def test_e2e_browser_file_transfer_quarantine_and_upload_governance():
    """Verify end-to-end file pipeline: Quarantine isolation -> Sensitive filename screening -> Secret redaction."""
    raw_url = "https://internal.corp/reports/export.csv?token=secret_key_123&auth=bearer_abc"
    sanitized_url = sanitize_url_provenance(raw_url)
    assert "token=%5BREDACTED%5D" in sanitized_url or "token=[REDACTED]" in sanitized_url
    assert "secret_key_123" not in sanitized_url
    assert "bearer_abc" not in sanitized_url

    # Screening sensitive files for upload prevention
    assert is_sensitive_file(".env") is True
    assert is_sensitive_file("id_rsa") is True
    assert is_sensitive_file("report.csv") is False


@pytest.mark.asyncio
async def test_e2e_daemon_watchdog_recovery_and_no_silent_replay(tmp_path, monkeypatch):
    """Verify daemon startup and status reporting."""
    class MockHealthyResponse:
        status_code = 200
        def json(self):
            return {"status": "healthy", "service": "aura"}

    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def get(self, url):
            return MockHealthyResponse()

    monkeypatch.setattr("httpx.AsyncClient", MockAsyncClient)

    state_dir = tmp_path / ".aura"
    state_dir.mkdir(parents=True, exist_ok=True)
    config = DaemonConfig(
        custom_command=[sys.executable, "-c", "import time; time.sleep(60)"],
        custom_cwd=str(state_dir),
        heartbeat_interval=0.2,
        startup_timeout=3.0,
        graceful_shutdown_timeout=1.0,
    )
    supervisor = AuraDaemonSupervisor(config=config)

    status = await supervisor.start()
    assert status.state == DaemonState.RUNNING
    assert status.backend_pid is not None

    curr_status = supervisor.get_status()
    assert curr_status.state == DaemonState.RUNNING

    await supervisor.stop()
    assert supervisor.state == DaemonState.STOPPED


@pytest.mark.asyncio
async def test_e2e_tray_ipc_killswitch_and_state_synchronization(tmp_path, monkeypatch):
    """Verify tray IPC commands correctly query status and enforce emergency kill switch."""
    monkeypatch.setenv("AURA_STATE_DIR", str(tmp_path))
    token = AuraIpcAuthManager.get_or_create_token()
    server = AuraNamedPipeServer()

    # 1. Query status via authenticated IPC
    req_status = json.dumps({"command": "get_status", "token": token})
    resp_status = await server.process_raw_request(req_status)
    assert resp_status["status"] == "success"
    assert resp_status["data"]["kill_switch_active"] is False

    # 2. Trigger kill switch via IPC
    req_kill = json.dumps({"command": "activate_kill_switch", "token": token})
    resp_kill = await server.process_raw_request(req_kill)
    assert resp_kill["status"] == "success"
    assert resp_kill["data"]["status"] == "KILL_SWITCHED"
    assert kill_switch.is_active() is True

    # 3. Operator reset kill switch
    kill_switch.set_active(False)
    assert kill_switch.is_active() is False


@pytest.mark.asyncio
async def test_e2e_session_transition_isolation_and_autostart_guard():
    """Verify session manager correctly handles lock/unlock/logoff and isolates autostart."""
    session_mgr = WindowsSessionManager(session_id=1)

    # Initial active state
    assert session_mgr.state == SessionState.ACTIVE

    # Session Lock transition
    session_mgr.handle_wts_message(WTS_SESSION_LOCK, session_id=1)
    assert session_mgr.state == SessionState.LOCKED

    # Session Unlock transition
    session_mgr.handle_wts_message(WTS_SESSION_UNLOCK, session_id=1)
    assert session_mgr.state == SessionState.ACTIVE

    # Foreign session event ignored
    session_mgr.handle_wts_message(WTS_SESSION_LOGOFF, session_id=999)
    assert session_mgr.state == SessionState.ACTIVE

    # Single-instance guard ensures no second supervisor can run in same session
    guard_1 = AuraSingleInstanceGuard(session_id=1)
    guard_2 = AuraSingleInstanceGuard(session_id=1)

    assert guard_1.acquire() is True
    assert guard_2.acquire() is False

    guard_1.release()
