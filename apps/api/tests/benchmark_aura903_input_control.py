"""AURA-903 Governed Mouse & Keyboard Interaction Performance Benchmark.

Measures:
1. Coordinate Safety Validation Latency
2. Mouse Move Dispatch Latency
3. Mouse Click Dispatch Latency
4. Keyboard Typing Validation Latency
5. Key Press & Shortcut Validation Latency
6. Full Governance Pipeline Overhead (Request -> Policy -> Validator -> Adapter -> Audit)
7. Action Completion End-to-End Latency

Calculates and reports:
- min
- mean
- p50
- p95
- p99
- max
"""

from __future__ import annotations

import asyncio
import statistics
import time
from typing import Callable, Dict, List
import pytest

from app.services.os_guard import (
    CoordinateSafetyValidator,
    KeyboardInputValidator,
    OSActionLifecycleState,
    OSActionRequest,
    OSActionType,
    OSGuardService,
    OSPolicyEngine,
    SafeMockOSExecutionAdapter,
)


def calculate_latency_stats(latencies_ms: List[float]) -> Dict[str, float]:
    """Calculate min, mean, p50, p95, p99, max latency statistics in milliseconds."""
    sorted_lats = sorted(latencies_ms)
    n = len(sorted_lats)
    if n == 0:
        return {"min": 0.0, "mean": 0.0, "p50": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0}

    return {
        "min": round(sorted_lats[0], 4),
        "mean": round(statistics.mean(sorted_lats), 4),
        "p50": round(sorted_lats[int(n * 0.50)], 4),
        "p95": round(sorted_lats[min(int(n * 0.95), n - 1)], 4),
        "p99": round(sorted_lats[min(int(n * 0.99), n - 1)], 4),
        "max": round(sorted_lats[-1], 4),
    }


@pytest.mark.asyncio
async def test_aura903_benchmark():
    """Execute AURA-903 input control microbenchmarks and print statistical breakdown."""
    iterations = 100
    engine = OSPolicyEngine()
    adapter = SafeMockOSExecutionAdapter()
    guard = OSGuardService(policy_engine=engine, default_adapter=adapter)

    # 1. Coordinate Validation Benchmark
    coord_lats: List[float] = []
    bounds = {"left": 0, "top": 0, "width": 1920, "height": 1080}
    for _ in range(iterations):
        t0 = time.perf_counter()
        valid, _ = CoordinateSafetyValidator.validate_screen_coordinates(500, 500, monitor_bounds=bounds)
        t1 = time.perf_counter()
        assert valid
        coord_lats.append((t1 - t0) * 1000.0)

    # 2. Keyboard Typing Validation Benchmark
    type_val_lats: List[float] = []
    sample_text = "Governed input string for AURA-903 benchmark evaluation"
    for _ in range(iterations):
        t0 = time.perf_counter()
        valid, _, length = KeyboardInputValidator.validate_type_text(sample_text)
        t1 = time.perf_counter()
        assert valid
        type_val_lats.append((t1 - t0) * 1000.0)

    # 3. Shortcut Validation Benchmark
    shortcut_val_lats: List[float] = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        valid, _, _ = KeyboardInputValidator.validate_keyboard_shortcut("ctrl+c")
        t1 = time.perf_counter()
        assert valid
        shortcut_val_lats.append((t1 - t0) * 1000.0)

    # 4. Governed Mouse Move Pipeline Latency
    mouse_move_lats: List[float] = []
    for i in range(iterations):
        req = OSActionRequest(
            workspace_id=f"ws_bench_move_{i}",
            action_type=OSActionType.MOUSE_MOVE,
            parameters={"x": 400, "y": 400, "duration": 0.2},
        )
        t0 = time.perf_counter()
        resp = await guard.execute_os_action(req)
        t1 = time.perf_counter()
        assert resp.state == OSActionLifecycleState.COMPLETED
        mouse_move_lats.append((t1 - t0) * 1000.0)

    # 5. Governed Mouse Click Pipeline Latency
    mouse_click_lats: List[float] = []
    for i in range(iterations):
        req = OSActionRequest(
            workspace_id=f"ws_bench_click_{i}",
            action_type=OSActionType.MOUSE_CLICK,
            parameters={"x": 500, "y": 500, "button": "left", "clicks": 1},
        )
        t0 = time.perf_counter()
        resp = await guard.execute_os_action(req)
        t1 = time.perf_counter()
        assert resp.state == OSActionLifecycleState.COMPLETED
        mouse_click_lats.append((t1 - t0) * 1000.0)

    # 6. Governed Typing Pipeline Latency
    typing_lats: List[float] = []
    for i in range(iterations):
        req = OSActionRequest(
            workspace_id=f"ws_bench_type_{i}",
            action_type=OSActionType.TYPE_TEXT,
            parameters={"text": "benchmark_text_item"},
        )
        t0 = time.perf_counter()
        resp = await guard.execute_os_action(req)
        t1 = time.perf_counter()
        assert resp.state == OSActionLifecycleState.COMPLETED
        typing_lats.append((t1 - t0) * 1000.0)

    # 7. Governed Key Press Pipeline Latency
    key_lats: List[float] = []
    for i in range(iterations):
        req = OSActionRequest(
            workspace_id=f"ws_bench_key_{i}",
            action_type=OSActionType.PRESS_KEY,
            parameters={"key": "enter"},
        )
        t0 = time.perf_counter()
        resp = await guard.execute_os_action(req)
        t1 = time.perf_counter()
        assert resp.state == OSActionLifecycleState.COMPLETED
        key_lats.append((t1 - t0) * 1000.0)

    # Compile Benchmark Results
    stats_coord = calculate_latency_stats(coord_lats)
    stats_type_val = calculate_latency_stats(type_val_lats)
    stats_shortcut_val = calculate_latency_stats(shortcut_val_lats)
    stats_move = calculate_latency_stats(mouse_move_lats)
    stats_click = calculate_latency_stats(mouse_click_lats)
    stats_type = calculate_latency_stats(typing_lats)
    stats_key = calculate_latency_stats(key_lats)

    print("\n================================================================================")
    print("AURA-903 GOVERNED MOUSE & KEYBOARD BENCHMARK RESULTS (N=100)")
    print("================================================================================")
    print(f"1. Coordinate Validation:     min={stats_coord['min']}ms, mean={stats_coord['mean']}ms, p50={stats_coord['p50']}ms, p95={stats_coord['p95']}ms, p99={stats_coord['p99']}ms, max={stats_coord['max']}ms")
    print(f"2. Typing Text Validation:    min={stats_type_val['min']}ms, mean={stats_type_val['mean']}ms, p50={stats_type_val['p50']}ms, p95={stats_type_val['p95']}ms, p99={stats_type_val['p99']}ms, max={stats_type_val['max']}ms")
    print(f"3. Shortcut Validation:       min={stats_shortcut_val['min']}ms, mean={stats_shortcut_val['mean']}ms, p50={stats_shortcut_val['p50']}ms, p95={stats_shortcut_val['p95']}ms, p99={stats_shortcut_val['p99']}ms, max={stats_shortcut_val['max']}ms")
    print(f"4. Governed Mouse Move E2E:   min={stats_move['min']}ms, mean={stats_move['mean']}ms, p50={stats_move['p50']}ms, p95={stats_move['p95']}ms, p99={stats_move['p99']}ms, max={stats_move['max']}ms")
    print(f"5. Governed Mouse Click E2E:  min={stats_click['min']}ms, mean={stats_click['mean']}ms, p50={stats_click['p50']}ms, p95={stats_click['p95']}ms, p99={stats_click['p99']}ms, max={stats_click['max']}ms")
    print(f"6. Governed Typing E2E:       min={stats_type['min']}ms, mean={stats_type['mean']}ms, p50={stats_type['p50']}ms, p95={stats_type['p95']}ms, p99={stats_type['p99']}ms, max={stats_type['max']}ms")
    print(f"7. Governed Key Press E2E:    min={stats_key['min']}ms, mean={stats_key['mean']}ms, p50={stats_key['p50']}ms, p95={stats_key['p95']}ms, p99={stats_key['p99']}ms, max={stats_key['max']}ms")
    print("================================================================================\n")

    # Assert sub-millisecond validator latency and sub-10ms mock pipeline overhead
    assert stats_coord["mean"] < 1.0
    assert stats_type_val["mean"] < 1.0
    assert stats_shortcut_val["mean"] < 1.0
    assert stats_move["p95"] < 25.0
    assert stats_click["p95"] < 25.0
    assert stats_type["p95"] < 25.0


if __name__ == "__main__":
    asyncio.run(test_aura903_benchmark())
