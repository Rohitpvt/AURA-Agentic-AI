"""AURA-704 Authenticated WebSocket Gateway Performance Benchmark.

Measures:
1. Ticket Issuance Latency (POST /ticket / service issuance)
2. WebSocket Handshake & Session Initialization Latency
3. Binary Transport Framing Parsing & Ingestion Overhead
4. Disconnect Cleanup & Ephemeral Memory Purge Latency

Protocol:
- N = 50 reproducible trials per metric
- Reports min, mean, p50, p95, p99, max, hardware condition
"""

import asyncio
import gc
import os
import platform
import statistics
import sys
import time
import uuid
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient

from app.api.v1.endpoints.voice import pack_audio_frame, unpack_audio_frame
from app.main import app
from app.services.voice.session_manager import voice_session_manager
from app.services.voice.ticket_service import VoiceTicketService, voice_ticket_service


def generate_pcm_sine(duration_sec: float = 0.030, sample_rate: int = 16000) -> bytes:
    num_samples = int(duration_sec * sample_rate)
    t = np.linspace(0, duration_sec, num_samples, endpoint=False)
    samples = 0.5 * np.sin(2 * np.pi * 440.0 * t)
    int16_samples = (samples * 32767).astype(np.int16)
    return int16_samples.tobytes()


async def run_aura704_gateway_benchmark_async(num_trials: int = 50):
    print(f"=== AURA-704 WEBSOCKET GATEWAY & TICKET BENCHMARK (N={num_trials}) ===")
    test_client = TestClient(app)

    ticket_latencies_ms = []
    handshake_latencies_ms = []
    frame_latencies_ms = []
    cleanup_latencies_ms = []

    pcm_30ms = generate_pcm_sine(0.030)

    for trial in range(1, num_trials + 1):
        user_id = uuid.uuid4()
        ws_id = uuid.uuid4()

        # 1. Ticket Issuance Latency
        t0 = time.perf_counter()
        ticket = await voice_ticket_service.issue_ticket(user_id=user_id, workspace_id=ws_id, ttl_seconds=60)
        t1 = time.perf_counter()
        ticket_latencies_ms.append((t1 - t0) * 1000.0)

        # 2. WebSocket Handshake & Session Init Latency
        t2 = time.perf_counter()
        with test_client.websocket_connect(f"/api/v1/voice/stream?ticket={ticket.ticket_token}") as ws:
            init_frame = ws.receive_json()
            t3 = time.perf_counter()
            handshake_latencies_ms.append((t3 - t2) * 1000.0)

            assert init_frame["type"] == "session_init"
            assert len(init_frame["session_nonce"]) == 64

            # 3. Binary Frame Processing & Parsing Overhead
            frame = pack_audio_frame(seq_num=trial, timestamp_ms=int(time.time() * 1000), pcm_bytes=pcm_30ms)
            t4 = time.perf_counter()
            ws.send_bytes(frame)
            ws.send_json({"type": "status"})
            status_resp = ws.receive_json()
            t5 = time.perf_counter()
            frame_latencies_ms.append((t5 - t4) * 1000.0)
            assert status_resp["type"] == "status"

            # 4. Disconnect & Cleanup Latency (Direct Session Cleanup Boundary)
            t6 = time.perf_counter()
            await voice_session_manager.close_session(session_id=init_frame["session_id"], workspace_id=ws_id)
            t7 = time.perf_counter()
            cleanup_latencies_ms.append((t7 - t6) * 1000.0)

        del ticket
        gc.collect()

    def print_stat_block(name: str, data: list, target_ms: float, boundary: str):
        min_v = min(data)
        mean_v = statistics.mean(data)
        p50_v = statistics.median(data)
        p95_v = float(np.percentile(data, 95))
        p99_v = float(np.percentile(data, 99))
        max_v = max(data)
        status_v = "PASS" if p99_v <= target_ms else "FAIL"

        print(f"\n--- {name.upper()} ---")
        print(f"Trial count:             {len(data)}")
        print(f"Min:                     {min_v:.4f} ms")
        print(f"Mean:                    {mean_v:.4f} ms")
        print(f"p50:                     {p50_v:.4f} ms")
        print(f"p95:                     {p95_v:.4f} ms")
        print(f"p99:                     {p99_v:.4f} ms")
        print(f"Max:                     {max_v:.4f} ms")
        print(f"Hardware condition:      CPU ({platform.processor() or 'x86_64'}), OS: {platform.system()} {platform.release()}")
        print(f"Measurement boundary:    {boundary}")
        print(f"Acceptance threshold:    <= {target_ms:.1f} ms")
        print(f"Result:                  {status_v} (p99 {p99_v:.4f} ms <= {target_ms:.1f} ms)")

        return {
            "min": min_v,
            "mean": mean_v,
            "p50": p50_v,
            "p95": p95_v,
            "p99": p99_v,
            "max": max_v,
            "status": status_v,
        }

    res_ticket = print_stat_block(
        "Ticket Issuance Latency",
        ticket_latencies_ms,
        target_ms=5.0,
        boundary="issue_ticket invocation -> 256-bit secure token generation -> registry insertion",
    )

    res_handshake = print_stat_block(
        "WebSocket Handshake & Init Latency",
        handshake_latencies_ms,
        target_ms=25.0,
        boundary="WebSocket connect -> single-use ticket consume -> 256-bit nonce gen -> session_init frame",
    )

    res_frame = print_stat_block(
        "Binary Frame Ingestion Overhead",
        frame_latencies_ms,
        target_ms=10.0,
        boundary="Binary frame transmit -> 12-byte header unpack -> VAD frame check -> status response",
    )

    res_cleanup = print_stat_block(
        "Disconnect Cleanup Latency",
        cleanup_latencies_ms,
        target_ms=10.0,
        boundary="WebSocket close -> session unregister -> ephemeral buffer zeroization",
    )

    return {
        "ticket": res_ticket,
        "handshake": res_handshake,
        "frame": res_frame,
        "cleanup": res_cleanup,
    }


if __name__ == "__main__":
    asyncio.run(run_aura704_gateway_benchmark_async(50))
