"""Governed Vision Tool Handlers for Agent Runtime (AURA-705 / AURA-804).

Provides canonical handlers for:
1. image_inspect (AURA-705 Static Image VLM & OCR)
2. inspect_current_screen (AURA-804 Live Screen Snapshot & VLM Reasoning)
3. inspect_active_window (AURA-804 Foreground Window Introspection & VLM)
4. inspect_camera_frame (AURA-804 Camera Ephemeral Ingestion & VLM)
5. query_visible_text (AURA-804 Continuous OCR Structured Geometry Extraction)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AuthorizationError, EntityNotFoundError, ValidationError
from app.core.logging import logger
from app.core.sanitization import prompt_sanitizer
from app.services.file_service import file_service
from app.services.vision.ocr_service import continuous_ocr_service
from app.services.vision.service import vision_service
from app.services.vision.vlm_service import vision_vlm_service


async def execute_image_inspect(
    workspace_id: uuid.UUID,
    arguments: Optional[Dict[str, Any]] = None,
    db: Optional[AsyncSession] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Execute image_inspect tool: Inspects static workspace image using local VLM."""
    args = dict(arguments or {})
    args.update(kwargs)

    file_id_raw = args.get("file_id")
    if not file_id_raw:
        raise ValidationError("Parameter 'file_id' is required for image_inspect")

    try:
        file_id = uuid.UUID(str(file_id_raw))
    except ValueError as exc:
        raise ValidationError(f"Invalid UUID format for file_id: {file_id_raw}") from exc

    if not db:
        raise ValidationError("Active database session required for workspace file lookup")

    # 1. Enforce Workspace Tenancy & File Authorization
    file_record = await file_service.get_file(db=db, workspace_id=workspace_id, file_id=file_id)

    # 2. Validate MIME Type / Format
    valid_mime_prefixes = ("image/jpeg", "image/png", "image/webp", "image/bmp", "image/jpg")
    valid_extensions = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
    if not (
        file_record.mime_type.lower().startswith(valid_mime_prefixes)
        or file_record.file_extension.lower() in valid_extensions
    ):
        raise ValidationError(
            f"File '{file_record.original_filename}' with MIME '{file_record.mime_type}' is not a supported static image format (JPEG, PNG, WEBP, BMP)"
        )

    # 3. Read image bytes from storage
    storage_path = Path(file_record.storage_path)
    if not storage_path.exists() or not storage_path.is_file():
        raise EntityNotFoundError("File payload not found on disk storage", str(file_id))

    try:
        with open(storage_path, "rb") as f_in:
            image_bytes = f_in.read()
    except Exception as read_err:
        logger.error(f"Failed to read image file {storage_path}: {read_err}")
        raise ValidationError(f"Unable to read image file from disk: {read_err}") from read_err

    # 4. Invoke VisionService
    prompt = args.get("prompt")
    detail_level = args.get("detail_level", "standard")
    model_override = args.get("model")

    result = await vision_service.inspect_image(
        image_bytes=image_bytes,
        prompt=prompt,
        detail_level=detail_level,
        model_override=model_override,
        file_id=str(file_record.id),
        workspace_id=workspace_id,
    )

    return {
        "file_id": str(file_record.id),
        "filename": file_record.original_filename,
        "format": result.format,
        "original_dimensions": {
            "width": result.original_dimensions[0],
            "height": result.original_dimensions[1],
        },
        "processed_dimensions": {
            "width": result.processed_dimensions[0],
            "height": result.processed_dimensions[1],
        },
        "size_bytes": result.size_bytes,
        "model_used": result.model_used,
        "processing_time_ms": round(result.processing_time_ms, 2),
        "description": result.description,
        "untrusted_content_envelope": result.untrusted_content_envelope,
        "is_untrusted_content": True,
        "security_flags": result.security_flags,
        "ocr_available": result.ocr_available,
        "status": "success",
    }


async def execute_inspect_current_screen(
    workspace_id: uuid.UUID,
    arguments: Optional[Dict[str, Any]] = None,
    db: Optional[AsyncSession] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Execute inspect_current_screen tool: Read-only snapshot inspection of current display via local VLM."""
    args = dict(arguments or {})
    args.update(kwargs)

    monitor_id = int(args.get("monitor_id", 1))
    prompt = args.get("prompt")
    detail_level = str(args.get("detail_level", "standard"))
    model_override = args.get("model")
    include_ocr_context = bool(args.get("include_ocr_context", True))

    obs = await vision_vlm_service.inspect_screen(
        workspace_id=workspace_id,
        monitor_id=monitor_id,
        prompt=prompt,
        detail_level=detail_level,
        model_override=model_override,
        include_ocr_context=include_ocr_context,
    )

    res = obs.to_dict()
    res["status"] = "success" if not obs.degraded else "degraded"
    return res


async def execute_inspect_active_window(
    workspace_id: uuid.UUID,
    arguments: Optional[Dict[str, Any]] = None,
    db: Optional[AsyncSession] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Execute inspect_active_window tool: Read-only inspection of foreground active window via local VLM."""
    args = dict(arguments or {})
    args.update(kwargs)

    prompt = args.get("prompt")
    detail_level = str(args.get("detail_level", "standard"))
    model_override = args.get("model")
    include_ocr_context = bool(args.get("include_ocr_context", True))

    obs = await vision_vlm_service.inspect_active_window(
        workspace_id=workspace_id,
        prompt=prompt,
        detail_level=detail_level,
        model_override=model_override,
        include_ocr_context=include_ocr_context,
    )

    res = obs.to_dict()
    res["status"] = "success" if not obs.degraded else "degraded"
    return res


async def execute_inspect_camera_frame(
    workspace_id: uuid.UUID,
    arguments: Optional[Dict[str, Any]] = None,
    db: Optional[AsyncSession] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Execute inspect_camera_frame tool: Read-only inspection of latest camera frame from AURA-803 buffer."""
    args = dict(arguments or {})
    args.update(kwargs)

    prompt = args.get("prompt")
    detail_level = str(args.get("detail_level", "standard"))
    model_override = args.get("model")

    obs = await vision_vlm_service.inspect_camera(
        workspace_id=workspace_id,
        prompt=prompt,
        detail_level=detail_level,
        model_override=model_override,
    )

    res = obs.to_dict()
    res["status"] = "success" if not obs.degraded else "camera_inactive"
    return res


async def execute_query_visible_text(
    workspace_id: uuid.UUID,
    arguments: Optional[Dict[str, Any]] = None,
    db: Optional[AsyncSession] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Execute query_visible_text tool: Queries structured local OCR observations across screen regions."""
    args = dict(arguments or {})
    args.update(kwargs)

    query = args.get("query")
    min_confidence = float(args.get("min_confidence", 0.0))
    case_sensitive = bool(args.get("case_sensitive", False))
    monitor_id = int(args.get("monitor_id", 1))

    # Extract or retrieve latest OCR text
    ocr_obs = continuous_ocr_service.extract_ocr(
        workspace_id=str(workspace_id),
        monitor_id=monitor_id,
    )

    # Filter regions by confidence and query
    matched_regions = []
    for reg in ocr_obs.text_regions:
        if reg.confidence < min_confidence:
            continue

        if query:
            target_q = query if case_sensitive else query.lower()
            text_val = reg.text if case_sensitive else reg.text.lower()
            if target_q not in text_val:
                continue

        matched_regions.append({
            "text": reg.text,
            "confidence": round(reg.confidence, 4),
            "bounding_box": [reg.bbox.x, reg.bbox.y, reg.bbox.width, reg.bbox.height],
            "polygon": reg.bbox.polygon,
            "normalized_box": reg.bbox.normalized_bbox,
            "coordinate_space": "captured_frame",
        })

    matched_text_lines = [r["text"] for r in matched_regions]
    matched_text = "\n".join(matched_text_lines)

    # Wrap in untrusted multimodal envelope
    untrusted_envelope = prompt_sanitizer.wrap_untrusted_multimodal_envelope(
        content=matched_text if matched_text else ocr_obs.full_text,
        origin="screen_ocr",
        model="rapidocr_onnx",
    )

    return {
        "query": query,
        "total_regions": len(ocr_obs.text_regions),
        "matched_regions_count": len(matched_regions),
        "matched_text": matched_text,
        "regions": matched_regions,
        "full_text": ocr_obs.full_text,
        "coordinate_space": "captured_frame",
        "degraded": ocr_obs.degraded,
        "status": "success" if not ocr_obs.degraded else "degraded",
        "untrusted_content_envelope": untrusted_envelope,
        "is_untrusted_content": True,
    }
