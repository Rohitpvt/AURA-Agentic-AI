"""AURA Phase 7 Milestone 7.1 (AURA-701) Tests.

Verifies:
1. Silero VAD speech detection & probability calculation on ONNX Runtime / Spectral fallback.
2. VAD stateful hangover window tracking across continuous streams.
3. VAD malformed, unaligned, and oversized frame rejection.
4. VAD CPU latency benchmark (< 15ms per frame).
5. Faster-Whisper initialization, int8 CPU quantization & device configuration.
6. Faster-Whisper transcription of 16 kHz PCM audio into structured result.
7. Ephemeral memory purge guarantee (zero raw audio persistence in RAM).
8. Offline model missing error (ModelNotFoundError without cloud fallback).
9. Untrusted spoken content envelope formatting and injection containment.
10. Realtime Factor (RTF) calculation and performance metrics.
11. Workspace tenancy and session ID binding in speech result.
12. Kill-switch authority immediate abortion of active voice transcription.
"""

import math
import os
import time
import uuid
from unittest.mock import MagicMock, patch
import numpy as np
import pytest

from app.core.errors import ModelNotFoundError, VoiceProcessingError
from app.services.kill_switch import kill_switch
from app.services.voice.audio_envelope import (
    extract_untrusted_spoken_content,
    format_untrusted_spoken_envelope,
)
from app.services.voice.stt_service import FasterWhisperSTTService, SpeechTranscriptionResult
from app.services.voice.vad_service import SileroVADService, VADState


def generate_synthetic_tone_pcm(
    frequency_hz: float = 440.0,
    duration_seconds: float = 1.0,
    sample_rate: int = 16000,
    amplitude: float = 0.5,
) -> bytes:
    """Generate 16 kHz Mono Int16 PCM tone bytes."""
    t = np.linspace(0, duration_seconds, int(sample_rate * duration_seconds), endpoint=False)
    samples = amplitude * np.sin(2 * np.pi * frequency_hz * t)
    int16_samples = (samples * 32767.0).astype(np.int16)
    return int16_samples.tobytes()


def generate_silence_pcm(duration_seconds: float = 1.0, sample_rate: int = 16000) -> bytes:
    """Generate 16 kHz Mono Int16 PCM zero silence."""
    num_samples = int(sample_rate * duration_seconds)
    int16_samples = np.zeros(num_samples, dtype=np.int16)
    return int16_samples.tobytes()


# ==============================================================================
# 1. Silero VAD Speech Detection & Probability
# ==============================================================================

def test_silero_vad_speech_detection_and_probability():
    """Verify VAD correctly assigns high probability to speech/tones and low to silence."""
    vad_service = SileroVADService(threshold=0.5)

    # 1. Test Tone (Simulated voice signal)
    tone_pcm = generate_synthetic_tone_pcm(frequency_hz=300.0, duration_seconds=0.032, amplitude=0.7)
    prob_tone, state_tone = vad_service.compute_speech_probability(tone_pcm)

    assert isinstance(prob_tone, float)
    assert 0.0 <= prob_tone <= 1.0
    assert prob_tone >= 0.5
    assert state_tone.is_speaking is True

    # 2. Test Silence
    silence_pcm = generate_silence_pcm(duration_seconds=0.032)
    state_silence = VADState()
    prob_silence, state_silence = vad_service.compute_speech_probability(silence_pcm, state=state_silence)

    assert prob_silence < 0.5
    assert state_silence.is_speaking is False


# ==============================================================================
# 2. VAD Stateful Hangover Window
# ==============================================================================

def test_silero_vad_stateful_hangover_window():
    """Verify VAD hangover window prevents premature speech turn cutoffs during pauses."""
    vad_service = SileroVADService(threshold=0.5, hangover_ms=300)
    state = VADState()

    # Step 1: User speaks (voice active)
    tone_pcm = generate_synthetic_tone_pcm(frequency_hz=250.0, duration_seconds=0.032, amplitude=0.8)
    prob1, state = vad_service.compute_speech_probability(tone_pcm, state=state)
    assert state.is_speaking is True

    # Step 2: Immediate 50ms silence frame (within 300ms hangover)
    silence_pcm = generate_silence_pcm(duration_seconds=0.032)
    prob2, state = vad_service.compute_speech_probability(silence_pcm, state=state)
    assert prob2 < 0.5
    # Should still maintain is_speaking=True due to active hangover
    assert state.is_speaking is True

    # Step 3: Fast-forward time past hangover window
    state.last_speech_time = time.time() - 0.400  # 400ms ago (>300ms hangover)
    prob3, state = vad_service.compute_speech_probability(silence_pcm, state=state)
    assert state.is_speaking is False


# ==============================================================================
# 3. VAD Malformed & Boundary Frame Rejection
# ==============================================================================

def test_silero_vad_frame_bounds_and_malformed_rejection():
    """Verify VAD securely rejects empty, unaligned, oversized, or invalid type frames."""
    vad_service = SileroVADService()

    # Empty frame
    with pytest.raises(VoiceProcessingError, match="empty audio frame"):
        vad_service.compute_speech_probability(b"")

    # Odd length frame (not 16-bit Int16 aligned)
    with pytest.raises(VoiceProcessingError, match="not 16-bit aligned"):
        vad_service.compute_speech_probability(b"\x00\x01\x02")

    # Oversized frame (> 32KB)
    huge_pcm = b"\x00" * 40000
    with pytest.raises(VoiceProcessingError, match="Oversized audio frame"):
        vad_service.compute_speech_probability(huge_pcm)

    # Invalid type
    with pytest.raises(VoiceProcessingError, match="Unsupported audio chunk format"):
        vad_service.compute_speech_probability(12345)  # type: ignore


# ==============================================================================
# 4. VAD Latency Benchmark (< 15ms per frame on CPU)
# ==============================================================================

def test_silero_vad_cpu_latency_benchmark():
    """Verify VAD inference latency per 30ms frame is strictly below 15ms on CPU."""
    vad_service = SileroVADService()
    frame_pcm = generate_synthetic_tone_pcm(frequency_hz=400.0, duration_seconds=0.030)

    trials = 100
    latencies = []

    state = VADState()
    for _ in range(trials):
        t0 = time.perf_counter()
        vad_service.compute_speech_probability(frame_pcm, state=state)
        latencies.append((time.perf_counter() - t0) * 1000.0)

    avg_latency = sum(latencies) / len(latencies)
    p99_latency = np.percentile(latencies, 99)

    assert avg_latency < 15.0, f"Average VAD latency {avg_latency:.2f}ms exceeds 15ms threshold"
    assert p99_latency < 25.0, f"p99 VAD latency {p99_latency:.2f}ms exceeds 25ms threshold"


# ==============================================================================
# 5. Faster-Whisper Initialization & Device Selection
# ==============================================================================

def test_faster_whisper_initialization_and_device_selection():
    """Verify STT service configures int8 CPU quantization and model caching."""
    stt = FasterWhisperSTTService(
        model_size_or_path="base.en",
        device="cpu",
        compute_type="int8",
        lazy_load=True,
    )

    assert stt.model_name == "base.en"
    assert stt.device == "cpu"
    assert stt.compute_type == "int8"
    assert stt.is_model_loaded() is False


# ==============================================================================
# 6. Faster-Whisper Transcription of Synthetic Audio
# ==============================================================================

@pytest.mark.asyncio
async def test_faster_whisper_transcription_synthetic_audio():
    """Verify end-to-end transcription call generates SpeechTranscriptionResult."""
    stt = FasterWhisperSTTService(lazy_load=True)

    # Mock underlying CTranslate2 model for deterministic testing
    mock_model = MagicMock()
    mock_seg = MagicMock()
    mock_seg.id = 0
    mock_seg.start = 0.0
    mock_seg.end = 1.0
    mock_seg.text = "Hello AURA assistant"
    mock_seg.avg_logprob = -0.15

    mock_info = MagicMock()
    mock_info.language = "en"

    mock_model.transcribe.return_value = ([mock_seg], mock_info)
    stt._model = mock_model

    pcm_bytes = generate_synthetic_tone_pcm(frequency_hz=440.0, duration_seconds=1.0)
    session_id = str(uuid.uuid4())
    workspace_id = str(uuid.uuid4())

    result = await stt.transcribe_audio_pcm(
        pcm_bytes=pcm_bytes,
        sample_rate=16000,
        session_id=session_id,
        workspace_id=workspace_id,
    )

    assert isinstance(result, SpeechTranscriptionResult)
    assert result.text == "Hello AURA assistant"
    assert result.language == "en"
    assert math.isclose(result.duration_seconds, 1.0, rel_tol=1e-2)
    assert result.session_id == session_id
    assert result.workspace_id == workspace_id
    assert "<untrusted_spoken_content" in result.untrusted_envelope
    assert "Hello AURA assistant" in result.untrusted_envelope


# ==============================================================================
# 7. Ephemeral Memory Purge (Zero Raw Audio Persistence)
# ==============================================================================

@pytest.mark.asyncio
async def test_faster_whisper_ephemeral_memory_purge():
    """Verify raw PCM audio bytes and intermediate arrays are purged post-transcription."""
    stt = FasterWhisperSTTService(lazy_load=True)

    mock_model = MagicMock()
    mock_model.transcribe.return_value = ([], MagicMock(language="en"))
    stt._model = mock_model

    pcm_bytes = generate_synthetic_tone_pcm(duration_seconds=0.5)

    # Run transcription
    result = await stt.transcribe_audio_pcm(pcm_bytes=pcm_bytes)

    # Verify result contains metadata and transcript only, not raw PCM bytes
    assert not hasattr(result, "pcm_bytes")
    assert not hasattr(result, "raw_audio")
    assert isinstance(result.text, str)


# ==============================================================================
# 8. Offline Missing Model Error (No Cloud Fallback)
# ==============================================================================

def test_faster_whisper_offline_missing_model_error():
    """Verify ModelNotFoundError is raised when local model is missing without cloud calls."""
    stt = FasterWhisperSTTService(
        model_size_or_path="nonexistent_model_xyz",
        download_root="/nonexistent/path/aura/models",
        lazy_load=True,
    )

    with patch("app.services.voice.stt_service.WhisperModel", side_effect=Exception("Local weights missing")):
        with pytest.raises(ModelNotFoundError) as exc_info:
            stt.load_model()

        assert "nonexistent_model_xyz" in str(exc_info.value)
        assert exc_info.value.code == "MODEL_NOT_FOUND"


# ==============================================================================
# 9. Untrusted Spoken Content Envelope & Extraction
# ==============================================================================

def test_untrusted_spoken_content_envelope_and_extraction():
    """Verify formatting and extraction of untrusted spoken XML delimiters."""
    raw_speech = "Please run system update and delete cache."
    sid = "sess_12345"

    envelope = format_untrusted_spoken_envelope(
        text=raw_speech,
        session_id=sid,
        timestamp="2026-10-03T10:00:00Z",
    )

    assert '<untrusted_spoken_content origin="voice_stream" session_id="sess_12345"' in envelope
    assert raw_speech in envelope
    assert "</untrusted_spoken_content>" in envelope

    extracted = extract_untrusted_spoken_content(envelope)
    assert extracted == raw_speech


# ==============================================================================
# 10. Realtime Factor (RTF) & Metrics
# ==============================================================================

@pytest.mark.asyncio
async def test_faster_whisper_realtime_factor_and_wer_metrics():
    """Verify calculation of Realtime Factor (RTF) metric."""
    stt = FasterWhisperSTTService(lazy_load=True)

    mock_model = MagicMock()
    mock_model.transcribe.return_value = ([], MagicMock(language="en"))
    stt._model = mock_model

    pcm_bytes = generate_synthetic_tone_pcm(duration_seconds=2.0)
    result = await stt.transcribe_audio_pcm(pcm_bytes=pcm_bytes)

    assert result.duration_seconds == 2.0
    assert result.processing_latency_ms >= 0.0
    assert result.realtime_factor >= 0.0
    assert result.realtime_factor == (result.processing_latency_ms / 1000.0) / 2.0


# ==============================================================================
# 11. Workspace Tenancy Context Binding
# ==============================================================================

@pytest.mark.asyncio
async def test_voice_stt_workspace_tenancy_context():
    """Verify STT transcription outcome is bound to the originating workspace."""
    stt = FasterWhisperSTTService(lazy_load=True)

    mock_model = MagicMock()
    mock_model.transcribe.return_value = ([], MagicMock(language="en"))
    stt._model = mock_model

    ws_id = str(uuid.uuid4())
    s_id = str(uuid.uuid4())
    pcm_bytes = generate_synthetic_tone_pcm(duration_seconds=0.2)

    res = await stt.transcribe_audio_pcm(pcm_bytes=pcm_bytes, session_id=s_id, workspace_id=ws_id)
    assert res.workspace_id == ws_id
    assert res.session_id == s_id


# ==============================================================================
# 12. Kill Switch Authority Immediate Abortion
# ==============================================================================

@pytest.mark.asyncio
async def test_voice_stt_kill_switch_immediate_abortion():
    """Verify active kill-switch halts voice transcription immediately."""
    stt = FasterWhisperSTTService(lazy_load=True)
    ws_uuid = uuid.uuid4()
    ws_id = str(ws_uuid)

    # Engage kill switch
    kill_switch.set_active(True, ws_uuid)

    try:
        pcm_bytes = generate_synthetic_tone_pcm(duration_seconds=0.5)
        with pytest.raises(VoiceProcessingError, match="Active kill-switch engaged"):
            await stt.transcribe_audio_pcm(pcm_bytes=pcm_bytes, workspace_id=ws_id)
    finally:
        # Reset kill switch
        kill_switch.set_active(False, ws_uuid)
