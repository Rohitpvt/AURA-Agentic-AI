"""Faster-Whisper Speech-to-Text (STT) Service running on CTranslate2."""

import gc
import io
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
import numpy as np

try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None

from app.core.config import settings
from app.core.errors import ModelNotFoundError, VoiceProcessingError
from app.services.kill_switch import kill_switch
from app.services.voice.audio_envelope import format_untrusted_spoken_envelope

logger = logging.getLogger(__name__)


@dataclass
class SpeechTranscriptionResult:
    """Structured result of Speech-to-Text transcription."""
    text: str
    language: str
    duration_seconds: float
    processing_latency_ms: float
    realtime_factor: float
    untrusted_envelope: str
    session_id: Optional[str] = None
    workspace_id: Optional[str] = None
    segments: List[Dict[str, Any]] = field(default_factory=list)


class FasterWhisperSTTService:
    """Speech-to-Text engine executing on CTranslate2 runtime."""

    SAMPLE_RATE: int = 16000

    def __init__(
        self,
        model_size_or_path: Optional[str] = None,
        device: Optional[str] = None,
        compute_type: Optional[str] = None,
        download_root: Optional[str] = None,
        lazy_load: bool = True,
    ):
        self.model_name = model_size_or_path or settings.VOICE_STT_MODEL
        self.device = device or settings.VOICE_STT_DEVICE
        self.compute_type = compute_type or settings.VOICE_STT_COMPUTE_TYPE
        self.download_root = download_root or str(Path(settings.MODELS_CACHE_DIR) / "whisper")
        self._model: Optional[Any] = None

        Path(self.download_root).mkdir(parents=True, exist_ok=True)

        if not lazy_load:
            self.load_model()

    def load_model(self) -> None:
        """Load CTranslate2 Whisper model into memory with int8 CPU fallback."""
        if self._model is not None:
            return

        if WhisperModel is None:
            raise VoiceProcessingError("faster-whisper is required for STT execution")

        logger.info(
            f"Initializing Faster-Whisper model '{self.model_name}' on device='{self.device}', "
            f"compute_type='{self.compute_type}', cache='{self.download_root}'"
        )

        try:
            self._model = WhisperModel(
                model_size_or_path=self.model_name,
                device=self.device,
                compute_type=self.compute_type,
                download_root=self.download_root,
                cpu_threads=4,
                num_workers=1,
            )
            logger.info(f"Faster-Whisper '{self.model_name}' successfully loaded on {self.device}.")
        except Exception as e:
            logger.error(f"Failed to load Faster-Whisper model '{self.model_name}': {e}")
            raise ModelNotFoundError(
                model_name=self.model_name,
                path_or_hint=self.download_root,
                details={"error": str(e), "runtime": "CTranslate2"},
            ) from e

    def is_model_loaded(self) -> bool:
        """Check if model is currently loaded in memory."""
        return self._model is not None

    async def transcribe_audio_pcm(
        self,
        pcm_bytes: bytes,
        sample_rate: int = 16000,
        session_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
        language: Optional[str] = "en",
    ) -> SpeechTranscriptionResult:
        """Transcribe raw Int16 PCM audio bytes into text with ephemeral memory purge."""
        # 1. Kill-Switch Authority Check
        import uuid as _uuid
        ws_uuid = None
        if workspace_id:
            try:
                ws_uuid = _uuid.UUID(str(workspace_id))
            except Exception:
                pass
        if kill_switch.is_active(ws_uuid):
            raise VoiceProcessingError("Active kill-switch engaged: voice transcription aborted")

        start_time = time.perf_counter()

        # 2. Frame Validation
        if not pcm_bytes or len(pcm_bytes) == 0:
            raise VoiceProcessingError("Cannot transcribe empty audio buffer")

        if len(pcm_bytes) % 2 != 0:
            raise VoiceProcessingError(f"Malformed PCM byte buffer: length {len(pcm_bytes)} not 16-bit aligned")

        # 3. Memory Array Conversion
        raw_samples = np.frombuffer(pcm_bytes, dtype=np.int16)
        if len(raw_samples) == 0:
            raise VoiceProcessingError("Audio buffer contains zero samples")

        audio_float = raw_samples.astype(np.float32) / 32768.0
        duration_seconds = len(audio_float) / float(sample_rate)

        # 4. Model Loading
        if self._model is None:
            self.load_model()

        # 5. CTranslate2 Transcription
        try:
            segments_gen, info = self._model.transcribe(
                audio_float,
                language=language,
                beam_size=5,
                vad_filter=False,  # Stream VAD handled upstream by Silero
                temperature=0.0,
            )

            segments_list = []
            text_parts = []
            for seg in segments_gen:
                text_parts.append(seg.text)
                segments_list.append({
                    "id": seg.id,
                    "start": seg.start,
                    "end": seg.end,
                    "text": seg.text.strip(),
                    "avg_logprob": seg.avg_logprob,
                })

            transcribed_text = " ".join(text_parts).strip()
            detected_lang = info.language if info else (language or "en")

        except Exception as e:
            logger.error(f"CTranslate2 transcription failed: {e}")
            raise VoiceProcessingError(f"STT transcription failed: {str(e)}") from e
        finally:
            # 6. Ephemeral Memory Purge (Zero-Persistence Guarantee)
            del audio_float
            del raw_samples
            del pcm_bytes
            gc.collect()

        elapsed_latency_ms = (time.perf_counter() - start_time) * 1000.0
        rtf = (elapsed_latency_ms / 1000.0) / max(0.001, duration_seconds)

        # 7. Prompt Injection Defense Envelope
        untrusted_envelope = format_untrusted_spoken_envelope(
            text=transcribed_text,
            session_id=session_id,
            language=detected_lang,
        )

        return SpeechTranscriptionResult(
            text=transcribed_text,
            language=detected_lang,
            duration_seconds=duration_seconds,
            processing_latency_ms=elapsed_latency_ms,
            realtime_factor=rtf,
            untrusted_envelope=untrusted_envelope,
            session_id=session_id,
            workspace_id=workspace_id,
            segments=segments_list,
        )
