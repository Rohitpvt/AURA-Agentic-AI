"""AURA-702 Acceptance Benchmark Script.

Measures:
1. Piper-TTS Time-To-First-Audio (TTFA) on en_US-lessac-medium (ONNX CPU).
2. Piper-TTS Realtime Factor (RTF) across standardized multi-sentence synthesis inputs.
"""

import asyncio
import os
import sys
import time
from pathlib import Path
from typing import List, Tuple
import numpy as np

# Ensure apps/api root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings
from app.services.voice.tts_service import PiperTTSService, SpeechSynthesisResult, TTSAudioChunk


async def run_ttfa_benchmark(tts: PiperTTSService, trials: int = 50) -> dict:
    """Measure Time-To-First-Audio (TTFA) across 50 trials using standard 15-word response."""
    test_sentence = "Hello! All system diagnostics confirm internal services are operational and ready for your command."

    print("\n=======================================================")
    print(f" 1. PIPER-TTS TTFA BENCHMARK ({trials} Trials)")
    print("    Model: en_US-lessac-medium | Runtime: ONNX Runtime | Device: CPU")
    print(f"    Fixture: '{test_sentence}' (15 words)")
    print("=======================================================")

    ttfa_list = []
    durations = []

    for trial in range(1, trials + 1):
        t0 = time.perf_counter()
        first_chunk_latency = None
        total_dur = 0.0

        async for chunk in tts.synthesize_stream(text=test_sentence):
            if first_chunk_latency is None:
                first_chunk_latency = (time.perf_counter() - t0) * 1000.0
            total_dur += chunk.duration_seconds

        ttfa_list.append(first_chunk_latency)
        durations.append(total_dur)

    min_ttfa = min(ttfa_list)
    mean_ttfa = sum(ttfa_list) / len(ttfa_list)
    p50_ttfa = np.percentile(ttfa_list, 50)
    p95_ttfa = np.percentile(ttfa_list, 95)
    p99_ttfa = np.percentile(ttfa_list, 99)
    max_ttfa = max(ttfa_list)
    mean_dur = sum(durations) / len(durations)

    print(f"Trials               : {trials}")
    print(f"Mean Audio Duration  : {mean_dur:.2f} s")
    print(f"Min TTFA             : {min_ttfa:.2f} ms")
    print(f"Mean TTFA            : {mean_ttfa:.2f} ms")
    print(f"p50 TTFA             : {p50_ttfa:.2f} ms")
    print(f"p95 TTFA             : {p95_ttfa:.2f} ms")
    print(f"p99 TTFA             : {p99_ttfa:.2f} ms")
    print(f"Max TTFA             : {max_ttfa:.2f} ms")
    print(f"Acceptance Threshold : TTFA <= 250.0 ms")
    print(f"Result               : {'PASS' if p95_ttfa <= 250.0 else 'FAIL'}")

    return {
        "trials": trials,
        "min": min_ttfa,
        "mean": mean_ttfa,
        "p50": p50_ttfa,
        "p95": p95_ttfa,
        "p99": p99_ttfa,
        "max": max_ttfa,
        "pass": p95_ttfa <= 250.0,
    }


async def run_rtf_benchmark(tts: PiperTTSService, trials: int = 30) -> dict:
    """Measure Realtime Factor (RTF) across 30 trials using a 50-word multi-sentence paragraph."""
    test_paragraph = (
        "Artificial intelligence operating systems require deterministic security and privacy. "
        "Voice activity detection prevents unnecessary compute during silent intervals. "
        "The encrypted database transaction completed successfully without errors. "
        "Emergency kill switches guarantee sub fifteen millisecond execution abortion across all active processes."
    )

    print("\n=======================================================")
    print(f" 2. PIPER-TTS REALTIME FACTOR (RTF) BENCHMARK ({trials} Trials)")
    print("    Model: en_US-lessac-medium | Runtime: ONNX Runtime | Device: CPU")
    print("=======================================================")

    rtf_list = []
    latencies = []
    durations = []

    for trial in range(1, trials + 1):
        res: SpeechSynthesisResult = await tts.synthesize_full(text=test_paragraph)
        rtf_list.append(res.realtime_factor)
        latencies.append(res.total_latency_ms)
        durations.append(res.duration_seconds)

    min_rtf = min(rtf_list)
    mean_rtf = sum(rtf_list) / len(rtf_list)
    p50_rtf = np.percentile(rtf_list, 50)
    p95_rtf = np.percentile(rtf_list, 95)
    p99_rtf = np.percentile(rtf_list, 99)
    max_rtf = max(rtf_list)
    mean_dur = sum(durations) / len(durations)
    mean_lat = sum(latencies) / len(latencies)

    print(f"Trials               : {trials}")
    print(f"Paragraph Sentences  : {res.chunk_count}")
    print(f"Mean Audio Duration  : {mean_dur:.2f} s")
    print(f"Mean Total Latency   : {mean_lat:.2f} ms")
    print(f"Min RTF              : {min_rtf:.4f}")
    print(f"Mean RTF             : {mean_rtf:.4f}")
    print(f"p50 RTF              : {p50_rtf:.4f}")
    print(f"p95 RTF              : {p95_rtf:.4f}")
    print(f"p99 RTF              : {p99_rtf:.4f}")
    print(f"Max RTF              : {max_rtf:.4f}")
    print(f"Acceptance Threshold : RTF <= 0.30")
    print(f"Result               : {'PASS' if mean_rtf <= 0.30 else 'FAIL'}")

    return {
        "trials": trials,
        "min": min_rtf,
        "mean": mean_rtf,
        "p50": p50_rtf,
        "p95": p95_rtf,
        "p99": p99_rtf,
        "max": max_rtf,
        "pass": mean_rtf <= 0.30,
    }


async def main():
    tts = PiperTTSService(
        model_name="en_US-lessac-medium",
        lazy_load=False,
    )
    await run_ttfa_benchmark(tts, trials=50)
    await run_rtf_benchmark(tts, trials=30)


if __name__ == "__main__":
    asyncio.run(main())
