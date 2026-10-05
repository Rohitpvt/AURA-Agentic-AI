"""AURA-902 Governed Operating System & Process Control Tool Handlers.

Provides canonical handlers for:
1. launch_application (Governed application launch from allowlist)
2. inspect_processes (Safe read-only active process inspection)
3. terminate_process (Governed process termination with PID + creation_time identity verification)
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional
import uuid
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AuthorizationError, ValidationError
from app.core.logging import logger



async def execute_launch_application(
    workspace_id: uuid.UUID,
    arguments: Optional[Dict[str, Any]] = None,
    db: Optional[AsyncSession] = None,
    hitl_token: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Execute launch_application tool strictly through OSGuardService."""
    args = dict(arguments or {})
    args.update(kwargs)

    application_id = args.get("application_id")
    if not application_id:
        raise ValidationError("Parameter 'application_id' is required for launch_application")

    raw_args = args.get("arguments") or []
    if isinstance(raw_args, str):
        raw_args = [raw_args]
    elif not isinstance(raw_args, list):
        raise ValidationError("Parameter 'arguments' must be a list of strings")

    working_dir = args.get("working_directory")

    from app.services.os_guard.adapters import WindowsOSExecutionAdapter
    from app.services.os_guard.os_guard_service import os_guard_service
    from app.services.os_guard.types import (
        OSActionLifecycleState,
        OSActionRequest,
        OSActionType,
        PolicyDecisionType,
    )

    # Build OSActionRequest
    action_req = OSActionRequest(
        workspace_id=str(workspace_id),
        action_type=OSActionType.APPLICATION_LAUNCH,
        parameters={
            "application_id": str(application_id).strip().lower(),
            "arguments": raw_args,
            "working_directory": working_dir,
        },
        hitl_approval_token=hitl_token or args.get("hitl_approval_token"),
    )

    resp = await os_guard_service.execute_os_action(
        request=action_req,
        db=db,
        adapter=WindowsOSExecutionAdapter(),
    )

    if resp.state == OSActionLifecycleState.WAITING_HITL or resp.policy_decision == PolicyDecisionType.REQUIRE_HITL:
        return {
            "status": "waiting_approval",
            "action_id": resp.action_id,
            "requires_hitl": True,
            "message": resp.error or f"Launch of application '{application_id}' requires human approval",
        }

    if resp.state != OSActionLifecycleState.COMPLETED or not resp.result:
        raise AuthorizationError(f"Application launch failed: {resp.error or 'Action policy denied'}")

    return resp.result


async def execute_inspect_processes(
    workspace_id: uuid.UUID,
    arguments: Optional[Dict[str, Any]] = None,
    db: Optional[AsyncSession] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Execute inspect_processes tool strictly through OSGuardService."""
    args = dict(arguments or {})
    args.update(kwargs)

    filter_name = args.get("filter_name")
    pid_val = args.get("pid")
    pid_int = int(pid_val) if pid_val is not None else None
    limit = int(args.get("limit", 50))

    from app.services.os_guard.adapters import WindowsOSExecutionAdapter
    from app.services.os_guard.os_guard_service import os_guard_service
    from app.services.os_guard.types import (
        OSActionLifecycleState,
        OSActionRequest,
        OSActionType,
        PolicyDecisionType,
    )

    action_req = OSActionRequest(
        workspace_id=str(workspace_id),
        action_type=OSActionType.READ_ONLY,
        parameters={
            "query_type": "processes",
            "filter_name": filter_name,
            "pid": pid_int,
            "limit": limit,
        },
    )

    resp = await os_guard_service.execute_os_action(
        request=action_req,
        db=db,
        adapter=WindowsOSExecutionAdapter(),
    )

    if resp.state != OSActionLifecycleState.COMPLETED or not resp.result:
        raise AuthorizationError(f"Process inspection failed: {resp.error or 'Action policy denied'}")

    return resp.result


async def execute_terminate_process(
    workspace_id: uuid.UUID,
    arguments: Optional[Dict[str, Any]] = None,
    db: Optional[AsyncSession] = None,
    hitl_token: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Execute terminate_process tool strictly through OSGuardService with PID + create_time verification."""
    args = dict(arguments or {})
    args.update(kwargs)

    pid_val = args.get("pid")
    if pid_val is None:
        raise ValidationError("Parameter 'pid' is required for terminate_process")

    try:
        pid = int(pid_val)
    except ValueError as exc:
        raise ValidationError(f"Invalid PID integer format: {pid_val}") from exc

    expected_create_time_val = args.get("expected_create_time")
    if expected_create_time_val is None:
        raise ValidationError("Parameter 'expected_create_time' is required for PID reuse verification")

    try:
        expected_create_time = float(expected_create_time_val)
    except ValueError as exc:
        raise ValidationError(f"Invalid expected_create_time float format: {expected_create_time_val}") from exc

    expected_name = args.get("expected_name")
    if not expected_name:
        raise ValidationError("Parameter 'expected_name' is required for process identity verification")

    reason = args.get("reason", "Operator requested process termination")

    from app.services.os_guard.adapters import WindowsOSExecutionAdapter
    from app.services.os_guard.os_guard_service import os_guard_service
    from app.services.os_guard.types import (
        OSActionLifecycleState,
        OSActionRequest,
        OSActionType,
        PolicyDecisionType,
    )

    action_req = OSActionRequest(
        workspace_id=str(workspace_id),
        action_type=OSActionType.PROCESS_TERMINATE,
        parameters={
            "pid": pid,
            "expected_create_time": expected_create_time,
            "expected_name": str(expected_name).strip(),
            "reason": reason,
        },
        hitl_approval_token=hitl_token or args.get("hitl_approval_token"),
    )

    resp = await os_guard_service.execute_os_action(
        request=action_req,
        db=db,
        adapter=WindowsOSExecutionAdapter(),
    )

    if resp.state == OSActionLifecycleState.WAITING_HITL or resp.policy_decision == PolicyDecisionType.REQUIRE_HITL:
        return {
            "status": "waiting_approval",
            "action_id": resp.action_id,
            "requires_hitl": True,
            "message": resp.error or f"Termination of process '{expected_name}' (PID: {pid}) requires human approval",
        }

    if resp.state != OSActionLifecycleState.COMPLETED or not resp.result:
        raise AuthorizationError(f"Process termination failed: {resp.error or 'Action policy denied'}")

    return resp.result
