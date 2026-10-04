"""AURA-801 Screen & Window Capture Latency & Resource Benchmark.

Measures:
1. Raw Screen Snapshot Latency (mss GDI BitBlt + PIL decode).
2. Active-Window Query Latency (GetForegroundWindow + metadata).
3. Monitor Discovery Latency (mss enumeration + DPI scaling).
4. DPI Coordinate Calculation Latency.
5. Normalized Delta Detection Latency (ImageChops difference + histogram).
6. Full Pipeline Latency (Grab + Delta + Downscale + WebP Encode).
7. Volatile Depth-1 Frame Access Latency.

Outputs exact reproducible metrics: min, mean, p50, p95, p99, max across 50 iterations.
"""

import ctypes
import io
import math
import os
import statistics
import sys
import time
from typing import Dict, List

# Ensure apps/api is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import mss
from PIL import Image
from app.services.vision.screen_capture import ScreenCaptureConfig, ScreenCaptureService


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


def run_screen_capture_benchmark(num_trials: int = 50) -> Dict[str, Dict[str, float]]:
    """Execute reproducible latency benchmark for AURA-801 capture engine."""
    svc = ScreenCaptureService(config=ScreenCaptureConfig(webp_method=0))
    svc.clear_ephemeral_buffer()

    monitor_discovery_latencies: List[float] = []
    dpi_calc_latencies: List[float] = []
    active_window_latencies: List[float] = []
    raw_snapshot_latencies: List[float] = []
    delta_detect_latencies: List[float] = []
    full_pipeline_latencies: List[float] = []
    frame_access_latencies: List[float] = []

    # Warmup
    _ = svc.list_monitors()
    _ = svc.get_system_dpi_scale()
    _ = svc.get_active_window()
    _ = svc.capture_frame(monitor_id=1)

    print(f"\n================================================================================")
    print(f"  AURA-801 SCREEN & ACTIVE-WINDOW CAPTURE ENGINE BENCHMARK ({num_trials} TRIALS)")
    print(f"================================================================================\n")

    # 1. Monitor Discovery
    for _ in range(num_trials):
        t0 = time.perf_counter()
        _ = svc.list_monitors()
        t1 = time.perf_counter()
        monitor_discovery_latencies.append((t1 - t0) * 1000.0)

    # 2. DPI Calculation
    for _ in range(num_trials):
        t0 = time.perf_counter()
        _ = svc.get_system_dpi_scale()
        t1 = time.perf_counter()
        dpi_calc_latencies.append((t1 - t0) * 1000.0)

    # 3. Active Window Query
    for _ in range(num_trials):
        t0 = time.perf_counter()
        _ = svc.get_active_window()
        t1 = time.perf_counter()
        active_window_latencies.append((t1 - t0) * 1000.0)

    # 4. Raw Screen Snapshot (mss GDI BitBlt + PIL decode)
    monitors = svc.list_monitors()
    target_rect = monitors[1].to_dict() if len(monitors) > 1 else monitors[0].to_dict()
    sct_dict = {"left": target_rect["left"], "top": target_rect["top"], "width": target_rect["width"], "height": target_rect["height"]}
    
    with mss.MSS() as sct:
        for _ in range(num_trials):
            t0 = time.perf_counter()
            raw_sct = sct.grab(sct_dict)
            _ = Image.frombytes("RGB", raw_sct.size, raw_sct.bgra, "raw", "BGRX")
            t1 = time.perf_counter()
            raw_snapshot_latencies.append((t1 - t0) * 1000.0)

    # 5. Delta Detection
    test_img_1 = Image.new("RGB", (1280, 720), color=(255, 255, 255))
    test_img_2 = Image.new("RGB", (1280, 720), color=(200, 200, 200))
    for i in range(num_trials):
        t0 = time.perf_counter()
        _ = svc._compute_frame_delta(test_img_2 if i % 2 == 0 else test_img_1)
        t1 = time.perf_counter()
        delta_detect_latencies.append((t1 - t0) * 1000.0)

    # 6. Full Pipeline (Capture + Delta + Downscale + WebP Encode)
    for _ in range(num_trials):
        t0 = time.perf_counter()
        _ = svc.capture_frame(monitor_id=1)
        t1 = time.perf_counter()
        full_pipeline_latencies.append((t1 - t0) * 1000.0)

    # 7. Ephemeral Frame Access
    for _ in range(num_trials):
        t0 = time.perf_counter()
        _ = svc.get_latest_frame()
        t1 = time.perf_counter()
        frame_access_latencies.append((t1 - t0) * 1000.0)

    results = {
        "Monitor Discovery": calculate_percentiles(monitor_discovery_latencies),
        "DPI Calculation": calculate_percentiles(dpi_calc_latencies),
        "Active Window Query": calculate_percentiles(active_window_latencies),
        "Raw Screen Snapshot": calculate_percentiles(raw_snapshot_latencies),
        "Delta Detection": calculate_percentiles(delta_detect_latencies),
        "Full Pipeline (WebP)": calculate_percentiles(full_pipeline_latencies),
        "Buffer Frame Access": calculate_percentiles(frame_access_latencies),
    }

    # Print Formatted Results
    print(f"{'Measurement':<26} | {'Min (ms)':<9} | {'Mean (ms)':<9} | {'p50 (ms)':<9} | {'p95 (ms)':<9} | {'p99 (ms)':<9} | {'Max (ms)':<9}")
    print(f"{'-'*26}-+-{'-'*9}-+-{'-'*9}-+-{'-'*9}-+-{'-'*9}-+-{'-'*9}-+-{'-'*9}")
    for name, p in results.items():
        print(f"{name:<26} | {p['min']:<9} | {p['mean']:<9} | {p['p50']:<9} | {p['p95']:<9} | {p['p99']:<9} | {p['max']:<9}")

    print(f"\nTarget Evaluation Against Preflight Specifications:")
    print(f"  * Raw Screen Snapshot <= 15 ms: Mean = {results['Raw Screen Snapshot']['mean']} ms (p50 = {results['Raw Screen Snapshot']['p50']} ms, p95 = {results['Raw Screen Snapshot']['p95']} ms)")
    print(f"  * Active-Window Query <= 5 ms: Mean = {results['Active Window Query']['mean']} ms (p50 = {results['Active Window Query']['p50']} ms, p95 = {results['Active Window Query']['p95']} ms)")
    print(f"  * Delta Detection <= 10 ms: Mean = {results['Delta Detection']['mean']} ms (p50 = {results['Delta Detection']['p50']} ms)")
    print(f"  * Full End-to-End Pipeline: Mean = {results['Full Pipeline (WebP)']['mean']} ms (p50 = {results['Full Pipeline (WebP)']['p50']} ms)")
    print(f"================================================================================\n")

    return results


if __name__ == "__main__":
    run_screen_capture_benchmark(num_trials=50)
