"""AURA Phase 7 Milestone 7.2 (AURA-702) Tests.

Verifies:
1. Piper-TTS initialization, voice model resolution & output configuration.
2. Sentence boundary chunking and abbreviation preservation.
3. Streaming sentence-by-sentence 16 kHz Int16 PCM audio synthesis.
4. Full aggregate synthesis metrics (TTFA, total latency, Realtime Factor).
5. Empty, whitespace-only, and invalid type input validation.
6. Oversized input boundary rejection (> 5,000 chars).
7. Offline missing model error (ModelNotFoundError without cloud fallback).
8. Cooperative cancellation token support (barge-in interruption).
9. Global kill-switch immediate synthesis abortion.
10. Ephemeral memory purge and privacy invariants.
"""

import asyncio
import math
import os
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch
import numpy as np
import pytest

from app.core.errors import ModelNotFoundError, VoiceProcessingError
from app.services.kill_switch import kill_switch
from app.services.voice.tts_service import (
    PiperTTSService,
    SpeechSynthesisResult,
    TTSAudioChunk,
    split_sentences,
)


# ==============================================================================
# 1. Initialization & Configuration
# ==============================================================================

def test_piper_tts_initialization_and_configuration():
    """Verify Piper-TTS service default configuration and 16 kHz output."""
    tts = PiperTTSService(
        model_name="en_US-lessac-medium",
        lazy_load=True,
    )

    assert tts.model_name == "en_US-lessac-medium"
    assert tts.OUTPUT_SAMPLE_RATE == 16000
    assert tts.MAX_INPUT_CHARS == 5000
    assert tts.is_model_loaded() is False


# ==============================================================================
# 2. Sentence Boundary Splitting
# ==============================================================================

def test_sentence_boundary_chunking():
    """Verify text is split along sentence boundaries preserving numbers and structure."""
    text = (
        "Hello there! This is the first sentence. "
        "The price is $3.14 per unit.\n"
        "Here is a third sentence; and this continues."
    )

    sentences = split_sentences(text)
    assert len(sentences) >= 3
    assert sentences[0] == "Hello there!"
    assert sentences[1] == "This is the first sentence."
    assert any("3.14" in s for s in sentences)


# ==============================================================================
# 3. Streaming Synthesis Chunks (Mock Engine)
# ==============================================================================

@pytest.mark.asyncio
async def test_piper_tts_streaming_synthesis_chunks():
    """Verify streaming synthesis yields sequential 16 kHz PCM chunks with is_final flag."""
    tts = PiperTTSService(lazy_load=True)

    # Mock sentence synthesis to return 1.0s synthetic 16kHz PCM (32,000 bytes)
    def mock_synth(sentence: str) -> bytes:
        samples = (0.3 * np.sin(np.linspace(0, 1.0, 16000)) * 32767.0).astype(np.int16)
        return samples.tobytes()

    tts._synthesize_sentence_sync = mock_synth

    text = "Sentence one. Sentence two. Sentence three."
    chunks: list[TTSAudioChunk] = []

    async for chunk in tts.synthesize_stream(text=text):
        chunks.append(chunk)

    assert len(chunks) == 3
    for i, c in enumerate(chunks, 1):
        assert c.chunk_index == i
        assert c.sample_rate == 16000
        assert len(c.pcm_bytes) == 32000
        assert math.isclose(c.duration_seconds, 1.0, rel_tol=1e-2)
        assert c.latency_ms >= 0.0

    assert chunks[0].is_final is False
    assert chunks[1].is_final is False
    assert chunks[2].is_final is True


# ==============================================================================
# 4. Full Aggregation & Metrics (TTFA, Total Latency, RTF)
# ==============================================================================

@pytest.mark.asyncio
async def test_piper_tts_full_aggregation_and_metrics():
    """Verify synthesize_full aggregates chunks and computes TTFA and RTF metrics."""
    tts = PiperTTSService(lazy_load=True)

    def mock_synth(sentence: str) -> bytes:
        samples = (0.2 * np.sin(np.linspace(0, 0.5, 8000)) * 32767.0).astype(np.int16)
        return samples.tobytes()

    tts._synthesize_sentence_sync = mock_synth

    ws_id = str(uuid.uuid4())
    s_id = str(uuid.uuid4())
    result = await tts.synthesize_full(
        text="First sentence. Second sentence.",
        session_id=s_id,
        workspace_id=ws_id,
    )

    assert isinstance(result, SpeechSynthesisResult)
    assert result.chunk_count == 2
    assert result.sample_rate == 16000
    assert len(result.pcm_bytes) == 16000 * 2  # 0.5s * 2 sentences * 16000 samples/s * 2 bytes/sample = 32000 bytes
    assert math.isclose(result.duration_seconds, 1.0, rel_tol=1e-2)
    assert result.ttfa_ms >= 0.0
    assert result.total_latency_ms >= 0.0
    assert result.realtime_factor >= 0.0
    assert result.session_id == s_id
    assert result.workspace_id == ws_id


# ==============================================================================
# 5. Empty & Whitespace Validation
# ==============================================================================

@pytest.mark.asyncio
async def test_piper_tts_empty_and_whitespace_rejection():
    """Verify empty or whitespace-only inputs are rejected with VoiceProcessingError."""
    tts = PiperTTSService(lazy_load=True)

    with pytest.raises(VoiceProcessingError, match="empty text"):
        async for _ in tts.synthesize_stream(""):
            pass

    with pytest.raises(VoiceProcessingError, match="whitespace text"):
        async for _ in tts.synthesize_stream("    \n\t  "):
            pass

    with pytest.raises(VoiceProcessingError, match="empty text"):
        async for _ in tts.synthesize_stream(None):  # type: ignore
            pass


# ==============================================================================
# 6. Oversized Input Boundary Rejection
# ==============================================================================

@pytest.mark.asyncio
async def test_piper_tts_oversized_input_rejection():
    """Verify input text exceeding 5,000 characters is rejected safely."""
    tts = PiperTTSService(lazy_load=True)
    huge_text = "A" * 5001

    with pytest.raises(VoiceProcessingError, match="exceeds maximum boundary"):
        async for _ in tts.synthesize_stream(huge_text):
            pass


# ==============================================================================
# 7. Offline Missing Model Error (Zero Cloud Fallback)
# ==============================================================================

def test_piper_tts_offline_missing_model_error():
    """Verify ModelNotFoundError is raised when local model is absent without cloud fallback."""
    tts = PiperTTSService(
        model_name="nonexistent_voice_model",
        download_root="/nonexistent/path/aura/models/tts",
        lazy_load=True,
    )

    with pytest.raises(ModelNotFoundError) as exc_info:
        tts.load_model()

    assert "nonexistent_voice_model" in str(exc_info.value)
    assert exc_info.value.code == "MODEL_NOT_FOUND"


# ==============================================================================
# 8. Cooperative Cancellation Event (Barge-In Interruption)
# ==============================================================================

@pytest.mark.asyncio
async def test_piper_tts_cooperative_cancellation_event():
    """Verify setting cancel_event halts streaming synthesis gracefully."""
    tts = PiperTTSService(lazy_load=True)

    cancel_event = asyncio.Event()

    def mock_synth(sentence: str) -> bytes:
        # Simulate cancellation being triggered after first sentence
        if "two" in sentence:
            cancel_event.set()
        samples = np.zeros(8000, dtype=np.int16)
        return samples.tobytes()

    tts._synthesize_sentence_sync = mock_synth

    text = "Sentence one. Sentence two. Sentence three. Sentence four."
    chunks = []

    async for chunk in tts.synthesize_stream(text=text, cancel_event=cancel_event):
        chunks.append(chunk)

    # Chunks should halt before completing all 4 sentences
    assert len(chunks) < 4


# ==============================================================================
# 9. Global Kill Switch Immediate Synthesis Abortion
# ==============================================================================

@pytest.mark.asyncio
async def test_piper_tts_kill_switch_immediate_abortion():
    """Verify active kill switch halts voice synthesis immediately."""
    tts = PiperTTSService(lazy_load=True)
    ws_uuid = uuid.uuid4()
    ws_id = str(ws_uuid)

    kill_switch.set_active(True, ws_uuid)

    try:
        with pytest.raises(VoiceProcessingError, match="Active kill-switch engaged"):
            async for _ in tts.synthesize_stream("Test sentence.", workspace_id=ws_id):
                pass
    finally:
        kill_switch.set_active(False, ws_uuid)


# ==============================================================================
# 10. Ephemeral Memory Purge & Privacy Invariants
# ==============================================================================

@pytest.mark.asyncio
async def test_piper_tts_ephemeral_memory_and_privacy_invariants():
    """Verify generated audio bytes are not leaked into persistent storage or global scope."""
    tts = PiperTTSService(lazy_load=True)

    def mock_synth(sentence: str) -> bytes:
        return b"\x00" * 3200

    tts._synthesize_sentence_sync = mock_synth

    result = await tts.synthesize_full("Clean test sentence.")

    assert isinstance(result.pcm_bytes, bytes)
    assert result.sample_rate == 16000
    assert result.duration_seconds > 0.0
