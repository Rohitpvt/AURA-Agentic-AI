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


async def execute_move_mouse(
    workspace_id: uuid.UUID,
    arguments: Optional[Dict[str, Any]] = None,
    db: Optional[AsyncSession] = None,
    hitl_token: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Execute move_mouse tool strictly through OSGuardService."""
    args = dict(arguments or {})
    args.update(kwargs)

    x_val = args.get("x")
    y_val = args.get("y")
    if x_val is None or y_val is None:
        raise ValidationError("Parameters 'x' and 'y' are required for move_mouse")

    try:
        x = int(x_val)
        y = int(y_val)
    except (ValueError, TypeError) as exc:
        raise ValidationError("Coordinates 'x' and 'y' must be valid integers") from exc

    duration = float(args.get("duration", 0.2))
    monitor_id = int(args.get("monitor_id", 1))
    coordinate_space = str(args.get("coordinate_space", "screen_desktop"))
    obs_ts = args.get("observation_timestamp")
    obs_float = float(obs_ts) if obs_ts is not None else None
    expected_window_title = args.get("expected_window_title")

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
        action_type=OSActionType.MOUSE_MOVE,
        parameters={
            "x": x,
            "y": y,
            "duration": duration,
            "monitor_id": monitor_id,
            "coordinate_space": coordinate_space,
            "observation_timestamp": obs_float,
            "expected_window_title": expected_window_title,
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
            "message": resp.error or f"Mouse move to ({x}, {y}) requires human approval",
        }

    if resp.state != OSActionLifecycleState.COMPLETED or not resp.result:
        raise AuthorizationError(f"Mouse move failed: {resp.error or 'Action policy denied'}")

    return resp.result


async def execute_click_mouse(
    workspace_id: uuid.UUID,
    arguments: Optional[Dict[str, Any]] = None,
    db: Optional[AsyncSession] = None,
    hitl_token: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Execute click_mouse tool strictly through OSGuardService."""
    args = dict(arguments or {})
    args.update(kwargs)

    x_val = args.get("x")
    y_val = args.get("y")
    if x_val is None or y_val is None:
        raise ValidationError("Parameters 'x' and 'y' are required for click_mouse")

    try:
        x = int(x_val)
        y = int(y_val)
    except (ValueError, TypeError) as exc:
        raise ValidationError("Coordinates 'x' and 'y' must be valid integers") from exc

    button = str(args.get("button", "left")).lower().strip()
    clicks = int(args.get("clicks", 1))
    monitor_id = int(args.get("monitor_id", 1))
    coordinate_space = str(args.get("coordinate_space", "screen_desktop"))
    obs_ts = args.get("observation_timestamp")
    obs_float = float(obs_ts) if obs_ts is not None else None
    expected_window_title = args.get("expected_window_title")

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
        action_type=OSActionType.MOUSE_CLICK,
        parameters={
            "x": x,
            "y": y,
            "button": button,
            "clicks": clicks,
            "monitor_id": monitor_id,
            "coordinate_space": coordinate_space,
            "observation_timestamp": obs_float,
            "expected_window_title": expected_window_title,
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
            "message": resp.error or f"Mouse click at ({x}, {y}) requires human approval",
        }

    if resp.state != OSActionLifecycleState.COMPLETED or not resp.result:
        raise AuthorizationError(f"Mouse click failed: {resp.error or 'Action policy denied'}")

    return resp.result


async def execute_type_text(
    workspace_id: uuid.UUID,
    arguments: Optional[Dict[str, Any]] = None,
    db: Optional[AsyncSession] = None,
    hitl_token: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Execute type_text tool strictly through OSGuardService."""
    args = dict(arguments or {})
    args.update(kwargs)

    text = args.get("text")
    if text is None:
        raise ValidationError("Parameter 'text' is required for type_text")

    text_str = str(text)
    interval = float(args.get("interval", 0.01))
    expected_window_title = args.get("expected_window_title")

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
        action_type=OSActionType.TYPE_TEXT,
        parameters={
            "text": text_str,
            "interval": interval,
            "expected_window_title": expected_window_title,
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
            "message": resp.error or "Keyboard typing requires human approval",
        }

    if resp.state != OSActionLifecycleState.COMPLETED or not resp.result:
        raise AuthorizationError(f"Keyboard typing failed: {resp.error or 'Action policy denied'}")

    return resp.result


async def execute_press_key(
    workspace_id: uuid.UUID,
    arguments: Optional[Dict[str, Any]] = None,
    db: Optional[AsyncSession] = None,
    hitl_token: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Execute press_key tool strictly through OSGuardService."""
    args = dict(arguments or {})
    args.update(kwargs)

    key = args.get("key")
    if not key:
        raise ValidationError("Parameter 'key' is required for press_key")

    key_str = str(key).strip().lower()
    presses = int(args.get("presses", 1))
    expected_window_title = args.get("expected_window_title")

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
        action_type=OSActionType.PRESS_KEY,
        parameters={
            "key": key_str,
            "presses": presses,
            "expected_window_title": expected_window_title,
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
            "message": resp.error or f"Key press '{key_str}' requires human approval",
        }

    if resp.state != OSActionLifecycleState.COMPLETED or not resp.result:
        raise AuthorizationError(f"Key press failed: {resp.error or 'Action policy denied'}")

    return resp.result


async def execute_keyboard_shortcut(
    workspace_id: uuid.UUID,
    arguments: Optional[Dict[str, Any]] = None,
    db: Optional[AsyncSession] = None,
    hitl_token: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Execute keyboard_shortcut tool strictly through OSGuardService."""
    args = dict(arguments or {})
    args.update(kwargs)

    shortcut = args.get("shortcut")
    keys = args.get("keys")
    if not shortcut and not keys:
        raise ValidationError("Parameter 'shortcut' or 'keys' is required for keyboard_shortcut")

    shortcut_str = str(shortcut or "+".join(keys)).strip().lower()
    expected_window_title = args.get("expected_window_title")

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
        action_type=OSActionType.KEYBOARD_SHORTCUT,
        parameters={
            "shortcut": shortcut_str,
            "expected_window_title": expected_window_title,
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
            "message": resp.error or f"Keyboard shortcut '{shortcut_str}' requires human approval",
        }

    if resp.state != OSActionLifecycleState.COMPLETED or not resp.result:
        raise AuthorizationError(f"Keyboard shortcut failed: {resp.error or 'Action policy denied'}")

    return resp.result


# ---------------------------------------------------------------------------
# AURA-904 Governed System Telemetry, Hardware & Clipboard Tools
# ---------------------------------------------------------------------------

async def execute_get_system_telemetry(
    workspace_id: uuid.UUID,
    arguments: Optional[Dict[str, Any]] = None,
    db: Optional[AsyncSession] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Execute get_system_telemetry tool strictly through OSGuardService."""
    from app.services.os_guard.adapters import WindowsOSExecutionAdapter
    from app.services.os_guard.os_guard_service import os_guard_service
    from app.services.os_guard.types import (
        OSActionLifecycleState,
        OSActionRequest,
        OSActionType,
    )

    action_req = OSActionRequest(
        workspace_id=str(workspace_id),
        action_type=OSActionType.SYSTEM_TELEMETRY,
        parameters={"query_type": "telemetry"},
    )

    resp = await os_guard_service.execute_os_action(
        request=action_req,
        db=db,
        adapter=WindowsOSExecutionAdapter(),
    )

    if resp.state != OSActionLifecycleState.COMPLETED or not resp.result:
        raise AuthorizationError(f"System telemetry retrieval failed: {resp.error or 'Action policy denied'}")

    return resp.result


async def execute_get_hardware_capabilities(
    workspace_id: uuid.UUID,
    arguments: Optional[Dict[str, Any]] = None,
    db: Optional[AsyncSession] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Execute get_hardware_capabilities tool strictly through OSGuardService."""
    from app.services.os_guard.adapters import WindowsOSExecutionAdapter
    from app.services.os_guard.os_guard_service import os_guard_service
    from app.services.os_guard.types import (
        OSActionLifecycleState,
        OSActionRequest,
        OSActionType,
    )

    action_req = OSActionRequest(
        workspace_id=str(workspace_id),
        action_type=OSActionType.HARDWARE_CONTROL,
        parameters={"control_type": "get_hardware_capabilities"},
    )

    resp = await os_guard_service.execute_os_action(
        request=action_req,
        db=db,
        adapter=WindowsOSExecutionAdapter(),
    )

    if resp.state != OSActionLifecycleState.COMPLETED or not resp.result:
        raise AuthorizationError(f"Hardware capability discovery failed: {resp.error or 'Action policy denied'}")

    return resp.result


async def execute_get_system_volume(
    workspace_id: uuid.UUID,
    arguments: Optional[Dict[str, Any]] = None,
    db: Optional[AsyncSession] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Execute get_system_volume tool strictly through OSGuardService."""
    from app.services.os_guard.adapters import WindowsOSExecutionAdapter
    from app.services.os_guard.os_guard_service import os_guard_service
    from app.services.os_guard.types import (
        OSActionLifecycleState,
        OSActionRequest,
        OSActionType,
    )

    action_req = OSActionRequest(
        workspace_id=str(workspace_id),
        action_type=OSActionType.HARDWARE_CONTROL,
        parameters={"control_type": "get_system_volume"},
    )

    resp = await os_guard_service.execute_os_action(
        request=action_req,
        db=db,
        adapter=WindowsOSExecutionAdapter(),
    )

    if resp.state != OSActionLifecycleState.COMPLETED or not resp.result:
        raise AuthorizationError(f"System volume retrieval failed: {resp.error or 'Action policy denied'}")

    return resp.result


async def execute_set_system_volume(
    workspace_id: uuid.UUID,
    arguments: Optional[Dict[str, Any]] = None,
    db: Optional[AsyncSession] = None,
    hitl_token: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Execute set_system_volume tool with <= +/-10% bounded adjustments strictly through OSGuardService."""
    args = dict(arguments or {})
    args.update(kwargs)

    rel_step = args.get("relative_step_percent")
    tgt_vol = args.get("target_volume_percent")
    mute = args.get("mute")

    if rel_step is None and tgt_vol is None and mute is None:
        raise ValidationError("At least one parameter ('relative_step_percent', 'target_volume_percent', or 'mute') is required for set_system_volume")

    rel_step_float = float(rel_step) if rel_step is not None else None
    if rel_step_float is not None and abs(rel_step_float) > 10.0:
        raise ValidationError(f"Relative volume step {rel_step_float:+.1f}% exceeds safety ceiling of +/-10.0%")

    tgt_vol_float = float(tgt_vol) if tgt_vol is not None else None
    mute_bool = bool(mute) if mute is not None else None

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
        action_type=OSActionType.HARDWARE_CONTROL,
        parameters={
            "control_type": "set_system_volume",
            "relative_step_percent": rel_step_float,
            "target_volume_percent": tgt_vol_float,
            "mute": mute_bool,
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
            "message": resp.error or "System volume adjustment requires human approval",
        }

    if resp.state != OSActionLifecycleState.COMPLETED or not resp.result:
        raise AuthorizationError(f"System volume adjustment failed: {resp.error or 'Action policy denied'}")

    return resp.result


async def execute_get_display_brightness(
    workspace_id: uuid.UUID,
    arguments: Optional[Dict[str, Any]] = None,
    db: Optional[AsyncSession] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Execute get_display_brightness tool strictly through OSGuardService."""
    args = dict(arguments or {})
    args.update(kwargs)
    monitor_id = int(args.get("monitor_id", 1))

    from app.services.os_guard.adapters import WindowsOSExecutionAdapter
    from app.services.os_guard.os_guard_service import os_guard_service
    from app.services.os_guard.types import (
        OSActionLifecycleState,
        OSActionRequest,
        OSActionType,
    )

    action_req = OSActionRequest(
        workspace_id=str(workspace_id),
        action_type=OSActionType.HARDWARE_CONTROL,
        parameters={
            "control_type": "get_display_brightness",
            "monitor_id": monitor_id,
        },
    )

    resp = await os_guard_service.execute_os_action(
        request=action_req,
        db=db,
        adapter=WindowsOSExecutionAdapter(),
    )

    if resp.state != OSActionLifecycleState.COMPLETED or not resp.result:
        raise AuthorizationError(f"Display brightness retrieval failed: {resp.error or 'Action policy denied'}")

    return resp.result


async def execute_set_display_brightness(
    workspace_id: uuid.UUID,
    arguments: Optional[Dict[str, Any]] = None,
    db: Optional[AsyncSession] = None,
    hitl_token: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Execute set_display_brightness tool with <= +/-10% bounded adjustments strictly through OSGuardService."""
    args = dict(arguments or {})
    args.update(kwargs)

    monitor_id = int(args.get("monitor_id", 1))
    rel_step = args.get("relative_step_percent")
    tgt_b = args.get("target_brightness_percent")

    if rel_step is None and tgt_b is None:
        raise ValidationError("Parameter 'relative_step_percent' or 'target_brightness_percent' is required for set_display_brightness")

    rel_step_float = float(rel_step) if rel_step is not None else None
    if rel_step_float is not None and abs(rel_step_float) > 10.0:
        raise ValidationError(f"Relative brightness step {rel_step_float:+.1f}% exceeds safety ceiling of +/-10.0%")

    tgt_b_int = int(tgt_b) if tgt_b is not None else None

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
        action_type=OSActionType.HARDWARE_CONTROL,
        parameters={
            "control_type": "set_display_brightness",
            "monitor_id": monitor_id,
            "relative_step_percent": rel_step_float,
            "target_brightness_percent": tgt_b_int,
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
            "message": resp.error or "Display brightness adjustment requires human approval",
        }

    if resp.state != OSActionLifecycleState.COMPLETED or not resp.result:
        raise AuthorizationError(f"Display brightness adjustment failed: {resp.error or 'Action policy denied'}")

    return resp.result


async def execute_clipboard_read(
    workspace_id: uuid.UUID,
    arguments: Optional[Dict[str, Any]] = None,
    db: Optional[AsyncSession] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Execute clipboard_read tool with automated secret scrubbing strictly through OSGuardService."""
    from app.services.os_guard.adapters import WindowsOSExecutionAdapter
    from app.services.os_guard.os_guard_service import os_guard_service
    from app.services.os_guard.types import (
        OSActionLifecycleState,
        OSActionRequest,
        OSActionType,
    )

    action_req = OSActionRequest(
        workspace_id=str(workspace_id),
        action_type=OSActionType.CLIPBOARD_READ,
        parameters={},
    )

    resp = await os_guard_service.execute_os_action(
        request=action_req,
        db=db,
        adapter=WindowsOSExecutionAdapter(),
    )

    if resp.state != OSActionLifecycleState.COMPLETED or not resp.result:
        raise AuthorizationError(f"Clipboard read failed: {resp.error or 'Action policy denied'}")

    return resp.result


async def execute_clipboard_write(
    workspace_id: uuid.UUID,
    arguments: Optional[Dict[str, Any]] = None,
    db: Optional[AsyncSession] = None,
    hitl_token: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Execute clipboard_write tool with bounded payload and cryptographic HITL strictly through OSGuardService."""
    args = dict(arguments or {})
    args.update(kwargs)

    text = args.get("text")
    if text is None or not isinstance(text, str):
        raise ValidationError("Parameter 'text' is required and must be a string for clipboard_write")

    if len(text) > 4096:
        raise ValidationError(f"Clipboard payload length ({len(text)} chars) exceeds maximum ceiling of 4096 characters")

    if "\x00" in text:
        raise ValidationError("NUL byte ('\\x00') detected in clipboard payload. Injection prohibited.")

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
        action_type=OSActionType.CLIPBOARD_WRITE,
        parameters={"text": text},
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
            "message": resp.error or "Clipboard write requires human approval",
        }

    if resp.state != OSActionLifecycleState.COMPLETED or not resp.result:
        raise AuthorizationError(f"Clipboard write failed: {resp.error or 'Action policy denied'}")

    return resp.result


