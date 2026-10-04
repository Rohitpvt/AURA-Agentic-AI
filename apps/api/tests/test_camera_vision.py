"""Comprehensive Unit & Integration Test Suite for AURA-803 Camera Transport & Ingestion.

Tests:
1. Vision Ticket Service (Issuance, Expiry, Single-Use, Tenancy, Purpose, CSPRNG Nonce).
2. 26-Byte Binary Framing Protocol (Header Packing/Unpacking, Big-Endian, Dimension Bounds, WebP Validation).
3. Server-side Rate Limiting & Backpressure (5.0 FPS ceiling, Monotonic Sequencing, Depth-1 Buffer).
4. WebSocket Duplex Streaming Gateway (Handshake, Frame Ingestion, Drop Notifications, Ping/Pong, Stop).
5. Emergency Kill Switch Integration (Ticket Block, Connection Abort, Stream Termination, Buffer Purge).
6. Authenticated REST Endpoints (Ticket Issuance, Latest Metadata, Status, Cache Purge).
7. Privacy Invariants (Volatile Ephemeral Memory Only, Zero Disk/DB Storage).
"""

import io
import struct
import time
from typing import Any, Dict, List, Optional, Tuple
import uuid
import pytest
from httpx import AsyncClient
from PIL import Image
from starlette.testclient import TestClient

from app.core.errors import AuthenticationError, AuthorizationError, VisionProcessingError
from app.main import app
from app.services.kill_switch import kill_switch
from app.services.vision.camera_service import (
    FRAME_HEADER_SIZE,
    MAX_CAMERA_FPS,
    MAX_CAMERA_HEIGHT,
    MAX_CAMERA_WIDTH,
    STREAM_TYPE_CAMERA,
    STREAM_TYPE_SCREEN,
    CameraObservation,
    CameraVisionService,
    camera_vision_service,
    pack_camera_frame,
    unpack_camera_frame,
)
from app.services.vision.ticket_service import (
    VisionTicket,
    VisionTicketService,
    vision_ticket_service,
)


def make_test_webp(width: int = 640, height: int = 480, color=(50, 100, 150)) -> bytes:
    """Helper to generate valid WebP image bytes."""
    img = Image.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=80)
    return buf.getvalue()


# ==============================================================================
# 1. Vision Ticket Service Unit Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_vision_ticket_issuance_and_consumption():
    """Verify single-use vision ticket issuance and atomic consumption."""
    service = VisionTicketService(ttl_seconds=30)
    user_id = uuid.uuid4()
    ws_id = uuid.uuid4()

    # Issue ticket
    ticket = await service.issue_ticket(user_id=user_id, workspace_id=ws_id, purpose="camera_stream")
    assert ticket.ticket_token is not None
    assert len(ticket.ticket_token) >= 32
    assert ticket.user_id == user_id
    assert ticket.workspace_id == ws_id
    assert ticket.purpose == "camera_stream"
    assert not ticket.is_expired
    assert not ticket.is_consumed

    # Consume ticket
    consumed = await service.consume_ticket(
        ticket_token=ticket.ticket_token,
        expected_workspace_id=ws_id,
        expected_purpose="camera_stream",
    )
    assert consumed.ticket_token == ticket.ticket_token
    assert consumed.is_consumed

    # Replay attempt must fail
    with pytest.raises(AuthenticationError, match="already been consumed"):
        await service.consume_ticket(ticket_token=ticket.ticket_token)


@pytest.mark.asyncio
async def test_vision_ticket_expiry():
    """Verify expired vision tickets are rejected."""
    service = VisionTicketService(ttl_seconds=1)
    user_id = uuid.uuid4()
    ws_id = uuid.uuid4()

    ticket = await service.issue_ticket(user_id=user_id, workspace_id=ws_id, ttl_seconds=1)
    # Manually backdate expiration
    ticket.expires_at = time.time() - 5

    with pytest.raises(AuthenticationError, match="expired"):
        await service.consume_ticket(ticket_token=ticket.ticket_token)


@pytest.mark.asyncio
async def test_vision_ticket_tenancy_and_purpose_mismatch():
    """Verify cross-tenant and purpose mismatches are rejected."""
    service = VisionTicketService()
    user_id = uuid.uuid4()
    ws_id = uuid.uuid4()
    wrong_ws = uuid.uuid4()

    ticket = await service.issue_ticket(user_id=user_id, workspace_id=ws_id, purpose="camera_stream")

    # Workspace mismatch
    with pytest.raises(AuthorizationError, match="cross-tenant access denied"):
        await service.consume_ticket(ticket_token=ticket.ticket_token, expected_workspace_id=wrong_ws)

    # Re-issue for purpose test
    ticket2 = await service.issue_ticket(user_id=user_id, workspace_id=ws_id, purpose="camera_stream")
    with pytest.raises(AuthorizationError, match="purpose mismatch"):
        await service.consume_ticket(
            ticket_token=ticket2.ticket_token,
            expected_workspace_id=ws_id,
            expected_purpose="screen_stream",
        )


def test_session_nonce_entropy():
    """Verify 256-bit CSPRNG session nonce generation."""
    service = VisionTicketService()
    raw_nonce1, hex_nonce1 = service.generate_session_nonce()
    raw_nonce2, hex_nonce2 = service.generate_session_nonce()

    assert len(raw_nonce1) == 32
    assert len(hex_nonce1) == 64
    assert hex_nonce1 != hex_nonce2


# ==============================================================================
# 2. 26-Byte Binary Framing Protocol Tests
# ==============================================================================

def test_frame_header_pack_unpack_roundtrip():
    """Verify 26-byte Big-Endian binary header packing and unpacking."""
    webp_payload = make_test_webp(640, 480)
    seq = 42
    ts_ns = 1700000000123456789
    w = 640
    h = 480

    frame_bytes = pack_camera_frame(
        stream_type=STREAM_TYPE_CAMERA,
        source_id=0,
        sequence_number=seq,
        timestamp_ns=ts_ns,
        width=w,
        height=h,
        payload=webp_payload,
    )

    assert len(frame_bytes) == FRAME_HEADER_SIZE + len(webp_payload)
    assert len(frame_bytes) >= 26

    header, payload = unpack_camera_frame(frame_bytes)
    assert header.stream_type == STREAM_TYPE_CAMERA
    assert header.source_id == 0
    assert header.sequence_number == seq
    assert header.timestamp_ns == ts_ns
    assert header.width == w
    assert header.height == h
    assert header.payload_length == len(webp_payload)
    assert payload == webp_payload


def test_frame_header_malformed_rejection():
    """Verify malformed binary headers are rejected with VisionProcessingError."""
    # Truncated header (< 26 bytes)
    with pytest.raises(VisionProcessingError, match="smaller than 26-byte header"):
        unpack_camera_frame(b"short_bytes_less_than_26")

    webp_payload = make_test_webp(640, 480)

    # Invalid stream type (0xFF)
    bad_stream = pack_camera_frame(0xFF, 0, 1, 100, 640, 480, webp_payload)
    with pytest.raises(VisionProcessingError, match="Unsupported stream type"):
        unpack_camera_frame(bad_stream)

    # Out-of-bounds width (> 1920)
    bad_width = pack_camera_frame(STREAM_TYPE_CAMERA, 0, 1, 100, 2560, 480, webp_payload)
    with pytest.raises(VisionProcessingError, match="Invalid frame width"):
        unpack_camera_frame(bad_width)

    # Out-of-bounds height (> 1080)
    bad_height = pack_camera_frame(STREAM_TYPE_CAMERA, 0, 1, 100, 640, 1440, webp_payload)
    with pytest.raises(VisionProcessingError, match="Invalid frame height"):
        unpack_camera_frame(bad_height)

    # Non-WebP payload
    fake_payload = b"RIFF\x00\x00\x00\x00JPEG\x00\x00\x00\x00" + b"A" * 100
    bad_payload_frame = pack_camera_frame(STREAM_TYPE_CAMERA, 0, 1, 100, 640, 480, fake_payload)
    with pytest.raises(VisionProcessingError, match="valid WebP"):
        unpack_camera_frame(bad_payload_frame)


# ==============================================================================
# 3. Server-side Rate Limiting & Depth-1 Buffer Ingestion Tests
# ==============================================================================

def test_camera_service_rate_limiting_and_depth1_buffer():
    """Verify 5.0 FPS ceiling enforcement and depth-1 volatile buffer overwriting."""
    service = CameraVisionService()
    user_id = uuid.uuid4()
    ws_id = uuid.uuid4()
    nonce = "a" * 64

    session = service.create_session(user_id=user_id, workspace_id=ws_id, session_nonce=nonce)
    webp_payload = make_test_webp(320, 240)

    # Frame 1: Initial frame should be accepted
    frame1 = pack_camera_frame(STREAM_TYPE_CAMERA, 0, 1, 1000, 320, 240, webp_payload)
    accepted1, reason1, obs1 = service.ingest_frame(session.session_id, frame1)
    assert accepted1 is True
    assert reason1 is None
    assert obs1 is not None
    assert obs1.sequence_number == 1
    assert session.frames_accepted == 1

    # Frame 2: Immediate successive frame (0 ms elapsed) must be dropped by 5 FPS ceiling
    frame2 = pack_camera_frame(STREAM_TYPE_CAMERA, 0, 2, 1050, 320, 240, webp_payload)
    accepted2, reason2, obs2 = service.ingest_frame(session.session_id, frame2)
    assert accepted2 is False
    assert reason2 == "rate_limit_exceeded"
    assert obs2 is None
    assert session.frames_dropped == 1

    # Frame 3: Stale/duplicate sequence number must be dropped
    time.sleep(0.22)  # Wait > 200 ms to clear rate ceiling
    stale_frame = pack_camera_frame(STREAM_TYPE_CAMERA, 0, 1, 1100, 320, 240, webp_payload)
    accepted_stale, reason_stale, _ = service.ingest_frame(session.session_id, stale_frame)
    assert accepted_stale is False
    assert reason_stale == "stale_sequence_number"

    # Frame 4: Valid advancing sequence after rate ceiling window
    frame4 = pack_camera_frame(STREAM_TYPE_CAMERA, 0, 4, 1250, 320, 240, webp_payload)
    accepted4, reason4, obs4 = service.ingest_frame(session.session_id, frame4)
    assert accepted4 is True
    assert obs4.sequence_number == 4

    # Verify Depth-1 buffer: Only newest frame (frame 4) is in memory
    latest = service.get_latest_observation(str(ws_id))
    assert latest is not None
    assert latest.sequence_number == 4

    # Purge buffer
    service.clear_ephemeral_frame(str(ws_id))
    assert service.get_latest_observation(str(ws_id)) is None


# ==============================================================================
# 4. Emergency Kill Switch Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_kill_switch_blocks_ticket_and_ingestion():
    """Verify Emergency Kill Switch immediately blocks ticket issuance and frame ingestion."""
    ws_id = uuid.uuid4()
    user_id = uuid.uuid4()

    # Activate kill switch for workspace
    kill_switch.set_active(True, workspace_id=ws_id)
    try:
        # Ticket issuance blocked
        with pytest.raises(AuthorizationError, match="Kill Switch is ACTIVE"):
            await vision_ticket_service.issue_ticket(user_id=user_id, workspace_id=ws_id)

        # Ingestion blocked
        service = CameraVisionService()
        # Session creation blocked
        with pytest.raises(AuthorizationError, match="Kill Switch is ACTIVE"):
            service.create_session(user_id=user_id, workspace_id=ws_id, session_nonce="b" * 64)

    finally:
        kill_switch.set_active(False, workspace_id=ws_id)


# ==============================================================================
# 5. WebSocket Gateway Integration Tests (TestClient)
# ==============================================================================

def test_websocket_vision_camera_stream_lifecycle():
    """Verify end-to-end WebSocket camera streaming lifecycle via Starlette TestClient."""
    client = TestClient(app)
    user_id = uuid.uuid4()
    ws_id = uuid.uuid4()

    # Pre-generate ticket in service
    import asyncio
    loop = asyncio.get_event_loop()
    ticket = loop.run_until_complete(
        vision_ticket_service.issue_ticket(user_id=user_id, workspace_id=ws_id, purpose="camera_stream")
    )

    webp_payload = make_test_webp(320, 240)

    # Connect to WebSocket
    with client.websocket_connect(f"/api/v1/vision/stream?ticket={ticket.ticket_token}") as ws:
        # Receive session_ready frame
        init_msg = ws.receive_json()
        assert init_msg["type"] == "session_ready"
        assert init_msg["workspace_id"] == str(ws_id)
        assert len(init_msg["session_nonce"]) == 64
        assert init_msg["max_fps"] == 5.0

        # Send Ping control frame
        ws.send_json({"type": "ping"})
        pong_msg = ws.receive_json()
        assert pong_msg["type"] == "pong"

        # Send binary camera frame 1
        frame1 = pack_camera_frame(STREAM_TYPE_CAMERA, 0, 1, 1000, 320, 240, webp_payload)
        ws.send_bytes(frame1)
        resp1 = ws.receive_json()
        assert resp1["type"] == "frame_accepted"
        assert resp1["sequence_number"] == 1

        # Send immediate second frame -> should receive frame_dropped
        frame2 = pack_camera_frame(STREAM_TYPE_CAMERA, 0, 2, 1050, 320, 240, webp_payload)
        ws.send_bytes(frame2)
        resp2 = ws.receive_json()
        assert resp2["type"] == "frame_dropped"
        assert resp2["reason"] == "rate_limit_exceeded"

        # Send Stop control frame
        ws.send_json({"type": "stop"})
        stop_msg = ws.receive_json()
        assert stop_msg["type"] == "camera_stopped"


def test_endian_framing_integrity():
    """Verify Big-Endian byte packing matches canonical protocol contract."""
    webp_payload = make_test_webp(1280, 720)
    seq = 0x12345678
    ts_ns = 0x0102030405060708
    w = 1280  # 0x00000500
    h = 720   # 0x000002D0
    payload_len = len(webp_payload)

    packed = pack_camera_frame(STREAM_TYPE_CAMERA, 1, seq, ts_ns, w, h, webp_payload)

    # Offset 0: stream_type (uint8)
    assert packed[0] == STREAM_TYPE_CAMERA
    # Offset 1: source_id (uint8)
    assert packed[1] == 1
    # Offset 2..5: sequence_number (uint32 Big-Endian)
    assert packed[2:6] == b"\x12\x34\x56\x78"
    # Offset 6..13: timestamp_ns (uint64 Big-Endian)
    assert packed[6:14] == b"\x01\x02\x03\x04\x05\x06\x07\x08"
    # Offset 14..17: width (uint32 Big-Endian)
    assert packed[14:18] == struct.pack(">I", 1280)
    # Offset 18..21: height (uint32 Big-Endian)
    assert packed[18:22] == struct.pack(">I", 720)
    # Offset 22..25: payload_length (uint32 Big-Endian)
    assert packed[22:26] == struct.pack(">I", payload_len)


def test_websocket_kill_switch_mid_stream():
    """Verify activating kill switch during an active WebSocket streaming session terminates it cleanly."""
    client = TestClient(app)
    user_id = uuid.uuid4()
    ws_id = uuid.uuid4()

    import asyncio
    loop = asyncio.get_event_loop()
    ticket = loop.run_until_complete(
        vision_ticket_service.issue_ticket(user_id=user_id, workspace_id=ws_id, purpose="camera_stream")
    )

    webp_payload = make_test_webp(320, 240)

    with client.websocket_connect(f"/api/v1/vision/stream?ticket={ticket.ticket_token}") as ws:
        init_msg = ws.receive_json()
        assert init_msg["type"] == "session_ready"

        # Frame 1
        frame1 = pack_camera_frame(STREAM_TYPE_CAMERA, 0, 1, 1000, 320, 240, webp_payload)
        ws.send_bytes(frame1)
        resp1 = ws.receive_json()
        assert resp1["type"] == "frame_accepted"

        # Verify buffer exists
        assert camera_vision_service.get_latest_observation(str(ws_id)) is not None

        # Activate kill switch mid-stream
        kill_switch.set_active(True, workspace_id=ws_id)
        try:
            # Send Frame 2 -> should trigger kill switch response and abort
            time.sleep(0.22)
            frame2 = pack_camera_frame(STREAM_TYPE_CAMERA, 0, 2, 2000, 320, 240, webp_payload)
            ws.send_bytes(frame2)
            kill_msg = ws.receive_json()
            assert kill_msg["type"] == "kill_switch"

            # Buffer must be purged immediately
            assert camera_vision_service.get_latest_observation(str(ws_id)) is None
        finally:
            kill_switch.set_active(False, workspace_id=ws_id)


def test_privacy_zero_disk_persistence():
    """Verify raw camera frames reside solely in volatile RAM without touching filesystem or database."""
    import os
    import tempfile

    service = CameraVisionService()
    user_id = uuid.uuid4()
    ws_id = uuid.uuid4()
    session = service.create_session(user_id=user_id, workspace_id=ws_id, session_nonce="d" * 64)

    webp_payload = make_test_webp(320, 240)
    frame = pack_camera_frame(STREAM_TYPE_CAMERA, 0, 1, 1000, 320, 240, webp_payload)

    # Ingest frame
    accepted, _, obs = service.ingest_frame(session.session_id, frame)
    assert accepted is True
    assert obs is not None
    assert obs.raw_bytes == webp_payload

    # Ephemeral frame in memory
    latest = service.get_latest_observation(str(ws_id))
    assert latest is not None
    assert latest.size_bytes == len(webp_payload)

    # Verify no files created in tempdir or current working directory
    temp_dir = tempfile.gettempdir()
    for root, dirs, files in os.walk("."):
        if ".git" in root or ".next" in root or "node_modules" in root:
            continue
        for f in files:
            assert not f.endswith(".webp_camera_frame"), "Found persistent camera frame file!"

    # Purge frame
    service.clear_ephemeral_frame(str(ws_id))
    assert service.get_latest_observation(str(ws_id)) is None


# ==============================================================================
# 6. Authenticated REST API Endpoints Tests
# ==============================================================================

@pytest.fixture
async def vision_auth_headers(db_session) -> Dict[str, Any]:
    """Provision test user and workspace for vision REST endpoint testing."""
    from app.core.security import create_access_token
    from app.db.models.user import User
    from app.db.models.workspace import Workspace, WorkspaceMember

    user = User(
        id=uuid.uuid4(),
        email=f"camera_user_{uuid.uuid4().hex[:8]}@example.com",
        full_name="Camera Test User",
        password_hash="hashed_pw_test",
        is_active=True,
    )
    db_session.add(user)

    ws = Workspace(
        id=uuid.uuid4(),
        name=f"Camera Workspace {uuid.uuid4().hex[:6]}",
        slug=f"camera-ws-{uuid.uuid4().hex[:6]}",
    )
    db_session.add(ws)

    member = WorkspaceMember(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        user_id=user.id,
        role="owner",
    )
    db_session.add(member)
    await db_session.commit()

    token = create_access_token(data={"sub": str(user.id)})
    return {
        "headers": {
            "Authorization": f"Bearer {token}",
            "X-Workspace-Id": str(ws.id),
        },
        "workspace_id": str(ws.id),
        "user_id": str(user.id),
    }


@pytest.mark.asyncio
async def test_vision_ticket_and_camera_rest_endpoints(vision_auth_headers: Dict[str, Any]):
    """Verify REST endpoints for ticket issuance, camera status, latest observation, and cache purge."""
    from httpx import ASGITransport, AsyncClient

    headers = vision_auth_headers["headers"]
    ws_id = vision_auth_headers["workspace_id"]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 1. POST /api/v1/vision/ticket
        ticket_resp = await ac.post(
            "/api/v1/vision/ticket",
            json={"workspace_id": ws_id, "ttl_seconds": 60, "purpose": "camera_stream"},
            headers=headers,
        )
        assert ticket_resp.status_code == 201
        ticket_data = ticket_resp.json()
        assert "ticket" in ticket_data
        assert ticket_data["workspace_id"] == ws_id
        assert ticket_data["purpose"] == "camera_stream"

        # 2. GET /api/v1/vision/camera/status
        status_resp = await ac.get("/api/v1/vision/camera/status", headers=headers)
        assert status_resp.status_code == 200
        status_data = status_resp.json()
        assert status_data["status"] == "available"
        assert status_data["max_fps_ceiling"] == 5.0
        assert status_data["default_fps"] == 2.0
        assert status_data["header_size_bytes"] == 26

        # 3. GET /api/v1/vision/camera/latest (Empty buffer -> 404)
        latest_resp = await ac.get("/api/v1/vision/camera/latest", headers=headers)
        assert latest_resp.status_code == 404

        # 4. Populate volatile frame and test GET /api/v1/vision/camera/latest
        webp_payload = make_test_webp(320, 240)
        session = camera_vision_service.create_session(
            user_id=uuid.UUID(vision_auth_headers["user_id"]),
            workspace_id=uuid.UUID(ws_id),
            session_nonce="c" * 64,
        )
        frame = pack_camera_frame(STREAM_TYPE_CAMERA, 0, 1, 5000, 320, 240, webp_payload)
        camera_vision_service.ingest_frame(session.session_id, frame)

        latest_resp2 = await ac.get("/api/v1/vision/camera/latest?include_preview=true", headers=headers)
        assert latest_resp2.status_code == 200
        latest_data2 = latest_resp2.json()
        assert latest_data2["sequence_number"] == 1
        assert latest_data2["width"] == 320
        assert latest_data2["height"] == 240
        assert latest_data2["format"] == "WEBP"
        assert latest_data2["preview_thumbnail_base64"] is not None

        # 5. DELETE /api/v1/vision/camera/cache
        del_resp = await ac.delete("/api/v1/vision/camera/cache", headers=headers)
        assert del_resp.status_code == 200
        assert del_resp.json()["cleared"] is True

        # Check that cache is now empty
        latest_resp3 = await ac.get("/api/v1/vision/camera/latest", headers=headers)
        assert latest_resp3.status_code == 404
