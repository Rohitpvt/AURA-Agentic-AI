"""AURA-1006 Windows Interactive User Session Manager & Transition Monitor."""

import asyncio
import ctypes
from ctypes import wintypes
from enum import Enum
import os
import platform
import time
from typing import Any, Callable, Dict, List, Optional

from app.core.logging import logger
from app.daemon.process_tracker import get_current_session_id

# Win32 Session Change Notification Constants
WM_WTSSESSION_CHANGE = 0x02B1
WTS_CONSOLE_CONNECT = 0x1
WTS_CONSOLE_DISCONNECT = 0x2
WTS_REMOTE_CONNECT = 0x3
WTS_REMOTE_DISCONNECT = 0x4
WTS_SESSION_LOGON = 0x5
WTS_SESSION_LOGOFF = 0x6
WTS_SESSION_LOCK = 0x7
WTS_SESSION_UNLOCK = 0x8
WTS_SESSION_REMOTE_CONTROL = 0x9

NOTIFY_FOR_THIS_SESSION = 0


class SessionState(str, Enum):
    """Authoritative Windows Interactive User Session State."""
    ACTIVE = "ACTIVE"
    LOCKED = "LOCKED"
    DISCONNECTED = "DISCONNECTED"
    LOGGING_OFF = "LOGGING_OFF"
    UNKNOWN = "UNKNOWN"


class WindowsSessionManager:
    """Manages Windows interactive session awareness, lock/unlock events, and logout lifecycle."""

    def __init__(self, session_id: Optional[int] = None):
        self.session_id = session_id if session_id is not None else get_current_session_id()
        self.state = SessionState.ACTIVE
        self.is_windows = platform.system() == "Windows"
        self._listeners: List[Callable[[SessionState, int], None]] = []
        self._registered_hwnd: Optional[int] = None

    def register_listener(self, callback: Callable[[SessionState, int], None]) -> None:
        """Register a callback for session state transition events."""
        if callback not in self._listeners:
            self._listeners.append(callback)

    def unregister_listener(self, callback: Callable[[SessionState, int], None]) -> None:
        """Unregister a callback."""
        if callback in self._listeners:
            self._listeners.remove(callback)

    def register_session_notification(self, hwnd: int) -> bool:
        """Register a Win32 window handle to receive WM_WTSSESSION_CHANGE messages."""
        if not self.is_windows or not hwnd:
            return False
        try:
            wtsapi32 = ctypes.windll.wtsapi32
            # WTSRegisterSessionNotification(HWND hWnd, DWORD dwFlags)
            success = wtsapi32.WTSRegisterSessionNotification(hwnd, NOTIFY_FOR_THIS_SESSION)
            if success:
                self._registered_hwnd = hwnd
                logger.info(f"WindowsSessionManager: Registered session notification for hWnd={hwnd} (Session {self.session_id})")
                return True
            err = ctypes.windll.kernel32.GetLastError()
            logger.debug(f"WindowsSessionManager: WTSRegisterSessionNotification failed with error {err}")
            return False
        except Exception as exc:
            logger.debug(f"WindowsSessionManager: Error registering session notification: {exc}")
            return False

    def unregister_session_notification(self) -> None:
        """Unregister session notifications for the active window."""
        if self.is_windows and self._registered_hwnd:
            try:
                ctypes.windll.wtsapi32.WTSUnRegisterSessionNotification(self._registered_hwnd)
                self._registered_hwnd = None
            except Exception:
                pass

    def handle_wts_message(self, event_code: int, session_id: int) -> SessionState:
        """Process incoming WM_WTSSESSION_CHANGE message and transition session state."""
        # Validate that event belongs to our interactive session
        if session_id != 0 and session_id != self.session_id:
            logger.debug(f"WindowsSessionManager: Ignoring event {event_code} for other session {session_id}")
            return self.state

        old_state = self.state
        if event_code in (WTS_SESSION_LOCK,):
            self.state = SessionState.LOCKED
            logger.info(f"WindowsSessionManager: Session {self.session_id} LOCKED. Pausing UI/Sensing streams.")

        elif event_code in (WTS_SESSION_UNLOCK, WTS_CONSOLE_CONNECT, WTS_SESSION_LOGON):
            self.state = SessionState.ACTIVE
            logger.info(f"WindowsSessionManager: Session {self.session_id} ACTIVE/UNLOCKED.")

        elif event_code in (WTS_CONSOLE_DISCONNECT, WTS_REMOTE_DISCONNECT):
            self.state = SessionState.DISCONNECTED
            logger.info(f"WindowsSessionManager: Session {self.session_id} DISCONNECTED.")

        elif event_code in (WTS_SESSION_LOGOFF,):
            self.state = SessionState.LOGGING_OFF
            logger.warning(f"WindowsSessionManager: Session {self.session_id} LOGGING OFF. Initiating clean exit.")

        if self.state != old_state:
            for listener in self._listeners:
                try:
                    listener(self.state, event_code)
                except Exception as exc:
                    logger.error(f"WindowsSessionManager: Error in session listener callback: {exc}")

        return self.state

    def get_session_info(self) -> Dict[str, Any]:
        """Return diagnostic session metadata."""
        return {
            "session_id": self.session_id,
            "state": self.state.value,
            "is_windows": self.is_windows,
            "registered_hwnd": self._registered_hwnd,
        }
