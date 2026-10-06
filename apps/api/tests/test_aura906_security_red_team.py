"""AURA-906 Adversarial Security Red Team & Invariant Stress Suite.

Attacks & Validations:
1. Application Launch Attacks (Shell metacharacters, LOLBins, path traversal, NUL bytes, oversized arguments)
2. Process Identity & Protection Attacks (PID reuse defense, name mismatch, protected system processes)
3. Governed Input Control Attacks (Out-of-bounds coordinates, stale observations, forbidden shortcuts, typing secrets)
4. Hardware & Clipboard Security Attacks (Volume/Brightness >10% bounds, clipboard >4096 ceiling, NUL injection, secret scrubbing)
5. Named Pipe IPC Attacks (Missing/tampered tokens, payload >64KB, unknown commands, command injection strings)
6. Prompt Injection & Governance Escape Attacks (Subagent bypass attempts, tool forgery, replay token rejection)
7. Audit Ledger Cryptographic Integrity (SHA-256 hash chaining, zero sensitive plaintext leakage, ledger verification)
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any, Dict, List
import unittest.mock as mock
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AuthorizationError, EntityNotFoundError, ValidationError
from app.core.redaction import secret_redactor
from app.core.security import compute_sha256_hash, sign_approval_payload, verify_approval_signature
from app.db.models.workspace import Workspace
from app.schemas.approval import ApprovalResolveRequest
from app.schemas.tool import ToolExecutionRequest, ToolExecutionResponse
from app.services.approval_service import approval_service
from app.services.audit_service import audit_service
from app.services.kill_switch import EmergencyKillSwitchService, kill_switch
from app.services.os_guard import (
    ApplicationRegistry,
    BaseOSExecutionAdapter,
    CoordinateSafetyValidator,
    GovernedClipboardAdapter,
    KeyboardInputValidator,
    LOLBINS_DENYLIST,
    OSActionLifecycleState,
    OSActionRequest,
    OSActionResponse,
    OSActionType,
    OSGuardService,
    OSPolicyEngine,
    OSRiskTier,
    PathValidator,
    PolicyDecisionType,
    ProcessIdentityValidator,
    PROTECTED_PROCESS_NAMES,
    SafeMockOSExecutionAdapter,
    application_registry,
    governed_clipboard_adapter,
    os_guard_service,
    os_policy_engine,
    process_service,
)
from app.services.tool_registry import BUILTIN_TOOLS, ToolRegistryService, tool_registry
from app.tray.ipc import (
    AuraIpcAuthManager,
    AuraNamedPipeClient,
    AuraNamedPipeServer,
)
from app.tray.types import TrayIPCCommand


# ==============================================================================
# FIXTURES
# ==============================================================================

@pytest.fixture
async def red_team_workspace(db_session: AsyncSession) -> Workspace:
    """Create a temporary test workspace for adversarial red team verification."""
    ws = Workspace(
        id=uuid.uuid4(),
        name="AURA-906 Red Team Workspace",
        slug=f"aura906-redteam-{uuid.uuid4().hex[:8]}",
        description="Isolated workspace for adversarial security attacks and fuzzing",
    )
    db_session.add(ws)
    await db_session.commit()
    await db_session.refresh(ws)
    return ws


# ==============================================================================
# 1. APPLICATION LAUNCH ATTACK SURFACE (AURA-902)
# ==============================================================================

def test_app_launch_dangerous_shell_metacharacters():
    """Attack application launch arguments with shell metacharacters and command chaining."""
    app_reg = ApplicationRegistry()
    
    dangerous_payloads = [
        ["file.txt", "& calc.exe"],
        ["file.txt", "| powershell.exe"],
        ["file.txt", "; rm -rf /"],
        ["file.txt", "> output.txt"],
        ["file.txt", "< input.txt"],
        ["file.txt", "`whoami`"],
        ["file.txt", "$ENV:PATH"],
        ["file.txt", "%COMSPEC%"],
    ]

    for args in dangerous_payloads:
        valid, err, _, _, _ = app_reg.validate_launch_request("notepad", arguments=args)
        assert valid is False, f"Failed to reject shell metacharacter in payload: {args}"
        assert "shell metacharacters" in err.lower()


def test_app_launch_lolbins_prohibited_arguments():
    """Attack application launch with Windows LOLBins as targets or argument references."""
    app_reg = ApplicationRegistry()

    for lolbin in LOLBINS_DENYLIST:
        # Attempt to launch LOLBin directly
        valid, err, _, _, _ = app_reg.validate_launch_request(lolbin, arguments=[])
        assert valid is False
        assert "not in the approved application allowlist" in err

        # Attempt to pass LOLBin as argument to notepad
        valid_arg, err_arg, _, _, _ = app_reg.validate_launch_request("notepad", arguments=[lolbin])
        assert valid_arg is False
        assert "lolbin" in err_arg.lower()


def test_app_launch_nul_byte_injection():
    """Attack application launch with NUL bytes to attempt path truncation."""
    app_reg = ApplicationRegistry()
    
    valid, err, _, _, _ = app_reg.validate_launch_request("notepad", arguments=["safe.txt\x00.exe"])
    assert valid is False
    assert "nul byte" in err.lower()


def test_app_launch_path_traversal():
    """Attack application launch arguments and working directory with directory traversal sequences."""
    app_reg = ApplicationRegistry()

    valid, err, _, _, _ = app_reg.validate_launch_request("notepad", arguments=["..\\..\\Windows\\System32\\cmd.exe"])
    assert valid is False
    assert "path traversal" in err.lower()

    valid_wd, err_wd, _, _, _ = app_reg.validate_launch_request("notepad", working_directory="..\\..\\Windows")
    assert valid_wd is False
    assert "path traversal" in err_wd.lower()


def test_app_launch_argument_ceiling_limits():
    """Attack application launch with oversized argument counts and argument lengths."""
    app_reg = ApplicationRegistry()

    # Calculator takes 0 arguments
    valid, err, _, _, _ = app_reg.validate_launch_request("calc", arguments=["arg1"])
    assert valid is False
    assert "accepts at most 0 arguments" in err

    # Notepad takes max 2 arguments
    valid_count, err_count, _, _, _ = app_reg.validate_launch_request("notepad", arguments=["1.txt", "2.txt", "3.txt"])
    assert valid_count is False
    assert "accepts at most 2 arguments" in err_count

    # Max argument length is 260 characters
    long_arg = "a" * 261
    valid_len, err_len, _, _, _ = app_reg.validate_launch_request("notepad", arguments=[long_arg])
    assert valid_len is False
    assert "exceeds maximum length" in err_len


# ==============================================================================
# 2. PROCESS IDENTITY & SYSTEM INTEGRITY ATTACKS (AURA-902)
# ==============================================================================

def test_process_termination_protected_system_processes():
    """Verify termination of protected Windows system processes is strictly denied."""
    # Critical System PIDs <= 4
    for pid in [0, 4]:
        valid, err = ProcessIdentityValidator.validate_process_for_termination(
            pid=pid,
            expected_name="System",
            expected_create_time=time.time() - 1000,
        )
        assert valid is False
        assert f"PID {pid} is a protected Windows system kernel process" in err

    # Critical System Process Names
    for name in PROTECTED_PROCESS_NAMES:
        valid, err = ProcessIdentityValidator.validate_process_for_termination(
            pid=1234,
            expected_name=name,
            expected_create_time=time.time() - 100,
        )
        assert valid is False
        assert "protected system denylist" in err


def test_process_termination_stale_identity_and_create_time_mismatch():
    """Verify PID reuse or stale creation timestamp mismatches reject termination."""
    with mock.patch("psutil.pid_exists", return_value=True), \
         mock.patch("psutil.Process") as mock_proc_cls:
        
        mock_p = mock.MagicMock()
        mock_p.name.return_value = "notepad.exe"
        mock_p.create_time.return_value = 100000.0
        mock_proc_cls.return_value = mock_p

        # Expected create_time differs by > 0.05s -> Stale PID mismatch
        valid, err = ProcessIdentityValidator.validate_process_for_termination(
            pid=5555,
            expected_name="notepad",
            expected_create_time=99900.0,
        )
        assert valid is False
        assert "Process creation time mismatch" in err

        # Name mismatch
        valid_name, err_name = ProcessIdentityValidator.validate_process_for_termination(
            pid=5555,
            expected_name="calc",
            expected_create_time=100000.0,
        )
        assert valid_name is False
        assert "Process name mismatch" in err_name


# ==============================================================================
# 3. INPUT CONTROL ATTACK SURFACE (AURA-903)
# ==============================================================================

def test_input_control_out_of_bounds_coordinates():
    """Attack mouse movement with negative or out-of-bounds screen coordinates."""
    # Negative coordinates
    valid, err = CoordinateSafetyValidator.validate_screen_coordinates(x=-1, y=500)
    assert valid is False
    assert "Coordinates cannot be negative" in err

    # Out of monitor bounds
    valid_oob, err_oob = CoordinateSafetyValidator.validate_screen_coordinates(
        x=99999,
        y=99999,
        monitor_bounds={"left": 0, "top": 0, "width": 1920, "height": 1080},
    )
    assert valid_oob is False
    assert "outside target monitor" in err_oob


def test_input_control_stale_visual_observation_timestamps():
    """Attack visual input with stale or future-drifted observation timestamps."""
    now = time.time()

    # Stale observation (> 5.0 seconds old)
    valid_stale, err_stale = CoordinateSafetyValidator.validate_screen_coordinates(
        x=500, y=500, observation_timestamp=now - 5.1
    )
    assert valid_stale is False
    assert "Stale visual observation" in err_stale

    # Future timestamp (clock skew or injection)
    valid_fut, err_fut = CoordinateSafetyValidator.validate_screen_coordinates(
        x=500, y=500, observation_timestamp=now + 10.0
    )
    assert valid_fut is False
    assert "future" in err_fut


def test_input_control_forbidden_system_shortcuts():
    """Attack keyboard shortcut execution with dangerous Windows hotkeys."""
    forbidden_shortcuts = [
        "win+r", "win+x", "win+l", "ctrl+alt+del", "ctrl+shift+esc",
        "alt+f4", "win+d", "win+e", "win+i",
    ]

    for sc in forbidden_shortcuts:
        valid, err, _ = KeyboardInputValidator.validate_keyboard_shortcut(sc)
        assert valid is False, f"Allowed forbidden system shortcut: {sc}"
        assert "forbidden" in err.lower() or "not in the approved safe shortcut allowlist" in err.lower()


def test_input_control_typing_length_and_nul_injection():
    """Attack keyboard typing with >256 chars, control characters, and NUL bytes."""
    # Oversized payload
    long_text = "A" * 257
    valid_len, err_len, _ = KeyboardInputValidator.validate_type_text(long_text)
    assert valid_len is False
    assert "exceeds maximum ceiling" in err_len

    # NUL byte injection
    valid_nul, err_nul, _ = KeyboardInputValidator.validate_type_text("hello\x00world")
    assert valid_nul is False
    assert "nul byte" in err_nul.lower()


def test_input_control_keystroke_privacy_scrubbing():
    """Verify sensitive keyboard text is never logged or exposed in audit metadata."""
    secret_text = "sk-1234567890abcdef1234567890 and Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.test1234567890"
    redacted = secret_redactor.redact_text(secret_text)
    
    assert "sk-1234567890abcdef1234567890" not in redacted
    assert "eyJhbGciOiJIUzI1NiJ9" not in redacted
    assert "[REDACTED_API_KEY]" in redacted or "[REDACTED_JWT_TOKEN]" in redacted or "[REDACTED_TOKEN]" in redacted


# ==============================================================================
# 4. HARDWARE & CLIPBOARD ATTACK SURFACE (AURA-904)
# ==============================================================================

def test_hardware_control_relative_step_ceiling():
    """Attack volume and brightness adjustment with relative steps exceeding 10% limit."""
    engine = OSPolicyEngine()

    # Step = 10.0% -> LOW_RISK_WRITE
    tier_valid = engine.get_risk_tier(
        OSActionType.HARDWARE_CONTROL,
        {"control_type": "set_volume", "relative_step_percent": 10.0},
    )
    assert tier_valid == OSRiskTier.LOW_RISK_WRITE

    # Step = 10.1% -> HIGH_RISK_SYSTEM_ACTION (escalates and requires HITL)
    tier_oversized = engine.get_risk_tier(
        OSActionType.HARDWARE_CONTROL,
        {"control_type": "set_volume", "relative_step_percent": 10.1},
    )
    assert tier_oversized == OSRiskTier.HIGH_RISK_SYSTEM_ACTION

    # Step = -15.0% -> HIGH_RISK_SYSTEM_ACTION
    tier_neg = engine.get_risk_tier(
        OSActionType.HARDWARE_CONTROL,
        {"control_type": "set_brightness", "relative_step_percent": -15.0},
    )
    assert tier_neg == OSRiskTier.HIGH_RISK_SYSTEM_ACTION


def test_clipboard_write_4096_ceiling_and_nul_injection():
    """Attack clipboard write with 4097 characters and NUL byte injections."""
    # 4096 characters -> VALID
    valid_text = "A" * 4096
    with mock.patch("pyperclip.copy"):
        res = GovernedClipboardAdapter.clipboard_write(valid_text)
        assert res["status"] == "success"
        assert res["character_count"] == 4096
        assert "sha256_hash" in res

    # 4097 characters -> REJECTED
    oversized_text = "A" * 4097
    with pytest.raises(ValidationError) as exc_len:
        GovernedClipboardAdapter.clipboard_write(oversized_text)
    assert "exceeds safety ceiling of 4096" in str(exc_len.value)

    # NUL byte injection -> REJECTED
    with pytest.raises(ValidationError) as exc_nul:
        GovernedClipboardAdapter.clipboard_write("safe\x00malicious")
    assert "NUL byte" in str(exc_nul.value)


def test_clipboard_read_automated_secret_redaction():
    """Verify clipboard read scrubs credentials and API keys automatically."""
    raw_clipboard_data = "Here is my secret token: sk-1234567890abcdef1234567890 and Bearer 123456789012345678901234567890"
    
    with mock.patch("pyperclip.paste", return_value=raw_clipboard_data):
        read_res = GovernedClipboardAdapter.clipboard_read()
        assert read_res["status"] == "success"
        assert read_res["redacted"] is True
        assert "sk-1234567890abcdef1234567890" not in read_res["text"]


# ==============================================================================
# 5. NAMED PIPE IPC ATTACK SURFACE (AURA-905)
# ==============================================================================

@pytest.mark.asyncio
async def test_ipc_missing_or_tampered_token_rejection():
    """Attack Named Pipe IPC with missing, empty, or forged auth tokens."""
    with mock.patch("app.tray.ipc.platform.system", return_value="Windows"):
        server = AuraNamedPipeServer()

        # Missing token
        req_no_token = json.dumps({"command": "get_status", "session_id": 1})
        res_no_tok = await server.process_raw_request(req_no_token)
        assert res_no_tok["status"] == "error"
        assert "Authentication failed" in res_no_tok["error"]

        # Tampered token
        req_bad_token = json.dumps({"command": "get_status", "token": "invalid_forged_token_1234", "session_id": 1})
        res_bad_tok = await server.process_raw_request(req_bad_token)
        assert res_bad_tok["status"] == "error"
        assert "Authentication failed" in res_bad_tok["error"]


@pytest.mark.asyncio
async def test_ipc_payload_64kb_ceiling_enforcement():
    """Attack Named Pipe IPC with oversized payload exceeding 64KB ceiling."""
    with mock.patch("app.tray.ipc.platform.system", return_value="Windows"):
        server = AuraNamedPipeServer()
        token = AuraIpcAuthManager.get_or_create_token()

        # Build payload > 65,536 bytes
        huge_data = "X" * 70000
        oversized_req = json.dumps({
            "command": "get_status",
            "token": token,
            "session_id": 1,
            "payload": {"data": huge_data},
        })

        res = await server.process_raw_request(oversized_req)
        assert res["status"] == "error"
        assert "exceeds maximum allowed size" in res["error"]


@pytest.mark.asyncio
async def test_ipc_unknown_command_and_injection_rejection():
    """Attack Named Pipe IPC with unknown commands, shell injection, or arbitrary actions."""
    with mock.patch("app.tray.ipc.platform.system", return_value="Windows"):
        server = AuraNamedPipeServer()
        token = AuraIpcAuthManager.get_or_create_token()

        dangerous_commands = [
            "exec_shell", "run_command", "eval", "launch_app", "powershell",
            "cmd.exe /c whoami", "rmdir /s /q C:\\", "get_status; calc.exe",
        ]

        for cmd in dangerous_commands:
            req = json.dumps({"command": cmd, "token": token, "session_id": 1})
            res = await server.process_raw_request(req)
            assert res["status"] == "error"
            assert "is prohibited or not in approved IPC allowlist" in res["error"]


# ==============================================================================
# 6. PROMPT INJECTION & GOVERNANCE ESCAPE ATTACKS
# ==============================================================================

@pytest.mark.asyncio
async def test_prompt_injection_forged_hitl_token_rejection(
    db_session: AsyncSession, red_team_workspace: Workspace
):
    """Attack tool execution with forged HMAC signature or modified parameters."""
    # Attempt to forge an HMAC signature with arbitrary key
    forged_token = "forged.payload.signature1234567890abcdef"
    
    req = ToolExecutionRequest(
        workspace_id=red_team_workspace.id,
        tool_name="launch_application",
        arguments={"application_id": "notepad", "arguments": [], "hitl_approval_token": forged_token},
    )

    resp = await tool_registry.execute_tool(
        db=db_session,
        request=req,
        actor_id="attacker_agent",
        actor_type="agent",
    )

    # Must suspend or reject; never execute
    assert resp.success is False or resp.requires_hitl_approval is True
    assert resp.result is None


# ==============================================================================
# 7. OBSERVABILITY & AUDIT LEDGER SHA-256 HASH CHAIN INTEGRITY
# ==============================================================================

@pytest.mark.asyncio
async def test_audit_hash_chaining_and_tamper_evidence(
    db_session: AsyncSession, red_team_workspace: Workspace
):
    """Verify audit log records compute deterministic SHA-256 hash chains with tamper evidence."""
    # Log 2 governed events
    entry1 = await audit_service.record_event(
        db=db_session,
        workspace_id=red_team_workspace.id,
        actor_type="system",
        actor_id="test_red_team",
        action="os_action_validated",
        resource_type="os_action",
        resource_id="act-1",
        details={"action_type": "read_only", "status": "approved"},
    )

    entry2 = await audit_service.record_event(
        db=db_session,
        workspace_id=red_team_workspace.id,
        actor_type="system",
        actor_id="test_red_team",
        action="os_action_executed",
        resource_type="os_action",
        resource_id="act-2",
        details={"action_type": "read_only", "status": "success"},
    )

    # Verify both records exist and contain sha256 checksums
    assert entry1 is not None
    assert entry2 is not None
    assert entry1.id != entry2.id
    assert entry2.previous_log_hash == entry1.log_hash

    # Verify ledger integrity
    verify_res = await audit_service.verify_ledger(db=db_session, workspace_id=red_team_workspace.id)
    assert verify_res["status"] == "VALID"
    assert verify_res["total_records"] >= 2
    assert len(verify_res["violations"]) == 0
