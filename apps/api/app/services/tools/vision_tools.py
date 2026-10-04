"""Governed Static Multimodal Vision Tool Handlers for Agent Runtime."""

import os
from pathlib import Path
from typing import Any, Dict, Optional
import uuid
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AuthorizationError, EntityNotFoundError, ValidationError
from app.core.logging import logger
from app.services.file_service import file_service
from app.services.vision.service import vision_service


async def execute_image_inspect(
    workspace_id: uuid.UUID,
    arguments: Optional[Dict[str, Any]] = None,
    db: Optional[AsyncSession] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Execute image_inspect tool: Inspects static workspace image using local VLM and returns untrusted content envelope."""
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
