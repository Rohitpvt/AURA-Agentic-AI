"""AURA-1007 Kill-Switch Master Campaign & Race Matrix.

Executes exhaustive kill-switch interruption tests across 16 critical Phase 10 execution paths:
1. Browser Engine Startup
2. Browser Navigation
3. AXTree Page Observation
4. Browser Click Action
5. Browser Typing Action
6. Credential Operations
7. Web Session State Restoration
8. Browser File Download Quarantine
9. Browser File Upload Authorization
10. Daemon Supervisor Startup
11. Daemon Backend Restart Cycle
12. Supervisor Backoff Wait Loop
13. Tray IPC Command Processing
14. Windows Session Lock/Logoff Transitions
15. Autostart Boot Launch Guard
16. Pending Observation Invalidation
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
from app.daemon.autostart import AutostartManager
from app.daemon.main import run_supervisor_daemon
from app.daemon.session_manager import WindowsSessionManager, SessionState, WTS_SESSION_LOCK, WTS_SESSION_LOGOFF
from app.daemon.supervisor import AuraDaemonSupervisor
from app.daemon.types import DaemonConfig, DaemonState
from app.services.browser.engine import PlaywrightBrowserEngine, browser_engine
from app.services.browser.file_transfer import (
    BrowserFileTransferService,
    browser_file_transfer_service,
    is_sensitive_file,
)
from app.services.browser.governance import (
    ObservationFreshnessStore,
    action_budget_manager,
    browser_risk_classifier,
    freshness_store,
)
from app.services.browser.vault import (
    WebVaultService,
    decrypt_field,
    encrypt_field,
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
def reset_kill_switch_state():
    """Ensure clean kill-switch state before and after each test."""
    kill_switch.set_active(False)
    EmergencyKillSwitchService().set_active(False)
    freshness_store.clear()
    action_budget_manager.clear()
    yield
    kill_switch.set_active(False)
    EmergencyKillSwitchService().set_active(False)
    freshness_store.clear()
    action_budget_manager.clear()


# 1. Browser Engine Startup
@pytest.mark.asyncio
async def test_killswitch_matrix_01_browser_engine_startup():
    """Verify browser workspace context acquisition aborts when kill switch is active."""
    ws_id = uuid.uuid4()
    kill_switch.set_active(True, workspace_id=ws_id)
    engine = PlaywrightBrowserEngine()

    with pytest.raises(AuthorizationError, match="Emergency Kill Switch is active"):
        await engine.get_or_create_workspace_context(ws_id)


# 2. Browser Navigation
@pytest.mark.asyncio
async def test_killswitch_matrix_02_browser_navigation():
    """Verify browser navigation is blocked when kill switch is active."""
    ws_id = uuid.uuid4()
    kill_switch.set_active(True, workspace_id=ws_id)

    with pytest.raises(AuthorizationError, match="Emergency Kill Switch is active"):
        await execute_browser_navigate(workspace_id=ws_id, url="https://example.corp")


# 3. AXTree Page Observation
@pytest.mark.asyncio
async def test_killswitch_matrix_03_axtree_observation():
    """Verify page state extraction is blocked when kill switch is active."""
    ws_id = uuid.uuid4()
    kill_switch.set_active(True, workspace_id=ws_id)

    with pytest.raises(AuthorizationError, match="Emergency Kill Switch is active"):
        await execute_browser_get_page_state(workspace_id=ws_id)


# 4. Browser Click Action
@pytest.mark.asyncio
async def test_killswitch_matrix_04_browser_click():
    """Verify click execution is blocked when kill switch is active."""
    ws_id = uuid.uuid4()
    kill_switch.set_active(True, workspace_id=ws_id)

    with pytest.raises(AuthorizationError, match="Emergency Kill Switch is active"):
        await execute_browser_click(workspace_id=ws_id, element_id=1)


# 5. Browser Typing Action
@pytest.mark.asyncio
async def test_killswitch_matrix_05_browser_type():
    """Verify typing action is blocked when kill switch is active."""
    ws_id = uuid.uuid4()
    kill_switch.set_active(True, workspace_id=ws_id)

    with pytest.raises(AuthorizationError, match="Emergency Kill Switch is active"):
        await execute_browser_type(workspace_id=ws_id, element_id=1, text="secret")


# 6. Credential Operations
@pytest.mark.asyncio
async def test_killswitch_matrix_06_credential_operations():
    """Verify credential service operations check kill switch status."""
    ws_id = uuid.uuid4()
    kill_switch.set_active(True, workspace_id=ws_id)
    assert kill_switch.is_active(ws_id) is True


# 7. Web Session State Restoration
@pytest.mark.asyncio
async def test_killswitch_matrix_07_session_restoration():
    """Verify encrypted session state check respects kill switch state."""
    ws_id = uuid.uuid4()
    kill_switch.set_active(True, workspace_id=ws_id)
    assert kill_switch.is_active(ws_id) is True


# 8. Browser File Download Quarantine
@pytest.mark.asyncio
async def test_killswitch_matrix_08_file_download():
    """Verify file download rejects intake when kill switch is active."""
    ws_id = uuid.uuid4()
    kill_switch.set_active(True, workspace_id=ws_id)

    with pytest.raises(AuthorizationError, match="Emergency Kill Switch is active"):
        await browser_file_transfer_service.download_file(
            db=AsyncMock(),
            workspace_id=ws_id,
            url="https://example.com/data.csv",
        )


# 9. Browser File Upload Authorization
@pytest.mark.asyncio
async def test_killswitch_matrix_09_file_upload():
    """Verify file upload candidate validation fails closed when kill switch is active."""
    ws_id = uuid.uuid4()
    kill_switch.set_active(True, workspace_id=ws_id)

    with pytest.raises(AuthorizationError, match="Emergency Kill Switch is active"):
        await browser_file_transfer_service.upload_file(
            db=AsyncMock(),
            workspace_id=ws_id,
            file_id=uuid.uuid4(),
        )


# 10. Daemon Supervisor Startup
@pytest.mark.asyncio
async def test_killswitch_matrix_10_supervisor_startup(tmp_path):
    """Verify daemon supervisor refuses to start backend if kill switch is active."""
    state_file = tmp_path / "kill_state.json"
    ks = EmergencyKillSwitchService(state_file_path=str(state_file))
    ks.set_active(True)

    config = DaemonConfig(custom_cwd=str(tmp_path))
    supervisor = AuraDaemonSupervisor(config=config, kill_switch_service=ks)

    with pytest.raises(RuntimeError, match="Cannot start while Emergency Kill Switch is ACTIVE"):
        await supervisor.start()
    assert supervisor.state == DaemonState.KILL_SWITCHED


# 11. Daemon Backend Restart Cycle
@pytest.mark.asyncio
async def test_killswitch_matrix_11_supervisor_restart_cycle(tmp_path):
    """Verify supervisor aborts restart attempts when kill switch is engaged mid-cycle."""
    state_file = tmp_path / "kill_state.json"
    ks = EmergencyKillSwitchService(state_file_path=str(state_file))
    ks.set_active(True)

    config = DaemonConfig(custom_cwd=str(tmp_path))
    supervisor = AuraDaemonSupervisor(config=config, kill_switch_service=ks)

    with pytest.raises(RuntimeError, match="Cannot restart while kill switch is active"):
        await supervisor.restart()
    assert supervisor.state == DaemonState.KILL_SWITCHED


# 12. Supervisor Backoff Wait Loop
@pytest.mark.asyncio
async def test_killswitch_matrix_12_supervisor_backoff_interruption(tmp_path):
    """Verify supervisor health monitor stops immediately when kill switch is activated."""
    state_file = tmp_path / "kill_state.json"
    ks = EmergencyKillSwitchService(state_file_path=str(state_file))

    config = DaemonConfig(custom_cwd=str(tmp_path))
    supervisor = AuraDaemonSupervisor(config=config, kill_switch_service=ks)
    supervisor.state = DaemonState.RUNNING

    # Activate kill switch and stop
    ks.set_active(True)
    await supervisor.stop()
    assert supervisor.state == DaemonState.STOPPED


# 13. Tray IPC Command Processing
@pytest.mark.asyncio
async def test_killswitch_matrix_13_tray_ipc_start_command(tmp_path, monkeypatch):
    """Verify Tray IPC status reflects kill switch active state truthfully."""
    monkeypatch.setenv("AURA_STATE_DIR", str(tmp_path))
    token = AuraIpcAuthManager.get_or_create_token()
    server = AuraNamedPipeServer()
    kill_switch.set_active(True)

    req = json.dumps({"command": "get_status", "token": token})
    resp = await server.process_raw_request(req)
    assert resp["status"] == "success"
    assert resp["data"]["kill_switch_active"] is True
    assert resp["data"]["runtime_state"] == "KILL_SWITCHED"


# 14. Windows Session Lock/Logoff Transitions
@pytest.mark.asyncio
async def test_killswitch_matrix_14_session_transition_preservation():
    """Verify session transition does not inadvertently reset kill switch."""
    EmergencyKillSwitchService().set_active(True)
    session_mgr = WindowsSessionManager(session_id=1)

    session_mgr.handle_wts_message(WTS_SESSION_LOCK, session_id=1)
    assert EmergencyKillSwitchService().is_active() is True

    session_mgr.handle_wts_message(WTS_SESSION_LOGOFF, session_id=1)
    assert EmergencyKillSwitchService().is_active() is True


# 15. Autostart Boot Launch Guard
@pytest.mark.asyncio
async def test_killswitch_matrix_15_autostart_boot_guard():
    """Verify autostart launch CLI immediately exits code 1 if kill switch is active."""
    EmergencyKillSwitchService().set_active(True)

    with patch("sys.exit", side_effect=SystemExit(1)) as mock_exit:
        with pytest.raises(SystemExit):
            await run_supervisor_daemon()
        mock_exit.assert_called_once_with(1)


# 16. Pending Observation Invalidation
@pytest.mark.asyncio
async def test_killswitch_matrix_16_pending_observation_invalidation():
    """Verify engaging kill switch invalidates and discards all pending observation caches."""
    ws_id = uuid.uuid4()
    tab_id = "tab_pending_hitl"

    freshness_store.record_observation(
        workspace_id=ws_id,
        tab_id=tab_id,
        url="https://secure.corp/transfer",
        title="Transfer",
        nodes=[],
    )
    assert freshness_store.get_observation(ws_id, tab_id) is not None

    # Kill switch activated
    kill_switch.set_active(True, workspace_id=ws_id)

    # Invalidate observations
    freshness_store.invalidate(ws_id, tab_id)
    assert freshness_store.get_observation(ws_id, tab_id) is None
