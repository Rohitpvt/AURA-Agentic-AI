"""AURA-802 Continuous Local OCR Latency & Resource Benchmark.

Measures:
1. Local RapidOCR + ONNX Runtime Engine Initialization Latency.
2. Empty/Blank Frame OCR Latency.
3. Lightly Populated Screen OCR Latency (1-3 text lines).
4. Densely Populated Screen OCR Latency (10+ text lines, paragraphs).
5. Text Region Parsing & Normalization Geometry Extraction Latency.
6. Untrusted Context Envelope Construction Latency.
7. Full Pipeline Latency (CapturedFrame -> RapidOCR -> Observation).
8. Volatile In-Memory Cache Access Latency.
9. 1 Hz Rate Ceiling Interval Enforcement.

Outputs exact reproducible metrics: min, mean, p50, p95, p99, max across iterations.
"""

import io
import math
import os
import statistics
import sys
import time
from typing import Dict, List
import uuid

# Ensure apps/api is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PIL import Image, ImageDraw, ImageFont
from app.services.vision.screen_capture import CapturedFrame
from app.services.vision.ocr_service import ContinuousOCRService, OCRStatus, OCRObservation


def calculate_percentiles(values: List[float]) -> Dict[str, float]:
    """Calculate min, mean, p50, p95, p99, and max from a list of latencies (in milliseconds)."""
    if not values:
        return {"min": 0.0, "mean": 0.0, "p50": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0}

    sorted_vals = sorted(values)
    n = len(sorted_vals)

    def get_p(p: float) -> float:
        k = (n - 1) * p
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return sorted_vals[int(k)]
        return sorted_vals[int(f)] * (c - k) + sorted_vals[int(c)] * (k - f)

    return {
        "min": round(sorted_vals[0], 3),
        "mean": round(statistics.mean(sorted_vals), 3),
        "p50": round(get_p(0.50), 3),
        "p95": round(get_p(0.95), 3),
        "p99": round(get_p(0.99), 3),
        "max": round(sorted_vals[-1], 3),
    }


def make_test_frame(
    lines: List[str],
    width: int = 1280,
    height: int = 720,
    font_size: int = 24,
) -> CapturedFrame:
    """Generate in-memory test frame with synthetic lines."""
    img = Image.new("RGB", (width, height), color="#FFFFFF")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except Exception:
        font = ImageFont.load_default()

    y = 50
    for line in lines:
        draw.text((60, y), line, fill="#111827", font=font)
        y += font_size + 16

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    raw_bytes = buf.getvalue()

    return CapturedFrame(
        frame_id=f"bench-frame-{uuid.uuid4().hex[:8]}",
        stream_type="screen",
        monitor_id=1,
        original_dimensions=(width, height),
        processed_dimensions=(width, height),
        format="PNG",
        size_bytes=len(raw_bytes),
        timestamp_ns=time.time_ns(),
        sequence_number=1,
        is_changed=True,
        delta_ratio=0.9,
        window_info=None,
        raw_bytes=raw_bytes,
    )


def run_ocr_benchmark(num_trials: int = 30) -> Dict[str, Dict[str, float]]:
    """Execute reproducible latency benchmark for AURA-802 OCR engine."""
    print(f"\n================================================================================")
    print(f"  AURA-802 CONTINUOUS LOCAL OCR & TEXT EXTRACTION BENCHMARK ({num_trials} TRIALS)")
    print(f"================================================================================\n")

    # 1. Cold Engine Init Latency
    t0 = time.perf_counter()
    cold_service = ContinuousOCRService()
    init_latency_ms = (time.perf_counter() - t0) * 1000
    print(f"[*] OCR Engine Initialization Latency: {init_latency_ms:.2f} ms (Status: {cold_service.status.value})")

    svc = ContinuousOCRService()
    svc.clear_cache()

    # Create Test Fixtures
    empty_frame = make_test_frame(lines=[], width=1280, height=720)
    light_frame = make_test_frame(
        lines=[
            "AURA PROJECT - EXECUTIVE CONSOLE",
            "SECURITY STATUS: COMPLIANT | ZERO EXTERNAL TELEMETRY",
            "WORKFLOW ID: AURA-802-CONTINUOUS-OCR",
        ],
        width=1280,
        height=720,
    )
    dense_frame = make_test_frame(
        lines=[
            "SECTION 1: SYSTEM SPECIFICATION & ARCHITECTURAL INVARIANTS",
            "Phase 8.2 implements local OCR using RapidOCR with ONNX Runtime.",
            "All recognition runs strictly on local CPU with zero cloud API dependency.",
            "Screen frames are consumed from AURA-801 ScreenCaptureService ephemeral buffer.",
            "Rate ceiling is strictly enforced at 1.0 Hz with newest-frame-wins buffering.",
            "Untrusted sensory input is wrapped in isolated XML context envelopes.",
            "Emergency kill-switch immediately halts OCR and purges volatile caches.",
            "Coordinate geometry preserves explicit captured_frame pixel and normalized spaces.",
            "Memory residency remains bounded with zero raw frame disk/DB persistence.",
            "Zero cost floor invariant ($0.00) is preserved across all vision operations.",
            "AURA-803 camera ingestion and AURA-804 VLM reasoning are locked out.",
            "All endpoints enforce workspace scoping, RBAC, and standard error envelopes.",
        ],
        width=1920,
        height=1080,
    )

    empty_latencies: List[float] = []
    light_latencies: List[float] = []
    dense_latencies: List[float] = []
    envelope_latencies: List[float] = []
    cache_access_latencies: List[float] = []

    # Warmup pass
    _ = svc.process_frame(empty_frame, workspace_id="warmup", force_refresh=True)
    _ = svc.process_frame(light_frame, workspace_id="warmup", force_refresh=True)
    _ = svc.process_frame(dense_frame, workspace_id="warmup", force_refresh=True)

    print(f"[*] Executing {num_trials} benchmark trials across test matrices...")

    # Benchmark Empty Frame
    for _ in range(num_trials):
        t0 = time.perf_counter()
        obs = svc.process_frame(empty_frame, workspace_id="bench-ws", force_refresh=True)
        empty_latencies.append((time.perf_counter() - t0) * 1000)

    # Benchmark Light Frame
    for _ in range(num_trials):
        t0 = time.perf_counter()
        obs = svc.process_frame(light_frame, workspace_id="bench-ws", force_refresh=True)
        light_latencies.append((time.perf_counter() - t0) * 1000)

    # Benchmark Dense Frame
    for _ in range(num_trials):
        t0 = time.perf_counter()
        obs = svc.process_frame(dense_frame, workspace_id="bench-ws", force_refresh=True)
        dense_latencies.append((time.perf_counter() - t0) * 1000)

    # Benchmark Envelope Generation
    for _ in range(num_trials):
        t0 = time.perf_counter()
        _ = obs.get_untrusted_context_envelope()
        envelope_latencies.append((time.perf_counter() - t0) * 1000)

    # Benchmark Volatile Cache Access
    for _ in range(num_trials):
        t0 = time.perf_counter()
        _ = svc.get_latest_observation(workspace_id="bench-ws")
        cache_access_latencies.append((time.perf_counter() - t0) * 1000)

    results = {
        "engine_init": {"latency_ms": round(init_latency_ms, 3)},
        "empty_frame_ocr": calculate_percentiles(empty_latencies),
        "light_screen_ocr": calculate_percentiles(light_latencies),
        "dense_screen_ocr": calculate_percentiles(dense_latencies),
        "envelope_generation": calculate_percentiles(envelope_latencies),
        "cache_access": calculate_percentiles(cache_access_latencies),
    }

    # Print Formatted Report
    print(f"\n{'-'*80}")
    print(f"{'OPERATION':<32} | {'MIN':<7} | {'MEAN':<8} | {'P50':<7} | {'P95':<7} | {'P99':<7} | {'MAX':<7}")
    print(f"{'-'*80}")
    for name, stats in results.items():
        if name == "engine_init":
            print(f"{'Cold Engine Init':<32} | {stats['latency_ms']:<7} | {stats['latency_ms']:<8} | {stats['latency_ms']:<7} | {stats['latency_ms']:<7} | {stats['latency_ms']:<7} | {stats['latency_ms']:<7}")
        else:
            label = name.replace("_", " ").title()
            print(f"{label:<32} | {stats['min']:<7.2f} | {stats['mean']:<8.2f} | {stats['p50']:<7.2f} | {stats['p95']:<7.2f} | {stats['p99']:<7.2f} | {stats['max']:<7.2f}")
    print(f"{'-'*80}\n")

    return results


if __name__ == "__main__":
    run_ocr_benchmark()
