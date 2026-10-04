"""AURA Phase 7 Real-Time Voice and Speech Subsystem."""

from app.services.voice.audio_envelope import (
    extract_untrusted_spoken_content,
    format_untrusted_spoken_envelope,
)
from app.services.voice.vad_service import SileroVADService, VADState
from app.services.voice.stt_service import FasterWhisperSTTService, SpeechTranscriptionResult
from app.services.voice.tts_service import (
    PiperTTSService,
    SpeechSynthesisResult,
    TTSAudioChunk,
    split_sentences,
)

from app.services.voice.session_manager import (
    VoiceEvent,
    VoiceSession,
    VoiceSessionManager,
    VoiceSessionState,
    VoiceTurn,
    voice_session_manager,
)
from app.services.voice.ticket_service import (
    VoiceTicket,
    VoiceTicketService,
    voice_ticket_service,
)

__all__ = [
    "SileroVADService",
    "VADState",
    "FasterWhisperSTTService",
    "SpeechTranscriptionResult",
    "PiperTTSService",
    "TTSAudioChunk",
    "SpeechSynthesisResult",
    "split_sentences",
    "format_untrusted_spoken_envelope",
    "extract_untrusted_spoken_content",
    "VoiceSessionState",
    "VoiceSession",
    "VoiceSessionManager",
    "VoiceTurn",
    "VoiceEvent",
    "voice_session_manager",
    "VoiceTicket",
    "VoiceTicketService",
    "voice_ticket_service",
]
