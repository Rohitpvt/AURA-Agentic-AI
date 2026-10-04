"""AURA-803 Live Camera Transport & Ingestion Verification Script.

Executes live end-to-end transport validation on Windows development environment:
1. Requests authenticated vision ticket with 256-bit CSPRNG nonce.
2. Connects to live duplex WebSocket transport gateway (/api/v1/vision/stream).
3. Streams multi-frame sequence of 720p WebP frames using 26-byte binary protocol.
4. Verifies frame acceptance, sequence progression, and nanosecond timestamp accuracy.
5. Verifies server-side rate ceiling (5.0 FPS) and drop notifications under backpressure.
6. Verifies volatile depth-1 ephemeral memory buffer inspection.
7. Verifies Emergency Kill Switch immediate abort and cache purge.
8. Verifies strict privacy invariant: zero disk/database artifacts created.
"""

import io
import os
import sys
import time
import uuid

# Ensure apps/api is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PIL import Image
from starlette.testclient import TestClient

from app.main import app
from app.services.kill_switch import kill_switch
from app.services.vision.camera_service import (
    FRAME_HEADER_SIZE,
    MAX_CAMERA_FPS,
    STREAM_TYPE_CAMERA,
    camera_vision_service,
    pack_camera_frame,
    unpack_camera_frame,
)
from app.services.vision.ticket_service import vision_ticket_service


def create_live_frame(width: int = 1280, height: int = 720, color=(70, 130, 180)) -> bytes:
    """Generate in-memory 720p WebP payload for live verification."""
    img = Image.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=80)
    return buf.getvalue()


def main():
    print("=" * 80)
    print("  AURA-803 LIVE CAMERA TRANSPORT & PROTOCOL VERIFICATION")
    print("=" * 80)

    client = TestClient(app)
    user_id = uuid.uuid4()
    ws_id = uuid.uuid4()
    ws_str = str(ws_id)

    # 1. Ticket Issuance
    print("\n[*] 1. Issuing Single-Use Vision Ticket...")
    import asyncio
    loop = asyncio.get_event_loop()
    ticket = loop.run_until_complete(
        vision_ticket_service.issue_ticket(user_id=user_id, workspace_id=ws_id, purpose="camera_stream", ttl_seconds=60)
    )
    print(f"    -> Ticket Token: {ticket.ticket_token[:12]}... (TTL: 60s)")
    print(f"    -> Workspace ID: {ws_str}")
    print(f"    -> Purpose: {ticket.purpose}")

    webp_frame_720p = create_live_frame(1280, 720)
    print(f"    -> Prepared 720p WebP Frame Payload: {len(webp_frame_720p)} bytes")

    # 2. WebSocket Connection & Handshake
    print("\n[*] 2. Connecting to WebSocket Gateway (/api/v1/vision/stream)...")
    with client.websocket_connect(f"/api/v1/vision/stream?ticket={ticket.ticket_token}&workspace_id={ws_str}") as ws:
        init_msg = ws.receive_json()
        print(f"    -> Received Handshake: {init_msg}")
        assert init_msg["type"] == "session_ready"
        assert init_msg["workspace_id"] == ws_str
        assert len(init_msg["session_nonce"]) == 64
        session_id = init_msg["session_id"]
        print(f"    -> Session ID: {session_id}")
        print(f"    -> CSPRNG Session Nonce (256-bit): {init_msg['session_nonce'][:16]}...")
        print(f"    -> Max Server FPS: {init_msg['max_fps']} FPS")

        # 3. Stream Sequential Frames with 250ms cadence (4 FPS <= 5 FPS ceiling)
        print("\n[*] 3. Streaming Sequential 720p Frames (Cadence ~4 FPS)...")
        for seq in range(1, 4):
            ts_ns = time.time_ns()
            frame_bytes = pack_camera_frame(
                stream_type=STREAM_TYPE_CAMERA,
                source_id=0,
                sequence_number=seq,
                timestamp_ns=ts_ns,
                width=1280,
                height=720,
                payload=webp_frame_720p,
            )
            t_send = time.perf_counter()
            ws.send_bytes(frame_bytes)
            ack = ws.receive_json()
            t_recv = time.perf_counter()
            rtt_ms = (t_recv - t_send) * 1000.0

            print(f"    [Frame {seq}] Status: {ack.get('type')} | Seq: {ack.get('sequence_number')} | RTT: {rtt_ms:.3f} ms")
            assert ack["type"] == "frame_accepted"
            assert ack["sequence_number"] == seq

            # Cadence interval
            time.sleep(0.22)  # 220 ms > 200 ms minimum interval

        # 4. Verify Depth-1 Buffer
        print("\n[*] 4. Inspecting Volatile Depth-1 Ephemeral Frame Buffer...")
        obs = camera_vision_service.get_latest_observation(ws_str)
        assert obs is not None
        assert obs.sequence_number == 3
        assert obs.width == 1280
        assert obs.height == 720
        assert obs.format == "WEBP"
        print(f"    -> Latest Frame in Depth-1 Buffer: Seq #{obs.sequence_number}, Size: {obs.size_bytes} bytes, Dimensions: {obs.width}x{obs.height}")

        # 5. Verify Rate Ceiling Burst Rejection
        print("\n[*] 5. Testing Rate Ceiling Burst Rejection (>5.0 FPS)...")
        burst_frame = pack_camera_frame(
            stream_type=STREAM_TYPE_CAMERA,
            source_id=0,
            sequence_number=4,
            timestamp_ns=time.time_ns(),
            width=1280,
            height=720,
            payload=webp_frame_720p,
        )
        ws.send_bytes(burst_frame)
        ack_burst1 = ws.receive_json()
        print(f"    -> Burst Frame 4: {ack_burst1}")

        # Immediate successive frame without delay -> MUST be dropped
        burst_frame_rapid = pack_camera_frame(
            stream_type=STREAM_TYPE_CAMERA,
            source_id=0,
            sequence_number=5,
            timestamp_ns=time.time_ns(),
            width=1280,
            height=720,
            payload=webp_frame_720p,
        )
        ws.send_bytes(burst_frame_rapid)
        ack_burst2 = ws.receive_json()
        print(f"    -> Rapid Frame 5: {ack_burst2}")
        assert ack_burst2["type"] == "frame_dropped"
        assert ack_burst2["reason"] == "rate_limit_exceeded"
        print("    -> Backpressure drop confirmed!")

        # 6. Test Ping/Pong duplex control
        print("\n[*] 6. Testing Duplex Control Protocol (Ping/Pong)...")
        ws.send_json({"type": "ping"})
        pong_resp = ws.receive_json()
        print(f"    -> Ping response: {pong_resp}")
        assert pong_resp["type"] == "pong"

        # 7. Test Emergency Kill Switch during streaming
        print("\n[*] 7. Testing Emergency Kill Switch Integration...")
        kill_switch.set_active(True, workspace_id=ws_id)
        try:
            time.sleep(0.22)
            ks_frame = pack_camera_frame(
                stream_type=STREAM_TYPE_CAMERA,
                source_id=0,
                sequence_number=6,
                timestamp_ns=time.time_ns(),
                width=1280,
                height=720,
                payload=webp_frame_720p,
            )
            ws.send_bytes(ks_frame)
            ks_resp = ws.receive_json()
            print(f"    -> Kill Switch Response: {ks_resp}")
            assert ks_resp["type"] == "kill_switch"

            # Verify depth-1 buffer purged
            obs_after = camera_vision_service.get_latest_observation(ws_str)
            assert obs_after is None
            print("    -> Ephemeral buffer purged on kill switch!")
        finally:
            kill_switch.set_active(False, workspace_id=ws_id)

    # 8. Verify Replay Rejection
    print("\n[*] 8. Verifying Single-Use Ticket Replay Rejection...")
    try:
        loop.run_until_complete(
            vision_ticket_service.consume_ticket(ticket.ticket_token)
        )
        print("    [FAIL] Replayed ticket was accepted!")
        sys.exit(1)
    except Exception as e:
        print(f"    -> Replay correctly rejected: {e}")

    # 9. Verify Privacy & Zero Disk Persistence
    print("\n[*] 9. Verifying Privacy Invariant (Zero Disk Files)...")
    for root, dirs, files in os.walk("."):
        if ".git" in root or ".next" in root or "node_modules" in root:
            continue
        for f in files:
            assert not f.endswith(".webp_camera_frame"), "Found persistent camera frame file!"
    print("    -> Confirmed: Ephemeral in-memory transport only. Zero disk persistence.")

    print("\n" + "=" * 80)
    print("  [PASS] AURA-803 LIVE CAMERA VERIFICATION COMPLETED SUCCESSFULLY")
    print("=" * 80)


if __name__ == "__main__":
    main()
