"""AURA-906 Master Phase 9 Integration & Control Plane Microbenchmarks.

Measures:
1. End-to-End Pipeline Latency (AgentToolBridge -> ToolRegistry -> Policy -> OSGuard -> MockAdapter) [N=100]
2. Cryptographic HMAC-SHA256 HITL Token Signing & Verification Latency [N=100]
3. OSGuard Single-Worker Concurrency Lock Acquisition Latency [N=100]
4. Emergency Kill Switch Sub-15ms Probing & Propagation Latency [N=100]
5. Windows Named Pipe IPC Local Roundtrip Latency [N=100]
"""

from __future__ import annotations

import asyncio
import json
import statistics
import time
from typing import Any, Dict, List
import unittest.mock as mock
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import compute_sha256_hash, sign_approval_payload, verify_approval_signature
from app.db.models.workspace import Workspace
from app.runtime.tool_bridge import AgentToolBridge
from app.services.kill_switch import EmergencyKillSwitchService, kill_switch
from app.services.os_guard import (
    OSActionLifecycleState,
    OSActionRequest,
    OSActionType,
    OSGuardService,
    SafeMockOSExecutionAdapter,
)
from app.tray.ipc import AuraIpcAuthManager, AuraNamedPipeServer


TRIALS = 100


@pytest.fixture
async def benchmark_workspace(db_session: AsyncSession) -> Workspace:
    """Create a temporary test workspace for benchmarking."""
    ws = Workspace(
        id=uuid.uuid4(),
        name="AURA-906 Benchmark Workspace",
        slug=f"aura906-bench-{uuid.uuid4().hex[:8]}",
    )
    db_session.add(ws)
    await db_session.commit()
    await db_session.refresh(ws)
    return ws


@pytest.mark.asyncio
async def test_benchmark_end_to_end_pipeline_latency(
    db_session: AsyncSession, benchmark_workspace: Workspace
):
    """Benchmark full governed tool execution pipeline (N=100 trials)."""
    bridge = AgentToolBridge()
    task_id = uuid.uuid4()
    agent_run_id = uuid.uuid4()
    durations: List[float] = []

    from app.services.os_guard.policy import os_policy_engine

    for i in range(TRIALS):
        os_policy_engine.rate_limiter.clear()
        start = time.perf_counter()
        res = await bridge.execute_governed_tool(
            db=db_session,
            workspace_id=benchmark_workspace.id,
            task_id=task_id,
            step_number=i + 1,
            agent_run_id=agent_run_id,
            tool_name="inspect_processes",
            arguments={"limit": 3},
            actor_id="benchmark_agent",
        )
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        assert res.get("status") == "success"
        durations.append(elapsed_ms)

    mean_lat = statistics.mean(durations)
    p95_lat = statistics.quantiles(durations, n=20)[18] if len(durations) >= 20 else max(durations)
    p99_lat = max(durations)

    print(f"\n[BENCHMARK] E2E Pipeline (N={TRIALS}): Mean={mean_lat:.3f}ms, P95={p95_lat:.3f}ms, Max={p99_lat:.3f}ms")
    assert mean_lat < 100.0, f"Mean pipeline latency ({mean_lat:.2f}ms) exceeded 100ms ceiling"


@pytest.mark.asyncio
async def test_benchmark_hitl_cryptographic_verification_latency():
    """Benchmark HMAC-SHA256 token generation and signature verification (N=100 trials)."""
    durations: List[float] = []
    param_hash = compute_sha256_hash(json.dumps({"app": "notepad"}, sort_keys=True, separators=(",", ":")))
    
    payload = {
        "workspace_id": str(uuid.uuid4()),
        "task_id": str(uuid.uuid4()),
        "agent_run_id": str(uuid.uuid4()),
        "step_number": 1,
        "tool_name": "launch_application",
        "param_hash": param_hash,
        "expires_at": "2026-10-06T18:00:00Z",
    }

    token = sign_approval_payload(payload)

    for _ in range(TRIALS):
        start = time.perf_counter()
        valid = verify_approval_signature(payload, token)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        assert valid is True
        durations.append(elapsed_ms)

    mean_lat = statistics.mean(durations)
    p95_lat = statistics.quantiles(durations, n=20)[18] if len(durations) >= 20 else max(durations)

    print(f"\n[BENCHMARK] Cryptographic HITL Verification (N={TRIALS}): Mean={mean_lat:.4f}ms, P95={p95_lat:.4f}ms")
    assert mean_lat < 1.0, f"HMAC-SHA256 verification mean latency ({mean_lat:.3f}ms) exceeded 1.0ms ceiling"


@pytest.mark.asyncio
async def test_benchmark_os_guard_lock_acquisition_latency(
    db_session: AsyncSession, benchmark_workspace: Workspace
):
    """Benchmark OSGuard MAX_ACTIVE_ACTIONS=1 action lock acquisition latency (N=100 trials)."""
    guard = OSGuardService(kill_switch=kill_switch)
    adapter = SafeMockOSExecutionAdapter()
    durations: List[float] = []

    req = OSActionRequest(
        workspace_id=str(benchmark_workspace.id),
        action_type=OSActionType.READ_ONLY,
        parameters={"inspection_type": "process_list"},
    )

    for _ in range(TRIALS):
        guard.policy_engine.rate_limiter.clear()
        start = time.perf_counter()
        resp = await guard.execute_os_action(req, db=db_session, adapter=adapter)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        assert resp.state == OSActionLifecycleState.COMPLETED
        durations.append(elapsed_ms)

    mean_lat = statistics.mean(durations)
    p95_lat = statistics.quantiles(durations, n=20)[18] if len(durations) >= 20 else max(durations)

    print(f"\n[BENCHMARK] OSGuard Lock & Action (N={TRIALS}): Mean={mean_lat:.3f}ms, P95={p95_lat:.3f}ms")
    assert mean_lat < 15.0, f"OSGuard lock mean latency ({mean_lat:.2f}ms) exceeded 15ms ceiling"


@pytest.mark.asyncio
async def test_benchmark_kill_switch_probing_latency(benchmark_workspace: Workspace):
    """Benchmark authoritative sub-15ms Emergency Kill Switch probe latency (N=100 trials)."""
    durations: List[float] = []
    ws_id = benchmark_workspace.id

    for _ in range(TRIALS):
        start = time.perf_counter()
        is_active = kill_switch.is_active(ws_id)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        assert is_active is False
        durations.append(elapsed_ms)

    mean_lat = statistics.mean(durations)
    p95_lat = statistics.quantiles(durations, n=20)[18] if len(durations) >= 20 else max(durations)

    print(f"\n[BENCHMARK] Kill Switch Probe (N={TRIALS}): Mean={mean_lat:.4f}ms, P95={p95_lat:.4f}ms")
    # Must comfortably meet the <15ms sub-15ms requirement
    assert mean_lat < 1.0, f"Kill switch probe mean latency ({mean_lat:.3f}ms) exceeded 1.0ms target"


@pytest.mark.asyncio
async def test_benchmark_named_pipe_ipc_roundtrip_latency():
    """Benchmark Windows Named Pipe IPC request-response roundtrip latency (N=100 trials)."""
    with mock.patch("app.tray.ipc.platform.system", return_value="Windows"):
        server = AuraNamedPipeServer()
        token = AuraIpcAuthManager.get_or_create_token()
        durations: List[float] = []

        payload_str = json.dumps({
            "command": "get_status",
            "token": token,
            "session_id": 1,
            "payload": {},
        })

        for _ in range(TRIALS):
            start = time.perf_counter()
            resp = await server.process_raw_request(payload_str)
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            assert resp.get("status") == "success"
            durations.append(elapsed_ms)

        mean_lat = statistics.mean(durations)
        p95_lat = statistics.quantiles(durations, n=20)[18] if len(durations) >= 20 else max(durations)

        print(f"\n[BENCHMARK] Named Pipe IPC Roundtrip (N={TRIALS}): Mean={mean_lat:.4f}ms, P95={p95_lat:.4f}ms")
        assert mean_lat < 5.0, f"Named Pipe IPC mean roundtrip ({mean_lat:.2f}ms) exceeded 5.0ms target"
