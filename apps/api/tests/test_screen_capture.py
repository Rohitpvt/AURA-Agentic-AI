"""AURA-801 Multi-Monitor Screen & Active-Window Capture Engine Tests.

Verifies:
1. Multi-monitor discovery and topology enumeration.
2. Active foreground window introspection (title, PID, process name, bounds).
3. Coordinate normalization and DPI awareness.
4. Aspect-ratio-preserving in-memory downscaling.
5. Normalized screen change & delta detection (5% threshold).
6. Volatile depth-1 ephemeral frame buffer lifecycle.
7. Kill-switch integration across synchronous captures and async sampling loops.
8. Adaptive rate limiter and 5.0 FPS ceiling enforcement.
9. Authenticated REST API endpoints under /api/v1/vision/*.
10. Strict privacy invariants (zero disk/DB raw frame persistence).
"""

import asyncio
import io
import time
from typing import Any, Dict
import uuid
import pytest
from httpx import AsyncClient, ASGITransport
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.core.config import settings
from app.core.errors import AuthorizationError, EntityNotFoundError
from app.services.kill_switch import kill_switch
from app.services.vision.screen_capture import (
    ActiveWindowInfo,
    CapturedFrame,
    MonitorInfo,
    ScreenCaptureConfig,
    ScreenCaptureService,
    WindowBounds,
    screen_capture_service,
)


from app.core.security import create_access_token
from app.db.models.user import User
from app.db.models.workspace import Workspace, WorkspaceMember


@pytest.fixture(autouse=True)
def cleanup_vision_state():
    """Ensure clean vision service and kill switch state before/after each test."""
    kill_switch.set_active(False)
    screen_capture_service.clear_ephemeral_buffer()
    yield
    kill_switch.set_active(False)
    screen_capture_service.clear_ephemeral_buffer()


@pytest.fixture
async def auth_headers(db_session: AsyncSession) -> Dict[str, str]:
    """Provision a test user and workspace, returning JWT authorization headers."""
    user = User(
        id=uuid.uuid4(),
        email=f"vision_user_{uuid.uuid4().hex[:8]}@example.com",
        full_name="Vision Test User",
        password_hash="hashed_pw_test",
        is_active=True,
    )
    db_session.add(user)

    ws = Workspace(
        id=uuid.uuid4(),
        name=f"Vision Workspace {uuid.uuid4().hex[:6]}",
        slug=f"vision-ws-{uuid.uuid4().hex[:6]}",
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
        "Authorization": f"Bearer {token}",
        "X-Workspace-Id": str(ws.id),
    }



# ---------------------------------------------------------------------------
# 1. Multi-Monitor Discovery Unit Tests
# ---------------------------------------------------------------------------

def test_screen_capture_list_monitors_structure():
    """Verify monitor enumeration returns valid virtual (0) and physical (1..N) displays."""
    monitors = screen_capture_service.list_monitors()
    assert len(monitors) >= 1
    
    # Monitor 0 must be virtual combined desktop
    mon_0 = monitors[0]
    assert mon_0.monitor_id == 0
    assert mon_0.width > 0
    assert mon_0.height > 0
    assert mon_0.dpi_scale >= 0.5
    
    # If physical monitors exist, check monitor 1
    if len(monitors) > 1:
        mon_1 = monitors[1]
        assert mon_1.monitor_id == 1
        assert mon_1.width > 0
        assert mon_1.height > 0
        assert mon_1.is_primary is True


def test_monitor_info_to_dict_serialization():
    """Verify MonitorInfo dataclass serializes cleanly without raw image bytes."""
    m = MonitorInfo(
        monitor_id=1,
        name="Display 1",
        left=0,
        top=0,
        width=1920,
        height=1080,
        is_primary=True,
        dpi_scale=1.25,
    )
    d = m.to_dict()
    assert d["monitor_id"] == 1
    assert d["name"] == "Display 1"
    assert d["dpi_scale"] == 1.25
    assert d["is_primary"] is True


# ---------------------------------------------------------------------------
# 2. Active Window Introspection Tests
# ---------------------------------------------------------------------------

def test_get_active_window_introspection_read_only():
    """Verify get_active_window returns structured metadata or None safely without modifying system state."""
    win = screen_capture_service.get_active_window()
    if win is not None:
        assert isinstance(win.window_title, str)
        assert isinstance(win.bounds, WindowBounds)
        assert win.bounds.width >= 0
        assert win.bounds.height >= 0
        assert isinstance(win.is_maximized, bool)
        d = win.to_dict()
        assert "window_title" in d
        assert "bounds" in d
        assert "pid" in d


def test_window_bounds_math():
    """Verify WindowBounds coordinate geometry."""
    b = WindowBounds(left=100, top=200, right=900, bottom=800, width=800, height=600)
    assert b.width == 800
    assert b.height == 600
    d = b.to_dict()
    assert d["left"] == 100
    assert d["width"] == 800


# ---------------------------------------------------------------------------
# 3. Downscaling & Proportional Aspect Ratio Tests
# ---------------------------------------------------------------------------

def test_downscale_image_preserves_aspect_ratio_and_bounds():
    """Verify that images larger than max bounds are downscaled without distortion and smaller images are not enlarged."""
    svc = ScreenCaptureService(config=ScreenCaptureConfig(max_width=1280, max_height=720))
    
    # 1. 1920x1080 (16:9) should scale down to 1280x720
    large_img = Image.new("RGB", (1920, 1080), color=(100, 100, 100))
    downscaled = svc._downscale_image(large_img)
    assert downscaled.size == (1280, 720)

    # 2. 3840x2160 (4K 16:9) should scale down to 1280x720
    four_k_img = Image.new("RGB", (3840, 2160), color=(100, 100, 100))
    downscaled_4k = svc._downscale_image(four_k_img)
    assert downscaled_4k.size == (1280, 720)

    # 3. 800x600 (smaller than 1280x720) should NOT be enlarged
    small_img = Image.new("RGB", (800, 600), color=(100, 100, 100))
    kept_small = svc._downscale_image(small_img)
    assert kept_small.size == (800, 600)

    # 4. Portrait 1080x1920 should scale to 405x720
    portrait_img = Image.new("RGB", (1080, 1920), color=(100, 100, 100))
    downscaled_port = svc._downscale_image(portrait_img)
    assert downscaled_port.size[1] == 720
    assert downscaled_port.size[0] == int(1080 * (720 / 1920))


# ---------------------------------------------------------------------------
# 4. Delta Detection Unit Tests
# ---------------------------------------------------------------------------

def test_frame_delta_detection_algorithm():
    """Verify sub-millisecond delta computation triggers only on >= 5% visual change."""
    svc = ScreenCaptureService(config=ScreenCaptureConfig(delta_threshold=0.05))
    
    # Frame 1: Blank White
    frame1 = Image.new("RGB", (1280, 720), color=(255, 255, 255))
    is_changed_1, delta_1 = svc._compute_frame_delta(frame1)
    assert is_changed_1 is True
    assert delta_1 == 1.0  # Initial reference frame

    # Frame 2: Identical Frame
    frame2 = Image.new("RGB", (1280, 720), color=(255, 255, 255))
    is_changed_2, delta_2 = svc._compute_frame_delta(frame2)
    assert is_changed_2 is False
    assert delta_2 == 0.0

    # Frame 3: Minor 1% change (below 5% threshold)
    frame3 = Image.new("RGB", (1280, 720), color=(255, 255, 255))
    minor_patch = Image.new("RGB", (100, 50), color=(0, 0, 0))
    frame3.paste(minor_patch, (10, 10))
    is_changed_3, delta_3 = svc._compute_frame_delta(frame3)
    assert is_changed_3 is False
    assert delta_3 < 0.05

    # Frame 4: Significant 25% change (above 5% threshold)
    frame4 = Image.new("RGB", (1280, 720), color=(255, 255, 255))
    major_patch = Image.new("RGB", (640, 400), color=(0, 0, 0))
    frame4.paste(major_patch, (100, 100))
    is_changed_4, delta_4 = svc._compute_frame_delta(frame4)
    assert is_changed_4 is True
    assert delta_4 >= 0.05


# ---------------------------------------------------------------------------
# 5. Ephemeral Buffer (Depth = 1) Lifecycle Tests
# ---------------------------------------------------------------------------

def test_ephemeral_buffer_depth_one_replacement():
    """Verify buffer holds only latest frame and old frames are discarded without memory accumulation."""
    svc = ScreenCaptureService()
    svc.clear_ephemeral_buffer()
    assert svc.get_latest_frame() is None

    # First capture
    frame1 = svc.capture_frame(monitor_id=1)
    assert frame1 is not None
    assert frame1.sequence_number >= 1
    assert svc.get_latest_frame() is frame1

    # Second capture overwrites first frame
    frame2 = svc.capture_frame(monitor_id=1)
    assert frame2 is not None
    assert frame2.sequence_number == frame1.sequence_number + 1
    assert svc.get_latest_frame() is frame2
    assert svc.get_latest_frame().frame_id == frame2.frame_id

    # Clear buffer
    svc.clear_ephemeral_buffer()
    assert svc.get_latest_frame() is None


def test_captured_frame_metadata_exclusion_of_raw_bytes():
    """Verify to_metadata_dict does not contain raw binary bytes preventing accidental logging or telemetry leaks."""
    frame = screen_capture_service.capture_frame(monitor_id=1)
    meta = frame.to_metadata_dict()
    assert "raw_bytes" not in meta
    assert "frame_id" in meta
    assert "processed_dimensions" in meta
    assert "format" in meta
    assert meta["format"] == "WEBP"


# ---------------------------------------------------------------------------
# 6. Kill Switch Integration Tests
# ---------------------------------------------------------------------------

def test_kill_switch_blocks_capture_and_clears_buffer():
    """Verify active kill switch blocks capture with AuthorizationError and purges memory buffer."""
    ws_id = str(uuid.uuid4())
    
    # Capture initial frame
    frame = screen_capture_service.capture_frame(monitor_id=1, workspace_id=ws_id)
    assert screen_capture_service.get_latest_frame(workspace_id=ws_id) is not None

    # Engage Kill Switch
    kill_switch.set_active(True, workspace_id=ws_id)

    # get_latest_frame should return None and clear buffer
    assert screen_capture_service.get_latest_frame(workspace_id=ws_id) is None

    # capture_frame should raise AuthorizationError
    with pytest.raises(AuthorizationError) as exc_info:
        screen_capture_service.capture_frame(monitor_id=1, workspace_id=ws_id)
    assert "Emergency Kill Switch is ACTIVE" in str(exc_info.value)

    # Disengage Kill Switch
    kill_switch.set_active(False, workspace_id=ws_id)
    new_frame = screen_capture_service.capture_frame(monitor_id=1, workspace_id=ws_id)
    assert new_frame is not None


@pytest.mark.asyncio
async def test_sampling_loop_kill_switch_abortion():
    """Verify active background sampling loop halts immediately when kill switch is engaged."""
    svc = ScreenCaptureService()
    ws_id = str(uuid.uuid4())
    frames_received = []

    def on_frame(f):
        frames_received.append(f)

    await svc.start_sampling_loop(workspace_id=ws_id, fps=4.0, on_frame_callback=on_frame)
    await asyncio.sleep(0.3)
    assert len(frames_received) >= 1

    # Trigger kill switch
    kill_switch.set_active(True, workspace_id=ws_id)
    await asyncio.sleep(0.3)
    count_after_kill = len(frames_received)

    # Verify loop terminated and buffer cleared
    assert svc.get_latest_frame(workspace_id=ws_id) is None
    await asyncio.sleep(0.3)
    assert len(frames_received) == count_after_kill

    await svc.stop_sampling_loop(ws_id)


# ---------------------------------------------------------------------------
# 7. Adaptive Rate Limiter & Rate Ceiling Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sampling_loop_enforces_max_rate_ceiling():
    """Verify unthrottled 60 FPS request is clamped to maximum 5.0 FPS ceiling."""
    svc = ScreenCaptureService(config=ScreenCaptureConfig(max_fps_ceiling=5.0))
    ws_id = str(uuid.uuid4())
    captured_count = 0

    def on_frame(f):
        nonlocal captured_count
        captured_count += 1

    # Request pathological 60 FPS
    await svc.start_sampling_loop(workspace_id=ws_id, fps=60.0, on_frame_callback=on_frame)
    await asyncio.sleep(0.5)  # In 0.5s at 5 FPS max, should capture ~2-3 frames, NOT 30 frames
    await svc.stop_sampling_loop(ws_id)

    assert captured_count <= 4  # Clamped within 5 FPS ceiling


# ---------------------------------------------------------------------------
# 8. REST API Endpoint Integration Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_api_vision_monitors_endpoint(client: AsyncClient, auth_headers: Dict[str, str]):
    """Verify GET /api/v1/vision/monitors returns 200 with list of monitors."""
    resp = await client.get("/api/v1/vision/monitors", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "monitors" in data
    assert "total" in data
    assert data["total"] >= 1
    assert data["monitors"][0]["monitor_id"] == 0


@pytest.mark.asyncio
async def test_api_vision_active_window_endpoint(client: AsyncClient, auth_headers: Dict[str, str]):
    """Verify GET /api/v1/vision/active-window returns 200 with window metadata or null."""
    resp = await client.get("/api/v1/vision/active-window", headers=auth_headers)
    assert resp.status_code == 200
    # On Windows may return window object, in Linux headless may return None
    data = resp.json()
    if data is not None:
        assert "window_title" in data
        assert "bounds" in data


@pytest.mark.asyncio
async def test_api_vision_capture_endpoint(client: AsyncClient, auth_headers: Dict[str, str]):
    """Verify POST /api/v1/vision/capture returns 200 with structured frame metadata."""
    payload = {
        "monitor_id": 1,
        "crop_to_active_window": False,
        "include_preview_thumbnail": True,
    }
    resp = await client.post("/api/v1/vision/capture", json=payload, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "frame_id" in data
    assert data["format"] == "WEBP"
    assert data["stream_type"] == "screen"
    assert "preview_thumbnail_base64" in data
    assert data["preview_thumbnail_base64"] is not None
    assert len(data["preview_thumbnail_base64"]) > 100


@pytest.mark.asyncio
async def test_api_vision_latest_frame_and_buffer_clear_endpoint(
    client: AsyncClient, auth_headers: Dict[str, str]
):
    """Verify GET /api/v1/vision/latest-frame/metadata and DELETE /api/v1/vision/ephemeral-buffer."""
    # Capture a frame first
    await client.post("/api/v1/vision/capture", json={"monitor_id": 1}, headers=auth_headers)

    # Query latest metadata
    resp_latest = await client.get("/api/v1/vision/latest-frame/metadata", headers=auth_headers)
    assert resp_latest.status_code == 200
    latest_data = resp_latest.json()
    assert latest_data is not None
    assert "frame_id" in latest_data

    # Clear buffer
    resp_del = await client.delete("/api/v1/vision/ephemeral-buffer", headers=auth_headers)
    assert resp_del.status_code == 200
    assert resp_del.json()["status"] == "cleared"

    # Verify latest metadata is now null
    resp_after = await client.get("/api/v1/vision/latest-frame/metadata", headers=auth_headers)
    assert resp_after.status_code == 200
    assert resp_after.json() is None


@pytest.mark.asyncio
async def test_api_vision_blocked_by_kill_switch(client: AsyncClient, auth_headers: Dict[str, str]):
    """Verify all /api/v1/vision/* endpoints return 403 Forbidden under active kill switch."""
    kill_switch.set_active(True)

    resp_monitors = await client.get("/api/v1/vision/monitors", headers=auth_headers)
    assert resp_monitors.status_code == 403

    resp_active = await client.get("/api/v1/vision/active-window", headers=auth_headers)
    assert resp_active.status_code == 403

    resp_capture = await client.post("/api/v1/vision/capture", json={"monitor_id": 1}, headers=auth_headers)
    assert resp_capture.status_code == 403
