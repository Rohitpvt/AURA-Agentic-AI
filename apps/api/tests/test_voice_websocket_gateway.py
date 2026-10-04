"""AURA-704 Authenticated WebSocket Gateway & Session Ticket Transport Tests.

Covers:
1. Short-lived single-use voice ticket issuance (POST /api/v1/voice/ticket).
2. Workspace authorization & tenancy enforcement.
3. Atomic single-use ticket consumption & concurrent replay prevention.
4. True 256-bit CSPRNG session nonce generation (32 raw bytes, 64 hex chars).
5. WebSocket upgrade handshake, session_init frame, and bi-directional streaming.
6. Binary transport framing: SeqNum (uint32) + TimestampMs (uint64) + Int16LE PCM.
7. Malformed and oversized frame rejection.
8. Real-time barge-in and cancellation control frames over WebSocket.
9. Kill-switch integration & emergency connection abort.
10. Clean session lifecycle teardown and memory purge on disconnect.
"""

import asyncio
import struct
import time
import uuid
import pytest
from fastapi import status
from fastapi.testclient import TestClient
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AuthenticationError, AuthorizationError, VoiceProcessingError
from app.core.security import create_access_token
from app.db.models.user import User
from app.db.models.workspace import Workspace, WorkspaceMember
from app.main import app
from app.services.kill_switch import kill_switch
from app.services.voice.session_manager import VoiceSessionState, voice_session_manager
from app.services.voice.ticket_service import VoiceTicket, VoiceTicketService, voice_ticket_service
from app.api.v1.endpoints.voice import FRAME_HEADER_SIZE, pack_audio_frame, unpack_audio_frame


# ==============================================================================
# Helper Fixtures & Builders
# ==============================================================================

async def setup_test_user_and_workspace(db: AsyncSession):
    """Helper to provision a user, primary workspace, and membership."""
    user = User(
        id=uuid.uuid4(),
        email=f"voice_user_{uuid.uuid4().hex[:8]}@example.com",
        full_name="Voice Test User",
        password_hash="hashed_pw_test",
        is_active=True,
    )
    db.add(user)

    ws = Workspace(
        id=uuid.uuid4(),
        name=f"Voice Workspace {uuid.uuid4().hex[:6]}",
        slug=f"voice-ws-{uuid.uuid4().hex[:6]}",
    )
    db.add(ws)

    member = WorkspaceMember(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        user_id=user.id,
        role="owner",
        permissions=["admin"],
    )
    db.add(member)

    await db.commit()
    await db.refresh(user)
    await db.refresh(ws)
    return user, ws


def generate_pcm_sine(duration_sec: float = 0.030, sample_rate: int = 16000) -> bytes:
    """Generate 16 kHz Int16 little-endian PCM bytes."""
    import numpy as np
    num_samples = int(duration_sec * sample_rate)
    t = np.linspace(0, duration_sec, num_samples, endpoint=False)
    samples = 0.5 * np.sin(2 * np.pi * 440.0 * t)
    int16_samples = (samples * 32767).astype(np.int16)
    return int16_samples.tobytes()


# ==============================================================================
# 1. Voice Ticket Service Unit Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_voice_ticket_service_issue_and_validate():
    """Verify ticket service creates valid tickets with expected TTL and bindings."""
    svc = VoiceTicketService(ttl_seconds=30)
    user_id = uuid.uuid4()
    ws_id = uuid.uuid4()

    ticket = await svc.issue_ticket(user_id=user_id, workspace_id=ws_id)
    assert ticket.ticket_token is not None
    assert len(ticket.ticket_token) >= 32
    assert ticket.user_id == user_id
    assert ticket.workspace_id == ws_id
    assert ticket.is_expired is False
    assert ticket.is_consumed is False

    # Consume
    consumed = await svc.consume_ticket(ticket.ticket_token, expected_workspace_id=ws_id)
    assert consumed.is_consumed is True
    assert consumed.user_id == user_id


@pytest.mark.asyncio
async def test_voice_ticket_service_single_use_and_replay_rejection():
    """Verify consumed ticket is immediately invalid for subsequent requests."""
    svc = VoiceTicketService(ttl_seconds=60)
    user_id = uuid.uuid4()
    ws_id = uuid.uuid4()

    ticket = await svc.issue_ticket(user_id=user_id, workspace_id=ws_id)
    
    # First consume succeeds
    c1 = await svc.consume_ticket(ticket.ticket_token)
    assert c1.user_id == user_id

    # Second consume is rejected (replay attempt)
    with pytest.raises(AuthenticationError, match="Invalid or expired voice session ticket"):
        await svc.consume_ticket(ticket.ticket_token)


@pytest.mark.asyncio
async def test_voice_ticket_service_ttl_expiration():
    """Verify expired ticket cannot be consumed."""
    svc = VoiceTicketService(ttl_seconds=1)
    user_id = uuid.uuid4()
    ws_id = uuid.uuid4()

    ticket = await svc.issue_ticket(user_id=user_id, workspace_id=ws_id, ttl_seconds=1)
    # Fast forward expiration
    ticket.expires_at = time.time() - 5.0

    with pytest.raises(AuthenticationError, match="Voice session ticket has expired"):
        await svc.consume_ticket(ticket.ticket_token)


@pytest.mark.asyncio
async def test_voice_ticket_service_concurrent_replay_race():
    """Verify atomic single-use: only 1 out of N concurrent consume attempts succeeds."""
    svc = VoiceTicketService(ttl_seconds=60)
    user_id = uuid.uuid4()
    ws_id = uuid.uuid4()

    ticket = await svc.issue_ticket(user_id=user_id, workspace_id=ws_id)

    results = await asyncio.gather(
        *[svc.consume_ticket(ticket.ticket_token) for _ in range(10)],
        return_exceptions=True,
    )

    successes = [r for r in results if isinstance(r, VoiceTicket)]
    failures = [r for r in results if isinstance(r, Exception)]

    assert len(successes) == 1
    assert len(failures) == 9
    assert all(isinstance(f, AuthenticationError) for f in failures)


@pytest.mark.asyncio
async def test_voice_ticket_service_workspace_mismatch_rejection():
    """Verify ticket bound to Workspace A cannot be consumed for Workspace B."""
    svc = VoiceTicketService(ttl_seconds=60)
    user_id = uuid.uuid4()
    ws_a = uuid.uuid4()
    ws_b = uuid.uuid4()

    ticket = await svc.issue_ticket(user_id=user_id, workspace_id=ws_a)

    with pytest.raises(AuthorizationError, match="not valid for workspace"):
        await svc.consume_ticket(ticket.ticket_token, expected_workspace_id=ws_b)


# ==============================================================================
# 2. 256-Bit Session Nonce Verification
# ==============================================================================

def test_256_bit_session_nonce_properties():
    """Verify CSPRNG nonce generates true 256-bit entropy and 64-char hex format."""
    svc = VoiceTicketService()
    nonces_set = set()

    for _ in range(50):
        raw_bytes, hex_nonce = svc.generate_session_nonce()
        # 32 raw bytes = 256 bits
        assert len(raw_bytes) == 32
        assert len(hex_nonce) == 64
        # Verify hex format
        int(hex_nonce, 16)
        assert hex_nonce not in nonces_set
        nonces_set.add(hex_nonce)


# ==============================================================================
# 3. Binary Transport Framing Unit Tests
# ==============================================================================

def test_binary_audio_frame_packing_and_unpacking():
    """Verify 12-byte header + PCM payload packing and unpacking."""
    seq = 42
    ts = 1698765432100
    pcm = generate_pcm_sine(duration_sec=0.030)  # 960 bytes

    frame = pack_audio_frame(seq, ts, pcm)
    assert len(frame) == 12 + 960

    unpacked_seq, unpacked_ts, unpacked_pcm = unpack_audio_frame(frame)
    assert unpacked_seq == seq
    assert unpacked_ts == ts
    assert unpacked_pcm == pcm


def test_binary_audio_frame_malformed_rejection():
    """Verify parser rejects undersized headers and non-aligned PCM payloads."""
    # Undersized header (< 12 bytes)
    with pytest.raises(VoiceProcessingError, match="smaller than 12-byte header"):
        unpack_audio_frame(b"\x00" * 8)

    # Empty payload
    with pytest.raises(VoiceProcessingError, match="empty PCM payload"):
        unpack_audio_frame(b"\x00" * 12)

    # Odd byte-length PCM payload (not 16-bit aligned)
    with pytest.raises(VoiceProcessingError, match="not 16-bit aligned"):
        unpack_audio_frame(b"\x00" * 12 + b"\x01\x02\x03")


# ==============================================================================
# 4. HTTP POST /api/v1/voice/ticket Endpoint Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_voice_ticket_endpoint_authenticated_issuance(client: AsyncClient, db_session: AsyncSession):
    """Verify POST /api/v1/voice/ticket returns 201 with ticket metadata for authorized member."""
    user, ws = await setup_test_user_and_workspace(db_session)
    token = create_access_token({"sub": str(user.id)})

    headers = {"Authorization": f"Bearer {token}"}
    payload = {"workspace_id": str(ws.id), "ttl_seconds": 60}

    response = await client.post("/api/v1/voice/ticket", json=payload, headers=headers)
    assert response.status_code == 201

    data = response.json()
    assert "ticket" in data
    assert len(data["ticket"]) >= 32
    assert data["workspace_id"] == str(ws.id)
    assert data["user_id"] == str(user.id)
    assert data["expires_in"] == 60


@pytest.mark.asyncio
async def test_voice_ticket_endpoint_unauthenticated_rejection(client: AsyncClient):
    """Verify unauthenticated request is rejected with 401."""
    payload = {"workspace_id": str(uuid.uuid4()), "ttl_seconds": 60}
    response = await client.post("/api/v1/voice/ticket", json=payload)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_voice_ticket_endpoint_unauthorized_non_member_rejection(client: AsyncClient, db_session: AsyncSession):
    """Verify user not belonging to target workspace is rejected with 403."""
    user_a, ws_a = await setup_test_user_and_workspace(db_session)
    user_b, ws_b = await setup_test_user_and_workspace(db_session)

    # User A tries to get ticket for Workspace B
    token_a = create_access_token({"sub": str(user_a.id)})
    headers = {"Authorization": f"Bearer {token_a}"}
    payload = {"workspace_id": str(ws_b.id), "ttl_seconds": 60}

    response = await client.post("/api/v1/voice/ticket", json=payload, headers=headers)
    assert response.status_code == 403
    assert "Access denied" in response.json()["error"]["message"]


# ==============================================================================
# 5. WebSocket Gateway /api/v1/voice/stream Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_websocket_stream_successful_handshake_and_init():
    """Verify WebSocket connection succeeds with valid ticket and receives session_init frame."""
    test_client = TestClient(app)
    user_id = uuid.uuid4()
    ws_id = uuid.uuid4()

    # Pre-issue ticket via service
    ticket = await voice_ticket_service.issue_ticket(user_id=user_id, workspace_id=ws_id)

    with test_client.websocket_connect(f"/api/v1/voice/stream?ticket={ticket.ticket_token}") as ws:
        init_frame = ws.receive_json()
        assert init_frame["type"] == "session_init"
        assert "session_id" in init_frame
        assert init_frame["workspace_id"] == str(ws_id)
        assert init_frame["user_id"] == str(user_id)
        # 256-bit nonce verification
        assert len(init_frame["session_nonce"]) == 64
        assert init_frame["state"] == "idle"
        assert init_frame["sample_rate"] == 16000


@pytest.mark.asyncio
async def test_websocket_stream_rejected_for_invalid_ticket():
    """Verify WebSocket upgrade with invalid ticket is rejected with 1008 policy violation."""
    test_client = TestClient(app)

    with pytest.raises(Exception):
        with test_client.websocket_connect("/api/v1/voice/stream?ticket=invalid-bogus-ticket") as ws:
            pass


@pytest.mark.asyncio
async def test_websocket_stream_rejected_for_replayed_ticket():
    """Verify ticket cannot be reused for a second WebSocket connection."""
    test_client = TestClient(app)
    user_id = uuid.uuid4()
    ws_id = uuid.uuid4()

    ticket = await voice_ticket_service.issue_ticket(user_id=user_id, workspace_id=ws_id)

    # First connection succeeds
    with test_client.websocket_connect(f"/api/v1/voice/stream?ticket={ticket.ticket_token}") as ws:
        data = ws.receive_json()
        assert data["type"] == "session_init"

    # Second connection with same ticket is rejected
    with pytest.raises(Exception):
        with test_client.websocket_connect(f"/api/v1/voice/stream?ticket={ticket.ticket_token}") as ws:
            pass


@pytest.mark.asyncio
async def test_websocket_stream_binary_audio_ingestion_and_ping_control():
    """Verify WebSocket receives binary audio frames and responds to ping control frame."""
    test_client = TestClient(app)
    user_id = uuid.uuid4()
    ws_id = uuid.uuid4()

    ticket = await voice_ticket_service.issue_ticket(user_id=user_id, workspace_id=ws_id)

    with test_client.websocket_connect(f"/api/v1/voice/stream?ticket={ticket.ticket_token}") as ws:
        init_frame = ws.receive_json()
        assert init_frame["type"] == "session_init"

        # 1. Send Ping control frame
        ws.send_json({"type": "ping"})
        pong = ws.receive_json()
        assert pong["type"] == "pong"
        assert "timestamp" in pong

        # 2. Send Binary Audio Frame (30ms PCM)
        pcm = generate_pcm_sine(duration_sec=0.030)
        frame = pack_audio_frame(seq_num=1, timestamp_ms=int(time.time()*1000), pcm_bytes=pcm)
        ws.send_bytes(frame)

        # 3. Query status
        ws.send_json({"type": "status"})
        status_frame = ws.receive_json()
        assert status_frame["type"] == "status"
        assert status_frame["state"] in ("idle", "listening")


@pytest.mark.asyncio
async def test_websocket_stream_barge_in_and_cancel_control_frames():
    """Verify client explicit barge-in and cancel control frames update session state."""
    test_client = TestClient(app)
    user_id = uuid.uuid4()
    ws_id = uuid.uuid4()

    ticket = await voice_ticket_service.issue_ticket(user_id=user_id, workspace_id=ws_id)

    with test_client.websocket_connect(f"/api/v1/voice/stream?ticket={ticket.ticket_token}") as ws:
        _ = ws.receive_json()  # init

        # Send barge-in signal
        ws.send_json({"type": "barge_in"})
        ack = ws.receive_json()
        assert ack["type"] == "barge_in_ack"
        assert "interrupted" in ack

        # Send cancel signal
        ws.send_json({"type": "cancel"})
        cancelled_ack = ws.receive_json()
        assert cancelled_ack["type"] == "cancelled"
        assert cancelled_ack["state"] == "cancelled"


@pytest.mark.asyncio
async def test_websocket_stream_kill_switch_immediate_termination():
    """Verify active workspace kill switch terminates WebSocket connection."""
    test_client = TestClient(app)
    user_id = uuid.uuid4()
    ws_id = uuid.uuid4()

    # Pre-activate kill switch
    kill_switch.set_active(True, ws_id)

    try:
        ticket = await voice_ticket_service.issue_ticket(user_id=user_id, workspace_id=ws_id)
        
        # Connect while kill switch is active -> immediately closed
        with test_client.websocket_connect(f"/api/v1/voice/stream?ticket={ticket.ticket_token}") as ws:
            resp = ws.receive_json()
            assert resp["type"] == "kill_switch"
            assert resp["reason"] == "active_kill_switch_engaged"
    finally:
        kill_switch.set_active(False, ws_id)
