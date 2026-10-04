"""AURA Phase 7 Milestone 7.3 (AURA-703) Tests.

Verifies:
1. VoiceSession state machine & strict transition validation.
2. VoiceSessionManager lifecycle & multi-tenant workspace isolation.
3. Audio frame ingestion, VAD buffering, and speech-turn boundary detection.
4. Full turn execution (STT -> Untrusted Envelope -> Agent Thought -> TTS Streaming).
5. Cooperative barge-in while speaking (immediate TTS abort & listen resume).
6. Cooperative barge-in while thinking (abort before speaking).
7. Repeated rapid barge-in sequence resilience.
8. Global KillSwitchManager immediate session cancellation & buffer purge.
9. Bulk workspace session cancellation isolation.
10. Malformed frames & empty utterance handling.
11. Historical conversational context preservation across interrupted turns.
12. Ephemeral memory purge guarantee.
"""

import asyncio
import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch
import numpy as np
import pytest

from app.core.errors import VoiceProcessingError
from app.services.kill_switch import kill_switch
from app.services.voice.session_manager import (
    VoiceEvent,
    VoiceSession,
    VoiceSessionManager,
    VoiceSessionState,
    VoiceTurn,
)
from app.services.voice.stt_service import SpeechTranscriptionResult
from app.services.voice.tts_service import TTSAudioChunk


def generate_tone_pcm(duration_sec: float = 0.5, freq: float = 440.0) -> bytes:
    """Generate 16 kHz Mono Int16 PCM tone."""
    t = np.linspace(0, duration_sec, int(16000 * duration_sec), endpoint=False)
    samples = (0.5 * np.sin(2 * np.pi * freq * t) * 32767.0).astype(np.int16)
    return samples.tobytes()


def generate_silence_pcm(duration_sec: float = 0.5) -> bytes:
    """Generate 16 kHz Mono Int16 PCM silence."""
    return (np.zeros(int(16000 * duration_sec), dtype=np.int16)).tobytes()


# ==============================================================================
# 1. State Machine & Transitions
# ==============================================================================

def test_voice_session_lifecycle_state_machine():
    """Verify deterministic state transitions and rejection of invalid jumps."""
    ws_id = uuid.uuid4()
    u_id = uuid.uuid4()
    session = VoiceSession(session_id="sess-01", workspace_id=ws_id, user_id=u_id)

    assert session.state == VoiceSessionState.IDLE

    # Valid progression
    session.transition_to(VoiceSessionState.LISTENING)
    assert session.state == VoiceSessionState.LISTENING

    session.transition_to(VoiceSessionState.TRANSCRIBING)
    assert session.state == VoiceSessionState.TRANSCRIBING

    session.transition_to(VoiceSessionState.THINKING)
    assert session.state == VoiceSessionState.THINKING

    session.transition_to(VoiceSessionState.SPEAKING)
    assert session.state == VoiceSessionState.SPEAKING

    session.transition_to(VoiceSessionState.COMPLETED)
    assert session.state == VoiceSessionState.COMPLETED

    # Invalid jump: COMPLETED -> SPEAKING must raise VoiceProcessingError
    with pytest.raises(VoiceProcessingError, match="Invalid voice state transition"):
        session.transition_to(VoiceSessionState.SPEAKING)


# ==============================================================================
# 2. Session Manager CRUD & Tenancy Isolation
# ==============================================================================

@pytest.mark.asyncio
async def test_voice_session_manager_crud_and_tenancy():
    """Verify session manager creates, retrieves, and enforces workspace scoping."""
    manager = VoiceSessionManager()
    ws_a = uuid.uuid4()
    ws_b = uuid.uuid4()
    user_id = uuid.uuid4()

    sess_a = await manager.create_session(workspace_id=ws_a, user_id=user_id, session_id="sess-a")
    assert sess_a.session_id == "sess-a"
    assert sess_a.workspace_id == ws_a

    # Retrieve matching workspace
    retrieved = await manager.get_session("sess-a", workspace_id=ws_a)
    assert retrieved is not None
    assert retrieved.session_id == "sess-a"

    # Cross-tenant retrieval mismatch returns None
    mismatch = await manager.get_session("sess-a", workspace_id=ws_b)
    assert mismatch is None

    # Close session
    closed = await manager.close_session("sess-a", workspace_id=ws_a)
    assert closed is True
    assert await manager.get_session("sess-a") is None


# ==============================================================================
# 3. Audio Frame Ingestion & VAD Boundary Trigger
# ==============================================================================

@pytest.mark.asyncio
async def test_voice_session_audio_frame_ingestion_and_vad_turn():
    """Verify audio frame ingestion buffers speech and detects speech-turn boundary."""
    ws_id = uuid.uuid4()
    session = VoiceSession(session_id="sess-vad", workspace_id=ws_id, user_id=uuid.uuid4())

    # Mock VAD to detect speech on first frames, then silence
    speech_frame = generate_tone_pcm(duration_sec=0.030)  # 30ms frame
    silence_frame = generate_silence_pcm(duration_sec=0.030)

    # Ingest 12 speech frames (360ms speech > 300ms min threshold)
    for _ in range(12):
        res = await session.ingest_audio_frame(speech_frame)
        assert res is not None

    assert session.state == VoiceSessionState.LISTENING
    assert len(session.ephemeral_audio_buffer) == 12 * len(speech_frame)

    # Ingest silence frames to trigger turn boundary
    ready_trigger = None
    for _ in range(15):
        res = await session.ingest_audio_frame(silence_frame)
        if res and res.get("action") == "speech_turn_ready":
            ready_trigger = res
            break

    assert ready_trigger is not None
    assert ready_trigger["action"] == "speech_turn_ready"
    assert len(ready_trigger["audio_bytes"]) >= 12 * len(speech_frame)
    assert len(session.ephemeral_audio_buffer) == 0  # Purged into ready payload


# ==============================================================================
# 4. Turn Processing End-to-End
# ==============================================================================

@pytest.mark.asyncio
async def test_voice_session_turn_processing_end_to_end():
    """Verify complete conversational turn: STT -> Agent Envelope -> TTS Streaming."""
    ws_id = uuid.uuid4()
    session = VoiceSession(session_id="sess-turn", workspace_id=ws_id, user_id=uuid.uuid4())

    # Mock STT
    mock_stt_res = SpeechTranscriptionResult(
        text="What is the system status?",
        language="en",
        duration_seconds=1.5,
        processing_latency_ms=120.0,
        realtime_factor=0.08,
        untrusted_envelope="<untrusted_spoken_content>What is the system status?</untrusted_spoken_content>",
        session_id=session.session_id,
        workspace_id=str(ws_id),
    )
    session.stt_service.transcribe_audio_pcm = AsyncMock(return_value=mock_stt_res)

    # Mock TTS stream
    async def mock_tts_stream(text, **kwargs):
        yield TTSAudioChunk(chunk_index=1, pcm_bytes=b"\x00"*3200, duration_seconds=0.1, is_final=True, sentence_text=text)

    session.tts_service.synthesize_stream = mock_tts_stream

    # Handler receives untrusted envelope
    received_envelope = []
    def agent_handler(envelope: str):
        received_envelope.append(envelope)
        return "All systems operational."

    audio_pcm = generate_tone_pcm(duration_sec=1.5)
    chunks = []
    async for chunk in session.process_turn(audio_pcm, agent_handler_fn=agent_handler):
        chunks.append(chunk)

    assert len(chunks) == 1
    assert len(received_envelope) == 1
    assert "<untrusted_spoken_content>" in received_envelope[0]
    assert session.state == VoiceSessionState.COMPLETED
    assert len(session.turns) == 1
    assert session.turns[0].user_transcript == "What is the system status?"
    assert session.turns[0].agent_text == "All systems operational."
    assert session.turns[0].is_interrupted is False


# ==============================================================================
# 5. Cooperative Barge-In While Speaking
# ==============================================================================

@pytest.mark.asyncio
async def test_cooperative_barge_in_while_speaking():
    """Verify speech onset while agent is speaking halts active TTS and resumes listening."""
    ws_id = uuid.uuid4()
    session = VoiceSession(session_id="sess-barge", workspace_id=ws_id, user_id=uuid.uuid4())

    # Put session in SPEAKING state
    session.transition_to(VoiceSessionState.LISTENING)
    session.transition_to(VoiceSessionState.TRANSCRIBING)
    session.transition_to(VoiceSessionState.THINKING)
    session.transition_to(VoiceSessionState.SPEAKING)

    turn = VoiceTurn(turn_index=1, agent_text="Long agent output sentence.")
    session.turns.append(turn)

    assert session.active_cancel_event.is_set() is False

    # Ingest speech frame triggering barge-in
    speech_frame = generate_tone_pcm(duration_sec=0.030)
    res = await session.ingest_audio_frame(speech_frame)

    assert res is not None
    assert res["action"] == "barge_in_triggered"
    assert session.state == VoiceSessionState.LISTENING
    assert turn.is_interrupted is True
    assert turn.interruption_reason == "vad_speech_onset"
    # Cancellation event was pulsed and a fresh event was created for next turn
    assert session.active_cancel_event.is_set() is False


# ==============================================================================
# 6. Cooperative Barge-In While Thinking
# ==============================================================================

@pytest.mark.asyncio
async def test_cooperative_barge_in_while_thinking():
    """Verify barge-in while thinking aborts turn before TTS speech begins."""
    ws_id = uuid.uuid4()
    session = VoiceSession(session_id="sess-think-barge", workspace_id=ws_id, user_id=uuid.uuid4())

    session.transition_to(VoiceSessionState.LISTENING)
    session.transition_to(VoiceSessionState.TRANSCRIBING)
    session.transition_to(VoiceSessionState.THINKING)

    barge_success = session.trigger_barge_in(reason="user_button_click")
    assert barge_success is True
    assert session.state == VoiceSessionState.LISTENING


# ==============================================================================
# 7. Repeated Rapid Barge-In Sequence Resilience
# ==============================================================================

@pytest.mark.asyncio
async def test_repeated_rapid_barge_in_robustness():
    """Verify rapid consecutive barge-ins do not deadlock or violate state invariants."""
    ws_id = uuid.uuid4()
    session = VoiceSession(session_id="sess-rapid", workspace_id=ws_id, user_id=uuid.uuid4())

    for i in range(10):
        session.transition_to(VoiceSessionState.LISTENING)
        session.transition_to(VoiceSessionState.TRANSCRIBING)
        session.transition_to(VoiceSessionState.THINKING)
        session.transition_to(VoiceSessionState.SPEAKING)
        assert session.state == VoiceSessionState.SPEAKING

        session.trigger_barge_in(reason=f"rapid_barge_{i}")
        assert session.state == VoiceSessionState.LISTENING

    assert len(session.events) >= 40


# ==============================================================================
# 8. Global Kill Switch Immediate Session Cancellation
# ==============================================================================

@pytest.mark.asyncio
async def test_voice_session_global_kill_switch_abortion():
    """Verify active kill switch halts voice turn and transitions session to CANCELLED."""
    ws_id = uuid.uuid4()
    session = VoiceSession(session_id="sess-kill", workspace_id=ws_id, user_id=uuid.uuid4())
    session.ephemeral_audio_buffer.extend(b"\x00" * 3200)

    # Activate kill switch
    kill_switch.set_active(True, ws_id)

    try:
        with pytest.raises(VoiceProcessingError, match="Active kill-switch engaged"):
            await session.ingest_audio_frame(b"\x00" * 640)

        assert session.state == VoiceSessionState.CANCELLED
        assert len(session.ephemeral_audio_buffer) == 0  # Buffer purged
    finally:
        kill_switch.set_active(False, ws_id)


# ==============================================================================
# 9. Bulk Workspace Session Cancellation
# ==============================================================================

@pytest.mark.asyncio
async def test_cancel_workspace_sessions_bulk():
    """Verify cancel_workspace_sessions cancels only target workspace sessions."""
    manager = VoiceSessionManager()
    ws_1 = uuid.uuid4()
    ws_2 = uuid.uuid4()

    s1 = await manager.create_session(workspace_id=ws_1, user_id=uuid.uuid4(), session_id="ws1-s1")
    s2 = await manager.create_session(workspace_id=ws_1, user_id=uuid.uuid4(), session_id="ws1-s2")
    s3 = await manager.create_session(workspace_id=ws_2, user_id=uuid.uuid4(), session_id="ws2-s1")

    s1.transition_to(VoiceSessionState.LISTENING)
    s2.transition_to(VoiceSessionState.LISTENING)
    s3.transition_to(VoiceSessionState.LISTENING)

    cancelled_count = await manager.cancel_workspace_sessions(ws_1, reason="emergency_abort")
    assert cancelled_count == 2

    assert s1.state == VoiceSessionState.CANCELLED
    assert s2.state == VoiceSessionState.CANCELLED
    assert s3.state == VoiceSessionState.LISTENING  # ws_2 untouched


# ==============================================================================
# 10. Malformed Frames & Empty Utterances
# ==============================================================================

@pytest.mark.asyncio
async def test_empty_utterance_and_malformed_frame_handling():
    """Verify robust rejection of malformed frames and empty transcript returns to LISTENING."""
    ws_id = uuid.uuid4()
    session = VoiceSession(session_id="sess-err", workspace_id=ws_id, user_id=uuid.uuid4())

    # Empty frame
    with pytest.raises(VoiceProcessingError, match="empty audio frame"):
        await session.ingest_audio_frame(b"")

    # Odd length frame
    with pytest.raises(VoiceProcessingError, match="not 16-bit aligned"):
        await session.ingest_audio_frame(b"\x00\x01\x02")

    # Empty transcript handling in process_turn
    mock_empty_stt = SpeechTranscriptionResult(
        text="   ",
        language="en",
        duration_seconds=0.5,
        processing_latency_ms=50.0,
        realtime_factor=0.1,
        untrusted_envelope="<untrusted_spoken_content></untrusted_spoken_content>",
    )
    session.stt_service.transcribe_audio_pcm = AsyncMock(return_value=mock_empty_stt)

    chunks = []
    async for chunk in session.process_turn(generate_tone_pcm(0.5)):
        chunks.append(chunk)

    assert len(chunks) == 0
    assert session.state == VoiceSessionState.LISTENING


# ==============================================================================
# 11. Context Preservation Across Interrupted Turns
# ==============================================================================

@pytest.mark.asyncio
async def test_conversation_context_preservation_after_barge_in():
    """Verify multi-turn history preserves completed and interrupted turns without duplication."""
    ws_id = uuid.uuid4()
    session = VoiceSession(session_id="sess-hist", workspace_id=ws_id, user_id=uuid.uuid4())

    # Turn 1: Completed
    t1 = VoiceTurn(turn_index=1, user_transcript="Turn 1 text", agent_text="Turn 1 reply", completed_at=time.time())
    session.turns.append(t1)

    # Turn 2: Interrupted by barge-in
    session.transition_to(VoiceSessionState.LISTENING)
    session.transition_to(VoiceSessionState.TRANSCRIBING)
    session.transition_to(VoiceSessionState.THINKING)
    session.transition_to(VoiceSessionState.SPEAKING)

    t2 = VoiceTurn(turn_index=2, user_transcript="Turn 2 text", agent_text="Turn 2 partial reply")
    session.turns.append(t2)

    session.trigger_barge_in(reason="user_interruption")
    assert t2.is_interrupted is True

    # Turn 3: Completed
    session.transition_to(VoiceSessionState.TRANSCRIBING)
    session.transition_to(VoiceSessionState.THINKING)
    session.transition_to(VoiceSessionState.SPEAKING)
    t3 = VoiceTurn(turn_index=3, user_transcript="Turn 3 text", agent_text="Turn 3 reply", completed_at=time.time())
    session.turns.append(t3)
    session.transition_to(VoiceSessionState.COMPLETED)

    assert len(session.turns) == 3
    assert session.turns[0].is_interrupted is False
    assert session.turns[1].is_interrupted is True
    assert session.turns[2].is_interrupted is False


# ==============================================================================
# 12. Ephemeral Memory Purge Guarantee
# ==============================================================================

@pytest.mark.asyncio
async def test_ephemeral_memory_purge_in_session():
    """Verify session audio buffers are cleared and not retained in memory."""
    ws_id = uuid.uuid4()
    session = VoiceSession(session_id="sess-purge", workspace_id=ws_id, user_id=uuid.uuid4())

    session.ephemeral_audio_buffer.extend(b"\x00" * 16000)
    assert len(session.ephemeral_audio_buffer) == 16000

    session.cancel_session(reason="user_disconnect")
    assert len(session.ephemeral_audio_buffer) == 0
    assert session.state == VoiceSessionState.CANCELLED
