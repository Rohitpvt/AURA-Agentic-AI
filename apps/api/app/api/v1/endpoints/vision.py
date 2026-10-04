"""AURA Vision & Screen Intelligence Endpoints (Phase 8 / AURA-801).

Provides authenticated REST endpoints for:
1. Multi-monitor discovery and geometry enumeration.
2. Active foreground window introspection.
3. On-demand screen snapshot capture into depth-1 ephemeral memory.
4. Ephemeral frame metadata querying and buffer clearing.
"""

import base64
import time
from typing import Any, Dict, List, Optional
import uuid
from fastapi import APIRouter, Depends, Header, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db_session, get_workspace_membership
from app.core.errors import AuthenticationError, AuthorizationError, EntityNotFoundError, ValidationError, VisionProcessingError
from app.core.logging import logger
from app.db.models.user import User
from app.services.kill_switch import kill_switch
from app.services.vision.camera_service import (
    DEFAULT_CAMERA_FPS,
    FRAME_HEADER_SIZE,
    MAX_CAMERA_FPS,
    camera_vision_service,
    pack_camera_frame,
    unpack_camera_frame,
)
from app.services.vision.screen_capture import (
    ActiveWindowInfo,
    CapturedFrame,
    MonitorInfo,
    screen_capture_service,
)
from app.services.vision.ticket_service import VisionTicket, vision_ticket_service

router = APIRouter()


# ---------------------------------------------------------------------------
# Request & Response Schemas
# ---------------------------------------------------------------------------

class VisionTicketRequest(BaseModel):
    """Payload for requesting a short-lived vision/camera session ticket."""
    workspace_id: uuid.UUID = Field(..., description="Target workspace UUID for vision session authorization")
    ttl_seconds: Optional[int] = Field(default=60, ge=10, le=300, description="Ticket validity window in seconds")
    purpose: Optional[str] = Field(default="camera_stream", description="Intended purpose of ticket (e.g. camera_stream)")


class VisionTicketResponse(BaseModel):
    """Metadata returned upon successful vision ticket issuance."""
    ticket: str = Field(..., description="Single-use cryptographically secure ticket token")
    expires_in: int = Field(default=60, description="Ticket TTL in seconds")
    workspace_id: uuid.UUID = Field(..., description="Authorized workspace UUID")
    user_id: uuid.UUID = Field(..., description="Authorized user UUID")
    created_at: float = Field(..., description="Epoch timestamp of ticket creation")
    purpose: str = Field(default="camera_stream", description="Authorized ticket purpose")


class CameraObservationResponse(BaseModel):
    """Metadata describing the latest ephemeral camera frame in volatile memory."""
    frame_id: str
    workspace_id: str
    session_id: str
    source_id: int
    sequence_number: int
    timestamp_ns: int
    width: int
    height: int
    format: str
    size_bytes: int
    received_at: float
    preview_thumbnail_base64: Optional[str] = None


class CameraStatusResponse(BaseModel):
    """Status and configuration limits for the camera streaming subsystem."""
    status: str
    active_sessions_count: int
    default_fps: float
    max_fps_ceiling: float
    min_frame_interval_sec: float
    max_resolution: str
    header_size_bytes: int
    buffer_depth: int
    has_ephemeral_frame: bool
    format: str


class CameraBufferClearResponse(BaseModel):
    """Response returned when ephemeral camera memory buffer is cleared."""
    status: str
    cleared: bool
    message: str

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


# ---------------------------------------------------------------------------
# OCR Schemas & Endpoints (Phase 8 / AURA-802)
# ---------------------------------------------------------------------------

class OCRBoundingBoxModel(BaseModel):
    x: float
    y: float
    width: float
    height: float
    polygon: List[List[float]]
    normalized_bbox: List[float]
    coordinate_space: str = "captured_frame"


class OCRTextRegionModel(BaseModel):
    region_id: str
    text: str
    confidence: float
    bbox: OCRBoundingBoxModel
    line_number: int


class OCRExtractRequest(BaseModel):
    monitor_id: int = Field(default=1, description="Monitor ID to capture and extract text from")
    force_refresh: bool = Field(default=False, description="Force OCR inference even if frame delta is below threshold")
    image_base64: Optional[str] = Field(default=None, description="Optional raw base64 image bytes to process")


class OCRExtractionResponse(BaseModel):
    observation_id: str
    workspace_id: Optional[str] = None
    frame_id: Optional[str] = None
    monitor_id: int
    capture_timestamp_ns: int
    ocr_timestamp_ns: int
    processing_duration_ms: float
    frame_dimensions: List[int]
    region_count: int
    text_regions: List[OCRTextRegionModel]
    full_text: str
    status: str
    degraded: bool
    untrusted_content_envelope: str
    is_untrusted_content: bool = True
    window_info: Optional[Dict[str, Any]] = None


class OCRStatusResponse(BaseModel):
    status: str
    engine: str = "RapidOCR-ONNX"
    rate_ceiling_fps: float = 1.0
    ocr_max_fps: float = 1.0
    ocr_min_interval_sec: float = 1.0
    engine_initialized: bool = True
    degraded: bool


class OCRBufferClearResponse(BaseModel):
    status: str = "cleared"
    cleared: bool = True
    message: str = "Ephemeral OCR observation cache successfully cleared."


@router.post(
    "/ocr/extract",
    response_model=OCRExtractionResponse,
    status_code=status.HTTP_200_OK,
    summary="Extract structured local OCR text with bounding boxes",
)
async def extract_ocr_from_screen(
    req: OCRExtractRequest,
    current_user: User = Depends(get_current_user),
    x_workspace_id: Optional[str] = Header(None, alias="X-Workspace-Id"),
) -> OCRExtractionResponse:
    """Perform local RapidOCR extraction on screen or image input with 1 Hz ceiling."""
    from app.services.vision.ocr_service import continuous_ocr_service

    ws_id = x_workspace_id or str(getattr(current_user, "default_workspace_id", ""))
    if kill_switch.is_active(workspace_id=ws_id):
        continuous_ocr_service.clear_ephemeral_observation()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Emergency Kill Switch is ACTIVE: OCR operation blocked.",
        )

    img_input = None
    if req.image_base64:
        try:
            img_bytes = base64.b64decode(req.image_base64)
            img_input = Image.open(io.BytesIO(img_bytes))
        except Exception as decode_err:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid base64 image payload: {decode_err}",
            )

    try:
        obs = continuous_ocr_service.extract_ocr(
            image_input=img_input,
            monitor_id=req.monitor_id,
            force_refresh=req.force_refresh,
            workspace_id=ws_id,
        )
    except AuthorizationError as auth_err:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(auth_err))
    except EntityNotFoundError as not_found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(not_found))
    except Exception as exc:
        logger.error(f"Failed to perform continuous OCR: {exc}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="OCR extraction failed.")

    regions_model = [
        OCRTextRegionModel(
            region_id=r.region_id,
            text=r.text,
            confidence=r.confidence,
            bbox=OCRBoundingBoxModel(
                x=r.bbox.x,
                y=r.bbox.y,
                width=r.bbox.width,
                height=r.bbox.height,
                polygon=r.bbox.polygon,
                normalized_bbox=r.bbox.normalized_bbox,
                coordinate_space=r.bbox.coordinate_space,
            ),
            line_number=r.line_number,
        )
        for r in obs.text_regions
    ]

    return OCRExtractionResponse(
        observation_id=obs.observation_id,
        workspace_id=obs.workspace_id,
        frame_id=obs.frame_id,
        monitor_id=obs.monitor_id,
        capture_timestamp_ns=obs.capture_timestamp_ns,
        ocr_timestamp_ns=obs.ocr_timestamp_ns,
        processing_duration_ms=obs.processing_duration_ms,
        frame_dimensions=list(obs.frame_dimensions),
        region_count=len(regions_model),
        text_regions=regions_model,
        full_text=obs.full_text,
        status=obs.status.value,
        degraded=obs.degraded,
        untrusted_content_envelope=obs.untrusted_content_envelope,
        is_untrusted_content=obs.is_untrusted_content,
        window_info=obs.window_info,
    )


@router.get(
    "/ocr/latest",
    response_model=OCRExtractionResponse,
    summary="Get latest cached OCR observation without re-triggering inference",
)
async def get_latest_ocr_observation(
    current_user: User = Depends(get_current_user),
    x_workspace_id: Optional[str] = Header(None, alias="X-Workspace-Id"),
) -> OCRExtractionResponse:
    """Retrieve the latest cached ephemeral OCR observation from volatile memory."""
    from app.services.vision.ocr_service import continuous_ocr_service

    ws_id = x_workspace_id or str(getattr(current_user, "default_workspace_id", ""))
    if kill_switch.is_active(workspace_id=ws_id):
        continuous_ocr_service.clear_ephemeral_observation()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Emergency Kill Switch is ACTIVE.",
        )

    obs = continuous_ocr_service.get_latest_observation(workspace_id=ws_id)
    if not obs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No ephemeral OCR observation available in volatile memory.",
        )

    regions_model = [
        OCRTextRegionModel(
            region_id=r.region_id,
            text=r.text,
            confidence=r.confidence,
            bbox=OCRBoundingBoxModel(
                x=r.bbox.x,
                y=r.bbox.y,
                width=r.bbox.width,
                height=r.bbox.height,
                polygon=r.bbox.polygon,
                normalized_bbox=r.bbox.normalized_bbox,
                coordinate_space=r.bbox.coordinate_space,
            ),
            line_number=r.line_number,
        )
        for r in obs.text_regions
    ]

    return OCRExtractionResponse(
        observation_id=obs.observation_id,
        workspace_id=obs.workspace_id,
        frame_id=obs.frame_id,
        monitor_id=obs.monitor_id,
        capture_timestamp_ns=obs.capture_timestamp_ns,
        ocr_timestamp_ns=obs.ocr_timestamp_ns,
        processing_duration_ms=obs.processing_duration_ms,
        frame_dimensions=list(obs.frame_dimensions),
        region_count=len(regions_model),
        text_regions=regions_model,
        full_text=obs.full_text,
        status=obs.status.value,
        degraded=obs.degraded,
        untrusted_content_envelope=obs.untrusted_content_envelope,
        is_untrusted_content=obs.is_untrusted_content,
        window_info=obs.window_info,
    )


@router.get(
    "/ocr/status",
    response_model=OCRStatusResponse,
    summary="Get OCR subsystem operational and health status",
)
async def get_ocr_status(
    current_user: User = Depends(get_current_user),
    x_workspace_id: Optional[str] = Header(None, alias="X-Workspace-Id"),
) -> OCRStatusResponse:
    """Check OCR engine availability and rate limits."""
    from app.services.vision.ocr_service import continuous_ocr_service

    ws_id = x_workspace_id or str(getattr(current_user, "default_workspace_id", ""))
    is_killed = kill_switch.is_active(workspace_id=ws_id)
    status_str = "kill_switched" if is_killed else continuous_ocr_service.status.value

    return OCRStatusResponse(
        status=status_str,
        engine="RapidOCR-ONNX",
        rate_ceiling_fps=1.0,
        ocr_max_fps=1.0,
        ocr_min_interval_sec=1.0,
        engine_initialized=continuous_ocr_service._engine_available,
        degraded=not continuous_ocr_service._engine_available,
    )


@router.delete(
    "/ocr/cache",
    response_model=OCRBufferClearResponse,
    summary="Clear ephemeral OCR observation cache",
)
async def clear_ocr_cache(
    current_user: User = Depends(get_current_user),
    x_workspace_id: Optional[str] = Header(None, alias="X-Workspace-Id"),
) -> OCRBufferClearResponse:
    """Purge ephemeral OCR observation from volatile memory."""
    from app.services.vision.ocr_service import continuous_ocr_service

    continuous_ocr_service.clear_ephemeral_observation()
    return OCRBufferClearResponse(
        status="cleared",
        cleared=True,
        message="Ephemeral OCR observation cache successfully cleared.",
    )


# ==============================================================================
# 3. Vision Session Ticket & Camera Transport Endpoints (AURA-803)
# ==============================================================================

@router.post(
    "/ticket",
    response_model=VisionTicketResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Issue single-use vision/camera session ticket",
    description="Authenticate user and validate workspace membership before issuing a 60-second single-use ticket for WebSocket upgrade.",
)
async def create_vision_ticket(
    body: VisionTicketRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> VisionTicketResponse:
    """Issue short-lived single-use vision session ticket."""
    # 1. Check workspace membership and authorization
    await get_workspace_membership(workspace_id=body.workspace_id, user=current_user, db=db)

    # 2. Check kill switch for workspace
    if kill_switch.is_active(body.workspace_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Emergency Kill Switch is ACTIVE: Vision tickets cannot be issued.",
        )

    # 3. Issue single-use ticket
    try:
        ticket = await vision_ticket_service.issue_ticket(
            user_id=current_user.id,
            workspace_id=body.workspace_id,
            purpose=body.purpose or "camera_stream",
            ttl_seconds=body.ttl_seconds,
        )
    except AuthorizationError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except AuthenticationError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to issue vision ticket: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to issue vision ticket")

    return VisionTicketResponse(
        ticket=ticket.ticket_token,
        expires_in=int(ticket.expires_at - ticket.created_at),
        workspace_id=ticket.workspace_id,
        user_id=ticket.user_id,
        created_at=ticket.created_at,
        purpose=ticket.purpose,
    )


@router.websocket("/stream")
async def vision_camera_stream(
    websocket: WebSocket,
    ticket: str = Query(..., description="Short-lived single-use vision ticket"),
    workspace_id: Optional[uuid.UUID] = Query(None, description="Optional workspace UUID for tenant assertion"),
):
    """Authenticated real-time duplex camera frame ingestion WebSocket gateway (AURA-803).
    
    Framing: 26-byte header (>BBIQIII) + WebP image payload.
    Rate Ceiling: 5.0 FPS hard limit (server-enforced).
    Buffer: Depth-1 ephemeral memory buffer.
    Kill Switch: Real-time session termination and buffer purge.
    """
    # 1. Validate & Atomically Consume Ticket before accepting WebSocket
    consumed_ticket: Optional[VisionTicket] = None
    try:
        consumed_ticket = await vision_ticket_service.consume_ticket(
            ticket_token=ticket,
            expected_workspace_id=workspace_id,
            expected_purpose="camera_stream",
        )
    except (AuthenticationError, AuthorizationError) as e:
        logger.warning(f"Vision WebSocket connection rejected during ticket verification: {e}")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=str(e))
        return
    except Exception as e:
        logger.error(f"Unexpected error during vision ticket consumption: {e}")
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR, reason="Internal ticket verification error")
        return

    # 2. Accept WebSocket Connection
    await websocket.accept()

    # 3. Kill-Switch Pre-flight Check
    if kill_switch.is_active(consumed_ticket.workspace_id):
        logger.warning(f"Vision WebSocket rejected: active kill switch on workspace {consumed_ticket.workspace_id}")
        await websocket.send_json({"type": "kill_switch", "reason": "active_kill_switch_engaged"})
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Active kill-switch engaged")
        return

    # 4. Generate True 256-bit CSPRNG Session Nonce & Register CameraSession
    raw_nonce, hex_nonce = vision_ticket_service.generate_session_nonce()
    session = camera_vision_service.create_session(
        user_id=consumed_ticket.user_id,
        workspace_id=consumed_ticket.workspace_id,
        session_nonce=hex_nonce,
    )

    try:
        # 5. Send Initial Session Ready Frame
        await websocket.send_json({
            "type": "session_ready",
            "session_id": session.session_id,
            "workspace_id": str(consumed_ticket.workspace_id),
            "user_id": str(consumed_ticket.user_id),
            "session_nonce": hex_nonce,
            "max_fps": MAX_CAMERA_FPS,
            "default_fps": DEFAULT_CAMERA_FPS,
            "header_size_bytes": FRAME_HEADER_SIZE,
            "created_at": session.created_at,
        })

        # 6. Duplex Message Event Loop
        while True:
            # Check kill switch on every iteration
            if kill_switch.is_active(consumed_ticket.workspace_id):
                logger.warning(f"[CameraSession {session.session_id}] Terminating connection due to kill-switch engagement.")
                camera_vision_service.clear_ephemeral_frame(str(consumed_ticket.workspace_id))
                await websocket.send_json({"type": "kill_switch", "reason": "emergency_stop"})
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Kill switch engaged")
                break

            message = await websocket.receive()

            # A. Binary Camera Frame Ingestion
            if "bytes" in message and message["bytes"]:
                raw_frame = message["bytes"]
                try:
                    accepted, reason, obs = camera_vision_service.ingest_frame(session.session_id, raw_frame)
                    if accepted and obs:
                        await websocket.send_json({
                            "type": "frame_accepted",
                            "sequence_number": obs.sequence_number,
                            "timestamp_ns": obs.timestamp_ns,
                            "width": obs.width,
                            "height": obs.height,
                            "size_bytes": obs.size_bytes,
                        })
                    else:
                        await websocket.send_json({
                            "type": "frame_dropped",
                            "reason": reason or "rejected",
                        })
                except AuthorizationError as auth_err:
                    logger.warning(f"[CameraSession {session.session_id}] Ingestion blocked by kill switch: {auth_err}")
                    await websocket.send_json({"type": "kill_switch", "reason": "emergency_stop"})
                    await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Kill switch engaged")
                    break
                except VisionProcessingError as frame_err:
                    logger.warning(f"[CameraSession {session.session_id}] Invalid camera frame: {frame_err}")
                    await websocket.send_json({"type": "error", "message": str(frame_err)})
                    continue
                except Exception as exc:
                    logger.error(f"[CameraSession {session.session_id}] Unexpected error in frame ingestion: {exc}")
                    await websocket.send_json({"type": "error", "message": "Frame processing error"})
                    continue

            # B. Text Control Frames
            elif "text" in message and message["text"]:
                try:
                    import json
                    data = json.loads(message["text"])
                    msg_type = data.get("type", "")

                    if msg_type == "ping":
                        await websocket.send_json({"type": "pong", "timestamp": time.time()})
                    elif msg_type == "stop":
                        logger.info(f"[CameraSession {session.session_id}] Client requested graceful stop.")
                        await websocket.send_json({"type": "camera_stopped", "reason": "client_requested"})
                        break
                    else:
                        await websocket.send_json({"type": "ack", "received_type": msg_type})
                except Exception as text_err:
                    logger.warning(f"[CameraSession {session.session_id}] Malformed text control frame: {text_err}")
                    await websocket.send_json({"type": "error", "message": "Malformed control JSON"})

    except WebSocketDisconnect:
        logger.info(f"[CameraSession {session.session_id}] WebSocket disconnected by client.")
    except Exception as e:
        logger.error(f"[CameraSession {session.session_id}] WebSocket error: {e}", exc_info=True)
    finally:
        camera_vision_service.close_session(session.session_id, reason="stream_ended")


@router.get(
    "/camera/latest",
    response_model=CameraObservationResponse,
    summary="Get latest cached camera observation without raw bytes",
)
async def get_latest_camera_observation(
    current_user: User = Depends(get_current_user),
    x_workspace_id: Optional[str] = Header(None, alias="X-Workspace-Id"),
    include_preview: bool = Query(default=False, description="Whether to include downscaled base64 thumbnail"),
) -> CameraObservationResponse:
    """Retrieve metadata for the latest cached camera frame in volatile memory."""
    ws_id = x_workspace_id or str(getattr(current_user, "default_workspace_id", ""))
    if kill_switch.is_active(workspace_id=ws_id):
        camera_vision_service.clear_ephemeral_frame(ws_id)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Emergency Kill Switch is ACTIVE.",
        )

    obs = camera_vision_service.get_latest_observation(workspace_id=ws_id)
    if not obs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No ephemeral camera observation available in volatile memory.",
        )

    preview_b64 = None
    if include_preview and obs.raw_bytes:
        preview_b64 = base64.b64encode(obs.raw_bytes).decode("ascii")

    return CameraObservationResponse(
        frame_id=obs.frame_id,
        workspace_id=obs.workspace_id,
        session_id=obs.session_id,
        source_id=obs.source_id,
        sequence_number=obs.sequence_number,
        timestamp_ns=obs.timestamp_ns,
        width=obs.width,
        height=obs.height,
        format=obs.format,
        size_bytes=obs.size_bytes,
        received_at=obs.received_at,
        preview_thumbnail_base64=preview_b64,
    )


@router.get(
    "/camera/status",
    response_model=CameraStatusResponse,
    summary="Get camera streaming subsystem status and limits",
)
async def get_camera_status(
    current_user: User = Depends(get_current_user),
    x_workspace_id: Optional[str] = Header(None, alias="X-Workspace-Id"),
) -> CameraStatusResponse:
    """Check camera transport subsystem availability, active sessions, and FPS limits."""
    ws_id = x_workspace_id or str(getattr(current_user, "default_workspace_id", ""))
    info = camera_vision_service.get_status(workspace_id=ws_id)

    return CameraStatusResponse(
        status=info["status"],
        active_sessions_count=info["active_sessions_count"],
        default_fps=info["default_fps"],
        max_fps_ceiling=info["max_fps_ceiling"],
        min_frame_interval_sec=info["min_frame_interval_sec"],
        max_resolution=info["max_resolution"],
        header_size_bytes=info["header_size_bytes"],
        buffer_depth=info["buffer_depth"],
        has_ephemeral_frame=info["has_ephemeral_frame"],
        format=info["format"],
    )


@router.delete(
    "/camera/cache",
    response_model=CameraBufferClearResponse,
    summary="Clear ephemeral camera observation cache",
)
async def clear_camera_cache(
    current_user: User = Depends(get_current_user),
    x_workspace_id: Optional[str] = Header(None, alias="X-Workspace-Id"),
) -> CameraBufferClearResponse:
    """Purge ephemeral camera observation from volatile memory."""
    ws_id = x_workspace_id or str(getattr(current_user, "default_workspace_id", ""))
    camera_vision_service.clear_ephemeral_frame(workspace_id=ws_id)
    return CameraBufferClearResponse(
        status="cleared",
        cleared=True,
        message="Ephemeral camera observation cache successfully cleared.",
    )

