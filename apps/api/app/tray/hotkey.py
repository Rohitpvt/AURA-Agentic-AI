"""AURA-905 Win32 Global Emergency Hotkey Manager (Ctrl + Alt + Shift + K)."""

import ctypes
import os
import platform
import time
from typing import Callable, Optional

from app.core.logging import logger
from app.tray.types import HotkeyRegistrationStatus

# Win32 Constants
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000
VK_K = 0x4B

AURA_KILL_HOTKEY_ID = 0x9051
DEBOUNCE_INTERVAL_SEC = 0.300  # 300 ms software debounce window


class GlobalHotkeyManager:
    """Manages the physical emergency interrupter hotkey (Ctrl+Alt+Shift+K)."""

    def __init__(
        self,
        hwnd: int = 0,
        on_emergency_trigger: Optional[Callable[[], None]] = None,
        debounce_sec: float = DEBOUNCE_INTERVAL_SEC,
    ):
        self.hwnd = hwnd
        self.on_emergency_trigger = on_emergency_trigger
        self.debounce_sec = debounce_sec
        self.status = HotkeyRegistrationStatus.UNREGISTERED
        self._last_trigger_time: float = 0.0
        self._trigger_count: int = 0

    def register_hotkey(self, hwnd: Optional[int] = None) -> bool:
        """Register Ctrl+Alt+Shift+K with the Windows kernel."""
        if hwnd is not None:
            self.hwnd = hwnd

        if platform.system() != "Windows":
            logger.info("GlobalHotkeyManager: Win32 hotkeys simulated on non-Windows platform.")
            self.status = HotkeyRegistrationStatus.ACTIVE
            return True

        try:
            user32 = ctypes.windll.user32
            modifiers = MOD_CONTROL | MOD_ALT | MOD_SHIFT | MOD_NOREPEAT

            # Call RegisterHotKey(hWnd, id, fsModifiers, vk)
            success = user32.RegisterHotKey(
                self.hwnd,
                AURA_KILL_HOTKEY_ID,
                modifiers,
                VK_K,
            )

            if success:
                self.status = HotkeyRegistrationStatus.ACTIVE
                logger.info("GlobalHotkeyManager: Ctrl+Alt+Shift+K successfully registered.")
                return True
            else:
                err = ctypes.GetLastError()
                logger.warning(
                    f"GlobalHotkeyManager: Failed to register hotkey (Win32 Error: {err}). Degraded mode engaged."
                )
                self.status = HotkeyRegistrationStatus.UNAVAILABLE
                return False

        except Exception as exc:
            logger.error(f"GlobalHotkeyManager: Error during hotkey registration: {exc}")
            self.status = HotkeyRegistrationStatus.ERROR
            return False

    def unregister_hotkey(self) -> bool:
        """Unregister the global hotkey on shutdown."""
        if self.status != HotkeyRegistrationStatus.ACTIVE:
            self.status = HotkeyRegistrationStatus.UNREGISTERED
            return True

        if platform.system() != "Windows":
            self.status = HotkeyRegistrationStatus.UNREGISTERED
            return True

        try:
            user32 = ctypes.windll.user32
            res = user32.UnregisterHotKey(self.hwnd, AURA_KILL_HOTKEY_ID)
            self.status = HotkeyRegistrationStatus.UNREGISTERED
            logger.info("GlobalHotkeyManager: Ctrl+Alt+Shift+K unregistered successfully.")
            return bool(res)
        except Exception as exc:
            logger.error(f"GlobalHotkeyManager: Error unregistering hotkey: {exc}")
            self.status = HotkeyRegistrationStatus.ERROR
            return False

    def handle_hotkey_message(self, hotkey_id: int) -> bool:
        """Handle incoming WM_HOTKEY message with software debounce enforcement."""
        if hotkey_id != AURA_KILL_HOTKEY_ID:
            return False

        now = time.perf_counter()
        elapsed = now - self._last_trigger_time

        # 1. Enforce >= 300ms software debounce
        if elapsed < self.debounce_sec:
            logger.debug(
                f"GlobalHotkeyManager: Debounce dropped repeated hotkey trigger (elapsed={elapsed*1000.0:.1f}ms < {self.debounce_sec*1000.0:.1f}ms)"
            )
            return False

        self._last_trigger_time = now
        self._trigger_count += 1
        logger.warning(
            f"GlobalHotkeyManager: EMERGENCY KILL SWITCH TRIGGERED VIA HOTKEY (Trigger #{self._trigger_count})"
        )

        # 2. Execute Emergency Kill Callback (Dual-path abort)
        if self.on_emergency_trigger:
            try:
                self.on_emergency_trigger()
            except Exception as exc:
                logger.error(f"GlobalHotkeyManager: Callback execution error: {exc}")

        return True
