"""Emergency Kill Switch and Global Execution Abort Service (AURA-507 Hardened).

Provides:
1. Authoritative global & tenant-scoped execution abort state.
2. Canonical kill sequence across sub-agents, Docker sandboxes, managed OS process trees, Playwright browser instances, and MCP servers.
3. Race-safe, concurrent, and idempotent kill switch triggers.
4. Cryptographic SHA-256 audit ledger integration.
5. Local OpenTelemetry tracing instrumentation with fail-safe isolation.
6. Explicit, auditable recovery state machine restoring normal operations safely.
"""

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set
import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.core.process import managed_process_registry
from app.core.telemetry import telemetry_manager
from app.db.models.agent_run import AgentRun, SubAgentRun
from app.db.models.task import Task, TaskStep
from app.mcp.manager import mcp_manager
from app.runtime.sandbox.manager import sandbox_manager
from app.runtime.subagents.pool import subagent_pool
from app.services.audit_service import audit_service
from app.services.tools.browser_manager import browser_manager


class EmergencyKillSwitchService:
    """Provides high-priority emergency kill-switch aborting active runtime, workers, processes, and sandboxes."""

    def __init__(self, state_file_path: Optional[str] = None):
        self._is_active: bool = False
        self._active_workspaces: Set[uuid.UUID] = set()
        self._kill_history: List[Dict[str, Any]] = []
        self._lock = asyncio.Lock()
        
        # Cross-process shared state persistence
        import os
        from pathlib import Path
        default_dir = Path(os.environ.get("AURA_STATE_DIR", Path.home() / ".aura"))
        default_dir.mkdir(parents=True, exist_ok=True)
        self._state_file = Path(state_file_path or os.environ.get("AURA_KILL_STATE_FILE", default_dir / "kill_state.json"))
        self._last_mtime: float = 0.0
        self._sync_from_disk()

    def _sync_from_disk(self) -> None:
        """Sync in-memory state from shared persistent state file if modified."""
        import json
        import os
        try:
            if not self._state_file.exists():
                return
            mtime = os.path.getmtime(self._state_file)
            if mtime == self._last_mtime:
                return
            with open(self._state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._is_active = bool(data.get("is_active_globally", False))
            self._active_workspaces = {
                uuid.UUID(ws) for ws in data.get("active_workspaces", []) if ws
            }
            self._last_mtime = mtime
        except Exception as e:
            logger.debug(f"KillSwitch: Failed syncing state from disk ({e})")

    def _sync_to_disk(self, actor_id: str = "system", reason: str = "") -> None:
        """Atomically persist kill state to shared disk file for cross-process visibility."""
        import json
        import os
        import tempfile
        try:
            data = {
                "is_active_globally": self._is_active,
                "active_workspaces": [str(w) for w in self._active_workspaces],
                "updated_at": time.time(),
                "actor_id": actor_id,
                "reason": reason,
            }
            parent_dir = self._state_file.parent
            parent_dir.mkdir(parents=True, exist_ok=True)
            # Atomic write via temp file + replace
            with tempfile.NamedTemporaryFile("w", dir=parent_dir, delete=False, encoding="utf-8") as tf:
                json.dump(data, tf, indent=2)
                temp_name = tf.name
            os.replace(temp_name, self._state_file)
            self._last_mtime = os.path.getmtime(self._state_file)
        except Exception as e:
            logger.warning(f"KillSwitch: Failed persisting state to disk ({e})")

    def is_active(self, workspace_id: Optional[uuid.UUID] = None) -> bool:
        """Check if global kill switch or workspace-specific kill switch is active."""
        self._sync_from_disk()
        if self._is_active:
            return True
        if workspace_id and workspace_id in self._active_workspaces:
            return True
        return False

    def set_active(self, active: bool = True, workspace_id: Optional[uuid.UUID] = None) -> None:
        """Set active kill-switch state globally or per workspace and persist atomically."""
        if workspace_id:
            if active:
                self._active_workspaces.add(workspace_id)
            else:
                self._active_workspaces.discard(workspace_id)
        else:
            self._is_active = active
            if not active:
                self._active_workspaces.clear()
        self._sync_to_disk(reason="State updated via set_active")

    async def trigger_emergency_kill(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        actor_id: str,
        reason: str = "Emergency kill switch activated by operator",
        target_task_id: Optional[uuid.UUID] = None,
    ) -> Dict[str, Any]:
        """Abort execution immediately across all runtimes, sub-agents, processes, MCP servers, and sandboxes."""
        async with self._lock:
            t0 = time.perf_counter()
            self.set_active(True, workspace_id)
            logger.warning(f"KillSwitch: Triggered for Workspace {workspace_id} by {actor_id} (Reason: {reason})")

            # 1. Cancel active Sub-Agent workers
            t_w0 = time.perf_counter()
            if target_task_id:
                subagent_pool.cancel_task_workers(target_task_id)
            else:
                for task_id in list(subagent_pool._active_workers.keys()):
                    subagent_pool.cancel_task_workers(task_id)
            t_workers = time.perf_counter()

            # 2. Terminate all active Sandbox containers
            sandboxes_terminated = sandbox_manager.terminate_all_sandboxes()
            t_sandbox = time.perf_counter()

            # 3. Terminate all managed OS process trees (Windows/POSIX)
            proc_res = await managed_process_registry.terminate_all_processes(
                workspace_id=workspace_id if target_task_id is None else None
            )
            t_proc = time.perf_counter()

            # 4. Close Playwright browser instances and contexts
            try:
                await browser_manager.close()
            except Exception as e:
                logger.warning(f"KillSwitch: Error closing browser manager: {e}")
            t_browser = time.perf_counter()

            # 5. Stop running MCP subprocesses
            await mcp_manager.stop_all_servers()
            t_mcp = time.perf_counter()

            # 6. Update Database State to CANCELLED
            if target_task_id:
                await db.execute(
                    update(Task)
                    .where(Task.id == target_task_id, Task.status.in_(["running", "waiting_approval", "pending"]))
                    .values(status="cancelled")
                )
                await db.execute(
                    update(TaskStep)
                    .where(TaskStep.task_id == target_task_id, TaskStep.status.in_(["running", "waiting_approval", "pending"]))
                    .values(status="cancelled")
                )
                await db.execute(
                    update(AgentRun)
                    .where(AgentRun.task_id == target_task_id, AgentRun.status.in_(["running", "waiting_approval"]))
                    .values(status="cancelled")
                )
            else:
                await db.execute(
                    update(Task)
                    .where(Task.workspace_id == workspace_id, Task.status.in_(["running", "waiting_approval", "pending"]))
                    .values(status="cancelled")
                )
                await db.execute(
                    update(AgentRun)
                    .where(AgentRun.workspace_id == workspace_id, AgentRun.status.in_(["running", "waiting_approval"]))
                    .values(status="cancelled")
                )

            await db.flush()
            t_db = time.perf_counter()

            # 7. Record Cryptographic Audit Entry
            audit_rec = await audit_service.record_event(
                db=db,
                workspace_id=workspace_id,
                actor_type="user",
                actor_id=actor_id,
                action="EMERGENCY_KILL_SWITCH_TRIGGERED",
                resource_type="workspace",
                resource_id=str(workspace_id),
                details={
                    "target_task_id": str(target_task_id) if target_task_id else "ALL_WORKSPACE_TASKS",
                    "reason": reason,
                    "sandboxes_terminated": sandboxes_terminated,
                    "processes_terminated": proc_res.get("processes_terminated", 0),
                    "total_pids_reaped": proc_res.get("total_pids_reaped", 0),
                },
            )
            t_final = time.perf_counter()

            total_latency_ms = (t_final - t0) * 1000.0

            result = {
                "status": "ABORTED",
                "workspace_id": str(workspace_id),
                "target_task_id": str(target_task_id) if target_task_id else "all",
                "sandboxes_terminated": sandboxes_terminated,
                "processes_terminated": proc_res.get("processes_terminated", 0),
                "total_pids_reaped": proc_res.get("total_pids_reaped", 0),
                "total_latency_ms": round(total_latency_ms, 2),
                "breakdown_ms": {
                    "worker_cancellation_ms": round((t_workers - t_w0) * 1000.0, 2),
                    "sandbox_termination_ms": round((t_sandbox - t_workers) * 1000.0, 2),
                    "process_tree_termination_ms": round((t_proc - t_sandbox) * 1000.0, 2),
                    "browser_cleanup_ms": round((t_browser - t_proc) * 1000.0, 2),
                    "mcp_termination_ms": round((t_mcp - t_browser) * 1000.0, 2),
                    "db_state_update_ms": round((t_db - t_mcp) * 1000.0, 2),
                    "audit_record_ms": round((t_final - t_db) * 1000.0, 2),
                },
                "audit_log_id": audit_rec.id,
                "message": "All execution, workers, processes, and sandboxes terminated successfully.",
            }

            # 8. Record OpenTelemetry Span (fail-safe)
            try:
                with telemetry_manager.start_span(
                    name="emergency_kill_switch",
                    span_type="security",
                    attributes={
                        "aura.workspace_id": str(workspace_id),
                        "kill.actor_id": actor_id,
                        "kill.target_task_id": str(target_task_id) if target_task_id else "all",
                        "kill.sandboxes_terminated": sandboxes_terminated,
                        "kill.processes_terminated": proc_res.get("processes_terminated", 0),
                        "kill.latency_ms": result["total_latency_ms"],
                        "kill.status": "ABORTED",
                    },
                ):
                    pass
            except Exception as otel_err:
                logger.warning(f"KillSwitch: OpenTelemetry span creation failed safely: {otel_err}")

            self._kill_history.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "workspace_id": str(workspace_id),
                "actor_id": actor_id,
                "reason": reason,
                "total_latency_ms": result["total_latency_ms"],
            })
            if len(self._kill_history) > 50:
                self._kill_history.pop(0)

            return result

    async def reset_emergency_state(
        self,
        db: AsyncSession,
        workspace_id: Optional[uuid.UUID] = None,
        actor_id: str = "operator",
        reason: str = "Operator restored normal operations",
    ) -> Dict[str, Any]:
        """Explicit recovery transition: Clear emergency kill state and audit restoration."""
        async with self._lock:
            t0 = time.perf_counter()
            prev_global = self._is_active
            prev_ws_active = bool(workspace_id and workspace_id in self._active_workspaces)

            self.set_active(False, workspace_id)
            logger.info(
                f"KillSwitch: Emergency state reset for workspace={workspace_id} (global_reset={workspace_id is None}) by {actor_id}"
            )

            # Reconcile registries
            active_procs = await managed_process_registry.get_active_processes(workspace_id)
            active_sbx = len(sandbox_manager.docker_sandbox._active_containers)

            # Record Cryptographic Audit Entry
            target_ws = workspace_id or uuid.UUID("00000000-0000-0000-0000-000000000000")
            audit_rec = await audit_service.record_event(
                db=db,
                workspace_id=target_ws,
                actor_type="user",
                actor_id=actor_id,
                action="EMERGENCY_KILL_SWITCH_RECOVERED",
                resource_type="workspace",
                resource_id=str(target_ws),
                details={
                    "scope": "workspace" if workspace_id else "global",
                    "reason": reason,
                    "active_processes_count": len(active_procs),
                    "active_sandboxes_count": active_sbx,
                },
            )

            duration_ms = (time.perf_counter() - t0) * 1000.0

            result = {
                "status": "RECOVERED",
                "workspace_id": str(workspace_id) if workspace_id else "global",
                "is_active_globally": self._is_active,
                "active_workspaces": [str(w) for w in self._active_workspaces],
                "active_processes_count": len(active_procs),
                "active_sandboxes_count": active_sbx,
                "recovery_duration_ms": round(duration_ms, 2),
                "audit_log_id": audit_rec.id,
                "message": "Emergency kill state reset successfully. System returned to normal operation.",
            }

            # OpenTelemetry Span (fail-safe)
            try:
                with telemetry_manager.start_span(
                    name="emergency_kill_switch_reset",
                    span_type="security",
                    attributes={
                        "aura.workspace_id": str(target_ws),
                        "recovery.actor_id": actor_id,
                        "recovery.scope": "workspace" if workspace_id else "global",
                        "recovery.duration_ms": result["recovery_duration_ms"],
                        "recovery.status": "RECOVERED",
                    },
                ):
                    pass
            except Exception as otel_err:
                logger.warning(f"KillSwitch: OpenTelemetry span creation failed safely: {otel_err}")

            return result

    def get_status(self, workspace_id: Optional[uuid.UUID] = None) -> Dict[str, Any]:
        """Get diagnostic summary of current emergency state."""
        return {
            "is_active_globally": self._is_active,
            "active_workspaces": [str(w) for w in self._active_workspaces],
            "is_active_for_query": self.is_active(workspace_id),
            "recent_events_count": len(self._kill_history),
        }


kill_switch = EmergencyKillSwitchService()
