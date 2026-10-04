"""AURA-801 Multi-Monitor Screen & Active-Window Capture Engine.

Provides:
1. Native multi-monitor discovery and geometry enumeration via mss.
2. Active foreground window introspection (title, PID, process name, bounding rect) via Win32 API / ctypes.
3. Windows Per-Monitor v2 DPI-aware coordinate normalization.
4. Aspect-ratio-preserving in-memory downscaling (preferred max 1280x720, absolute max 1920x1080).
5. Sub-millisecond screen delta detection (ImageChops normalized thumbnail diff, >= 5% threshold).
6. Volatile depth-1 ephemeral frame buffer with zero disk/database persistence.
7. Adaptive capture rate limiter (0.5–1.0 FPS idle, 2.0–5.0 FPS active; 60 FPS unthrottled strictly prohibited).
8. Authoritative global & workspace-scoped Emergency Kill Switch integration.
9. Strict read-only sensory capability boundary (zero OS automation, zero clicks, zero keypresses).
"""

import asyncio
import ctypes
import ctypes.wintypes
import io
import math
import os
import platform
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
import uuid
from dataclasses import asdict, dataclass, field

import mss
from PIL import Image, ImageChops
import psutil

from app.core.config import settings
from app.core.errors import (
    AuthorizationError,
    EntityNotFoundError,
    ValidationError,
)
from app.core.logging import logger


# ---------------------------------------------------------------------------
# Data Models & Schemas
# ---------------------------------------------------------------------------

@dataclass
class WindowBounds:
    """Bounding coordinates of a window on the desktop."""
    left: int
    top: int
    right: int
    bottom: int
    width: int
    height: int

    def to_dict(self) -> Dict[str, int]:
        return {
            "left": self.left,
            "top": self.top,
            "right": self.right,
            "bottom": self.bottom,
            "width": self.width,
            "height": self.height,
        }


@dataclass
class ActiveWindowInfo:
    """Metadata describing the currently active foreground window."""
    window_title: str
    process_name: Optional[str]
    pid: Optional[int]
    bounds: WindowBounds
    is_maximized: bool = False
    monitor_id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "window_title": self.window_title,
            "process_name": self.process_name,
            "pid": self.pid,
            "bounds": self.bounds.to_dict(),
            "is_maximized": self.is_maximized,
            "monitor_id": self.monitor_id,
        }


@dataclass
class MonitorInfo:
    """Metadata describing a physical or virtual display monitor."""
    monitor_id: int
    name: str
    left: int
    top: int
    width: int
    height: int
    is_primary: bool = False
    dpi_scale: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "monitor_id": self.monitor_id,
            "name": self.name,
            "left": self.left,
            "top": self.top,
            "width": self.width,
            "height": self.height,
            "is_primary": self.is_primary,
            "dpi_scale": self.dpi_scale,
        }


@dataclass
class CapturedFrame:
    """Ephemeral screen or window frame captured in volatile memory."""
    frame_id: str
    stream_type: str  # "screen" | "active_window"
    monitor_id: int
    original_dimensions: Tuple[int, int]
    processed_dimensions: Tuple[int, int]
    format: str  # "WEBP"
    size_bytes: int
    timestamp_ns: int
    sequence_number: int
    is_changed: bool
    delta_ratio: float
    window_info: Optional[ActiveWindowInfo] = None
    # Ephemeral raw image bytes held in memory ONLY (never logged or serialized to JSON)
    raw_bytes: bytes = field(default=b"", repr=False)

    def to_metadata_dict(self) -> Dict[str, Any]:
        """Return safe metadata dictionary without raw image pixel bytes."""
        return {
            "frame_id": self.frame_id,
            "stream_type": self.stream_type,
            "monitor_id": self.monitor_id,
            "original_dimensions": list(self.original_dimensions),
            "processed_dimensions": list(self.processed_dimensions),
            "format": self.format,
            "size_bytes": self.size_bytes,
            "timestamp_ns": self.timestamp_ns,
            "sequence_number": self.sequence_number,
            "is_changed": self.is_changed,
            "delta_ratio": round(self.delta_ratio, 4),
            "window_info": self.window_info.to_dict() if self.window_info else None,
        }


@dataclass
class ScreenCaptureConfig:
    """Configuration constraints and limits for ScreenCaptureService."""
    max_width: int = 1280
    max_height: int = 720
    abs_max_width: int = 1920
    abs_max_height: int = 1080
    webp_quality: int = 80
    webp_method: int = 0          # 0 = Fast real-time encoding, 4 = High compression
    delta_threshold: float = 0.05  # 5% visual change trigger
    idle_fps: float = 1.0          # 0.5 - 1.0 FPS
    active_fps: float = 3.0        # 2.0 - 5.0 FPS
    max_fps_ceiling: float = 5.0   # Hard maximum
    thumbnail_size: Tuple[int, int] = (64, 36)
    depth: int = 1                 # Single-frame ephemeral buffer



# ---------------------------------------------------------------------------
# Core ScreenCaptureService Implementation
# ---------------------------------------------------------------------------

class ScreenCaptureService:
    """AURA Multi-Monitor Screen & Active-Window Capture Capability Service."""

    def __init__(self, config: Optional[ScreenCaptureConfig] = None):
        self.config = config or ScreenCaptureConfig()
        self._sequence_counter: int = 0
        self._lock = asyncio.Lock()
        self._ephemeral_frame: Optional[CapturedFrame] = None
        self._reference_thumbnail: Optional[Image.Image] = None
        self._sampling_tasks: Dict[str, asyncio.Task] = {}
        self._is_windows: bool = platform.system() == "Windows"
        
        # Initialize Windows Per-Monitor DPI awareness
        self._init_dpi_awareness()

    def _is_kill_switch_active(self, workspace_id: Optional[str] = None) -> bool:
        """Helper to evaluate kill switch status dynamically avoiding circular imports."""
        try:
            from app.services.kill_switch import kill_switch
            return kill_switch.is_active(workspace_id=workspace_id)
        except Exception:
            return False

    def _init_dpi_awareness(self) -> None:
        """Configure Windows Per-Monitor v2 DPI awareness safely."""
        if not self._is_windows:
            return
        try:
            user32 = ctypes.windll.user32
            if hasattr(user32, "SetProcessDpiAwarenessContext"):
                user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
                logger.debug("ScreenCaptureService: SetProcessDpiAwarenessContext(V2) configured.")
                return
        except Exception as e:
            logger.debug(f"ScreenCaptureService: SetProcessDpiAwarenessContext notice: {e}")

        try:
            shcore = ctypes.windll.shcore
            if hasattr(shcore, "SetProcessDpiAwareness"):
                shcore.SetProcessDpiAwareness(2)
                logger.debug("ScreenCaptureService: SetProcessDpiAwareness(2) configured.")
        except Exception as e:
            logger.debug(f"ScreenCaptureService: SetProcessDpiAwareness fallback notice: {e}")

    def _attach_thread_desktop(self) -> None:
        """Ensure the current calling thread is attached to the interactive input desktop."""
        if not self._is_windows:
            return
        try:
            user32 = ctypes.windll.user32
            hdesk = user32.OpenInputDesktop(0, False, 0x01FF)
            if hdesk:
                user32.SetThreadDesktop(hdesk)
        except Exception as e:
            logger.debug(f"ScreenCaptureService: Attach desktop notice: {e}")

    def get_system_dpi_scale(self) -> float:
        """Get the current system DPI scaling factor (e.g. 1.0, 1.25, 1.5)."""
        if not self._is_windows:
            return 1.0
        try:
            self._attach_thread_desktop()
            user32 = ctypes.windll.user32
            if hasattr(user32, "GetDpiForSystem"):
                dpi = user32.GetDpiForSystem()
                return round(dpi / 96.0, 2)
            
            hdc = user32.GetDC(0)
            if hdc:
                gdi32 = ctypes.windll.gdi32
                LOGPIXELSX = 88
                dpi = gdi32.GetDeviceCaps(hdc, LOGPIXELSX)
                user32.ReleaseDC(0, hdc)
                return round(dpi / 96.0, 2)
        except Exception:
            pass
        return 1.0

    def list_monitors(self) -> List[MonitorInfo]:
        """Discover all connected physical and virtual monitors with coordinates and DPI scaling."""
        self._attach_thread_desktop()
        monitors: List[MonitorInfo] = []
        dpi_scale = self.get_system_dpi_scale()

        try:
            with mss.MSS() as sct:
                raw_monitors = sct.monitors
                for idx, m in enumerate(raw_monitors):
                    name = "Virtual Combined Desktop" if idx == 0 else f"Display {idx}"
                    if idx > 0 and m.get("name"):
                        name = m["name"]

                    is_primary = False
                    if idx == 1:
                        is_primary = True
                    elif m.get("is_primary"):
                        is_primary = True
                    elif idx > 0 and m.get("left") == 0 and m.get("top") == 0:
                        is_primary = True

                    monitors.append(
                        MonitorInfo(
                            monitor_id=idx,
                            name=name,
                            left=m.get("left", 0),
                            top=m.get("top", 0),
                            width=m.get("width", 1920),
                            height=m.get("height", 1080),
                            is_primary=is_primary,
                            dpi_scale=dpi_scale,
                        )
                    )
        except Exception as e:
            logger.warning(f"ScreenCaptureService: Error enumerating monitors via mss: {e}")
            monitors.append(
                MonitorInfo(
                    monitor_id=0,
                    name="Virtual Combined Desktop (Fallback)",
                    left=0,
                    top=0,
                    width=1920,
                    height=1080,
                    is_primary=False,
                    dpi_scale=1.0,
                )
            )
            monitors.append(
                MonitorInfo(
                    monitor_id=1,
                    name="Primary Display (Fallback)",
                    left=0,
                    top=0,
                    width=1920,
                    height=1080,
                    is_primary=True,
                    dpi_scale=1.0,
                )
            )

        return monitors

    def get_active_window(self) -> Optional[ActiveWindowInfo]:
        """Inspect the active foreground window and retrieve bounds, title, PID, and process name.
        
        Strictly read-only; does NOT manipulate, focus, or send input to windows.
        """
        if not self._is_windows:
            return None

        self._attach_thread_desktop()
        try:
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            if not hwnd or hwnd == 0:
                return None

            # Get Window Title
            length = user32.GetWindowTextLengthW(hwnd)
            title = ""
            if length > 0:
                buff = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buff, length + 1)
                title = buff.value.strip()

            if not title:
                title = "Untitled Window"

            # Get Window Bounding Rectangle
            rect = ctypes.wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            
            width = max(0, rect.right - rect.left)
            height = max(0, rect.bottom - rect.top)
            
            bounds = WindowBounds(
                left=rect.left,
                top=rect.top,
                right=rect.right,
                bottom=rect.bottom,
                width=width,
                height=height,
            )

            # Check if maximized (IsZoomed)
            is_maximized = bool(user32.IsZoomed(hwnd))

            # Get PID and Process Name
            pid_val = ctypes.wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_val))
            pid = pid_val.value if pid_val.value > 0 else None
            
            process_name: Optional[str] = None
            if pid:
                try:
                    proc = psutil.Process(pid)
                    process_name = proc.name()
                except Exception:
                    process_name = None

            # Determine which monitor contains this window
            monitor_id: Optional[int] = None
            center_x = (rect.left + rect.right) // 2
            center_y = (rect.top + rect.bottom) // 2
            
            for m in self.list_monitors():
                if m.monitor_id == 0:
                    continue
                if (m.left <= center_x < m.left + m.width) and (m.top <= center_y < m.top + m.height):
                    monitor_id = m.monitor_id
                    break

            return ActiveWindowInfo(
                window_title=title,
                process_name=process_name,
                pid=pid,
                bounds=bounds,
                is_maximized=is_maximized,
                monitor_id=monitor_id,
            )
        except Exception as e:
            logger.debug(f"ScreenCaptureService: Error querying active window: {e}")
            return None

    def _downscale_image(self, img: Image.Image) -> Image.Image:
        """Proportionally downscale image to fit within configured max bounds without enlarging."""
        orig_w, orig_h = img.size
        max_w = min(self.config.max_width, self.config.abs_max_width)
        max_h = min(self.config.max_height, self.config.abs_max_height)

        if orig_w <= max_w and orig_h <= max_h:
            return img

        ratio = min(max_w / orig_w, max_h / orig_h)
        new_w = max(1, int(orig_w * ratio))
        new_h = max(1, int(orig_h * ratio))

        return img.resize((new_w, new_h), Image.Resampling.BILINEAR)

    def _compute_frame_delta(self, img: Image.Image) -> Tuple[bool, float]:
        """Compute normalized pixel delta against previous reference frame thumbnail."""
        thumb_w, thumb_h = self.config.thumbnail_size
        curr_thumb = img.resize((thumb_w, thumb_h)).convert("L")

        if self._reference_thumbnail is None:
            self._reference_thumbnail = curr_thumb
            return True, 1.0

        try:
            diff = ImageChops.difference(self._reference_thumbnail, curr_thumb)
            hist = diff.histogram()
            total_diff = sum(i * count for i, count in enumerate(hist))
            norm_delta = total_diff / (thumb_w * thumb_h * 255.0)

            is_changed = norm_delta >= self.config.delta_threshold
            if is_changed:
                self._reference_thumbnail = curr_thumb

            return is_changed, norm_delta
        except Exception as e:
            logger.debug(f"ScreenCaptureService: Delta computation notice: {e}")
            self._reference_thumbnail = curr_thumb
            return True, 1.0

    def capture_frame(
        self,
        monitor_id: int = 1,
        crop_to_active_window: bool = False,
        custom_roi: Optional[Tuple[int, int, int, int]] = None,
        workspace_id: Optional[str] = None,
    ) -> CapturedFrame:
        """Capture an on-demand screen or active-window frame in ephemeral memory."""
        # 1. Authoritative Kill-Switch Validation
        if self._is_kill_switch_active(workspace_id=workspace_id):
            self.clear_ephemeral_buffer()
            raise AuthorizationError(
                "Emergency Kill Switch is ACTIVE: Screen capture operation was blocked and aborted."
            )

        self._attach_thread_desktop()
        timestamp_ns = time.time_ns()
        self._sequence_counter += 1
        seq = self._sequence_counter
        frame_id = str(uuid.uuid4())

        active_win: Optional[ActiveWindowInfo] = None
        if crop_to_active_window:
            active_win = self.get_active_window()

        img_pil: Optional[Image.Image] = None
        monitors = self.list_monitors()
        
        target_mon = next((m for m in monitors if m.monitor_id == monitor_id), None)
        if target_mon is None:
            if monitors:
                target_mon = monitors[0]
                monitor_id = target_mon.monitor_id
            else:
                raise EntityNotFoundError(f"Monitor with ID {monitor_id} not found.")

        # Capture using mss
        try:
            with mss.MSS() as sct:
                raw_monitors = sct.monitors
                if 0 <= monitor_id < len(raw_monitors):
                    sct_rect = raw_monitors[monitor_id]
                else:
                    sct_rect = raw_monitors[1] if len(raw_monitors) > 1 else raw_monitors[0]

                sct_img = sct.grab(sct_rect)
                img_pil = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
        except Exception as e:
            logger.warning(f"ScreenCaptureService: mss grab notice ({e}), using fallback image surface.")
            img_pil = Image.new("RGB", (target_mon.width, target_mon.height), color=(30, 30, 40))

        orig_w, orig_h = img_pil.size

        # Crop to active window or custom ROI
        stream_type = "screen"
        if crop_to_active_window and active_win and active_win.bounds:
            stream_type = "active_window"
            b = active_win.bounds
            crop_x1 = max(0, b.left - target_mon.left)
            crop_y1 = max(0, b.top - target_mon.top)
            crop_x2 = min(orig_w, crop_x1 + b.width)
            crop_y2 = min(orig_h, crop_y1 + b.height)

            if crop_x2 > crop_x1 and crop_y2 > crop_y1:
                img_pil = img_pil.crop((crop_x1, crop_y1, crop_x2, crop_y2))
                orig_w, orig_h = img_pil.size
        elif custom_roi:
            roi_x, roi_y, roi_w, roi_h = custom_roi
            crop_x1 = max(0, roi_x)
            crop_y1 = max(0, roi_y)
            crop_x2 = min(orig_w, crop_x1 + roi_w)
            crop_y2 = min(orig_h, crop_y1 + roi_h)
            if crop_x2 > crop_x1 and crop_y2 > crop_y1:
                img_pil = img_pil.crop((crop_x1, crop_y1, crop_x2, crop_y2))
                orig_w, orig_h = img_pil.size

        # Delta Detection
        is_changed, delta_ratio = self._compute_frame_delta(img_pil)

        # Proportional Downscaling
        processed_img = self._downscale_image(img_pil)
        proc_w, proc_h = processed_img.size

        # In-memory WebP Encoding
        webp_buf = io.BytesIO()
        processed_img.save(webp_buf, format="WEBP", quality=self.config.webp_quality, method=self.config.webp_method)
        raw_webp_bytes = webp_buf.getvalue()
        size_bytes = len(raw_webp_bytes)


        # Construct CapturedFrame
        frame = CapturedFrame(
            frame_id=frame_id,
            stream_type=stream_type,
            monitor_id=monitor_id,
            original_dimensions=(orig_w, orig_h),
            processed_dimensions=(proc_w, proc_h),
            format="WEBP",
            size_bytes=size_bytes,
            timestamp_ns=timestamp_ns,
            sequence_number=seq,
            is_changed=is_changed,
            delta_ratio=delta_ratio,
            window_info=active_win,
            raw_bytes=raw_webp_bytes,
        )

        # Depth-1 Ephemeral Buffer update
        self._ephemeral_frame = frame
        return frame

    def get_latest_frame(self, workspace_id: Optional[str] = None) -> Optional[CapturedFrame]:
        """Retrieve the latest frame from the depth-1 ephemeral memory buffer."""
        if self._is_kill_switch_active(workspace_id=workspace_id):
            self.clear_ephemeral_buffer()
            return None
        return self._ephemeral_frame

    def clear_ephemeral_buffer(self) -> None:
        """Atomically clear the depth-1 ephemeral frame buffer and reset reference states."""
        self._ephemeral_frame = None
        self._reference_thumbnail = None

    async def start_sampling_loop(
        self,
        workspace_id: str,
        fps: float = 1.0,
        monitor_id: int = 1,
        crop_to_active_window: bool = False,
        on_frame_callback: Optional[Callable[[CapturedFrame], None]] = None,
    ) -> None:
        """Start an adaptive background screen sampling loop for an active task or session."""
        if not workspace_id:
            raise ValidationError("workspace_id is required to start sampling loop.")

        effective_fps = max(0.5, min(fps, self.config.max_fps_ceiling))
        interval = 1.0 / effective_fps

        await self.stop_sampling_loop(workspace_id)

        async def _sampling_worker() -> None:
            logger.info(f"ScreenCaptureService: Started sampling loop for workspace {workspace_id} @ {effective_fps} FPS.")
            try:
                while True:
                    if self._is_kill_switch_active(workspace_id=workspace_id):
                        logger.warning(f"ScreenCaptureService: Kill switch triggered in sampling loop for {workspace_id}.")
                        self.clear_ephemeral_buffer()
                        break

                    try:
                        frame = self.capture_frame(
                            monitor_id=monitor_id,
                            crop_to_active_window=crop_to_active_window,
                            workspace_id=workspace_id,
                        )
                        if on_frame_callback:
                            try:
                                if asyncio.iscoroutinefunction(on_frame_callback):
                                    await on_frame_callback(frame)
                                else:
                                    on_frame_callback(frame)
                            except Exception as cb_err:
                                logger.debug(f"ScreenCaptureService: Callback error: {cb_err}")
                    except AuthorizationError:
                        break
                    except Exception as loop_err:
                        logger.warning(f"ScreenCaptureService: Sampling error tick: {loop_err}")

                    await asyncio.sleep(interval)
            except asyncio.CancelledError:
                logger.debug(f"ScreenCaptureService: Sampling loop cancelled for {workspace_id}.")
            finally:
                self.clear_ephemeral_buffer()

        task = asyncio.create_task(_sampling_worker())
        self._sampling_tasks[workspace_id] = task

    async def stop_sampling_loop(self, workspace_id: str) -> None:
        """Stop active background sampling loop for a workspace."""
        task = self._sampling_tasks.pop(workspace_id, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self.clear_ephemeral_buffer()


# Global Singleton Instance
screen_capture_service = ScreenCaptureService()
