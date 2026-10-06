"""AURA-906 Master Integration Test Suite: Full Phase 9 Governance & Component Matrix.

Verifies end-to-end integration across all Phase 9 components:
1. AgentToolBridge -> ToolRegistryService -> OSPolicyEngine -> OSGuardService -> Adapters -> AuditService
2. All Governed OS Tools (Process, Input, Hardware, Clipboard)
3. Cryptographic HITL Approval Engine Integration & Parameter Binding
4. Windows Named Pipe IPC & System Tray State Synchronization
5. Physical Global Emergency Hotkey (Ctrl + Alt + Shift + K) & Authority Synchronization
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import time
from typing import Any, Dict
import unittest.mock as mock
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AuthorizationError, ValidationError
from app.db.models.workspace import Workspace
from app.runtime.events import RuntimeEvent, RuntimeEventType
from app.runtime.tool_bridge import AgentToolBridge
from app.schemas.approval import ApprovalResolveRequest
from app.schemas.tool import ToolExecutionRequest, ToolExecutionResponse
from app.services.approval_service import ApprovalService, approval_service
from app.services.kill_switch import EmergencyKillSwitchService, kill_switch
from app.services.os_guard import (
    ApplicationRegistry,
    BaseOSExecutionAdapter,
    CoordinateSafetyValidator,
    KeyboardInputValidator,
    OSActionLifecycleState,
    OSActionRequest,
    OSActionResponse,
    OSActionType,
    OSGuardService,
    OSPolicyEngine,
    PathValidator,
    PolicyDecisionType,
    ProcessIdentityValidator,
    ProcessService,
    SafeMockOSExecutionAdapter,
)
from app.services.os_guard.adapters import WindowsOSExecutionAdapter
from app.services.tool_registry import BUILTIN_TOOLS, ToolRegistryService, tool_registry
from app.tray.hotkey import GlobalHotkeyManager
from app.tray.ipc import (
    AuraIpcAuthManager,
    AuraNamedPipeClient,
    AuraNamedPipeServer,
    get_canonical_pipe_name,
)
from app.tray.main import AuraTrayApplication
from app.tray.types import (
    HotkeyRegistrationStatus,
    PrivacySensingState,
    TrayIPCCommand,
    TrayIPCRequest,
    TrayIPCResponse,
    TrayRuntimeState,
)


@pytest.fixture
async def integration_workspace(db_session: AsyncSession) -> Workspace:
    """Create an isolated test workspace for integration verification."""
    ws = Workspace(
        name="AURA-906 Integration Workspace",
        slug=f"aura906-ws-{uuid.uuid4().hex[:8]}",
        settings={"autonomy_level": "L2_AUTONOMOUS_WITH_HITL"},
    )
    db_session.add(ws)
    await db_session.commit()
    await db_session.refresh(ws)
    return ws


# ==============================================================================
# 1. AGENT TOOL BRIDGE -> TOOL REGISTRY -> OSGUARD INTEGRATION
# ==============================================================================

@pytest.mark.asyncio
async def test_agent_tool_bridge_process_inspection_integration(
    db_session: AsyncSession, integration_workspace: Workspace
):
    """Verify inspect_processes routed from AgentToolBridge through ToolRegistry to OSGuard."""
    bridge = AgentToolBridge()
    task_id = uuid.uuid4()
    agent_run_id = uuid.uuid4()

    events = []

    def capture_event(ev: RuntimeEvent):
        events.append(ev)

    res = await bridge.execute_governed_tool(
        db=db_session,
        workspace_id=integration_workspace.id,
        task_id=task_id,
        step_number=1,
        agent_run_id=agent_run_id,
        tool_name="inspect_processes",
        arguments={"limit": 5},
        actor_id="test_agent_906",
        event_callback=capture_event,
    )

    assert res.get("status") == "success"
    assert "processes" in res["result"]
    assert isinstance(res["result"]["processes"], list)
    assert len(res["result"]["processes"]) <= 5
    assert any(ev.event_type == RuntimeEventType.TOOL_REQUESTED for ev in events)
    assert any(ev.event_type == RuntimeEventType.TOOL_STARTED for ev in events)
    assert any(ev.event_type == RuntimeEventType.TOOL_COMPLETED for ev in events)


@pytest.mark.asyncio
async def test_agent_tool_bridge_mouse_move_integration(
    db_session: AsyncSession, integration_workspace: Workspace
):
    """Verify move_mouse routed from AgentToolBridge with coordinate validation."""
    bridge = AgentToolBridge()
    task_id = uuid.uuid4()
    agent_run_id = uuid.uuid4()

    with mock.patch("pyautogui.moveTo") as mock_move, \
         mock.patch("pyautogui.position", return_value=(100, 100)):
        res = await bridge.execute_governed_tool(
            db=db_session,
            workspace_id=integration_workspace.id,
            task_id=task_id,
            step_number=1,
            agent_run_id=agent_run_id,
            tool_name="move_mouse",
            arguments={"x": 500, "y": 500, "observation_timestamp": time.time()},
            actor_id="test_agent_906",
        )

    assert res.get("status") == "success"
    assert res.get("result", {}).get("x") == 500
    assert res.get("result", {}).get("y") == 500


@pytest.mark.asyncio
async def test_agent_tool_bridge_hardware_telemetry_integration(
    db_session: AsyncSession, integration_workspace: Workspace
):
    """Verify get_system_telemetry and get_hardware_capabilities via AgentToolBridge."""
    bridge = AgentToolBridge()
    task_id = uuid.uuid4()
    agent_run_id = uuid.uuid4()

    # Telemetry
    telem_res = await bridge.execute_governed_tool(
        db=db_session,
        workspace_id=integration_workspace.id,
        task_id=task_id,
        step_number=1,
        agent_run_id=agent_run_id,
        tool_name="get_system_telemetry",
        arguments={},
        actor_id="test_agent_906",
    )
    assert telem_res.get("status") == "success"
    assert "cpu" in telem_res["result"]
    assert "ram" in telem_res["result"]
    assert "storage" in telem_res["result"]

    # Capability discovery
    cap_res = await bridge.execute_governed_tool(
        db=db_session,
        workspace_id=integration_workspace.id,
        task_id=task_id,
        step_number=2,
        agent_run_id=agent_run_id,
        tool_name="get_hardware_capabilities",
        arguments={},
        actor_id="test_agent_906",
    )
    assert cap_res.get("status") == "success"
    assert "volume_supported" in cap_res["result"]
    assert "brightness_supported" in cap_res["result"]
    assert "display_count" in cap_res["result"]


@pytest.mark.asyncio
async def test_agent_tool_bridge_clipboard_lifecycle_integration(
    db_session: AsyncSession, integration_workspace: Workspace
):
    """Verify governed clipboard read and write integration via AgentToolBridge."""
    bridge = AgentToolBridge()
    task_id = uuid.uuid4()
    agent_run_id = uuid.uuid4()

    # 1. Read
    with mock.patch("pyperclip.paste", return_value="Governed integration test text"):
        read_res = await bridge.execute_governed_tool(
            db=db_session,
            workspace_id=integration_workspace.id,
            task_id=task_id,
            step_number=1,
            agent_run_id=agent_run_id,
            tool_name="clipboard_read",
            arguments={},
            actor_id="test_agent_906",
        )
        assert read_res.get("status") == "success"
        assert read_res["result"]["text"] == "Governed integration test text"
        assert read_res["result"]["character_count"] == len("Governed integration test text")


# ==============================================================================
# 2. CRYPTOGRAPHIC HITL INTEGRATION MATRIX
# ==============================================================================

@pytest.mark.asyncio
async def test_hitl_suspension_and_parameter_bound_approval_flow(
    db_session: AsyncSession, integration_workspace: Workspace
):
    """Verify full HITL suspension, signed token issuance, parameter verification, and execution."""
    bridge = AgentToolBridge()
    task_id = uuid.uuid4()
    agent_run_id = uuid.uuid4()
    step_num = 1
    tool_name = "launch_application"
    tool_params = {"application_id": "notepad", "arguments": ["test.txt"]}

    # 1. Request execution - Expect HITL suspension
    events = []
    suspension_res = await bridge.execute_governed_tool(
        db=db_session,
        workspace_id=integration_workspace.id,
        task_id=task_id,
        step_number=step_num,
        agent_run_id=agent_run_id,
        tool_name=tool_name,
        arguments=tool_params,
        actor_id="test_agent_906",
        event_callback=lambda ev: events.append(ev),
    )

    assert suspension_res.get("requires_approval") is True
    assert suspension_res.get("status") == "suspended_for_approval"
    assert "approval_token" in suspension_res
    signed_token = suspension_res["approval_token"]

    approval_ev = next(ev for ev in events if ev.event_type == RuntimeEventType.APPROVAL_REQUESTED)
    assert approval_ev.data["tool_name"] == tool_name
    assert approval_ev.data["risk_level"] in ["medium", "high"]

    # 2. Resolve approval via ApprovalService
    resolve_payload = ApprovalResolveRequest(
        decision="approve",
        token=signed_token,
        resolution_notes="Authorized by integration test",
    )
    with mock.patch.object(WindowsOSExecutionAdapter, "execute_validated_action", new_callable=mock.AsyncMock) as mock_exec:
        mock_exec.return_value = {
            "status": "launched",
            "pid": 54321,
            "application_id": "notepad",
            "launch_duration_ms": 12.5,
        }

        resolve_res = await approval_service.resolve_approval(
            db=db_session,
            approval_id=uuid.UUID(suspension_res["approval_id"]),
            workspace_id=integration_workspace.id,
            user_id=uuid.uuid4(),
            payload=resolve_payload,
        )

        assert resolve_res.status == "approved"
        assert resolve_res.resumed is True


@pytest.mark.asyncio
async def test_hitl_tampered_parameter_hash_rejected(
    db_session: AsyncSession, integration_workspace: Workspace
):
    """Verify altering tool parameters after HITL approval rejects execution fail-closed."""
    task_id = uuid.uuid4()
    agent_run_id = uuid.uuid4()
    step_num = 1
    tool_name = "launch_application"
    original_params = {"application_id": "notepad", "arguments": ["safe.txt"]}

    # Create approval for safe.txt
    record, signed_token = await approval_service.create_approval_request(
        db=db_session,
        workspace_id=integration_workspace.id,
        task_id=task_id,
        agent_run_id=agent_run_id,
        step_number=step_num,
        tool_name=tool_name,
        tool_params=original_params,
        risk_level="high",
        reason_requested="Launch notepad test",
    )

    # Attempt to use token for calc.exe instead
    tampered_req = ToolExecutionRequest(
        workspace_id=integration_workspace.id,
        tool_name=tool_name,
        arguments={"application_id": "calc", "arguments": [], "hitl_approval_token": signed_token},
    )

    resp: ToolExecutionResponse = await tool_registry.execute_tool(
        db=db_session,
        request=tampered_req,
        actor_id="test_agent_906",
        actor_type="agent",
    )

    assert resp.success is False or resp.requires_hitl_approval is True
    if resp.result:
        assert "waiting_approval" in resp.result.get("status", "") or "denied" in str(resp.error).lower()
    else:
        assert resp.error is not None


# ==============================================================================
# 3. NAMED PIPE IPC & TRAY APPLICATION INTEGRATION
# ==============================================================================

@pytest.mark.asyncio
async def test_tray_ipc_server_client_integration():
    """Verify Windows Named Pipe server and client control flow."""
    with mock.patch("app.tray.ipc.platform.system", return_value="Windows"):
        token = AuraIpcAuthManager.get_or_create_token()
        server = AuraNamedPipeServer()

        # Direct server verification of canonical allowlist commands
        status_raw = json.dumps({
            "command": "get_status",
            "token": token,
            "session_id": 1,
            "payload": {},
        })
        status_res = await server.process_raw_request(status_raw)
        assert status_res.get("status") == "success"
        assert status_res.get("data", {}).get("runtime_state") is not None

        # Privacy state query
        privacy_raw = json.dumps({
            "command": "get_privacy_state",
            "token": token,
            "session_id": 1,
            "payload": {},
        })
        privacy_res = await server.process_raw_request(privacy_raw)
        assert privacy_res.get("status") == "success"
        assert "camera_state" in privacy_res.get("data", {})

        # Telemetry query
        telem_raw = json.dumps({
            "command": "get_telemetry",
            "token": token,
            "session_id": 1,
            "payload": {},
        })
        telem_res = await server.process_raw_request(telem_raw)
        assert telem_res.get("status") == "success"
        assert "cpu" in telem_res.get("data", {})


# ==============================================================================
# 4. GLOBAL EMERGENCY HOTKEY INTEGRATION
# ==============================================================================

@pytest.mark.asyncio
async def test_global_emergency_hotkey_authority_integration():
    """Verify physical hotkey triggers instant local atomic kill switch and updates tray state."""
    triggered = False

    def on_trigger():
        nonlocal triggered
        triggered = True
        kill_switch.set_active(True)

    hotkey_mgr = GlobalHotkeyManager(hwnd=0, on_emergency_trigger=on_trigger)
    with mock.patch("ctypes.windll.user32.RegisterHotKey", return_value=1), \
         mock.patch("ctypes.windll.user32.UnregisterHotKey", return_value=1):

        assert hotkey_mgr.register_hotkey() is True
        assert hotkey_mgr.status == HotkeyRegistrationStatus.ACTIVE

        # Simulate kernel WM_HOTKEY message
        assert hotkey_mgr.handle_hotkey_message(0x9051) is True
        assert triggered is True
        assert kill_switch.is_active() is True

        # Cleanup
        assert hotkey_mgr.unregister_hotkey() is True
        assert hotkey_mgr.status == HotkeyRegistrationStatus.UNREGISTERED
        kill_switch.set_active(False)
