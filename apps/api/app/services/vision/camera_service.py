"""AURA Phase 8 Live Camera Ingestion & Duplex Vision Transport Service (AURA-803).

Provides:
1. 26-Byte Binary Framing Protocol (StreamType + SourceID + SeqNum + TimestampNs + Width + Height + PayloadLen + WebP).
2. Camera Session Management with True 256-bit CSPRNG Session Nonce.
3. Server-side Rate Limiting (Default 2.0 FPS, Hard Ceiling 5.0 FPS).
4. Depth-1 Volatile Ephemeral In-Memory Frame Buffer (Newest-Frame-Wins).
5. Strict Multi-Tenant Workspace Tenancy & Emergency Kill Switch Enforcement.
6. Zero Persistent Disk, Database, Logging, or Telemetry Storage of Raw Camera Pixels.
"""

import asyncio
import io
import logging
import struct
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from app.core.errors import AuthorizationError, VisionProcessingError

logger = logging.getLogger(__name__)


def _is_kill_switch_active(workspace_id: Optional[str] = None) -> bool:
    """Lazy check for kill switch state to prevent circular import chain."""
    try:
        from app.services.kill_switch import kill_switch
        return kill_switch.is_active(workspace_id=workspace_id)
    except Exception:
        return False

# ==============================================================================
# Binary Framing Protocol Constants
# ==============================================================================
# Fixed 26-byte header format (Big-Endian):
# uint8  stream_type      (1 byte, offset 0)  - 0x01=Screen, 0x02=Camera, 0x03=Window
# uint8  source_id        (1 byte, offset 1)  - Camera device index (0-255)
# uint32 sequence_number  (4 bytes, offset 2) - Monotonic frame counter
# uint64 timestamp_ns     (8 bytes, offset 6) - Nanosecond Unix epoch timestamp
# uint32 width            (4 bytes, offset 14) - Frame width in pixels
# uint32 height           (4 bytes, offset 18) - Frame height in pixels
# uint32 payload_length   (4 bytes, offset 22) - Byte length N of WebP payload
FRAME_HEADER_FORMAT = ">BBIQIII"
FRAME_HEADER_SIZE = struct.calcsize(FRAME_HEADER_FORMAT)  # Exactly 26 bytes

# Stream Types
STREAM_TYPE_SCREEN: int = 0x01
STREAM_TYPE_CAMERA: int = 0x02
STREAM_TYPE_WINDOW: int = 0x03

# Transport and Resource Limits
DEFAULT_CAMERA_FPS: float = 2.0
MAX_CAMERA_FPS: float = 5.0  # Absolute server-side ceiling
MIN_FRAME_INTERVAL_SEC: float = 1.0 / MAX_CAMERA_FPS  # 0.20s (200 ms)
MAX_PAYLOAD_SIZE_BYTES: int = 5 * 1024 * 1024  # 5 MB
MAX_CAMERA_WIDTH: int = 1920
MAX_CAMERA_HEIGHT: int = 1080
MIN_CAMERA_DIMENSION: int = 1


@dataclass
class CameraFrameHeader:
    """Parsed metadata from 26-byte binary frame header."""
    stream_type: int
    source_id: int
    sequence_number: int
    timestamp_ns: int
    width: int
    height: int
    payload_length: int


@dataclass
class CameraObservation:
    """Ephemeral in-memory camera frame observation."""
    frame_id: str
    workspace_id: str
    session_id: str
    source_id: int
    sequence_number: int
    timestamp_ns: int
    width: int
    height: int
    format: str = "WEBP"
    size_bytes: int = 0
    raw_bytes: bytes = field(default_factory=bytes, repr=False)
    received_at: float = field(default_factory=time.time)


@dataclass
class CameraSession:
    """Active live camera WebSocket transport session."""
    session_id: str
    workspace_id: str
    user_id: str
    session_nonce: str  # 64-char hex
    created_at: float = field(default_factory=time.time)
    last_accepted_time: float = 0.0
    last_sequence_number: int = -1
    frames_received: int = 0
    frames_accepted: int = 0
    frames_dropped: int = 0
    is_active: bool = True
    close_reason: Optional[str] = None


def pack_camera_frame(
    stream_type: int,
    source_id: int,
    sequence_number: int,
    timestamp_ns: int,
    width: int,
    height: int,
    payload: bytes,
) -> bytes:
    """Pack frame metadata and WebP payload into canonical 26-byte header + binary payload."""
    payload_len = len(payload)
    header = struct.pack(
        FRAME_HEADER_FORMAT,
        stream_type,
        source_id,
        sequence_number,
        timestamp_ns,
        width,
        height,
        payload_len,
    )
    return header + payload


def unpack_camera_frame(frame_bytes: bytes) -> Tuple[CameraFrameHeader, bytes]:
    """Validate and unpack binary camera frame into CameraFrameHeader and raw WebP payload bytes.
    
    Raises:
        VisionProcessingError: If header is malformed, dimensions are invalid, or payload is corrupt.
    """
    if len(frame_bytes) < FRAME_HEADER_SIZE:
        raise VisionProcessingError(
            f"Malformed binary frame: length {len(frame_bytes)} bytes is smaller than 26-byte header"
        )

    (
        stream_type,
        source_id,
        sequence_number,
        timestamp_ns,
        width,
        height,
        payload_length,
    ) = struct.unpack(FRAME_HEADER_FORMAT, frame_bytes[:FRAME_HEADER_SIZE])

    # Validate stream type
    if stream_type not in (STREAM_TYPE_SCREEN, STREAM_TYPE_CAMERA, STREAM_TYPE_WINDOW):
        raise VisionProcessingError(f"Unsupported stream type in binary header: 0x{stream_type:02X}")

    # Validate dimensions
    if not (MIN_CAMERA_DIMENSION <= width <= MAX_CAMERA_WIDTH):
        raise VisionProcessingError(
            f"Invalid frame width {width}px: must be between {MIN_CAMERA_DIMENSION} and {MAX_CAMERA_WIDTH}px"
        )

    if not (MIN_CAMERA_DIMENSION <= height <= MAX_CAMERA_HEIGHT):
        raise VisionProcessingError(
            f"Invalid frame height {height}px: must be between {MIN_CAMERA_DIMENSION} and {MAX_CAMERA_HEIGHT}px"
        )

    # Validate payload length matching
    actual_payload = frame_bytes[FRAME_HEADER_SIZE:]
    if len(actual_payload) != payload_length:
        raise VisionProcessingError(
            f"Payload length mismatch: header specifies {payload_length} bytes, actual is {len(actual_payload)} bytes"
        )

    if payload_length == 0:
        raise VisionProcessingError("Binary camera frame contains empty payload")

    if payload_length > MAX_PAYLOAD_SIZE_BYTES:
        raise VisionProcessingError(
            f"Oversized camera payload: {payload_length} bytes exceeds {MAX_PAYLOAD_SIZE_BYTES} bytes max limit"
        )

    # Verify WebP container header signature (RIFF....WEBP)
    if len(actual_payload) >= 12:
        if not (actual_payload[:4] == b"RIFF" and actual_payload[8:12] == b"WEBP"):
            raise VisionProcessingError("Malformed payload: image bytes do not have valid WebP RIFF/WEBP signature")
    else:
        raise VisionProcessingError("Malformed payload: byte length insufficient for WebP header")

    header = CameraFrameHeader(
        stream_type=stream_type,
        source_id=source_id,
        sequence_number=sequence_number,
        timestamp_ns=timestamp_ns,
        width=width,
        height=height,
        payload_length=payload_length,
    )
    return header, actual_payload


class CameraVisionService:
    """Manages live camera WebSocket sessions, rate limiting, and depth-1 volatile buffering."""

    def __init__(self):
        self._sessions: Dict[str, CameraSession] = {}
        # Depth-1 ephemeral memory buffer keyed by workspace_id
        self._ephemeral_frames: Dict[str, CameraObservation] = {}
        self._lock = asyncio.Lock()

    def create_session(
        self,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        session_nonce: str,
    ) -> CameraSession:
        """Initialize a new live camera session bound to user, workspace, and 256-bit nonce."""
        ws_str = str(workspace_id)
        if _is_kill_switch_active(workspace_id=ws_str):
            raise AuthorizationError("Emergency Kill Switch is ACTIVE: Camera session creation blocked.")

        session_id = str(uuid.uuid4())
        session = CameraSession(
            session_id=session_id,
            workspace_id=ws_str,
            user_id=str(user_id),
            session_nonce=session_nonce,
            created_at=time.time(),
        )
        self._sessions[session_id] = session
        logger.info(f"Initialized camera session {session_id} for ws={ws_str}")
        return session

    def get_session(self, session_id: str) -> Optional[CameraSession]:
        """Retrieve active session by ID."""
        return self._sessions.get(session_id)

    def close_session(self, session_id: str, reason: Optional[str] = None) -> None:
        """Clean up and close camera session, releasing ephemeral resources."""
        session = self._sessions.pop(session_id, None)
        if session:
            session.is_active = False
            session.close_reason = reason or "closed"
            logger.info(
                f"Closed camera session {session_id} for ws={session.workspace_id} "
                f"(accepted={session.frames_accepted}, dropped={session.frames_dropped}, reason={session.close_reason})"
            )
            # Purge ephemeral frame for workspace
            self._ephemeral_frames.pop(session.workspace_id, None)

    def ingest_frame(
        self,
        session_id: str,
        frame_bytes: bytes,
    ) -> Tuple[bool, Optional[str], Optional[CameraObservation]]:
        """Ingest and validate binary camera frame with rate limiting and depth-1 buffering.
        
        Returns:
            Tuple[bool, Optional[str], Optional[CameraObservation]]:
                - accepted: True if frame passed validation and rate limiting.
                - reason: None if accepted, or rejection reason ("rate_limit_exceeded", "stale_sequence_number", etc.).
                - observation: CameraObservation if accepted, None otherwise.
        """
        session = self._sessions.get(session_id)
        if not session or not session.is_active:
            return False, "session_inactive", None

        # 1. Kill Switch Check
        if _is_kill_switch_active(workspace_id=session.workspace_id):
            self.clear_ephemeral_frame(session.workspace_id)
            raise AuthorizationError("Emergency Kill Switch is ACTIVE: Ingestion aborted.")

        session.frames_received += 1

        # 2. Parse 26-byte binary framing
        header, payload = unpack_camera_frame(frame_bytes)

        now = time.time()

        # 3. Enforce Server-Side Rate Ceiling (Max 5.0 FPS / Min 200 ms interval)
        if session.last_accepted_time > 0.0:
            elapsed = now - session.last_accepted_time
            if elapsed < MIN_FRAME_INTERVAL_SEC:
                session.frames_dropped += 1
                return False, "rate_limit_exceeded", None

        # 4. Enforce Monotonic Sequence Number (Reject regressions/duplicates)
        if header.sequence_number <= session.last_sequence_number:
            session.frames_dropped += 1
            return False, "stale_sequence_number", None

        # 5. Accept Frame & Update Session State
        session.frames_accepted += 1
        session.last_accepted_time = now
        session.last_sequence_number = header.sequence_number

        observation = CameraObservation(
            frame_id=str(uuid.uuid4()),
            workspace_id=session.workspace_id,
            session_id=session.session_id,
            source_id=header.source_id,
            sequence_number=header.sequence_number,
            timestamp_ns=header.timestamp_ns,
            width=header.width,
            height=header.height,
            format="WEBP",
            size_bytes=len(payload),
            raw_bytes=payload,
            received_at=now,
        )

        # 6. Depth-1 Buffer Update (Newest-Frame-Wins)
        self._ephemeral_frames[session.workspace_id] = observation

        return True, None, observation

    def get_latest_observation(self, workspace_id: str) -> Optional[CameraObservation]:
        """Retrieve latest ephemeral camera observation for workspace."""
        if _is_kill_switch_active(workspace_id=workspace_id):
            self.clear_ephemeral_frame(workspace_id)
            return None
        return self._ephemeral_frames.get(workspace_id)

    def get_latest_frame(self, workspace_id: str) -> Optional[CameraObservation]:
        """Convenience alias for get_latest_observation."""
        return self.get_latest_observation(workspace_id)

    def clear_ephemeral_frame(self, workspace_id: Optional[str] = None) -> None:
        """Purge volatile camera frame memory for workspace or all workspaces."""
        if workspace_id:
            self._ephemeral_frames.pop(workspace_id, None)
        else:
            self._ephemeral_frames.clear()

    def get_status(self, workspace_id: Optional[str] = None) -> Dict[str, Any]:
        """Get operational status and configuration limits of the camera transport subsystem."""
        active_sessions = sum(1 for s in self._sessions.values() if s.is_active)
        has_ephemeral = bool(workspace_id and workspace_id in self._ephemeral_frames)
        is_killed = bool(workspace_id and _is_kill_switch_active(workspace_id=workspace_id))

        return {
            "status": "kill_switched" if is_killed else "available",
            "active_sessions_count": active_sessions,
            "default_fps": DEFAULT_CAMERA_FPS,
            "max_fps_ceiling": MAX_CAMERA_FPS,
            "min_frame_interval_sec": MIN_FRAME_INTERVAL_SEC,
            "max_resolution": f"{MAX_CAMERA_WIDTH}x{MAX_CAMERA_HEIGHT}",
            "header_size_bytes": FRAME_HEADER_SIZE,
            "buffer_depth": 1,
            "has_ephemeral_frame": has_ephemeral,
            "format": "WEBP",
        }


# Global singleton instance
camera_vision_service = CameraVisionService()
