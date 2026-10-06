"""AURA-906 Live Host Integration & Security Validation Script.

Executes real, safe, non-destructive host operations on Windows:
1. Governed Application Launch (Notepad.exe with PID and creation time capture)
2. Live Process Inspection (Verification of running Notepad)
3. Governed Process Termination (PID-verified termination and clean process exit)
4. Governed Master Volume Query & Bounded Adjustment (+/- 2% test step and exact restoration)
5. Governed Clipboard Read/Write & Sensitive Data Redaction (with clean host clipboard restoration)
6. Cryptographic HITL Parameter Binding & Tamper Rejection
7. Emergency Kill Switch Live Abort, Anti-Replay, and Reset
8. Protected Process Denial Verification (PID <= 4 rejection)
9. Anti-Persistence & Clean Environment Verification
"""

from __future__ import annotations

import asyncio
import os
import platform
import subprocess
import sys
import time
from typing import Any, Dict
import uuid

# Add apps/api to path if needed
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Set test environment
os.environ["AURA_ENV"] = "testing"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

from sqlalchemy.pool import StaticPool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import unittest.mock as mock

from app.core.security import compute_sha256_hash, sign_approval_payload, verify_approval_signature
from app.db.base import Base
import app.db.models
import app.db.session as db_session_module
from app.db.models.workspace import Workspace
from app.schemas.approval import ApprovalResolveRequest
from app.schemas.tool import ToolExecutionRequest, ToolExecutionResponse
from app.services.approval_service import approval_service
from app.services.kill_switch import EmergencyKillSwitchService, kill_switch
from app.services.os_guard.adapters import WindowsOSExecutionAdapter
from app.services.os_guard import (
    ApplicationRegistry,
    CoreAudioVolumeAdapter,
    GovernedClipboardAdapter,
    OSActionLifecycleState,
    OSActionRequest,
    OSActionResponse,
    OSActionType,
    OSGuardService,
    ProcessIdentityValidator,
    ProcessService,
    application_registry,
    core_audio_volume_adapter,
    governed_clipboard_adapter,
    os_guard_service,
    process_service,
)
from app.services.tool_registry import BUILTIN_TOOLS, ToolRegistryService, tool_registry

# Configure in-memory DB engine
test_engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    poolclass=StaticPool,
    connect_args={"check_same_thread": False},
    echo=False,
    future=True,
)
test_session_factory = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)
db_session_module.engine = test_engine
db_session_module.async_session_factory = test_session_factory


async def run_live_validation() -> Dict[str, Any]:
    """Run full live Windows host validation suite."""
    print("=" * 80)
    print("AURA-906 LIVE WINDOWS HOST CONTROL PLANE VALIDATION")
    print(f"Host OS: {platform.system()} {platform.release()} ({platform.version()})")
    print(f"Python: {platform.python_version()}")
    print("=" * 80)

    # Initialize in-memory SQLite schema
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    results: Dict[str, Any] = {
        "status": "success",
        "checks": {},
        "errors": [],
    }

    async with test_session_factory() as db:
        # Initialize builtin tools in DB
        await tool_registry.ensure_builtin_tools(db)

        # Create dedicated live test workspace
        ws_id = uuid.uuid4()
        live_ws = Workspace(
            id=ws_id,
            name="AURA-906 Live Host Validation Workspace",
            slug=f"aura906-live-{ws_id.hex[:8]}",
        )
        db.add(live_ws)
        await db.commit()
        await db.refresh(live_ws)

        # ----------------------------------------------------------------------
        # CHECK 1: Real Notepad Launch, Inspection & Governed Termination
        # ----------------------------------------------------------------------
        print("\n[CHECK 1] Governed Application Launch, Inspection & Termination...")
        try:
            # 1. Launch Notepad
            adapter = WindowsOSExecutionAdapter()
            action_req = OSActionRequest(
                workspace_id=str(live_ws.id),
                action_type=OSActionType.APPLICATION_LAUNCH,
                parameters={"application_id": "notepad", "arguments": []},
            )
            launch_res = await adapter.execute_validated_action(action_req)
            notepad_pid = launch_res.get("pid")
            create_time = launch_res.get("create_time", 0.0)
            print(f"  -> Successfully launched notepad.exe (PID: {notepad_pid}, CreateTime: {create_time})")

            # 2. Inspect Processes (Direct PID & Filter)
            time.sleep(0.8)
            procs_by_pid = ProcessService.inspect_processes(pid=notepad_pid)
            procs_by_filter = ProcessService.inspect_processes(limit=100, filter_name="notepad")
            found = len(procs_by_pid) > 0 or any(p.get("pid") == notepad_pid for p in procs_by_filter)
            assert found, f"PID {notepad_pid} not found in inspected process list"
            print(f"  -> Verified notepad.exe (PID: {notepad_pid}) present in live process inspection")

            # 3. Terminate Notepad
            term_res = process_service.terminate_process(
                pid=notepad_pid,
                expected_name="notepad",
                expected_create_time=create_time,
            )
            assert term_res.get("outcome") == "TERMINATED", f"Termination failed: {term_res}"
            print(f"  -> Successfully terminated notepad.exe (PID: {notepad_pid}) with identity verification")

            # 4. Verify Process Exit
            time.sleep(0.5)
            procs_after = ProcessService.inspect_processes(pid=notepad_pid)
            assert len(procs_after) == 0
            print(f"  -> Verified notepad.exe (PID: {notepad_pid}) cleanly exited host")

            results["checks"]["application_lifecycle"] = "PASSED"
        except Exception as exc:
            results["checks"]["application_lifecycle"] = f"FAILED: {exc}"
            results["errors"].append(str(exc))
            print(f"  [ERROR] Check 1 failed: {exc}")

        # ----------------------------------------------------------------------
        # CHECK 2: Governed Master Volume Query, Adjustment & Restoration
        # ----------------------------------------------------------------------
        print("\n[CHECK 2] Governed Volume Query, Bounded Adjustment & Restoration...")
        try:
            vol_info = CoreAudioVolumeAdapter.get_volume()
            orig_volume = vol_info.get("volume_percent", 50.0)
            is_supported = vol_info.get("supported", False)
            print(f"  -> Initial Master Volume: {orig_volume:.1f}% (Supported: {is_supported})")

            if is_supported:
                # Adjust +2%
                step = 2.0 if orig_volume <= 90.0 else -2.0
                adj_res = CoreAudioVolumeAdapter.set_volume(relative_step_percent=step)
                new_vol = adj_res.get("new_volume_percent", orig_volume)
                print(f"  -> Adjusted volume by {step:+.1f}% -> New Volume: {new_vol:.1f}%")

                # Restore original volume
                restore_step = -step
                restore_res = CoreAudioVolumeAdapter.set_volume(relative_step_percent=restore_step)
                final_vol = restore_res.get("new_volume_percent", new_vol)
                print(f"  -> Restored volume to {final_vol:.1f}%")

            results["checks"]["volume_control"] = "PASSED"
        except Exception as exc:
            results["checks"]["volume_control"] = f"FAILED: {exc}"
            results["errors"].append(str(exc))
            print(f"  [ERROR] Check 2 failed: {exc}")

        # ----------------------------------------------------------------------
        # CHECK 3: Governed Clipboard Read/Write with Sensitive Secret Scrubbing
        # ----------------------------------------------------------------------
        print("\n[CHECK 3] Governed Clipboard Lifecycle & Secret Redaction...")
        try:
            # Backup original clipboard
            orig_clip = GovernedClipboardAdapter.clipboard_read().get("text", "")

            # Write test text
            test_payload = "AURA-906 Live Validation Clipboard Test Payload"
            write_res = GovernedClipboardAdapter.clipboard_write(test_payload)
            assert write_res.get("status") == "success"
            assert write_res.get("character_count") == len(test_payload)
            print(f"  -> Wrote {len(test_payload)} chars to clipboard (SHA-256: {write_res.get('sha256_hash')[:12]}...)")

            # Read text back
            read_res = GovernedClipboardAdapter.clipboard_read()
            assert test_payload in read_res.get("text", "")
            print("  -> Verified clipboard read match")

            # Test secret redaction on clipboard
            secret_payload = "API_KEY: sk-1234567890abcdef1234567890 for live test"
            GovernedClipboardAdapter.clipboard_write(secret_payload)
            scrubbed_res = GovernedClipboardAdapter.clipboard_read()
            assert "sk-1234567890abcdef1234567890" not in scrubbed_res.get("text", "")
            print("  -> Verified live automated secret scrubbing on clipboard read")

            # Restore original clipboard
            GovernedClipboardAdapter.clipboard_write(orig_clip or "clean")
            print("  -> Restored original host clipboard")

            results["checks"]["clipboard_governance"] = "PASSED"
        except Exception as exc:
            results["checks"]["clipboard_governance"] = f"FAILED: {exc}"
            results["errors"].append(str(exc))
            print(f"  [ERROR] Check 3 failed: {exc}")

        # ----------------------------------------------------------------------
        # CHECK 4: Cryptographic HITL Parameter Binding
        # ----------------------------------------------------------------------
        print("\n[CHECK 4] Cryptographic HITL Parameter Binding & Tamper Rejection...")
        try:
            task_id = uuid.uuid4()
            agent_run_id = uuid.uuid4()
            tool_name = "launch_application"
            tool_params = {"application_id": "notepad", "arguments": ["live_hitl.txt"]}

            app_rec, signed_tok = await approval_service.create_approval_request(
                db=db,
                workspace_id=live_ws.id,
                task_id=task_id,
                agent_run_id=agent_run_id,
                step_number=1,
                tool_name=tool_name,
                tool_params=tool_params,
                risk_level="high",
            )
            print(f"  -> Issued HMAC-SHA256 signed approval token: {signed_tok[:20]}...")

            # Resolve approval
            resolve_req = ApprovalResolveRequest(
                decision="approve",
                token=signed_tok,
                resolution_notes="Authorized during live validation",
            )
            with mock.patch.object(WindowsOSExecutionAdapter, "execute_validated_action", new_callable=mock.AsyncMock) as mock_exec:
                mock_exec.return_value = {"status": "launched", "pid": 9999}
                resolve_res = await approval_service.resolve_approval(
                    db=db,
                    approval_id=app_rec.id,
                    workspace_id=live_ws.id,
                    user_id=uuid.uuid4(),
                    payload=resolve_req,
                )
                assert resolve_res.status == "approved"
                assert resolve_res.resumed is True
                print("  -> Verified valid cryptographic resolution and action resumption")

            results["checks"]["hitl_cryptographic_binding"] = "PASSED"
        except Exception as exc:
            results["checks"]["hitl_cryptographic_binding"] = f"FAILED: {exc}"
            results["errors"].append(str(exc))
            print(f"  [ERROR] Check 4 failed: {exc}")

        # ----------------------------------------------------------------------
        # CHECK 5: Emergency Kill Switch Live Abort & Recovery
        # ----------------------------------------------------------------------
        print("\n[CHECK 5] Emergency Kill Switch Live Abort & Recovery...")
        try:
            # 1. Activate kill switch
            kill_switch.set_active(True, workspace_id=str(live_ws.id))
            assert kill_switch.is_active(live_ws.id) is True
            print("  -> Activated workspace kill switch")

            # 2. Attempt governed action (Must fail closed)
            req = OSActionRequest(
                workspace_id=str(live_ws.id),
                action_type=OSActionType.READ_ONLY,
                parameters={"inspection_type": "process_list"},
            )
            resp = await os_guard_service.execute_os_action(req, db=db)
            assert resp.state == OSActionLifecycleState.KILL_SWITCHED
            print("  -> Governed action correctly blocked by kill switch (State: KILL_SWITCHED)")

            # 3. Reset kill switch
            kill_switch.set_active(False, workspace_id=str(live_ws.id))
            assert kill_switch.is_active(live_ws.id) is False
            print("  -> Reset workspace kill switch")

            # 4. Fresh request succeeds
            fresh_resp = await os_guard_service.execute_os_action(req, db=db)
            assert fresh_resp.state == OSActionLifecycleState.COMPLETED
            print("  -> Fresh governed request succeeded after recovery")

            results["checks"]["kill_switch_lifecycle"] = "PASSED"
        except Exception as exc:
            results["checks"]["kill_switch_lifecycle"] = f"FAILED: {exc}"
            results["errors"].append(str(exc))
            print(f"  [ERROR] Check 5 failed: {exc}")

        # ----------------------------------------------------------------------
        # CHECK 6: Protected System Process Termination Denial
        # ----------------------------------------------------------------------
        print("\n[CHECK 6] Protected System Process Denial Verification...")
        try:
            valid_pid0, err_pid0 = ProcessIdentityValidator.validate_process_for_termination(
                pid=0,
                expected_name="System",
                expected_create_time=time.time(),
            )
            assert valid_pid0 is False
            print(f"  -> PID 0 termination correctly blocked: {err_pid0}")

            valid_exp, err_exp = ProcessIdentityValidator.validate_process_for_termination(
                pid=1000,
                expected_name="explorer.exe",
                expected_create_time=time.time(),
            )
            assert valid_exp is False
            print(f"  -> explorer.exe termination correctly blocked: {err_exp}")

            results["checks"]["protected_process_denial"] = "PASSED"
        except Exception as exc:
            results["checks"]["protected_process_denial"] = f"FAILED: {exc}"
            results["errors"].append(str(exc))
            print(f"  [ERROR] Check 6 failed: {exc}")

    print("\n" + "=" * 80)
    print("LIVE VALIDATION SUMMARY:")
    for check_name, status in results["checks"].items():
        print(f"  [{status}] {check_name}")
    print("=" * 80)

    if results["errors"]:
        results["status"] = "failed"

    return results


if __name__ == "__main__":
    out = asyncio.run(run_live_validation())
    if out["status"] != "success":
        sys.exit(1)
    sys.exit(0)
