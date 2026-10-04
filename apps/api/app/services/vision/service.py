"""AURA-705 Static Multimodal Vision & Image Inspection Service.

Provides:
1. Static image validation, format screening (JPEG, PNG, WEBP, BMP), and corrupt file rejection.
2. Aspect-ratio-preserving proportional downscaling to max 2048x2048.
3. Local VLM visual description & question answering (Moondream2 / Qwen2-VL 2B via Ollama).
4. Local OCR inspection integration with graceful degraded fallback.
5. Canonical <untrusted_multimodal_content> prompt-injection containment envelope.
6. Ephemeral memory processing: Zero raw image persistence to logs, OTel, or audit trails.
"""

import base64
import io
import time
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid
from dataclasses import dataclass, field
import httpx
from PIL import Image, UnidentifiedImageError

from app.core.config import settings
from app.core.errors import (
    AuthorizationError,
    EntityNotFoundError,
    LocalModelUnavailableError,
    ModelTimeoutError,
    ValidationError,
    VoiceProcessingError,
)
from app.core.logging import logger
from app.core.sanitization import prompt_sanitizer


# Supported image formats
SUPPORTED_IMAGE_FORMATS: Set[str] = {"JPEG", "JPG", "PNG", "WEBP", "BMP"}
MAX_FILE_SIZE_BYTES: int = 10 * 1024 * 1024  # 10 MB
MAX_DIMENSION: int = 2048
DEFAULT_VISION_TIMEOUT: float = 15.0


@dataclass
class VisionInspectionResult:
    """Structured result of static multimodal image inspection."""

    file_id: Optional[str]
    original_dimensions: Tuple[int, int]
    processed_dimensions: Tuple[int, int]
    format: str
    size_bytes: int
    model_used: str
    processing_time_ms: float
    description: str
    untrusted_content_envelope: str
    is_untrusted_content: bool = True
    security_flags: List[str] = field(default_factory=list)
    ocr_available: bool = False
    ocr_text: Optional[str] = None


class VisionService:
    """Local Static Multimodal Vision & Image Inspection Capability Service."""

    def __init__(
        self,
        default_model: Optional[str] = None,
        alternative_model: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
        ollama_base_url: Optional[str] = None,
    ):
        self.default_model = default_model or getattr(settings, "VISION_DEFAULT_MODEL", "moondream")
        self.alternative_model = alternative_model or getattr(settings, "VISION_ALTERNATIVE_MODEL", "qwen2-vl:2b")
        self.timeout_seconds = timeout_seconds or getattr(settings, "VISION_TIMEOUT_SECONDS", DEFAULT_VISION_TIMEOUT)
        self.ollama_base_url = (ollama_base_url or settings.OLLAMA_BASE_URL).rstrip("/")

    def validate_and_preprocess_image(
        self,
        image_bytes: bytes,
    ) -> Tuple[bytes, Tuple[int, int], Tuple[int, int], str, int]:
        """Validate format, screen magic bytes, decode pixels, and downscale proportionally if oversized.
        
        Returns:
            (processed_bytes, original_dimensions, processed_dimensions, format_name, original_size_bytes)
        """
        if not image_bytes:
            raise ValidationError("Image payload is empty (0 bytes)")

        orig_size = len(image_bytes)
        if orig_size > MAX_FILE_SIZE_BYTES:
            raise ValidationError(
                f"Image file size {orig_size} bytes exceeds maximum limit of 10 MB ({MAX_FILE_SIZE_BYTES} bytes)"
            )

        try:
            # Open with PIL and decode image structure
            img_io = io.BytesIO(image_bytes)
            with Image.open(img_io) as img:
                raw_format = (img.format or "").upper()
                if raw_format not in SUPPORTED_IMAGE_FORMATS:
                    raise ValidationError(
                        f"Unsupported image format '{raw_format}'. Supported formats: JPEG, PNG, WEBP, BMP"
                    )

                orig_w, orig_h = img.size
                if orig_w <= 0 or orig_h <= 0:
                    raise ValidationError(f"Invalid image dimensions: {orig_w}x{orig_h}")

                # Check if proportional downscaling is needed (never enlarge smaller images)
                needs_downscale = orig_w > MAX_DIMENSION or orig_h > MAX_DIMENSION
                
                # Load pixel data to verify complete uncorrupted payload
                img.load()

                # Process image in memory
                work_img = img.copy()
                if needs_downscale:
                    work_img.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.Resampling.BILINEAR)
                
                new_w, new_h = work_img.size

                # Normalize color mode for VLM compatibility
                if work_img.mode in ("RGBA", "LA", "P"):
                    # Convert transparent or palette images to RGB with white background
                    bg = Image.new("RGB", work_img.size, (255, 255, 255))
                    if work_img.mode == "P":
                        work_img = work_img.convert("RGBA")
                    bg.paste(work_img, mask=work_img.split()[-1] if len(work_img.split()) == 4 else None)
                    work_img = bg
                elif work_img.mode != "RGB":
                    work_img = work_img.convert("RGB")

                # Export preprocessed bytes
                out_io = io.BytesIO()
                export_format = "JPEG" if raw_format in ("JPEG", "JPG") else raw_format
                if export_format not in ("JPEG", "PNG", "WEBP", "BMP"):
                    export_format = "PNG"

                save_kwargs: Dict[str, Any] = {}
                if export_format in ("JPEG", "JPG"):
                    save_kwargs["quality"] = 90
                elif export_format == "WEBP":
                    save_kwargs["quality"] = 85
                elif export_format == "PNG":
                    save_kwargs["compress_level"] = 1

                work_img.save(out_io, format=export_format, **save_kwargs)
                processed_bytes = out_io.getvalue()

                return processed_bytes, (orig_w, orig_h), (new_w, new_h), raw_format, orig_size

        except (UnidentifiedImageError, OSError, ValueError) as exc:
            logger.warning(f"VisionService: Image decoding failed: {exc}")
            raise ValidationError(f"Malformed, corrupt, or unsupported image file: {exc}") from exc

    async def _execute_vlm_inference(
        self,
        image_bytes: bytes,
        prompt: str,
        model_name: str,
    ) -> str:
        """Execute local VLM inference against Ollama /api/generate or local model runtime."""
        b64_image = base64.b64encode(image_bytes).decode("utf-8")
        payload = {
            "model": model_name,
            "prompt": prompt,
            "images": [b64_image],
            "stream": False,
            "options": {
                "temperature": 0.2,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                resp = await client.post(f"{self.ollama_base_url}/api/generate", json=payload)
                if resp.status_code != 200:
                    error_detail = resp.text
                    logger.warning(f"VisionService: Ollama VLM returned status {resp.status_code}: {error_detail}")
                    raise LocalModelUnavailableError(
                        f"Local VLM model '{model_name}' execution failed with status {resp.status_code}: {error_detail}"
                    )
                data = resp.json()
                response_text = data.get("response", "")
                return response_text.strip()

        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            logger.warning(f"VisionService: Cannot connect to local Ollama at {self.ollama_base_url}")
            raise LocalModelUnavailableError(
                f"Local VLM runtime is unavailable at {self.ollama_base_url}. Zero-cost invariant: cloud fallback prohibited."
            ) from exc
        except httpx.TimeoutException as exc:
            logger.warning(f"VisionService: VLM inference timed out after {self.timeout_seconds}s for model {model_name}")
            raise ModelTimeoutError(
                f"Local VLM inference timed out after {self.timeout_seconds} seconds for model '{model_name}'."
            ) from exc

    def _execute_local_ocr_if_available(self, image_bytes: bytes) -> Tuple[bool, Optional[str]]:
        """Attempt local OCR extraction if local engine (e.g. pytesseract) is installed."""
        try:
            import pytesseract  # type: ignore
            img = Image.open(io.BytesIO(image_bytes))
            text = pytesseract.image_to_string(img)
            return True, text.strip() if text else None
        except (ImportError, Exception):
            # Graceful degraded fallback: OCR not available in local environment
            return False, None

    async def inspect_image(
        self,
        image_bytes: bytes,
        prompt: Optional[str] = None,
        detail_level: str = "standard",
        model_override: Optional[str] = None,
        file_id: Optional[str] = None,
        workspace_id: Optional[uuid.UUID] = None,
    ) -> VisionInspectionResult:
        """Inspect a static image using local VLM, validate security envelopes, and return structured analysis."""
        t0 = time.perf_counter()

        # 1. Validation & Preprocessing (downscale, format check)
        processed_bytes, orig_dims, proc_dims, img_format, orig_size = self.validate_and_preprocess_image(image_bytes)

        # 2. Select VLM Model
        model_name = model_override or self.default_model

        # 3. Construct effective prompt
        user_prompt = prompt.strip() if prompt and prompt.strip() else "Describe this image in detail and extract all visible text."
        if detail_level == "high":
            effective_prompt = f"Provide an exhaustive visual analysis, describe layout, color palette, objects, relationships, and extract all readable text: {user_prompt}"
        elif detail_level == "low":
            effective_prompt = f"Provide a concise one-paragraph summary of this image: {user_prompt}"
        else:
            effective_prompt = user_prompt

        # 4. Execute VLM Inference & OCR
        vlm_description = ""
        try:
            vlm_description = await self._execute_vlm_inference(
                image_bytes=processed_bytes,
                prompt=effective_prompt,
                model_name=model_name,
            )
        except LocalModelUnavailableError as exc:
            # If Ollama is offline, provide structured degraded response or re-raise based on caller expectation
            logger.warning(f"VisionService: Local VLM unavailable: {exc}")
            vlm_description = f"[LOCAL_VLM_UNAVAILABLE: {str(exc)}]"

        ocr_available, ocr_text = self._execute_local_ocr_if_available(processed_bytes)

        # 5. Aggregate extracted text
        full_content_parts = []
        if vlm_description:
            full_content_parts.append(f"Visual Analysis ({model_name}):\n{vlm_description}")
        if ocr_text:
            full_content_parts.append(f"OCR Extracted Text:\n{ocr_text}")
        
        raw_combined_content = "\n\n".join(full_content_parts) if full_content_parts else "No visual content extracted."

        # 6. Prompt Injection Detection Heuristics
        has_injection, security_flags = prompt_sanitizer.detect_injection_signatures(raw_combined_content)
        if has_injection:
            logger.warning(
                f"VisionService: Potential adversarial prompt injection detected in image text for file '{file_id}': {security_flags}"
            )

        # 7. Untrusted Multimodal XML Envelope Wrapping
        untrusted_envelope = prompt_sanitizer.wrap_untrusted_multimodal_envelope(
            content=raw_combined_content,
            origin="vlm_inspection",
            model=model_name,
            file_id=file_id,
        )

        duration_ms = (time.perf_counter() - t0) * 1000.0

        return VisionInspectionResult(
            file_id=file_id,
            original_dimensions=orig_dims,
            processed_dimensions=proc_dims,
            format=img_format,
            size_bytes=orig_size,
            model_used=model_name,
            processing_time_ms=duration_ms,
            description=vlm_description,
            untrusted_content_envelope=untrusted_envelope,
            is_untrusted_content=True,
            security_flags=security_flags,
            ocr_available=ocr_available,
            ocr_text=ocr_text,
        )


# Global singleton
vision_service = VisionService()
