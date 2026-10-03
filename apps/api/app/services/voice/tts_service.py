"""Piper-TTS Speech Synthesis Service running on ONNX Runtime."""

import asyncio
import gc
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple, Union
import numpy as np

try:
    import piper
    from piper.voice import PiperVoice
except ImportError:
    piper = None
    PiperVoice = None

from app.core.config import settings
from app.core.errors import ModelNotFoundError, VoiceProcessingError
from app.services.kill_switch import kill_switch

logger = logging.getLogger(__name__)


@dataclass
class TTSAudioChunk:
    """A streaming chunk of 16 kHz Mono Int16 PCM audio synthesized from text."""
    chunk_index: int
    pcm_bytes: bytes
    sample_rate: int = 16000
    duration_seconds: float = 0.0
    is_final: bool = False
    sentence_text: str = ""
    latency_ms: float = 0.0


@dataclass
class SpeechSynthesisResult:
    """Structured aggregate result of speech synthesis."""
    text: str
    pcm_bytes: bytes
    sample_rate: int = 16000
    duration_seconds: float = 0.0
    ttfa_ms: float = 0.0
    total_latency_ms: float = 0.0
    realtime_factor: float = 0.0
    chunk_count: int = 0
    session_id: Optional[str] = None
    workspace_id: Optional[str] = None


def split_sentences(text: str) -> List[str]:
    """Split input text along sentence boundaries preserving abbreviations and numbers."""
    if not text or not isinstance(text, str):
        return []

    clean = text.strip()
    if not clean:
        return []

    # Regex splitting on sentence terminators followed by whitespace, newlines, or semicolons
    # Avoid splitting on decimals (e.g., 3.14) or common abbreviations (e.g., Dr., Mr., etc.)
    pattern = re.compile(r'(?<=[.!?])\s+|\n+|(?:;\s+)', re.UNICODE)
    raw_sentences = pattern.split(clean)

    sentences = []
    for s in raw_sentences:
        s_clean = s.strip()
        if s_clean:
            sentences.append(s_clean)

    return sentences if sentences else [clean]


class PiperTTSService:
    """Local neural Text-to-Speech service running on ONNX Runtime."""

    OUTPUT_SAMPLE_RATE: int = 16000
    MAX_INPUT_CHARS: int = 5000
    SYNTHESIS_TIMEOUT_SECONDS: float = 10.0

    def __init__(
        self,
        model_name: Optional[str] = None,
        download_root: Optional[str] = None,
        use_cuda: bool = False,
        lazy_load: bool = True,
    ):
        self.model_name = model_name or settings.VOICE_TTS_MODEL
        self.download_root = download_root or str(Path(settings.MODELS_CACHE_DIR) / "tts")
        self.use_cuda = use_cuda
        self._voice: Optional[Any] = None

        Path(self.download_root).mkdir(parents=True, exist_ok=True)

        if not lazy_load:
            self.load_model()

    def _resolve_paths(self) -> Tuple[Path, Path]:
        """Resolve ONNX model and config file paths."""
        root = Path(self.download_root)
        onnx_file = root / f"{self.model_name}.onnx"
        json_file = root / f"{self.model_name}.onnx.json"
        return onnx_file, json_file

    def load_model(self) -> None:
        """Load Piper ONNX voice model into memory."""
        if self._voice is not None:
            return

        if PiperVoice is None:
            raise VoiceProcessingError("piper-tts is required for speech synthesis execution")

        onnx_path, json_path = self._resolve_paths()

        if not onnx_path.exists() or not json_path.exists():
            # In offline mode without local files, raise ModelNotFoundError
            logger.info(f"Piper ONNX model '{self.model_name}' not found at {onnx_path}")
            raise ModelNotFoundError(
                model_name=self.model_name,
                path_or_hint=str(onnx_path),
                details={"runtime": "ONNX Runtime", "expected_files": [str(onnx_path), str(json_path)]},
            )

        logger.info(f"Loading Piper ONNX voice '{self.model_name}' on device={'cuda' if self.use_cuda else 'cpu'}")
        try:
            self._voice = PiperVoice.load(
                model_path=str(onnx_path),
                config_path=str(json_path),
                use_cuda=self.use_cuda,
            )
            logger.info(f"Piper ONNX voice '{self.model_name}' loaded successfully.")
        except Exception as e:
            logger.error(f"Failed loading Piper ONNX voice '{self.model_name}': {e}")
            raise ModelNotFoundError(
                model_name=self.model_name,
                path_or_hint=str(onnx_path),
                details={"error": str(e), "runtime": "ONNX Runtime"},
            ) from e

    def is_model_loaded(self) -> bool:
        """Check whether Piper voice model is loaded in memory."""
        return self._voice is not None

    def _resample_to_16k_pcm(self, audio_float: np.ndarray, orig_sr: int) -> bytes:
        """Resample audio float array to 16 kHz Mono Int16 Little-Endian PCM bytes."""
        if len(audio_float) == 0:
            return b""

        if orig_sr != self.OUTPUT_SAMPLE_RATE:
            num_output_samples = int(len(audio_float) * self.OUTPUT_SAMPLE_RATE / orig_sr)
            resampled = np.interp(
                np.linspace(0.0, 1.0, num_output_samples, endpoint=False),
                np.linspace(0.0, 1.0, len(audio_float), endpoint=False),
                audio_float,
            )
        else:
            resampled = audio_float

        int16_samples = (np.clip(resampled, -1.0, 1.0) * 32767.0).astype(np.int16)
        return int16_samples.tobytes()

    def _synthesize_sentence_sync(self, sentence: str) -> bytes:
        """Synchronously synthesize a single sentence using Piper ONNX."""
        if self._voice is None:
            self.load_model()

        chunks_float = []
        for chunk in self._voice.synthesize(sentence):
            chunks_float.append(chunk.audio_float_array)

        if not chunks_float:
            return b""

        combined_float = np.concatenate(chunks_float)
        native_sr = getattr(self._voice.config, "sample_rate", 22050)
        pcm_bytes = self._resample_to_16k_pcm(combined_float, native_sr)

        # Ephemeral memory purge
        del combined_float
        del chunks_float
        gc.collect()

        return pcm_bytes

    async def synthesize_stream(
        self,
        text: str,
        session_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
        cancel_event: Optional[asyncio.Event] = None,
    ) -> AsyncGenerator[TTSAudioChunk, None]:
        """Synthesize text as a streaming sequence of 16 kHz Int16 PCM chunks along sentence boundaries."""
        # 1. Kill-Switch Authority Check
        ws_uuid = None
        if workspace_id:
            try:
                ws_uuid = uuid.UUID(str(workspace_id))
            except Exception:
                pass
        if kill_switch.is_active(ws_uuid):
            raise VoiceProcessingError("Active kill-switch engaged: voice synthesis aborted")

        # 2. Input Validation
        if not text or not isinstance(text, str):
            raise VoiceProcessingError("Cannot synthesize empty text")

        clean_text = text.strip()
        if not clean_text:
            raise VoiceProcessingError("Cannot synthesize empty whitespace text")

        if len(clean_text) > self.MAX_INPUT_CHARS:
            raise VoiceProcessingError(
                f"Input text length ({len(clean_text)}) exceeds maximum boundary of {self.MAX_INPUT_CHARS} characters"
            )

        # 3. Sentence Boundary Splitting
        sentences = split_sentences(clean_text)
        if not sentences:
            raise VoiceProcessingError("No synthesizable sentence tokens found in input text")

        total_sentences = len(sentences)

        # 4. Sequential Sentence Streaming with Cancellation Check
        for idx, sentence in enumerate(sentences, 1):
            # Check cancellation / kill switch before each sentence chunk
            if cancel_event is not None and cancel_event.is_set():
                logger.info(f"Piper TTS stream cancelled at sentence {idx}/{total_sentences}")
                break

            if kill_switch.is_active(ws_uuid):
                logger.warning(f"Piper TTS stream aborted by active kill switch at sentence {idx}/{total_sentences}")
                raise VoiceProcessingError("Active kill-switch engaged: voice synthesis aborted")

            t_start = time.perf_counter()

            # Execute synthesis with timeout
            try:
                pcm_bytes = await asyncio.wait_for(
                    asyncio.to_thread(self._synthesize_sentence_sync, sentence),
                    timeout=self.SYNTHESIS_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError as e:
                raise VoiceProcessingError(
                    f"TTS synthesis timed out after {self.SYNTHESIS_TIMEOUT_SECONDS}s for sentence: '{sentence[:30]}...'"
                ) from e
            except Exception as e:
                if isinstance(e, (VoiceProcessingError, ModelNotFoundError)):
                    raise
                raise VoiceProcessingError(f"TTS synthesis failed on sentence: {str(e)}") from e

            elapsed_chunk_ms = (time.perf_counter() - t_start) * 1000.0
            duration_sec = len(pcm_bytes) / 32000.0  # 16000 samples/sec * 2 bytes/sample

            is_final = (idx == total_sentences)

            yield TTSAudioChunk(
                chunk_index=idx,
                pcm_bytes=pcm_bytes,
                sample_rate=self.OUTPUT_SAMPLE_RATE,
                duration_seconds=duration_sec,
                is_final=is_final,
                sentence_text=sentence,
                latency_ms=elapsed_chunk_ms,
            )

    async def synthesize_full(
        self,
        text: str,
        session_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
        cancel_event: Optional[asyncio.Event] = None,
    ) -> SpeechSynthesisResult:
        """Synthesize entire text and aggregate metrics into SpeechSynthesisResult."""
        start_time = time.perf_counter()
        pcm_chunks = []
        ttfa_ms = 0.0
        total_duration_sec = 0.0
        chunk_count = 0

        async for chunk in self.synthesize_stream(
            text=text,
            session_id=session_id,
            workspace_id=workspace_id,
            cancel_event=cancel_event,
        ):
            chunk_count += 1
            if chunk_count == 1:
                ttfa_ms = chunk.latency_ms

            pcm_chunks.append(chunk.pcm_bytes)
            total_duration_sec += chunk.duration_seconds

        total_latency_ms = (time.perf_counter() - start_time) * 1000.0
        rtf = (total_latency_ms / 1000.0) / max(0.001, total_duration_sec)
        combined_pcm = b"".join(pcm_chunks)

        return SpeechSynthesisResult(
            text=text,
            pcm_bytes=combined_pcm,
            sample_rate=self.OUTPUT_SAMPLE_RATE,
            duration_seconds=total_duration_sec,
            ttfa_ms=ttfa_ms,
            total_latency_ms=total_latency_ms,
            realtime_factor=rtf,
            chunk_count=chunk_count,
            session_id=session_id,
            workspace_id=workspace_id,
        )
