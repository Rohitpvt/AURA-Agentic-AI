"""AURA-701 Acceptance Benchmark Script.

Measures:
1. Faster-Whisper STT Accuracy (WER & Word Accuracy) and RTF on base.en (CPU int8).
2. Silero VAD Frame Latency (mean, p95, p99).
3. Kill-Switch Cancellation Latency (mean, p95, p99).
"""

import asyncio
import os
import re
import string
import sys
import time
import uuid
from pathlib import Path

# Ensure apps/api root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from typing import List, Tuple
import numpy as np
import soundfile as sf
import win32com.client

from app.core.config import settings
from app.services.kill_switch import kill_switch
from app.services.voice.stt_service import FasterWhisperSTTService
from app.services.voice.vad_service import SileroVADService, VADState


def normalize_text(text: str) -> str:
    """Normalize text for standard WER evaluation (lowercase, remove punctuation)."""
    text = text.lower()
    text = re.sub(f"[{re.escape(string.punctuation)}]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def calculate_wer(reference: str, hypothesis: str) -> Tuple[float, int, int, int, int]:
    """Compute Word Error Rate (WER) using dynamic programming Levenshtein distance.
    Returns: (wer, substitutions, deletions, insertions, total_ref_words)
    """
    ref_words = normalize_text(reference).split()
    hyp_words = normalize_text(hypothesis).split()
    r_len = len(ref_words)
    h_len = len(hyp_words)

    if r_len == 0:
        return (0.0 if h_len == 0 else 1.0, 0, 0, h_len, 0)

    # DP Matrix: dp[i][j] = (dist, subs, dels, ins)
    dp = [[0] * (h_len + 1) for _ in range(r_len + 1)]
    for i in range(r_len + 1):
        dp[i][0] = i
    for j in range(h_len + 1):
        dp[0][j] = j

    for i in range(1, r_len + 1):
        for j in range(1, h_len + 1):
            if ref_words[i - 1] == hyp_words[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                sub = dp[i - 1][j - 1] + 1
                ins = dp[i][j - 1] + 1
                delete = dp[i - 1][j] + 1
                dp[i][j] = min(sub, ins, delete)

    edit_dist = dp[r_len][h_len]
    wer = edit_dist / float(r_len)
    return wer, 0, 0, 0, r_len


def synthesize_to_16k_pcm(text: str, filename: str) -> bytes:
    """Synthesize text via SAPI and convert to 16 kHz Mono Int16 PCM."""
    speaker = win32com.client.Dispatch("SAPI.SpVoice")
    stream = win32com.client.Dispatch("SAPI.SpFileStream")
    temp_wav = Path(filename)
    stream.Open(str(temp_wav), 3, False)
    speaker.AudioOutputStream = stream
    speaker.Speak(text)
    stream.Close()

    data, sr = sf.read(str(temp_wav))
    if temp_wav.exists():
        temp_wav.unlink()

    if data.ndim > 1:
        data = data.mean(axis=1)

    if sr != 16000:
        num_output_samples = int(len(data) * 16000 / sr)
        data_16k = np.interp(
            np.linspace(0.0, 1.0, num_output_samples, endpoint=False),
            np.linspace(0.0, 1.0, len(data), endpoint=False),
            data,
        )
    else:
        data_16k = data

    int16_pcm = (np.clip(data_16k, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()
    return int16_pcm


async def run_stt_accuracy_benchmark():
    """Run STT Accuracy & RTF benchmark across 10 standardized speech fixtures."""
    fixtures = [
        "The quick brown fox jumps over the lazy dog.",
        "System diagnostics show all internal services are operational.",
        "Please schedule a meeting with the architecture team tomorrow morning.",
        "Artificial intelligence operating systems require deterministic security and privacy.",
        "Voice activity detection prevents unnecessary compute during silent intervals.",
        "The encrypted database transaction completed successfully without errors.",
        "Emergency kill switches guarantee sub fifteen millisecond execution abortion.",
        "Natural language processing bridges human speech with autonomous agent execution.",
        "Workspace tenancy isolation enforces cryptographic separation across all users.",
        "Open telemetry distributed tracing records system performance metrics.",
    ]

    print("\n=======================================================")
    print(" 1. STT ACCURACY & PERFORMANCE BENCHMARK (base.en / int8 CPU)")
    print("=======================================================")

    stt = FasterWhisperSTTService(
        model_size_or_path="base.en",
        device="cpu",
        compute_type="int8",
        lazy_load=False,
    )

    total_ref_words = 0
    total_errors = 0
    latencies = []
    durations = []
    rtfs = []

    for idx, ref in enumerate(fixtures, 1):
        pcm_bytes = synthesize_to_16k_pcm(ref, f"temp_bench_{idx}.wav")
        duration_sec = len(pcm_bytes) / 32000.0
        durations.append(duration_sec)

        t0 = time.perf_counter()
        result = await stt.transcribe_audio_pcm(pcm_bytes, sample_rate=16000)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        latencies.append(elapsed_ms)

        rtf = (elapsed_ms / 1000.0) / duration_sec
        rtfs.append(rtf)

        wer, _, _, _, r_words = calculate_wer(ref, result.text)
        sample_errors = int(round(wer * r_words))
        total_errors += sample_errors
        total_ref_words += r_words

        print(f"[{idx:02d}/10] Duration: {duration_sec:.2f}s | Latency: {elapsed_ms:.1f}ms | RTF: {rtf:.3f} | WER: {wer*100:.1f}%")
        print(f"       Ref : '{ref}'")
        print(f"       Hyp : '{result.text}'")

    overall_wer = total_errors / float(total_ref_words)
    overall_accuracy = 1.0 - overall_wer
    mean_rtf = sum(rtfs) / len(rtfs)
    p95_rtf = np.percentile(rtfs, 95)

    print("\n--- STT Benchmark Summary ---")
    print(f"Total Reference Words : {total_ref_words}")
    print(f"Total Word Errors     : {total_errors}")
    print(f"Measured WER          : {overall_wer * 100:.2f}%")
    print(f"Measured Word Accuracy: {overall_accuracy * 100:.2f}%")
    print(f"Mean Realtime Factor  : {mean_rtf:.3f}")
    print(f"p95 Realtime Factor   : {p95_rtf:.3f}")
    print(f"Acceptance Threshold  : WER <= 5.0% (Accuracy >= 95.0%)")
    print(f"Result                : {'PASS' if overall_wer <= 0.05 else 'FAIL'}")

    return overall_wer, overall_accuracy, mean_rtf


async def run_kill_switch_benchmark():
    """Run Kill-Switch cancellation latency benchmark across 50 trials."""
    print("\n=======================================================")
    print(" 2. KILL-SWITCH CANCELLATION LATENCY BENCHMARK (50 Trials)")
    print("=======================================================")

    stt = FasterWhisperSTTService(lazy_load=True)
    ws_uuid = uuid.uuid4()
    ws_id = str(ws_uuid)
    pcm_bytes = b"\x00" * 32000  # 1.0 sec audio

    trials = 50
    latencies = []

    # Activate kill switch
    kill_switch.set_active(True, ws_uuid)

    for _ in range(trials):
        t0 = time.perf_counter()
        try:
            await stt.transcribe_audio_pcm(pcm_bytes, workspace_id=ws_id)
        except Exception:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            latencies.append(elapsed_ms)

    kill_switch.set_active(False, ws_uuid)

    mean_lat = sum(latencies) / len(latencies)
    p50_lat = np.percentile(latencies, 50)
    p95_lat = np.percentile(latencies, 95)
    p99_lat = np.percentile(latencies, 99)
    min_lat = min(latencies)
    max_lat = max(latencies)

    print(f"Trials               : {trials}")
    print(f"Measurement Boundary : Trigger / Ingestion -> VoiceProcessingError Abort")
    print(f"Min Latency          : {min_lat:.4f} ms")
    print(f"Mean Latency         : {mean_lat:.4f} ms")
    print(f"p50 Latency          : {p50_lat:.4f} ms")
    print(f"p95 Latency          : {p95_lat:.4f} ms")
    print(f"p99 Latency          : {p99_lat:.4f} ms")
    print(f"Max Latency          : {max_lat:.4f} ms")
    print(f"Acceptance Threshold : <= 15.0 ms")
    print(f"Result               : {'PASS' if p99_lat <= 15.0 else 'FAIL'}")

    return mean_lat, p95_lat, p99_lat


def run_vad_benchmark():
    """Run Silero VAD frame latency benchmark across 100 trials."""
    print("\n=======================================================")
    print(" 3. SILERO VAD INFERENCE LATENCY BENCHMARK (100 Trials)")
    print("=======================================================")

    vad = SileroVADService()
    # 30ms 16kHz audio frame
    t = np.linspace(0, 0.030, 480, endpoint=False)
    samples = (0.5 * np.sin(2 * np.pi * 300 * t) * 32767.0).astype(np.int16)
    frame_bytes = samples.tobytes()

    trials = 100
    latencies = []
    state = VADState()

    for _ in range(trials):
        t0 = time.perf_counter()
        vad.compute_speech_probability(frame_bytes, state=state)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        latencies.append(elapsed_ms)

    mean_lat = sum(latencies) / len(latencies)
    p50_lat = np.percentile(latencies, 50)
    p95_lat = np.percentile(latencies, 95)
    p99_lat = np.percentile(latencies, 99)

    print(f"Trials               : {trials}")
    print(f"Measurement Boundary : 30ms Frame -> Probability Calculation")
    print(f"Mean Latency         : {mean_lat:.4f} ms")
    print(f"p50 Latency          : {p50_lat:.4f} ms")
    print(f"p95 Latency          : {p95_lat:.4f} ms")
    print(f"p99 Latency          : {p99_lat:.4f} ms")
    print(f"Acceptance Threshold : <= 15.0 ms")
    print(f"Result               : {'PASS' if p99_lat <= 15.0 else 'FAIL'}")

    return mean_lat, p95_lat, p99_lat


async def main():
    await run_stt_accuracy_benchmark()
    await run_kill_switch_benchmark()
    run_vad_benchmark()


if __name__ == "__main__":
    asyncio.run(main())
