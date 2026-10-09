"""AURA Phase 7 Voice Session Protocol and Cooperative Barge-In Engine (AURA-703).

Provides:
1. Strict VoiceSessionState state machine with deterministic transitions.
2. Cooperative barge-in cancellation: user speech onset halts active Piper-TTS streaming and LLM thinking.
3. Multi-tenant workspace scoping (zero cross-tenant state leakage).
4. Global KillSwitchManager integration with instantaneous session termination.
5. Ephemeral raw audio handling with zero disk/DB retention.
6. <untrusted_spoken_content> security envelope enforcement.
"""

import asyncio
import gc
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional, Set, Tuple

from app.core.config import settings
from app.core.errors import VoiceProcessingError
from app.services.kill_switch import kill_switch
from app.services.voice.audio_envelope import format_untrusted_spoken_envelope
from app.services.voice.stt_service import FasterWhisperSTTService, SpeechTranscriptionResult
from app.services.voice.tts_service import PiperTTSService, TTSAudioChunk, split_sentences
from app.services.voice.vad_service import SileroVADService, VADState

logger = logging.getLogger(__name__)


class VoiceSessionState(str, Enum):
    """Deterministic states of the voice conversation turn lifecycle."""
    IDLE = "idle"
    LISTENING = "listening"
    TRANSCRIBING = "transcribing"
    THINKING = "thinking"
    SPEAKING = "speaking"
    INTERRUPTED = "interrupted"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ERROR = "error"


# Valid state transitions graph
VALID_TRANSITIONS: Dict[VoiceSessionState, Set[VoiceSessionState]] = {
    VoiceSessionState.IDLE: {
        VoiceSessionState.LISTENING,
        VoiceSessionState.CANCELLED,
        VoiceSessionState.ERROR,
    },
    VoiceSessionState.LISTENING: {
        VoiceSessionState.TRANSCRIBING,
        VoiceSessionState.IDLE,
        VoiceSessionState.INTERRUPTED,
        VoiceSessionState.CANCELLED,
        VoiceSessionState.ERROR,
    },
    VoiceSessionState.TRANSCRIBING: {
        VoiceSessionState.THINKING,
        VoiceSessionState.LISTENING,
        VoiceSessionState.INTERRUPTED,
        VoiceSessionState.CANCELLED,
        VoiceSessionState.ERROR,
    },
    VoiceSessionState.THINKING: {
        VoiceSessionState.SPEAKING,
        VoiceSessionState.INTERRUPTED,
        VoiceSessionState.CANCELLED,
        VoiceSessionState.ERROR,
        VoiceSessionState.COMPLETED,
    },
    VoiceSessionState.SPEAKING: {
        VoiceSessionState.INTERRUPTED,
        VoiceSessionState.LISTENING,
        VoiceSessionState.COMPLETED,
        VoiceSessionState.CANCELLED,
        VoiceSessionState.ERROR,
    },
    VoiceSessionState.INTERRUPTED: {
        VoiceSessionState.LISTENING,
        VoiceSessionState.IDLE,
        VoiceSessionState.CANCELLED,
        VoiceSessionState.ERROR,
    },
    VoiceSessionState.COMPLETED: {
        VoiceSessionState.LISTENING,
        VoiceSessionState.IDLE,
        VoiceSessionState.CANCELLED,
    },
    VoiceSessionState.CANCELLED: {
        VoiceSessionState.IDLE,
        VoiceSessionState.LISTENING,
    },
    VoiceSessionState.ERROR: {
        VoiceSessionState.IDLE,
        VoiceSessionState.LISTENING,
    },
}


@dataclass
class VoiceTurn:
    """Historical record of an individual conversational turn in a voice session."""
    turn_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    turn_index: int = 1
    user_audio_duration_seconds: float = 0.0
    user_transcript: str = ""
    untrusted_envelope: str = ""
    agent_text: str = ""
    agent_audio_chunks_count: int = 0
    is_interrupted: bool = False
    interrupted_at_sentence_index: Optional[int] = None
    interruption_reason: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None


@dataclass
class VoiceEvent:
    """Structured telemetry/audit event emitted during voice session execution."""
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str = "state_change"
    timestamp: float = field(default_factory=time.time)
    from_state: Optional[str] = None
    to_state: Optional[str] = None
    reason: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)


class VoiceSession:
    """Encapsulates real-time voice interaction, bi-directional state, and cooperative barge-in."""

    MIN_SPEECH_DURATION_MS: float = 500.0  # Minimum speech required to trigger transcription

    def __init__(
        self,
        session_id: str,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
        vad_service: Optional[SileroVADService] = None,
        stt_service: Optional[FasterWhisperSTTService] = None,
        tts_service: Optional[PiperTTSService] = None,
    ):
        self.session_id = session_id
        self.workspace_id = workspace_id
        self.user_id = user_id

        self.vad_service = vad_service or SileroVADService()
        self.stt_service = stt_service or FasterWhisperSTTService(lazy_load=True)
        self.tts_service = tts_service or PiperTTSService(lazy_load=True)

        self.state: VoiceSessionState = VoiceSessionState.IDLE
        self.vad_state: VADState = VADState()
        self.turns: List[VoiceTurn] = []
        self.events: List[VoiceEvent] = []

        self.active_cancel_event: asyncio.Event = asyncio.Event()
        self.active_turn_task: Optional[asyncio.Task] = None
        self.ephemeral_audio_buffer: bytearray = bytearray()
        self.lock: asyncio.Lock = asyncio.Lock()
        self.created_at: float = time.time()
        self.last_activity_at: float = time.time()

        self._record_event("session_created", payload={"workspace_id": str(workspace_id), "user_id": str(user_id)})

    def _record_event(
        self,
        event_type: str,
        from_state: Optional[VoiceSessionState] = None,
        to_state: Optional[VoiceSessionState] = None,
        reason: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> VoiceEvent:
        """Append a structured event to the session audit timeline."""
        evt = VoiceEvent(
            event_type=event_type,
            timestamp=time.time(),
            from_state=from_state.value if from_state else None,
            to_state=to_state.value if to_state else None,
            reason=reason,
            payload=payload or {},
        )
        self.events.append(evt)
        return evt

    def transition_to(
        self,
        new_state: VoiceSessionState,
        reason: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Transition voice session state enforcing deterministic graph rules."""
        if self.state == new_state:
            return

        valid_targets = VALID_TRANSITIONS.get(self.state, set())
        if new_state not in valid_targets:
            err_msg = f"Invalid voice state transition: '{self.state.value}' -> '{new_state.value}'"
            logger.error(f"[Session {self.session_id}] {err_msg}")
            self._record_event("invalid_transition_attempt", from_state=self.state, to_state=new_state, reason=err_msg)
            raise VoiceProcessingError(err_msg)

        old_state = self.state
        self.state = new_state
        self.last_activity_at = time.time()
        logger.debug(f"[Session {self.session_id}] State changed: {old_state.value} -> {new_state.value} (reason: {reason})")
        self._record_event("state_change", from_state=old_state, to_state=new_state, reason=reason, payload=payload)

    def trigger_barge_in(self, reason: str = "user_speech_onset") -> bool:
        """Cooperatively interrupt active agent speaking/thinking turn."""
        if self.state not in (VoiceSessionState.SPEAKING, VoiceSessionState.THINKING):
            return False

        logger.info(f"[Session {self.session_id}] Cooperative barge-in triggered (reason: {reason})")
        # 1. Signal cancellation to active Piper TTS and LLM stream generators
        self.active_cancel_event.set()
        if self.active_turn_task is not None and not self.active_turn_task.done():
            self.active_turn_task.cancel()

        # 2. Transition to INTERRUPTED
        self.transition_to(VoiceSessionState.INTERRUPTED, reason=reason)

        # 3. Mark current turn as interrupted if active
        if self.turns and self.turns[-1].completed_at is None:
            self.turns[-1].is_interrupted = True
            self.turns[-1].interruption_reason = reason
            self.turns[-1].completed_at = time.time()

        # 4. Prepare fresh cancellation event for the next turn
        self.active_cancel_event = asyncio.Event()

        # 5. Transition to LISTENING for the new incoming user utterance
        self.transition_to(VoiceSessionState.LISTENING, reason="barge_in_listen_resume")
        return True

    def cancel_session(self, reason: str = "kill_switch") -> None:
        """Halt all active voice processing and cancel session."""
        self.active_cancel_event.set()
        if self.active_turn_task is not None and not self.active_turn_task.done():
            self.active_turn_task.cancel()
        # Ephemeral memory purge (zeroize buffers)
        self.ephemeral_audio_buffer.clear()
        self.vad_state.reset()

        if self.state != VoiceSessionState.CANCELLED:
            try:
                self.transition_to(VoiceSessionState.CANCELLED, reason=reason)
            except Exception:
                self.state = VoiceSessionState.CANCELLED

    async def ingest_audio_frame(self, pcm_frame: bytes) -> Optional[Dict[str, Any]]:
        """Ingest a 16 kHz Int16 PCM audio frame (20-30ms), update VAD, and handle barge-in."""
        # 1. Kill-Switch Authority Check
        if kill_switch.is_active(self.workspace_id):
            self.cancel_session(reason="kill_switch_active")
            raise VoiceProcessingError("Active kill-switch engaged: voice session aborted")

        # 2. Frame bounds and validation
        if not pcm_frame or len(pcm_frame) == 0:
            raise VoiceProcessingError("Received empty audio frame")
        if len(pcm_frame) % 2 != 0:
            raise VoiceProcessingError(f"Malformed PCM frame: length {len(pcm_frame)} not 16-bit aligned")
        if len(pcm_frame) > SileroVADService.MAX_FRAME_BYTES:
            raise VoiceProcessingError(f"Oversized audio frame ({len(pcm_frame)} bytes)")

        async with self.lock:
            # 3. Check VAD on frame
            speech_prob, self.vad_state = self.vad_service.compute_speech_probability(pcm_frame, state=self.vad_state)
            is_voice = speech_prob >= self.vad_service.threshold

            # 4. Barge-In Trigger: If speaking or thinking and speech is detected
            if self.state in (VoiceSessionState.SPEAKING, VoiceSessionState.THINKING) and is_voice:
                self.trigger_barge_in(reason="vad_speech_onset")
                self.ephemeral_audio_buffer.extend(pcm_frame)
                return {"action": "barge_in_triggered", "prob": speech_prob}

            # 5. In IDLE or COMPLETED, first voice onset moves session to LISTENING
            if self.state in (VoiceSessionState.IDLE, VoiceSessionState.COMPLETED) and is_voice:
                self.transition_to(VoiceSessionState.LISTENING, reason="voice_onset")
                self.ephemeral_audio_buffer.clear()
                self.ephemeral_audio_buffer.extend(pcm_frame)
                return {"action": "listening_started", "prob": speech_prob}

            # 6. In LISTENING state: buffer speech frames
            if self.state == VoiceSessionState.LISTENING:
                if self.vad_state.is_speaking or is_voice:
                    self.ephemeral_audio_buffer.extend(pcm_frame)
                    return {"action": "buffering", "prob": speech_prob, "buffered_bytes": len(self.ephemeral_audio_buffer)}
                else:
                    # Speech turn boundary reached (silence confirmed after speech)
                    buffered_duration_ms = (len(self.ephemeral_audio_buffer) / 32.0)
                    if buffered_duration_ms >= self.MIN_SPEECH_DURATION_MS:
                        # Return trigger for turn processing
                        audio_to_process = bytes(self.ephemeral_audio_buffer)
                        self.ephemeral_audio_buffer.clear()
                        self.vad_state.reset()
                        return {
                            "action": "speech_turn_ready",
                            "audio_bytes": audio_to_process,
                            "duration_ms": buffered_duration_ms,
                        }
                    elif len(self.ephemeral_audio_buffer) > 0:
                        # Transient noise / click below speech threshold; purge buffer
                        self.ephemeral_audio_buffer.clear()
                        self.vad_state.reset()

            return {"action": "noop", "prob": speech_prob}

    async def process_turn(
        self,
        audio_pcm: bytes,
        agent_handler_fn: Optional[Callable[[str], Any]] = None,
    ) -> AsyncGenerator[TTSAudioChunk, None]:
        """Execute a full conversational turn: STT -> Agent Thought -> Streaming TTS."""
        # 1. Kill-Switch Check
        if kill_switch.is_active(self.workspace_id):
            self.cancel_session(reason="kill_switch_active")
            raise VoiceProcessingError("Active kill-switch engaged: voice turn aborted")

        # Ensure session transitions through LISTENING if in IDLE, COMPLETED, or INTERRUPTED
        if self.state in (VoiceSessionState.IDLE, VoiceSessionState.COMPLETED, VoiceSessionState.INTERRUPTED):
            self.transition_to(VoiceSessionState.LISTENING, reason="turn_start")

        # 2. Transition to TRANSCRIBING
        self.transition_to(VoiceSessionState.TRANSCRIBING, reason="audio_ingestion_complete")

        # Create Turn Record
        turn = VoiceTurn(
            turn_index=len(self.turns) + 1,
            user_audio_duration_seconds=len(audio_pcm) / 32000.0,
        )
        self.turns.append(turn)

        # 3. Faster-Whisper Speech-to-Text
        try:
            stt_res: SpeechTranscriptionResult = await self.stt_service.transcribe_audio_pcm(
                pcm_bytes=audio_pcm,
                sample_rate=16000,
                session_id=self.session_id,
                workspace_id=str(self.workspace_id),
            )
            turn.user_transcript = stt_res.text
            turn.untrusted_envelope = stt_res.untrusted_envelope
        except Exception as e:
            self.transition_to(VoiceSessionState.ERROR, reason=f"STT failed: {e}")
            raise

        # Check if transcription produced empty speech
        if not turn.user_transcript.strip():
            logger.info(f"[Session {self.session_id}] Empty transcript received; returning to LISTENING.")
            self.transition_to(VoiceSessionState.LISTENING, reason="empty_transcript")
            return

        # 4. Transition to THINKING
        self.transition_to(VoiceSessionState.THINKING, reason="transcript_ready", payload={"transcript": turn.user_transcript})

        # 5. Invoke Agent Handler / Reasoning Engine
        if self.active_cancel_event.is_set():
            logger.info(f"[Session {self.session_id}] Turn cancelled during thinking.")
            self.transition_to(VoiceSessionState.INTERRUPTED, reason="cancelled_in_thinking")
            return

        agent_response_text = ""
        if agent_handler_fn is not None:
            try:
                # Agent receives untrusted spoken envelope
                res = agent_handler_fn(turn.untrusted_envelope)
                if asyncio.iscoroutine(res):
                    res = await res
                agent_response_text = str(res)
            except Exception as e:
                self.transition_to(VoiceSessionState.ERROR, reason=f"Agent handler failed: {e}")
                raise
        else:
            # Default response
            agent_response_text = f"I received: {turn.user_transcript}"

        turn.agent_text = agent_response_text

        # 6. Transition to SPEAKING
        if self.active_cancel_event.is_set():
            logger.info(f"[Session {self.session_id}] Turn cancelled before speaking.")
            self.transition_to(VoiceSessionState.INTERRUPTED, reason="cancelled_before_speaking")
            return

        self.transition_to(VoiceSessionState.SPEAKING, reason="agent_response_ready", payload={"text_length": len(agent_response_text)})

        # 7. Stream Piper-TTS Audio Chunks
        chunks_count = 0
        try:
            async for chunk in self.tts_service.synthesize_stream(
                text=agent_response_text,
                session_id=self.session_id,
                workspace_id=str(self.workspace_id),
                cancel_event=self.active_cancel_event,
            ):
                if self.active_cancel_event.is_set():
                    turn.is_interrupted = True
                    turn.interrupted_at_sentence_index = chunk.chunk_index
                    break

                chunks_count += 1
                turn.agent_audio_chunks_count = chunks_count
                yield chunk

        except Exception as e:
            if not self.active_cancel_event.is_set():
                self.transition_to(VoiceSessionState.ERROR, reason=f"TTS stream failed: {e}")
                raise

        # 8. Turn Completion
        turn.completed_at = time.time()
        if not turn.is_interrupted:
            self.transition_to(VoiceSessionState.COMPLETED, reason="turn_synthesis_complete")


class VoiceSessionManager:
    """Manages active multi-tenant voice sessions, barge-in routing, and global kill-switch isolation."""

    def __init__(
        self,
        vad_service: Optional[SileroVADService] = None,
        stt_service: Optional[FasterWhisperSTTService] = None,
        tts_service: Optional[PiperTTSService] = None,
    ):
        self._sessions: Dict[str, VoiceSession] = {}
        self._workspace_index: Dict[uuid.UUID, Set[str]] = {}
        self._lock = asyncio.Lock()

        self.vad_service = vad_service or SileroVADService()
        self.stt_service = stt_service or FasterWhisperSTTService(lazy_load=True)
        self.tts_service = tts_service or PiperTTSService(lazy_load=True)

    async def create_session(
        self,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
        session_id: Optional[str] = None,
    ) -> VoiceSession:
        """Create and register an isolated voice session for a workspace."""
        sid = session_id or str(uuid.uuid4())

        async with self._lock:
            if sid in self._sessions:
                raise VoiceProcessingError(f"Voice session with ID '{sid}' already exists")

            session = VoiceSession(
                session_id=sid,
                workspace_id=workspace_id,
                user_id=user_id,
                vad_service=self.vad_service,
                stt_service=self.stt_service,
                tts_service=self.tts_service,
            )

            self._sessions[sid] = session
            if workspace_id not in self._workspace_index:
                self._workspace_index[workspace_id] = set()
            self._workspace_index[workspace_id].add(sid)

            logger.info(f"Created VoiceSession {sid} in workspace {workspace_id}")
            return session

    async def get_session(
        self,
        session_id: str,
        workspace_id: Optional[uuid.UUID] = None,
    ) -> Optional[VoiceSession]:
        """Retrieve a voice session ensuring workspace tenant scoping."""
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            if workspace_id is not None and session.workspace_id != workspace_id:
                logger.warning(f"Tenant isolation mismatch: session {session_id} belongs to {session.workspace_id}, requested {workspace_id}")
                return None
            return session

    async def close_session(
        self,
        session_id: str,
        workspace_id: Optional[uuid.UUID] = None,
    ) -> bool:
        """Close and purge a voice session."""
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False
            if workspace_id is not None and session.workspace_id != workspace_id:
                return False

            session.cancel_session(reason="session_closed")
            del self._sessions[session_id]

            if session.workspace_id in self._workspace_index:
                self._workspace_index[session.workspace_id].discard(session_id)
                if not self._workspace_index[session.workspace_id]:
                    del self._workspace_index[session.workspace_id]

            logger.info(f"Closed VoiceSession {session_id}")
            return True

    async def cancel_workspace_sessions(
        self,
        workspace_id: uuid.UUID,
        reason: str = "kill_switch",
    ) -> int:
        """Cancel all active voice sessions within a specific workspace."""
        async with self._lock:
            session_ids = self._workspace_index.get(workspace_id, set()).copy()
            count = 0
            for sid in session_ids:
                sess = self._sessions.get(sid)
                if sess:
                    sess.cancel_session(reason=reason)
                    count += 1
            logger.info(f"Cancelled {count} voice sessions in workspace {workspace_id} (reason: {reason})")
            return count

    async def list_active_sessions(
        self,
        workspace_id: Optional[uuid.UUID] = None,
    ) -> List[VoiceSession]:
        """List active voice sessions optionally filtered by workspace."""
        async with self._lock:
            if workspace_id:
                sids = self._workspace_index.get(workspace_id, set())
                return [self._sessions[sid] for sid in sids if sid in self._sessions]
            return list(self._sessions.values())


# Singleton VoiceSessionManager instance
voice_session_manager = VoiceSessionManager()
