import asyncio
import os
import sys
import time
import statistics
import uuid

# Path setup
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

import pytest

from app.core.security import create_access_token, verify_password, get_password_hash, compute_sha256_hash, sign_approval_payload, verify_approval_signature
from app.core.redaction import SecretRedactor
from app.services.structural_chunker import structural_chunker
from app.services.kill_switch import kill_switch
import json


@pytest.mark.asyncio
async def test_benchmark_master_phase01_to_phase09():
    """
    Run 100-trial microbenchmarks across key subsystems from Phase 1 through Phase 9.
    """
    N = 100
    results = {}

    # 1. Phase 2 Auth: JWT Token Generation
    jwt_latencies = []
    for _ in range(N):
        t0 = time.perf_counter()
        token = create_access_token(data={"sub": "benchmark_user"})
        t1 = time.perf_counter()
        jwt_latencies.append((t1 - t0) * 1000.0)
    results["jwt_generation_ms"] = {
        "mean": statistics.mean(jwt_latencies),
        "p95": statistics.quantiles(jwt_latencies, n=20)[18],
    }

    # 2. Phase 5 Redaction: Sensitive Data Scrubbing
    redact_latencies = []
    sample_payload = "Here is an API key AIzaSyD9876543210FedCba9876543210 and Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.sig"
    for _ in range(N):
        t0 = time.perf_counter()
        _ = SecretRedactor.redact_text(sample_payload)
        t1 = time.perf_counter()
        redact_latencies.append((t1 - t0) * 1000.0)
    results["redaction_ms"] = {
        "mean": statistics.mean(redact_latencies),
        "p95": statistics.quantiles(redact_latencies, n=20)[18],
    }

    # 3. Phase 6 Files: Structural Chunker
    doc_sample = "Sentence in a long document for benchmarking chunking performance. " * 20
    chunk_latencies = []
    for _ in range(N):
        t0 = time.perf_counter()
        _ = structural_chunker._subdivide_oversized_text(doc_sample, max_tokens=384, overlap_tokens=48)
        t1 = time.perf_counter()
        chunk_latencies.append((t1 - t0) * 1000.0)
    results["chunking_ms"] = {
        "mean": statistics.mean(chunk_latencies),
        "p95": statistics.quantiles(chunk_latencies, n=20)[18],
    }

    # 4. Phase 9 Kill Switch: Probe Latency (< 15ms target)
    probe_latencies = []
    for _ in range(N):
        t0 = time.perf_counter()
        _ = kill_switch.is_active()
        t1 = time.perf_counter()
        probe_latencies.append((t1 - t0) * 1000.0)
    results["kill_switch_probe_ms"] = {
        "mean": statistics.mean(probe_latencies),
        "p95": statistics.quantiles(probe_latencies, n=20)[18],
    }
    assert results["kill_switch_probe_ms"]["p95"] < 15.0

    # 5. Phase 9 HITL: HMAC-SHA256 Token Verification (< 1ms target)
    hitl_latencies = []
    ws_id = str(uuid.uuid4())
    params = {"pid": 1234}
    param_hash = compute_sha256_hash(json.dumps(params, sort_keys=True, separators=(",", ":")))
    token_payload = {
        "workspace_id": ws_id,
        "action_type": "process_terminate",
        "param_hash": param_hash,
    }
    sig = sign_approval_payload(token_payload)
    for _ in range(N):
        t0 = time.perf_counter()
        _ = verify_approval_signature(token_payload, sig)
        t1 = time.perf_counter()
        hitl_latencies.append((t1 - t0) * 1000.0)
    results["hitl_verify_ms"] = {
        "mean": statistics.mean(hitl_latencies),
        "p95": statistics.quantiles(hitl_latencies, n=20)[18],
    }
    assert results["hitl_verify_ms"]["p95"] < 1.0

    print("\n--- MASTER BENCHMARK RESULTS (N=100) ---")
    for k, v in results.items():
        print(f"{k:25s}: Mean = {v['mean']:.4f} ms, P95 = {v['p95']:.4f} ms")


if __name__ == "__main__":
    asyncio.run(test_benchmark_master_phase01_to_phase09())
