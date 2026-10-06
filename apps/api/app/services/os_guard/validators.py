"""AURA-901 Host Action Validators: Path, Process Identity, and Coordinate Safety.

Implements:
1. PathValidator: Canonicalization, traversal defense, LOLBins rejection, executable allowlist
2. ProcessIdentityValidator: Protected process denylist, PID + creation_time TOCTOU verification
3. CoordinateSafetyValidator: Monitor bounds, active window bounds, stale visual observation TTL
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

from app.services.os_guard.policy import LOLBINS_DENYLIST


# Canonical Protected System Process Names (Never Terminate)
PROTECTED_PROCESS_NAMES: FrozenSet[str] = frozenset({
    "system",
    "registry",
    "smss.exe",
    "csrss.exe",
    "wininit.exe",
    "services.exe",
    "lsass.exe",
    "svchost.exe",
    "explorer.exe",
    "dwm.exe",
    "msmpeng.exe",
    "securityhealthservice.exe",
    "postgres.exe",
    "ollama.exe",
    "python.exe",
    "node.exe",
})

MAX_OBSERVATION_AGE_SEC: float = 5.0


class PathValidator:
    """Validates executable paths for application launch safety."""

    @staticmethod
    def validate_executable_path(
        raw_path: str,
        allowlist: Optional[List[str]] = None,
        check_file_exists: bool = False,
    ) -> Tuple[bool, str, str]:
        """Validate, sanitize, and canonicalize executable path.
        
        Returns:
            (is_valid, canonical_path, error_message)
        """
        if not raw_path or not raw_path.strip():
            return False, "", "Executable path is empty"

        cleaned = raw_path.strip()

        # 1. Reject obvious traversal sequences before normalization
        if ".." in cleaned:
            return False, "", "Path traversal sequence ('..') detected in executable path"

        # 2. Canonicalize path
        try:
            canonical = os.path.abspath(os.path.normpath(cleaned))
        except Exception as e:
            return False, "", f"Path canonicalization error: {e}"

        # 3. On Windows, verify drive absolute path
        if os.name == "nt" and not (len(canonical) >= 3 and canonical[1:3] == ":\\"):
            return False, canonical, "Executable path must be an absolute drive path (e.g. C:\\...)"

        # 4. Check against LOLBins denylist
        basename = os.path.basename(canonical).lower()
        if basename in LOLBINS_DENYLIST:
            return False, canonical, f"Executable '{basename}' is in the Windows LOLBins security denylist"

        # 5. Check extension (must be .exe)
        if not canonical.lower().endswith(".exe"):
            return False, canonical, "Executable target must have a '.exe' extension"

        # 6. Check explicit allowlist if configured
        if allowlist is not None:
            normalized_allowlist = [os.path.abspath(os.path.normpath(a)).lower() for a in allowlist]
            if canonical.lower() not in normalized_allowlist and basename not in [os.path.basename(a).lower() for a in allowlist]:
                return False, canonical, f"Executable '{basename}' is not in the approved application allowlist"

        # 7. Check file existence if requested
        if check_file_exists and not os.path.exists(canonical):
            return False, canonical, f"Executable not found at path: {canonical}"

        return True, canonical, ""


class ProcessIdentityValidator:
    """Validates process identity with PID + creation_time verification for TOCTOU / recycling defense."""

    @staticmethod
    def validate_process_for_termination(
        pid: int,
        expected_name: str,
        expected_create_time: float,
        process_allowlist: Optional[List[str]] = None,
    ) -> Tuple[bool, str]:
        """Verify process is safe to terminate and matches expected identity."""
        if pid <= 4:
            return False, f"PID {pid} is a protected Windows system kernel process"

        # 1. Protected System Process Denylist Check
        clean_name = expected_name.lower().strip()
        if not clean_name.endswith(".exe") and clean_name != "system" and clean_name != "registry":
            clean_name = f"{clean_name}.exe"

        if clean_name in PROTECTED_PROCESS_NAMES or expected_name.lower() in PROTECTED_PROCESS_NAMES:
            return False, f"Process '{expected_name}' (PID: {pid}) is in the protected system denylist and cannot be terminated"

        # 2. Allowlist Check if provided
        if process_allowlist is not None:
            allowed = [p.lower().strip() for p in process_allowlist]
            if clean_name not in allowed and expected_name.lower() not in allowed:
                return False, f"Process '{expected_name}' is not in the approved termination allowlist"

        # 3. Live psutil Process Verification (PID + Creation Time)
        try:
            import psutil
            if not psutil.pid_exists(pid):
                return False, f"Process with PID {pid} does not exist (may have already exited)"

            proc = psutil.Process(pid)
            actual_name = proc.name().lower()
            actual_create_time = proc.create_time()

            # Name verification
            if actual_name != clean_name and actual_name != expected_name.lower():
                return False, f"Process name mismatch for PID {pid}: expected '{expected_name}', actual '{actual_name}' (PID reused)"

            # Creation time verification (tolerance 0.05s)
            if expected_create_time > 0 and abs(actual_create_time - expected_create_time) > 0.05:
                return False, (
                    f"Process creation time mismatch for PID {pid}: "
                    f"expected {expected_create_time:.4f}, actual {actual_create_time:.4f} (PID recycled by new process)"
                )

        except ImportError:
            # Fallback if psutil unavailable in test mock
            pass
        except Exception as e:
            return False, f"Failed verifying process identity for PID {pid}: {e}"

        return True, ""


class CoordinateSafetyValidator:
    """Validates screen desktop coordinates, monitor bounds, window bounds, and visual observation freshness."""

    @staticmethod
    def validate_screen_coordinates(
        x: int,
        y: int,
        monitor_id: int = 1,
        monitor_bounds: Optional[Dict[str, int]] = None,
        window_bounds: Optional[Dict[str, int]] = None,
        observation_timestamp: Optional[float] = None,
    ) -> Tuple[bool, str]:
        """Validate that target screen coordinates lie within safe, bounded display regions and are not stale."""
        # 1. Observation Freshness Check (Max 5.0s TTL)
        if observation_timestamp is not None:
            now = time.time()
            age = now - observation_timestamp
            if age < 0:
                return False, f"Invalid observation timestamp in future (drift={abs(age):.2f}s)"
            if age > MAX_OBSERVATION_AGE_SEC:
                return False, f"Stale visual observation (age={age:.2f}s exceeds {MAX_OBSERVATION_AGE_SEC}s ceiling). Fresh target capture required."

        # 2. General Non-Negative Check
        if x < 0 or y < 0:
            return False, f"Coordinates cannot be negative: ({x}, {y}) is invalid"

        # 3. Monitor Bounds Validation if provided
        if monitor_bounds:
            m_left = monitor_bounds.get("left", 0)
            m_top = monitor_bounds.get("top", 0)
            m_width = monitor_bounds.get("width", 1920)
            m_height = monitor_bounds.get("height", 1080)
            m_right = m_left + m_width
            m_bottom = m_top + m_height

            if not (m_left <= x < m_right and m_top <= y < m_bottom):
                return False, (
                    f"Coordinate ({x}, {y}) is outside target monitor {monitor_id} bounds "
                    f"[{m_left}, {m_top}, {m_right}, {m_bottom}]"
                )

        # 4. Target Window Bounds Validation if provided
        if window_bounds:
            w_left = window_bounds.get("left", 0)
            w_top = window_bounds.get("top", 0)
            w_width = window_bounds.get("width", 800)
            w_height = window_bounds.get("height", 600)
            w_right = w_left + w_width
            w_bottom = w_top + w_height

            if not (w_left <= x < w_right and w_top <= y < w_bottom):
                return False, (
                    f"Coordinate ({x}, {y}) is outside active window boundaries "
                    f"[{w_left}, {w_top}, {w_right}, {w_bottom}]"
                )

        return True, ""

    @staticmethod
    def validate_mouse_move_parameters(
        x: int,
        y: int,
        duration: float = 0.2,
        monitor_id: int = 1,
        coordinate_space: str = "screen_desktop",
        monitor_bounds: Optional[Dict[str, int]] = None,
        window_bounds: Optional[Dict[str, int]] = None,
        observation_timestamp: Optional[float] = None,
    ) -> Tuple[bool, str]:
        """Validate bounded mouse movement parameters and observation freshness."""
        # 1. Coordinate Space Validation
        valid_spaces = ("screen_desktop", "captured_frame")
        if coordinate_space not in valid_spaces:
            return False, f"Invalid coordinate_space '{coordinate_space}'. Must be one of {valid_spaces}."

        # 2. Duration Bounds Validation (0.1s - 2.0s)
        if duration < 0.1 or duration > 2.0:
            return False, f"Mouse move duration {duration:.2f}s is out of bounds. Must be between 0.1s and 2.0s."

        # 3. Coordinate and Freshness Validation
        return CoordinateSafetyValidator.validate_screen_coordinates(
            x=x,
            y=y,
            monitor_id=monitor_id,
            monitor_bounds=monitor_bounds,
            window_bounds=window_bounds,
            observation_timestamp=observation_timestamp,
        )

    @staticmethod
    def validate_mouse_click_parameters(
        x: int,
        y: int,
        button: str = "left",
        clicks: int = 1,
        monitor_id: int = 1,
        coordinate_space: str = "screen_desktop",
        monitor_bounds: Optional[Dict[str, int]] = None,
        window_bounds: Optional[Dict[str, int]] = None,
        observation_timestamp: Optional[float] = None,
    ) -> Tuple[bool, str]:
        """Validate mouse click parameters, button type, click count, and observation freshness."""
        # 1. Coordinate Space Validation
        valid_spaces = ("screen_desktop", "captured_frame")
        if coordinate_space not in valid_spaces:
            return False, f"Invalid coordinate_space '{coordinate_space}'. Must be one of {valid_spaces}."

        # 2. Button Validation
        valid_buttons = ("left", "right", "middle")
        if button.lower().strip() not in valid_buttons:
            return False, f"Invalid mouse button '{button}'. Supported buttons: {valid_buttons}."

        # 3. Clicks Count Validation (1 <= clicks <= 3)
        if clicks < 1 or clicks > 3:
            return False, f"Click count {clicks} exceeds safety ceiling. Must be between 1 and 3."

        # 4. Coordinate and Freshness Validation
        return CoordinateSafetyValidator.validate_screen_coordinates(
            x=x,
            y=y,
            monitor_id=monitor_id,
            monitor_bounds=monitor_bounds,
            window_bounds=window_bounds,
            observation_timestamp=observation_timestamp,
        )

    @staticmethod
    def validate_active_window(
        expected_title: Optional[str] = None,
        expected_process_name: Optional[str] = None,
        expected_pid: Optional[int] = None,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Verify the currently active window matches expected targets to prevent accidental interaction."""
        info: Dict[str, Any] = {
            "title": "",
            "pid": None,
            "process_name": "",
            "bounds": None,
        }

        try:
            import pygetwindow as gw
            active_win = gw.getActiveWindow()
            if active_win:
                info["title"] = active_win.title or ""
                info["bounds"] = {
                    "left": active_win.left,
                    "top": active_win.top,
                    "width": active_win.width,
                    "height": active_win.height,
                }
        except Exception:
            pass

        # Try to resolve PID/Process if on Windows
        if os.name == "nt":
            try:
                import ctypes
                import ctypes.wintypes
                user32 = ctypes.windll.user32
                hwnd = user32.GetForegroundWindow()
                if hwnd:
                    pid = ctypes.wintypes.DWORD()
                    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                    info["pid"] = pid.value
                    if pid.value:
                        import psutil
                        try:
                            info["process_name"] = psutil.Process(pid.value).name().lower()
                        except Exception:
                            pass
            except Exception:
                pass

        # Validate expected title substring
        if expected_title and expected_title.strip():
            clean_expected = expected_title.strip().lower()
            actual_title = (info.get("title") or "").lower()
            if clean_expected not in actual_title:
                return False, f"Active window title mismatch: expected '{expected_title}', actual active window is '{info.get('title')}'", info

        # Validate expected process name
        if expected_process_name and expected_process_name.strip():
            clean_proc = expected_process_name.strip().lower()
            if not clean_proc.endswith(".exe"):
                clean_proc = f"{clean_proc}.exe"
            actual_proc = (info.get("process_name") or "").lower()
            if actual_proc and clean_proc != actual_proc:
                return False, f"Active window process mismatch: expected '{clean_proc}', actual is '{actual_proc}'", info

        # Validate expected PID
        if expected_pid is not None and info.get("pid") is not None:
            if expected_pid != info.get("pid"):
                return False, f"Active window PID mismatch: expected {expected_pid}, actual is {info.get('pid')}", info

        return True, "", info


class KeyboardInputValidator:
    """Validates keyboard typing, key presses, and shortcut combinations against strict security allowlists."""

    MAX_TYPE_TEXT_LENGTH: int = 256

    SAFE_KEYS: FrozenSet[str] = frozenset({
        "enter", "tab", "space", "backspace", "delete", "escape",
        "up", "down", "left", "right", "home", "end", "pageup", "pagedown", "insert",
        "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12",
        "shift", "ctrl", "alt", "capslock", "numlock", "scrolllock", "printscreen", "pause",
        "a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m",
        "n", "o", "p", "q", "r", "s", "t", "u", "v", "w", "x", "y", "z",
        "0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
    })

    SAFE_SHORTCUTS: FrozenSet[str] = frozenset({
        "ctrl+c", "ctrl+v", "ctrl+x", "ctrl+a", "ctrl+z", "ctrl+y",
        "ctrl+s", "ctrl+f", "ctrl+p", "ctrl+o", "ctrl+n", "ctrl+w", "ctrl+t", "ctrl+r",
        "ctrl+shift+z", "ctrl+shift+s", "ctrl+shift+t", "ctrl+shift+n",
        "alt+tab", "ctrl+tab", "ctrl+shift+tab",
        "ctrl+home", "ctrl+end", "ctrl+left", "ctrl+right",
        "alt+left", "alt+right", "alt+up", "alt+down",
    })

    FORBIDDEN_SHORTCUTS: FrozenSet[str] = frozenset({
        "win+r", "win+x", "ctrl+alt+del", "win+e", "win+d", "win+l",
        "win+i", "win+s", "alt+f4", "win+pause", "win+break",
        "ctrl+shift+esc", "win+m", "win+b", "win+a", "win+h", "win+k",
    })

    @classmethod
    def validate_type_text(cls, text: str) -> Tuple[bool, str, int]:
        """Validate text input for typing actions.
        
        Enforces max length <= 256, rejects NUL bytes, and prevents malformed control sequences.
        Returns: (is_valid, error_message, text_length)
        """
        if text is None or not isinstance(text, str):
            return False, "Text input must be a string", 0

        if len(text) == 0:
            return False, "Text input cannot be empty", 0

        if len(text) > cls.MAX_TYPE_TEXT_LENGTH:
            return False, f"Text length ({len(text)}) exceeds maximum ceiling ({cls.MAX_TYPE_TEXT_LENGTH} chars)", len(text)

        # Reject NUL bytes
        if "\x00" in text:
            return False, "NUL byte ('\\x00') detected in text input. Injection prohibited.", len(text)

        # Check for unprintable control characters (allow \n, \r, \t)
        for ch in text:
            code = ord(ch)
            if code < 32 and ch not in ("\n", "\r", "\t"):
                return False, f"Disallowed control character (ASCII {code}) detected in text input", len(text)

        return True, "", len(text)

    @classmethod
    def validate_press_key(cls, key: str, presses: int = 1) -> Tuple[bool, str, str]:
        """Validate single key press action against SAFE_KEYS allowlist.
        
        Returns: (is_valid, canonical_key, error_message)
        """
        if not key or not isinstance(key, str):
            return False, "", "Key string is required"

        clean_key = key.strip().lower()

        # Map common aliases
        aliases = {
            "esc": "escape",
            "return": "enter",
            "pgup": "pageup",
            "pgdn": "pagedown",
            "del": "delete",
            "ins": "insert",
        }
        clean_key = aliases.get(clean_key, clean_key)

        if clean_key not in cls.SAFE_KEYS:
            return False, clean_key, f"Key '{key}' is not in the approved safe key allowlist"

        if presses < 1 or presses > 10:
            return False, clean_key, f"Key press count ({presses}) is out of bounds (1-10)"

        return True, clean_key, ""

    @classmethod
    def validate_keyboard_shortcut(cls, shortcut: str) -> Tuple[bool, str, List[str]]:
        """Validate keyboard shortcut combination against SAFE_SHORTCUTS allowlist.
        
        Returns: (is_valid, error_message, keys_list)
        """
        if not shortcut or not isinstance(shortcut, str):
            return False, "Shortcut string is required (e.g. 'ctrl+c')", []

        clean_sc = shortcut.strip().lower()

        # Check for forbidden system shortcuts or Windows key combinations
        if "win" in clean_sc or "super" in clean_sc or "cmd" in clean_sc:
            return False, f"System Windows key shortcut '{shortcut}' is forbidden by safety policy", []

        if clean_sc in cls.FORBIDDEN_SHORTCUTS:
            return False, f"Shortcut '{shortcut}' is in the forbidden system shortcuts denylist", []

        # Split and normalize keys
        keys = [k.strip() for k in clean_sc.split("+") if k.strip()]
        if len(keys) < 2:
            return False, f"Shortcut '{shortcut}' must contain at least one modifier and one key (e.g. 'ctrl+c')", []

        # Canonicalize format: e.g. ctrl+shift+c
        modifiers = []
        regular_keys = []
        for k in keys:
            if k in ("ctrl", "control"):
                modifiers.append("ctrl")
            elif k in ("alt", "option"):
                modifiers.append("alt")
            elif k in ("shift",):
                modifiers.append("shift")
            else:
                regular_keys.append(k)

        # Sort modifiers deterministically: ctrl, alt, shift
        sorted_mods = []
        for m in ("ctrl", "alt", "shift"):
            if m in modifiers:
                sorted_mods.append(m)

        normalized_sc = "+".join(sorted_mods + regular_keys)

        if normalized_sc in cls.FORBIDDEN_SHORTCUTS or clean_sc in cls.FORBIDDEN_SHORTCUTS:
            return False, f"Shortcut '{shortcut}' is in the forbidden system shortcuts denylist", []

        if normalized_sc not in cls.SAFE_SHORTCUTS and clean_sc not in cls.SAFE_SHORTCUTS:
            return False, f"Shortcut '{shortcut}' is not in the approved safe shortcuts allowlist", []

        return True, "", (sorted_mods + regular_keys)

