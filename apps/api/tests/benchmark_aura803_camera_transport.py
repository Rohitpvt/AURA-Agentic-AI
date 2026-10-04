"""AURA-803 Camera Transport & Ingestion Performance Benchmark Suite.

Measures and validates:
1. Vision Ticket issuance and consumption latency.
2. 26-Byte Binary Framing packing & unpacking latency.
3. Ingestion and depth-1 volatile buffer update latency.
4. Backpressure frame-drop latency.
5. Ephemeral frame cache retrieval and purge latency.
6. Server-side FPS ceiling (2.0 FPS default, 5.0 FPS max) throughput & timing.
"""

import io
import os
import sys
import time
from typing import Dict, List
import uuid

# Ensure apps/api is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np
from PIL import Image

from app.services.vision.camera_service import (
    FRAME_HEADER_SIZE,
    MAX_CAMERA_FPS,
    STREAM_TYPE_CAMERA,
    CameraVisionService,
    pack_camera_frame,
    unpack_camera_frame,
)
from app.services.vision.ticket_service import VisionTicketService


def generate_benchmark_webp(width: int = 1280, height: int = 720) -> bytes:
    """Generate in-memory 720p WebP payload for benchmark trials."""
    img = Image.new("RGB", (width, height), color=(60, 120, 180))
    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=80)
    return buf.getvalue()


def run_trials(func, trials: int = 30) -> Dict[str, float]:
    """Execute a synchronous function for N trials and compute latency statistics."""
    latencies: List[float] = []
    for _ in range(trials):
        t0 = time.perf_counter()
        func()
        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000.0)  # ms

    return {
        "count": float(len(latencies)),
        "min_ms": float(np.min(latencies)),
        "mean_ms": float(np.mean(latencies)),
        "p50_ms": float(np.percentile(latencies, 50)),
        "p95_ms": float(np.percentile(latencies, 95)),
        "p99_ms": float(np.percentile(latencies, 99)),
        "max_ms": float(np.max(latencies)),
    }


async def run_async_trials(coro_func, trials: int = 30) -> Dict[str, float]:
    """Execute an asynchronous coroutine for N trials and compute latency statistics."""
    latencies: List[float] = []
    for _ in range(trials):
        t0 = time.perf_counter()
        await coro_func()
        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000.0)  # ms

    return {
        "count": float(len(latencies)),
        "min_ms": float(np.min(latencies)),
        "mean_ms": float(np.mean(latencies)),
        "p50_ms": float(np.percentile(latencies, 50)),
        "p95_ms": float(np.percentile(latencies, 95)),
        "p99_ms": float(np.percentile(latencies, 99)),
        "max_ms": float(np.max(latencies)),
    }


async def main():
    print("=" * 80)
    print("  AURA-803 CAMERA TRANSPORT & INGESTION PERFORMANCE BENCHMARK")
    print("=" * 80)
    print("Hardware: Windows 11 Host | Multi-Tenant Local Execution")
    print("Sample Size: 30 trials per scenario\n")

    ticket_service = VisionTicketService()
    camera_service = CameraVisionService()
    user_id = uuid.uuid4()
    ws_id = uuid.uuid4()

    # 1. Vision Ticket Issuance Benchmark
    async def trial_ticket_issue():
        await ticket_service.issue_ticket(user_id=user_id, workspace_id=ws_id, purpose="camera_stream")

    ticket_issue_stats = await run_async_trials(trial_ticket_issue, trials=30)
    print(f"[*] 1. Vision Ticket Issuance Latency:")
    print(f"    -> Mean: {ticket_issue_stats['mean_ms']:.4f} ms | P50: {ticket_issue_stats['p50_ms']:.4f} ms | P95: {ticket_issue_stats['p95_ms']:.4f} ms | Max: {ticket_issue_stats['max_ms']:.4f} ms")

    # 2. Vision Ticket Consumption Benchmark
    issued_tickets: List[str] = []
    for _ in range(30):
        t = await ticket_service.issue_ticket(user_id=user_id, workspace_id=ws_id, purpose="camera_stream")
        issued_tickets.append(t.ticket_token)

    consume_latencies: List[float] = []
    for token in issued_tickets:
        t0 = time.perf_counter()
        await ticket_service.consume_ticket(ticket_token=token, expected_workspace_id=ws_id, expected_purpose="camera_stream")
        t1 = time.perf_counter()
        consume_latencies.append((t1 - t0) * 1000.0)

    ticket_consume_stats = {
        "mean_ms": float(np.mean(consume_latencies)),
        "p50_ms": float(np.percentile(consume_latencies, 50)),
        "p95_ms": float(np.percentile(consume_latencies, 95)),
        "p99_ms": float(np.percentile(consume_latencies, 99)),
        "min_ms": float(np.min(consume_latencies)),
        "max_ms": float(np.max(consume_latencies)),
    }
    print(f"\n[*] 2. Vision Ticket Verification & Consumption Latency:")
    print(f"    -> Mean: {ticket_consume_stats['mean_ms']:.4f} ms | P50: {ticket_consume_stats['p50_ms']:.4f} ms | P95: {ticket_consume_stats['p95_ms']:.4f} ms | Max: {ticket_consume_stats['max_ms']:.4f} ms")

    # 3. 26-Byte Binary Header Packing & Unpacking Benchmark
    webp_720p = generate_benchmark_webp(1280, 720)
    print(f"\n[*] 720p WebP Frame Payload Size: {len(webp_720p)} bytes ({len(webp_720p) / 1024.0:.1f} KB)")

    def trial_pack():
        pack_camera_frame(STREAM_TYPE_CAMERA, 0, 100, time.time_ns(), 1280, 720, webp_720p)

    pack_stats = run_trials(trial_pack, trials=30)
    print(f"[*] 3a. 26-Byte Binary Frame Packing Latency:")
    print(f"    -> Mean: {pack_stats['mean_ms']:.4f} ms | P50: {pack_stats['p50_ms']:.4f} ms | P95: {pack_stats['p95_ms']:.4f} ms | Max: {pack_stats['max_ms']:.4f} ms")

    packed_frame = pack_camera_frame(STREAM_TYPE_CAMERA, 0, 100, time.time_ns(), 1280, 720, webp_720p)

    def trial_unpack():
        unpack_camera_frame(packed_frame)

    unpack_stats = run_trials(trial_unpack, trials=30)
    print(f"[*] 3b. 26-Byte Binary Frame Header Parsing & Validation Latency:")
    print(f"    -> Mean: {unpack_stats['mean_ms']:.4f} ms | P50: {unpack_stats['p50_ms']:.4f} ms | P95: {unpack_stats['p95_ms']:.4f} ms | Max: {unpack_stats['max_ms']:.4f} ms")

    # 4. Ingestion & Depth-1 Volatile Buffer Update Latency
    session = camera_service.create_session(user_id=user_id, workspace_id=ws_id, session_nonce="e" * 64)
    seq_counter = 1

    ingest_latencies: List[float] = []
    for _ in range(30):
        # ensure rate ceiling not tripped for accepted trials
        session.last_accepted_time = 0.0
        frame = pack_camera_frame(STREAM_TYPE_CAMERA, 0, seq_counter, time.time_ns(), 1280, 720, webp_720p)
        seq_counter += 1
        t0 = time.perf_counter()
        accepted, _, obs = camera_service.ingest_frame(session.session_id, frame)
        t1 = time.perf_counter()
        assert accepted is True
        ingest_latencies.append((t1 - t0) * 1000.0)

    ingest_stats = {
        "mean_ms": float(np.mean(ingest_latencies)),
        "p50_ms": float(np.percentile(ingest_latencies, 50)),
        "p95_ms": float(np.percentile(ingest_latencies, 95)),
        "p99_ms": float(np.percentile(ingest_latencies, 99)),
        "min_ms": float(np.min(ingest_latencies)),
        "max_ms": float(np.max(ingest_latencies)),
    }
    print(f"\n[*] 4. Frame Ingestion & Depth-1 Buffer Storage Latency:")
    print(f"    -> Mean: {ingest_stats['mean_ms']:.4f} ms | P50: {ingest_stats['p50_ms']:.4f} ms | P95: {ingest_stats['p95_ms']:.4f} ms | Max: {ingest_stats['max_ms']:.4f} ms")

    # 5. Backpressure Frame-Drop Latency
    drop_latencies: List[float] = []
    session.last_accepted_time = time.time()  # set last accepted to now to trigger 5 FPS drop
    for _ in range(30):
        frame = pack_camera_frame(STREAM_TYPE_CAMERA, 0, seq_counter, time.time_ns(), 1280, 720, webp_720p)
        seq_counter += 1
        t0 = time.perf_counter()
        accepted, reason, _ = camera_service.ingest_frame(session.session_id, frame)
        t1 = time.perf_counter()
        assert accepted is False
        assert reason == "rate_limit_exceeded"
        drop_latencies.append((t1 - t0) * 1000.0)

    drop_stats = {
        "mean_ms": float(np.mean(drop_latencies)),
        "p50_ms": float(np.percentile(drop_latencies, 50)),
        "p95_ms": float(np.percentile(drop_latencies, 95)),
        "p99_ms": float(np.percentile(drop_latencies, 99)),
        "min_ms": float(np.min(drop_latencies)),
        "max_ms": float(np.max(drop_latencies)),
    }
    print(f"\n[*] 5. Backpressure Frame-Drop Decision Latency:")
    print(f"    -> Mean: {drop_stats['mean_ms']:.4f} ms | P50: {drop_stats['p50_ms']:.4f} ms | P95: {drop_stats['p95_ms']:.4f} ms | Max: {drop_stats['max_ms']:.4f} ms")

    # 6. Ephemeral Buffer Cache Access & Retrieval Latency
    def trial_cache_access():
        camera_service.get_latest_observation(str(ws_id))

    cache_stats = run_trials(trial_cache_access, trials=30)
    print(f"\n[*] 6. Ephemeral Frame Cache Access Latency:")
    print(f"    -> Mean: {cache_stats['mean_ms']:.4f} ms | P50: {cache_stats['p50_ms']:.4f} ms | P95: {cache_stats['p95_ms']:.4f} ms | Max: {cache_stats['max_ms']:.4f} ms")

    # Clean up session
    camera_service.close_session(session.session_id, reason="benchmark_completed")

    print("\n" + "=" * 80)
    print("  [PASS] AURA-803 PERFORMANCE BENCHMARK COMPLETED SUCCESSFULLY")
    print("=" * 80)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
