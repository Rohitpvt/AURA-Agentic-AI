"""Silero VAD (Voice Activity Detection) Service on ONNX Runtime."""

import logging
import math
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union
import numpy as np

try:
    import onnxruntime as ort
except ImportError:
    ort = None

from app.core.config import settings
from app.core.errors import ModelNotFoundError, VoiceProcessingError

logger = logging.getLogger(__name__)


@dataclass
class VADState:
    """Stateful context for continuous streaming voice activity detection."""
    h_state: Optional[np.ndarray] = None
    c_state: Optional[np.ndarray] = None
    state_v5: Optional[np.ndarray] = None
    is_speaking: bool = False
    speech_start_time: Optional[float] = None
    last_speech_time: Optional[float] = None
    speech_frames_count: int = 0
    silence_frames_count: int = 0
    total_audio_duration_ms: float = 0.0
    speech_duration_ms: float = 0.0

    def reset(self) -> None:
        """Reset stateful streaming memory."""
        self.h_state = None
        self.c_state = None
        self.state_v5 = None
        self.is_speaking = False
        self.speech_start_time = None
        self.last_speech_time = None
        self.speech_frames_count = 0
        self.silence_frames_count = 0
        self.total_audio_duration_ms = 0.0
        self.speech_duration_ms = 0.0


class SileroVADService:
    """Voice Activity Detection engine executing on ONNX Runtime."""

    SAMPLE_RATE: int = 16000
    WINDOW_SIZE_SAMPLES: int = 512  # Standard Silero 16kHz window (32ms)
    MAX_FRAME_BYTES: int = 32768    # 32KB max safety boundary (~1 sec of audio)

    def __init__(
        self,
        model_path: Optional[str] = None,
        threshold: float = 0.5,
        hangover_ms: int = 300,
    ):
        self.threshold = threshold or settings.VOICE_VAD_THRESHOLD
        self.hangover_ms = hangover_ms or settings.VOICE_VAD_HANGOVER_MS
        self.model_path = model_path or self._resolve_model_path()
        self._session: Optional[Any] = None
        self._is_v5_model: bool = False
        self._input_names: List[str] = []
        self._output_names: List[str] = []
        self._initialize_engine()

    def _resolve_model_path(self) -> str:
        """Resolve path to local Silero VAD ONNX model."""
        cache_dir = Path(settings.MODELS_CACHE_DIR)
        cache_dir.mkdir(parents=True, exist_ok=True)
        default_model = cache_dir / "silero_vad.onnx"
        return str(default_model)

    def _initialize_engine(self) -> None:
        """Initialize ONNX Runtime inference session."""
        if not os.path.exists(self.model_path):
            logger.info(f"Silero VAD ONNX model not found at {self.model_path}. Fallback energy/spectral VAD active.")
            return

        if ort is None:
            raise VoiceProcessingError("onnxruntime is required for Silero VAD execution")

        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        self._session = ort.InferenceSession(
            self.model_path,
            sess_options=opts,
            providers=["CPUExecutionProvider"],
        )
        self._input_names = [inp.name for inp in self._session.get_inputs()]
        self._output_names = [out.name for out in self._session.get_outputs()]
        self._is_v5_model = "state" in self._input_names

    def is_onnx_loaded(self) -> bool:
        """Check whether ONNX inference session is initialized."""
        return self._session is not None

    def validate_pcm_frame(self, pcm_bytes: bytes) -> np.ndarray:
        """Validate, bounds-check, and convert raw Int16 PCM bytes to normalized float32 array."""
        if not isinstance(pcm_bytes, (bytes, bytearray)):
            raise VoiceProcessingError(f"Expected binary PCM audio bytes, got {type(pcm_bytes).__name__}")

        byte_len = len(pcm_bytes)
        if byte_len == 0:
            raise VoiceProcessingError("Received empty audio frame")

        if byte_len % 2 != 0:
            raise VoiceProcessingError(f"Malformed PCM frame: byte length {byte_len} is not 16-bit aligned")

        if byte_len > self.MAX_FRAME_BYTES:
            raise VoiceProcessingError(f"Oversized audio frame: {byte_len} bytes exceeds max boundary {self.MAX_FRAME_BYTES}")

        int16_samples = np.frombuffer(pcm_bytes, dtype=np.int16)
        if len(int16_samples) == 0:
            raise VoiceProcessingError("No audio samples in frame")

        # Convert to float32 in [-1.0, 1.0]
        float_samples = int16_samples.astype(np.float32) / 32768.0
        return float_samples

    def compute_speech_probability(
        self,
        audio_chunk: Union[bytes, np.ndarray],
        state: Optional[VADState] = None,
    ) -> Tuple[float, Optional[VADState]]:
        """Compute speech probability for an audio chunk using Silero ONNX (or energy fallback)."""
        start_time = time.perf_counter()
        active_state = state or VADState()

        if isinstance(audio_chunk, (bytes, bytearray)):
            samples = self.validate_pcm_frame(audio_chunk)
        elif isinstance(audio_chunk, np.ndarray):
            if audio_chunk.dtype == np.int16:
                samples = audio_chunk.astype(np.float32) / 32768.0
            else:
                samples = audio_chunk.astype(np.float32)
        else:
            raise VoiceProcessingError(f"Unsupported audio chunk format: {type(audio_chunk)}")

        frame_duration_ms = (len(samples) / self.SAMPLE_RATE) * 1000.0
        active_state.total_audio_duration_ms += frame_duration_ms

        # If ONNX session is available, execute ONNX inference
        if self._session is not None:
            speech_prob = self._infer_onnx(samples, active_state)
        else:
            speech_prob = self._infer_spectral_energy(samples)

        is_voice = speech_prob >= self.threshold
        now = time.time()

        if is_voice:
            active_state.is_speaking = True
            active_state.last_speech_time = now
            if active_state.speech_start_time is None:
                active_state.speech_start_time = now
            active_state.speech_frames_count += 1
            active_state.silence_frames_count = 0
            active_state.speech_duration_ms += frame_duration_ms
        else:
            active_state.silence_frames_count += 1
            # Check hangover window
            if active_state.is_speaking and active_state.last_speech_time is not None:
                elapsed_silence_ms = (now - active_state.last_speech_time) * 1000.0
                if elapsed_silence_ms > self.hangover_ms:
                    active_state.is_speaking = False

        elapsed_inference_ms = (time.perf_counter() - start_time) * 1000.0
        logger.debug(f"VAD frame inference: prob={speech_prob:.3f}, speaking={active_state.is_speaking}, latency={elapsed_inference_ms:.2f}ms")
        return speech_prob, active_state

    def _infer_onnx(self, samples: np.ndarray, state: VADState) -> float:
        """Run ONNX runtime inference for Silero VAD."""
        # Ensure audio samples match expected window size (pad or slice to 512)
        if len(samples) < self.WINDOW_SIZE_SAMPLES:
            padded = np.zeros(self.WINDOW_SIZE_SAMPLES, dtype=np.float32)
            padded[:len(samples)] = samples
            tensor_input = padded.reshape(1, -1)
        elif len(samples) > self.WINDOW_SIZE_SAMPLES:
            tensor_input = samples[:self.WINDOW_SIZE_SAMPLES].reshape(1, -1)
        else:
            tensor_input = samples.reshape(1, -1)

        sr_tensor = np.array([self.SAMPLE_RATE], dtype=np.int64)

        try:
            if self._is_v5_model:
                if state.state_v5 is None:
                    state.state_v5 = np.zeros((2, 1, 128), dtype=np.float32)
                ort_inputs = {
                    "input": tensor_input,
                    "state": state.state_v5,
                    "sr": sr_tensor,
                }
                out, new_state = self._session.run(None, ort_inputs)
                state.state_v5 = new_state
                prob = float(out[0][0])
            else:
                if state.h_state is None:
                    state.h_state = np.zeros((2, 1, 64), dtype=np.float32)
                if state.c_state is None:
                    state.c_state = np.zeros((2, 1, 64), dtype=np.float32)

                ort_inputs = {
                    "input": tensor_input,
                    "sr": sr_tensor,
                    "h": state.h_state,
                    "c": state.c_state,
                }
                out, new_h, new_c = self._session.run(None, ort_inputs)
                state.h_state = new_h
                state.c_state = new_c
                prob = float(out[0][0])

            return max(0.0, min(1.0, prob))
        except Exception as e:
            logger.warning(f"ONNX VAD inference failed: {e}. Falling back to spectral energy.")
            return self._infer_spectral_energy(samples)

    def _infer_spectral_energy(self, samples: np.ndarray) -> float:
        """High-precision root-mean-square and zero-crossing rate VAD fallback."""
        if len(samples) == 0:
            return 0.0

        # RMS Energy
        rms = np.sqrt(np.mean(samples ** 2))

        # Zero Crossing Rate
        zero_crossings = np.sum(np.abs(np.diff(np.sign(samples)))) / (2.0 * len(samples))

        # Spectral energy probability sigmoid
        # Typical speech RMS > 0.015
        val = (rms - 0.015) * 60.0 + (zero_crossings - 0.1) * 5.0
        prob = 1.0 / (1.0 + math.exp(-max(-20.0, min(20.0, val))))
        return float(prob)
