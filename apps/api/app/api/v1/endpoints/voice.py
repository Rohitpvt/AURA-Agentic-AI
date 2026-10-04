"""AURA Phase 7 Voice Session Protocol and WebSocket Gateway Endpoint (AURA-704).

Provides:
1. POST /api/v1/voice/ticket: Authenticated HTTPS endpoint for issuing short-lived single-use voice tickets.
2. GET /api/v1/voice/stream: Authenticated WebSocket gateway for bi-directional streaming audio.
3. Binary Transport Framing: SeqNum (uint32) + TimestampMs (uint64) + Int16LE PCM.
4. Dynamic Cooperative Barge-In & State Synchronization over WebSocket.
5. Strict Multi-Tenant Workspace Tenancy & Kill Switch Integration.
"""

import asyncio
import logging
import struct
import time
import uuid
from typing import Any, Dict, Optional, Tuple
from fastapi import APIRouter, Depends, Header, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db_session, get_workspace_membership
from app.core.errors import AuthenticationError, AuthorizationError, VoiceProcessingError
from app.db.models.user import User
from app.services.kill_switch import kill_switch
from app.services.voice.session_manager import VoiceSession, VoiceSessionManager, VoiceSessionState, voice_session_manager
from app.services.voice.ticket_service import VoiceTicket, VoiceTicketService, voice_ticket_service

logger = logging.getLogger(__name__)

router = APIRouter()

# Binary Framing Constants (Little-Endian: 4-byte uint32 SeqNum + 8-byte uint64 TimestampMs = 12 bytes)
FRAME_HEADER_FORMAT = "<IQ"
FRAME_HEADER_SIZE = struct.calcsize(FRAME_HEADER_FORMAT)  # 12 bytes


class VoiceTicketRequest(BaseModel):
    """Payload for requesting a short-lived voice session ticket."""
    workspace_id: uuid.UUID = Field(..., description="Target workspace UUID for voice session authorization")
    ttl_seconds: Optional[int] = Field(default=60, ge=10, le=300, description="Ticket validity window in seconds")


class VoiceTicketResponse(BaseModel):
    """Metadata returned upon successful voice ticket issuance."""
    ticket: str = Field(..., description="Single-use cryptographically secure ticket token")
    expires_in: int = Field(default=60, description="Ticket TTL in seconds")
    workspace_id: uuid.UUID = Field(..., description="Authorized workspace UUID")
    user_id: uuid.UUID = Field(..., description="Authorized user UUID")
    created_at: float = Field(..., description="Epoch timestamp of ticket creation")


def unpack_audio_frame(frame_bytes: bytes) -> Tuple[int, int, bytes]:
    """Validate and unpack binary audio frame into (seq_num, timestamp_ms, pcm_bytes)."""
    if len(frame_bytes) < FRAME_HEADER_SIZE:
        raise VoiceProcessingError(
            f"Malformed binary frame: length {len(frame_bytes)} bytes is smaller than 12-byte header"
        )

    seq_num, timestamp_ms = struct.unpack(FRAME_HEADER_FORMAT, frame_bytes[:FRAME_HEADER_SIZE])
    pcm_bytes = frame_bytes[FRAME_HEADER_SIZE:]

    if len(pcm_bytes) == 0:
        raise VoiceProcessingError("Binary frame contains empty PCM payload")

    if len(pcm_bytes) % 2 != 0:
        raise VoiceProcessingError(f"Malformed PCM payload: byte length {len(pcm_bytes)} is not 16-bit aligned")

    if len(pcm_bytes) > 32768:
        raise VoiceProcessingError(f"Oversized PCM payload: {len(pcm_bytes)} bytes exceeds 32KB max limit")

    return seq_num, timestamp_ms, pcm_bytes


def pack_audio_frame(seq_num: int, timestamp_ms: int, pcm_bytes: bytes) -> bytes:
    """Pack seq_num, timestamp_ms, and 16 kHz Int16 PCM into binary transport frame."""
    header = struct.pack(FRAME_HEADER_FORMAT, seq_num, timestamp_ms)
    return header + pcm_bytes


# ==============================================================================
# 1. Authenticated Voice Ticket Issuance (HTTPS POST)
# ==============================================================================

@router.post(
    "/ticket",
    response_model=VoiceTicketResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Issue single-use voice session ticket",
    description="Authenticate user and validate workspace membership before issuing a 60-second single-use ticket for WebSocket upgrade.",
)
async def create_voice_ticket(
    body: VoiceTicketRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> VoiceTicketResponse:
    """Issue short-lived single-use voice session ticket."""
    # 1. Check workspace membership and authorization
    await get_workspace_membership(workspace_id=body.workspace_id, user=current_user, db=db)

    # 2. Check kill switch for workspace
    if kill_switch.is_active(body.workspace_id):
        raise AuthorizationError("Voice sessions are disabled while workspace kill switch is active")

    # 3. Issue single-use ticket
    ticket = await voice_ticket_service.issue_ticket(
        user_id=current_user.id,
        workspace_id=body.workspace_id,
        ttl_seconds=body.ttl_seconds,
    )

    return VoiceTicketResponse(
        ticket=ticket.ticket_token,
        expires_in=int(ticket.expires_at - ticket.created_at),
        workspace_id=ticket.workspace_id,
        user_id=ticket.user_id,
        created_at=ticket.created_at,
    )


# ==============================================================================
# 2. Authenticated Real-Time Voice WebSocket Gateway
# ==============================================================================

@router.websocket("/stream")
async def voice_stream_gateway(
    websocket: WebSocket,
    ticket: str = Query(..., description="Single-use voice session ticket token"),
    workspace_id: Optional[uuid.UUID] = Query(None, description="Optional workspace UUID verification"),
) -> None:
    """Authenticated real-time bidirectional voice streaming WebSocket gateway.
    
    Workflow:
    1. Authenticate & consume single-use ticket atomically.
    2. Enforce workspace tenancy & kill switch checks.
    3. Generate 256-bit CSPRNG session nonce and register VoiceSession.
    4. Send session_init handshake frame.
    5. Handle binary audio frames (12-byte header + Int16 PCM) and JSON control events.
    6. Stream synthesized TTS audio frames and transcribe spoken envelopes.
    7. Clean up session and ephemeral buffers on disconnect.
    """
    # 1. Validate & Atomically Consume Ticket before accepting WebSocket
    consumed_ticket: Optional[VoiceTicket] = None
    try:
        consumed_ticket = await voice_ticket_service.consume_ticket(
            ticket_token=ticket,
            expected_workspace_id=workspace_id,
        )
    except (AuthenticationError, AuthorizationError) as e:
        logger.warning(f"Voice WebSocket connection rejected during ticket verification: {e}")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=str(e))
        return
    except Exception as e:
        logger.error(f"Unexpected error during voice ticket consumption: {e}")
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR, reason="Internal ticket verification error")
        return

    # 2. Accept WebSocket Connection
    await websocket.accept()

    # 3. Kill-Switch Pre-flight Check
    if kill_switch.is_active(consumed_ticket.workspace_id):
        logger.warning(f"Voice WebSocket rejected: active kill switch on workspace {consumed_ticket.workspace_id}")
        await websocket.send_json({"type": "kill_switch", "reason": "active_kill_switch_engaged"})
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Active kill-switch engaged")
        return

    # 4. Generate True 256-bit CSPRNG Session Nonce & Register VoiceSession
    raw_nonce, hex_nonce = voice_ticket_service.generate_session_nonce()
    session_id = f"voice-sess-{uuid.uuid4()}"

    session = await voice_session_manager.create_session(
        workspace_id=consumed_ticket.workspace_id,
        user_id=consumed_ticket.user_id,
        session_id=session_id,
    )

    out_seq_counter = 0

    try:
        # 5. Send Initial Session Initialization Frame
        await websocket.send_json({
            "type": "session_init",
            "session_id": session.session_id,
            "workspace_id": str(consumed_ticket.workspace_id),
            "user_id": str(consumed_ticket.user_id),
            "session_nonce": hex_nonce,
            "state": session.state.value,
            "sample_rate": 16000,
            "frame_header_size": FRAME_HEADER_SIZE,
            "created_at": session.created_at,
        })

        # 6. Bi-directional Message Event Loop
        while True:
            # Check kill switch on every iteration
            if kill_switch.is_active(consumed_ticket.workspace_id):
                logger.warning(f"[Session {session.session_id}] Terminating connection due to kill-switch engagement.")
                session.cancel_session(reason="kill_switch_engaged")
                await websocket.send_json({"type": "kill_switch", "reason": "emergency_stop"})
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Kill switch engaged")
                break

            message = await websocket.receive()

            # A. Binary Audio Frame Ingestion
            if "bytes" in message and message["bytes"]:
                raw_frame = message["bytes"]
                try:
                    seq_num, timestamp_ms, pcm_bytes = unpack_audio_frame(raw_frame)
                except VoiceProcessingError as frame_err:
                    logger.warning(f"[Session {session.session_id}] Invalid audio frame: {frame_err}")
                    await websocket.send_json({"type": "error", "message": str(frame_err)})
                    continue

                # Ingest PCM into VoiceSession (Silero VAD + Barge-in Detection)
                ingest_res = await session.ingest_audio_frame(pcm_bytes)

                if ingest_res is None:
                    continue

                action = ingest_res.get("action")

                # Handle Barge-In Triggered by Speech Onset
                if action == "barge_in_triggered":
                    await websocket.send_json({
                        "type": "barge_in",
                        "state": session.state.value,
                        "timestamp": time.time(),
                        "reason": "vad_speech_onset",
                    })

                # Handle Full Speech Turn Ready (Silence confirmed after speech)
                elif action == "speech_turn_ready":
                    audio_to_process = ingest_res.get("audio_bytes")
                    if audio_to_process:
                        # Notify client turn transcription started
                        await websocket.send_json({
                            "type": "state_change",
                            "state": VoiceSessionState.TRANSCRIBING.value,
                        })

                        # Execute turn processing: STT -> Envelope -> Agent -> TTS Stream
                        async for chunk in session.process_turn(audio_to_process):
                            if session.active_cancel_event.is_set():
                                break

                            # Stream synthesized audio chunk as binary frame
                            out_seq_counter += 1
                            out_ts = int(time.time() * 1000)
                            out_frame = pack_audio_frame(out_seq_counter, out_ts, chunk.pcm_bytes)
                            await websocket.send_bytes(out_frame)

                        # Send turn completion status if not interrupted
                        if not session.active_cancel_event.is_set():
                            last_turn = session.turns[-1] if session.turns else None
                            await websocket.send_json({
                                "type": "turn_completed",
                                "turn_id": last_turn.turn_id if last_turn else None,
                                "state": session.state.value,
                                "transcript": last_turn.user_transcript if last_turn else "",
                                "agent_response": last_turn.agent_text if last_turn else "",
                            })

            # B. Text / JSON Control Frames
            elif "text" in message and message["text"]:
                try:
                    import json
                    ctrl_msg = json.loads(message["text"])
                except Exception:
                    await websocket.send_json({"type": "error", "message": "Malformed JSON control frame"})
                    continue

                msg_type = ctrl_msg.get("type")

                if msg_type == "barge_in":
                    # Client explicit barge-in signal (e.g. push-to-talk button or user click)
                    interrupted = session.trigger_barge_in(reason="client_signal")
                    await websocket.send_json({
                        "type": "barge_in_ack",
                        "interrupted": interrupted,
                        "state": session.state.value,
                    })

                elif msg_type == "cancel":
                    # Cancel active turn / session
                    session.cancel_session(reason="client_requested_cancel")
                    await websocket.send_json({
                        "type": "cancelled",
                        "state": session.state.value,
                    })

                elif msg_type == "ping":
                    # Keep-alive heartbeat
                    await websocket.send_json({"type": "pong", "timestamp": time.time()})

                elif msg_type == "status":
                    # Query current session status
                    await websocket.send_json({
                        "type": "status",
                        "session_id": session.session_id,
                        "state": session.state.value,
                        "turns_count": len(session.turns),
                    })

            elif message.get("type") == "websocket.disconnect":
                logger.info(f"[Session {session.session_id}] Client initiated WebSocket disconnect.")
                break

    except WebSocketDisconnect:
        logger.info(f"[Session {session.session_id}] WebSocket disconnected.")
    except Exception as e:
        logger.error(f"[Session {session.session_id}] Unhandled WebSocket gateway error: {e}", exc_info=True)
    finally:
        # 7. Clean up session and ensure zero ephemeral memory leaks
        await voice_session_manager.close_session(
            session_id=session.session_id,
            workspace_id=consumed_ticket.workspace_id,
        )
        logger.info(f"[Session {session.session_id}] Voice session closed and ephemeral resources purged.")
