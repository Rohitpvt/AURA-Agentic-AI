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

