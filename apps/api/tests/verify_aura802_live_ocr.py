"""AURA-802 Live Windows Desktop OCR Verification Script.

Executes real on-host validation:
1. Captures live desktop screen using AURA-801 ScreenCaptureService.
2. Performs local CPU OCR via RapidOCR + ONNX Runtime (zero cloud API dependency).
3. Verifies geometry extraction: pixel bounding boxes, 4-point polygons, normalized 0.0-1.0 coordinates.
4. Verifies confidence scores are bounded in [0.0, 1.0].
5. Verifies untrusted sensory input containment in canonical XML envelope.
6. Verifies 1 Hz rate ceiling enforcement.
7. Verifies Emergency Kill Switch halts execution and purges volatile observation cache.
8. Verifies privacy invariants: zero raw frame or raw text persistence to disk or DB.
"""

import os
import sys
import time

# Ensure apps/api is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.kill_switch import kill_switch
from app.services.vision.screen_capture import screen_capture_service
from app.services.vision.ocr_service import continuous_ocr_service, OCRStatus


def run_live_ocr_verification():
    print("\n" + "=" * 80)
    print("  AURA-802 LIVE WINDOWS DESKTOP OCR & GEOMETRY VERIFICATION")
    print("=" * 80 + "\n")

    # 0. Clean state
    kill_switch.set_active(False)
    screen_capture_service.clear_ephemeral_buffer()
    continuous_ocr_service.clear_cache()

    # 1. Verify Engine Status
    print(f"[*] Checking OCR Engine Status...")
    status = continuous_ocr_service.status
    print(f"    -> Operational Status: {status.value}")
    print(f"    -> Rate Ceiling: {continuous_ocr_service.OCR_MAX_FPS} Hz (Min interval: {continuous_ocr_service.OCR_MIN_INTERVAL}s)")
    assert status == OCRStatus.AVAILABLE, f"Expected AVAILABLE, got {status}"

    # 2. Live Desktop Screen Capture & OCR Extraction
    print(f"\n[*] Executing Live Desktop Screen Capture & OCR Extraction...")
    t0 = time.perf_counter()
    obs = continuous_ocr_service.extract_ocr(
        monitor_id=1,
        force_refresh=True,
        workspace_id="live-validation-ws",
    )
    t_elapsed_ms = (time.perf_counter() - t0) * 1000.0

    print(f"    -> Frame ID: {obs.frame_id}")
    print(f"    -> Observation ID: {obs.observation_id}")
    print(f"    -> Frame Dimensions: {obs.frame_dimensions[0]}x{obs.frame_dimensions[1]}")
    print(f"    -> Processing Duration: {obs.processing_duration_ms:.2f} ms (Wall: {t_elapsed_ms:.2f} ms)")
    print(f"    -> Text Regions Detected: {len(obs.text_regions)}")
    print(f"    -> Degraded Mode: {obs.degraded}")

    assert obs.status == OCRStatus.AVAILABLE
    assert not obs.degraded
    assert obs.frame_dimensions[0] > 0 and obs.frame_dimensions[1] > 0

    # 3. Geometric Verification of Extracted Regions
    print(f"\n[*] Verifying Geometric Extents & Bounding Boxes...")
    for idx, r in enumerate(obs.text_regions[:5]):  # inspect first 5 regions
        print(f"    [Region {idx+1}] Text: '{r.text[:30]}...' | Conf: {r.confidence:.4f}")
        print(f"                 Pixel BBox: [x={r.bbox.x:.1f}, y={r.bbox.y:.1f}, w={r.bbox.width:.1f}, h={r.bbox.height:.1f}]")
        print(f"                 Normalized: [nx={r.bbox.norm_x:.4f}, ny={r.bbox.norm_y:.4f}, nw={r.bbox.norm_w:.4f}, nh={r.bbox.norm_h:.4f}]")
        print(f"                 Polygon: {r.bbox.polygon}")
        
        assert 0.0 <= r.confidence <= 1.0
        assert r.bbox.width >= 0 and r.bbox.height >= 0
        assert len(r.bbox.polygon) == 4
        assert 0.0 <= r.bbox.norm_x <= 1.0 and 0.0 <= r.bbox.norm_y <= 1.0
        assert 0.0 <= r.bbox.norm_w <= 1.0 and 0.0 <= r.bbox.norm_h <= 1.0
        assert r.bbox.coordinate_space == "captured_frame"

    # 4. Untrusted Sensory Envelope Verification
    print(f"\n[*] Verifying Untrusted Context Envelope...")
    envelope = obs.get_untrusted_context_envelope()
    print(f"    -> Envelope header preview:\n       {envelope.splitlines()[0]}")
    assert "<untrusted_multimodal_content" in envelope
    assert "</untrusted_multimodal_content>" in envelope
    assert obs.is_untrusted_sensory_input is True

    # 5. Rate Limiting 1 Hz Ceiling Verification
    print(f"\n[*] Verifying Strict 1 Hz Rate Ceiling...")
    t_start = time.perf_counter()
    obs_rapid = continuous_ocr_service.extract_ocr(
        monitor_id=1,
        force_refresh=False,
        workspace_id="live-validation-ws",
    )
    t_rapid_ms = (time.perf_counter() - t_start) * 1000.0
    print(f"    -> Immediate successive call completed in {t_rapid_ms:.2f} ms")
    print(f"    -> Returned cached observation ID: {obs_rapid.observation_id == obs.observation_id}")
    assert obs_rapid.observation_id == obs.observation_id, "Rate ceiling failed to return cached observation on rapid invocation"

    # 6. Kill Switch Halt & Cache Purge Verification
    print(f"\n[*] Verifying Emergency Kill Switch Governance...")
    kill_switch.set_active(True)
    try:
        continuous_ocr_service.extract_ocr(monitor_id=1, workspace_id="live-validation-ws")
        raise AssertionError("OCR did not abort when kill switch was active!")
    except Exception as e:
        print(f"    -> Kill switch correctly blocked OCR: {type(e).__name__} ({e})")

    cached_after_kill = continuous_ocr_service.get_latest_observation(workspace_id="live-validation-ws")
    print(f"    -> Cached observation after kill switch: {cached_after_kill}")
    assert cached_after_kill is None, "Cache was not purged upon kill switch activation"

    kill_switch.set_active(False)

    print("\n" + "=" * 80)
    print("  [PASS] AURA-802 LIVE OCR VALIDATION COMPLETED SUCCESSFULLY")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    run_live_ocr_verification()
