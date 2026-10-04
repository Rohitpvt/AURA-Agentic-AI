"""AURA Vision & Screen Intelligence Endpoints (Phase 8 / AURA-801).

Provides authenticated REST endpoints for:
1. Multi-monitor discovery and geometry enumeration.
2. Active foreground window introspection.
3. On-demand screen snapshot capture into depth-1 ephemeral memory.
4. Ephemeral frame metadata querying and buffer clearing.
"""

import base64
from typing import Any, Dict, List, Optional
import uuid
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.deps import get_current_user
from app.core.errors import AuthorizationError, EntityNotFoundError, ValidationError
from app.core.logging import logger
from app.db.models.user import User
from app.services.kill_switch import kill_switch
from app.services.vision.screen_capture import (
    ActiveWindowInfo,
    CapturedFrame,
    MonitorInfo,
    screen_capture_service,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Request & Response Schemas
# ---------------------------------------------------------------------------

class MonitorResponse(BaseModel):
    monitor_id: int
    name: str
    left: int
    top: int
    width: int
    height: int
    is_primary: bool
    dpi_scale: float


class MonitorListResponse(BaseModel):
    monitors: List[MonitorResponse]
    total: int


class WindowBoundsModel(BaseModel):
    left: int
    top: int
    right: int
    bottom: int
    width: int
    height: int


class ActiveWindowResponse(BaseModel):
    window_title: str
    process_name: Optional[str] = None
    pid: Optional[int] = None
    bounds: WindowBoundsModel
    is_maximized: bool = False
    monitor_id: Optional[int] = None


class ScreenCaptureRequest(BaseModel):
    monitor_id: int = Field(default=1, description="Monitor ID to capture (0 = virtual desktop, 1..N = physical)")
    crop_to_active_window: bool = Field(default=False, description="Whether to crop capture to active foreground window")
    custom_roi: Optional[List[int]] = Field(default=None, description="Optional custom ROI [left, top, width, height]")
    include_preview_thumbnail: bool = Field(default=False, description="Whether to include downscaled base64 thumbnail for UI preview")


class FrameMetadataResponse(BaseModel):
    frame_id: str
    stream_type: str
    monitor_id: int
    original_dimensions: List[int]
    processed_dimensions: List[int]
    format: str
    size_bytes: int
    timestamp_ns: int
    sequence_number: int
    is_changed: bool
    delta_ratio: float
    window_info: Optional[ActiveWindowResponse] = None
    preview_thumbnail_base64: Optional[str] = None


class BufferClearResponse(BaseModel):
    status: str
    message: str


# ---------------------------------------------------------------------------
# Endpoint Handlers
# ---------------------------------------------------------------------------

@router.get(
    "/monitors",
    response_model=MonitorListResponse,
    summary="List available monitors and display topology",
)
async def get_monitors(
    current_user: User = Depends(get_current_user),
    x_workspace_id: Optional[str] = Header(None, alias="X-Workspace-Id"),
) -> MonitorListResponse:
    """Discover all connected physical displays and the virtual desktop bounds."""
    ws_id = x_workspace_id or str(getattr(current_user, "default_workspace_id", ""))
    if kill_switch.is_active(workspace_id=ws_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Emergency Kill Switch is ACTIVE: Vision operations are blocked.",
        )

    monitors = screen_capture_service.list_monitors()
    items = [
        MonitorResponse(
            monitor_id=m.monitor_id,
            name=m.name,
            left=m.left,
            top=m.top,
            width=m.width,
            height=m.height,
            is_primary=m.is_primary,
            dpi_scale=m.dpi_scale,
        )
        for m in monitors
    ]
    return MonitorListResponse(monitors=items, total=len(items))


@router.get(
    "/active-window",
    response_model=Optional[ActiveWindowResponse],
    summary="Get active foreground window context",
)
async def get_active_window(
    current_user: User = Depends(get_current_user),
    x_workspace_id: Optional[str] = Header(None, alias="X-Workspace-Id"),
) -> Optional[ActiveWindowResponse]:
    """Inspect the active foreground window without manipulation."""
    ws_id = x_workspace_id or str(getattr(current_user, "default_workspace_id", ""))
    if kill_switch.is_active(workspace_id=ws_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Emergency Kill Switch is ACTIVE: Vision operations are blocked.",
        )

    win = screen_capture_service.get_active_window()
    if not win:
        return None

    return ActiveWindowResponse(
        window_title=win.window_title,
        process_name=win.process_name,
        pid=win.pid,
        bounds=WindowBoundsModel(
            left=win.bounds.left,
            top=win.bounds.top,
            right=win.bounds.right,
            bottom=win.bounds.bottom,
            width=win.bounds.width,
            height=win.bounds.height,
        ),
        is_maximized=win.is_maximized,
        monitor_id=win.monitor_id,
    )


@router.post(
    "/capture",
    response_model=FrameMetadataResponse,
    status_code=status.HTTP_200_OK,
    summary="Capture an on-demand screen or window frame",
)
async def capture_screen_frame(
    req: ScreenCaptureRequest,
    current_user: User = Depends(get_current_user),
    x_workspace_id: Optional[str] = Header(None, alias="X-Workspace-Id"),
) -> FrameMetadataResponse:
    """Capture a screen or active window frame into volatile memory buffer."""
    ws_id = x_workspace_id or str(getattr(current_user, "default_workspace_id", ""))
    if kill_switch.is_active(workspace_id=ws_id):
        screen_capture_service.clear_ephemeral_buffer()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Emergency Kill Switch is ACTIVE: Screen capture blocked.",
        )

    roi_tuple = None
    if req.custom_roi:
        if len(req.custom_roi) == 4:
            roi_tuple = (req.custom_roi[0], req.custom_roi[1], req.custom_roi[2], req.custom_roi[3])
        else:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="custom_roi must contain exactly 4 integers: [left, top, width, height]",
            )

    try:
        frame = screen_capture_service.capture_frame(
            monitor_id=req.monitor_id,
            crop_to_active_window=req.crop_to_active_window,
            custom_roi=roi_tuple,
            workspace_id=ws_id,
        )
    except AuthorizationError as auth_err:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(auth_err))
    except EntityNotFoundError as not_found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(not_found))
    except Exception as exc:
        logger.error(f"Failed to capture frame: {exc}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Screen capture failed.")

    win_model = None
    if frame.window_info:
        w = frame.window_info
        win_model = ActiveWindowResponse(
            window_title=w.window_title,
            process_name=w.process_name,
            pid=w.pid,
            bounds=WindowBoundsModel(
                left=w.bounds.left,
                top=w.bounds.top,
                right=w.bounds.right,
                bottom=w.bounds.bottom,
                width=w.bounds.width,
                height=w.bounds.height,
            ),
            is_maximized=w.is_maximized,
            monitor_id=w.monitor_id,
        )

    preview_b64 = None
    if req.include_preview_thumbnail and frame.raw_bytes:
        preview_b64 = base64.b64encode(frame.raw_bytes).decode("ascii")

    return FrameMetadataResponse(
        frame_id=frame.frame_id,
        stream_type=frame.stream_type,
        monitor_id=frame.monitor_id,
        original_dimensions=list(frame.original_dimensions),
        processed_dimensions=list(frame.processed_dimensions),
        format=frame.format,
        size_bytes=frame.size_bytes,
        timestamp_ns=frame.timestamp_ns,
        sequence_number=frame.sequence_number,
        is_changed=frame.is_changed,
        delta_ratio=round(frame.delta_ratio, 4),
        window_info=win_model,
        preview_thumbnail_base64=preview_b64,
    )


@router.get(
    "/latest-frame/metadata",
    response_model=Optional[FrameMetadataResponse],
    summary="Get metadata of the current depth-1 frame",
)
async def get_latest_frame_metadata(
    current_user: User = Depends(get_current_user),
    x_workspace_id: Optional[str] = Header(None, alias="X-Workspace-Id"),
) -> Optional[FrameMetadataResponse]:
    """Retrieve metadata of the latest frame stored in ephemeral memory."""
    ws_id = x_workspace_id or str(getattr(current_user, "default_workspace_id", ""))
    if kill_switch.is_active(workspace_id=ws_id):
        screen_capture_service.clear_ephemeral_buffer()
        return None

    frame = screen_capture_service.get_latest_frame(workspace_id=ws_id)
    if not frame:
        return None

    win_model = None
    if frame.window_info:
        w = frame.window_info
        win_model = ActiveWindowResponse(
            window_title=w.window_title,
            process_name=w.process_name,
            pid=w.pid,
            bounds=WindowBoundsModel(
                left=w.bounds.left,
                top=w.bounds.top,
                right=w.bounds.right,
                bottom=w.bounds.bottom,
                width=w.bounds.width,
                height=w.bounds.height,
            ),
            is_maximized=w.is_maximized,
            monitor_id=w.monitor_id,
        )

    return FrameMetadataResponse(
        frame_id=frame.frame_id,
        stream_type=frame.stream_type,
        monitor_id=frame.monitor_id,
        original_dimensions=list(frame.original_dimensions),
        processed_dimensions=list(frame.processed_dimensions),
        format=frame.format,
        size_bytes=frame.size_bytes,
        timestamp_ns=frame.timestamp_ns,
        sequence_number=frame.sequence_number,
        is_changed=frame.is_changed,
        delta_ratio=round(frame.delta_ratio, 4),
        window_info=win_model,
        preview_thumbnail_base64=None,
    )


@router.delete(
    "/ephemeral-buffer",
    response_model=BufferClearResponse,
    summary="Clear the depth-1 ephemeral frame buffer",
)
async def clear_ephemeral_buffer(
    current_user: User = Depends(get_current_user),
    x_workspace_id: Optional[str] = Header(None, alias="X-Workspace-Id"),
) -> BufferClearResponse:
    """Manually clear and reset the volatile frame buffer."""
    screen_capture_service.clear_ephemeral_buffer()
    return BufferClearResponse(
        status="cleared",
        message="Ephemeral vision frame buffer successfully purged from memory.",
    )
