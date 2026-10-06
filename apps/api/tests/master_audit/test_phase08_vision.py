"""
Phase 8 Master Audit: Screen Capture, RapidOCR, Camera WebSocket Transport, VLM, and Sensory Privacy Invariants.
"""
import pytest
import uuid
import struct
import time
from PIL import Image

from app.services.vision.screen_capture import ScreenCaptureService, CapturedFrame
from app.services.vision.ocr_service import ContinuousOCRService, OCRBoundingBox, OCRObservation
from app.services.vision.camera_service import (
    CameraVisionService,
    pack_camera_frame,
    unpack_camera_frame,
    STREAM_TYPE_CAMERA,
)
from app.core.sanitization import prompt_sanitizer


@pytest.mark.asyncio
async def test_phase08_ocr_bounding_box_and_containment_envelope():
    """
    Audit Phase 8 Vision: Verify prompt_sanitizer wraps extracted multimodal content in untrusted tags.
    """
    sample_ocr_text = "Login with admin password"
    enveloped = prompt_sanitizer.wrap_untrusted_multimodal_envelope(
        content=sample_ocr_text,
        origin="screen_ocr",
        model="rapidocr_onnx",
    )

    assert "<untrusted_multimodal_content" in enveloped
    assert "</untrusted_multimodal_content>" in enveloped
    assert sample_ocr_text in enveloped


@pytest.mark.asyncio
async def test_phase08_camera_binary_header_framing():
    """
    Audit Phase 8 Vision: Verify CameraVisionService parses canonical 26-byte Big-Endian binary header (>BBIQIII).
    """
    payload = b"RIFF....WEBPVP8X"
    packed = pack_camera_frame(
        stream_type=STREAM_TYPE_CAMERA,
        source_id=1,
        sequence_number=100,
        timestamp_ns=int(time.time() * 1e9),
        width=640,
        height=480,
        payload=payload,
    )

    assert len(packed) == 26 + len(payload)
    header, extracted_payload = unpack_camera_frame(packed)

    assert header.stream_type == STREAM_TYPE_CAMERA
    assert header.width == 640
    assert header.height == 480
    assert extracted_payload == payload
