"""AURA-905 Win32 System Tray Icon & Context Menu Implementation."""

import ctypes
import os
import platform
import threading
import time
from typing import Any, Callable, Dict, Optional

from app.core.logging import logger
from app.tray.hotkey import GlobalHotkeyManager
from app.tray.types import (
    HotkeyRegistrationStatus,
    PrivacySensingState,
    TrayRuntimeState,
)

# Win32 Messages & Constants
WM_USER = 0x0400
WM_TRAYNOTIFY = WM_USER + 20
WM_COMMAND = 0x0111
WM_DESTROY = 0x0002
WM_HOTKEY = 0x0312
WM_WTSSESSION_CHANGE = 0x02B1
WTS_SESSION_LOCK = 0x7
WTS_SESSION_UNLOCK = 0x8

# Menu Command IDs
CMD_KILL_SWITCH = 1001
CMD_OPEN_DASHBOARD = 1002
CMD_VIEW_TELEMETRY = 1003
CMD_EXIT_TRAY = 1004
CMD_INFO_HEADER = 1005
CMD_INFO_STATUS = 1006
CMD_INFO_CAM = 1007
CMD_INFO_SCREEN = 1008
CMD_INFO_MIC = 1009
CMD_INFO_OCR = 1010
CMD_INFO_VLM = 1011
CMD_INFO_HOTKEY = 1012
CMD_START_BACKEND = 1013
CMD_STOP_BACKEND = 1014
CMD_RESTART_BACKEND = 1015
CMD_TOGGLE_AUTOSTART = 1016


class WindowsTrayIcon:
    """Manages the Windows taskbar notification area presence and context menu."""

    def __init__(
        self,
        on_kill_switch: Optional[Callable[[], None]] = None,
        on_exit: Optional[Callable[[], None]] = None,
        on_open_dashboard: Optional[Callable[[], None]] = None,
        on_start_backend: Optional[Callable[[], None]] = None,
        on_stop_backend: Optional[Callable[[], None]] = None,
        on_restart_backend: Optional[Callable[[], None]] = None,
        on_toggle_autostart: Optional[Callable[[], None]] = None,
        session_manager: Optional[Any] = None,
    ):
        self.on_kill_switch = on_kill_switch
        self.on_exit = on_exit
        self.on_open_dashboard = on_open_dashboard
        self.on_start_backend = on_start_backend
        self.on_stop_backend = on_stop_backend
        self.on_restart_backend = on_restart_backend
        self.on_toggle_autostart = on_toggle_autostart

        from app.daemon.session_manager import WindowsSessionManager
        self.session_manager = session_manager or WindowsSessionManager()

        self.state: TrayRuntimeState = TrayRuntimeState.READY
        self.privacy_state = PrivacySensingState()
        self.hwnd: int = 0
        self._is_running = False
        self._message_thread: Optional[threading.Thread] = None

        # Hotkey manager integration
        self.hotkey_manager = GlobalHotkeyManager(
            on_emergency_trigger=self._handle_hotkey_emergency_trigger
        )

    def _handle_hotkey_emergency_trigger(self) -> None:
        """Internal callback when emergency hotkey is physically pressed."""
        self.set_state(TrayRuntimeState.KILL_SWITCHED)
        if self.on_kill_switch:
            self.on_kill_switch()

    def set_state(self, new_state: TrayRuntimeState) -> None:
        """Update active tray runtime state and update tooltip/icon."""
        self.state = new_state
        self._update_icon_and_tooltip()

    def set_privacy_state(self, privacy: PrivacySensingState) -> None:
        """Update live sensing privacy state indicators."""
        self.privacy_state = privacy

    def _update_icon_and_tooltip(self) -> None:
        """Update the notify icon data structure in Windows Shell."""
        if platform.system() != "Windows" or not self.hwnd:
            return

        try:
            import win32gui
            import win32con

            tooltip = f"AURA: {self.state.value}"
            if self.hotkey_manager.status == HotkeyRegistrationStatus.UNAVAILABLE:
                tooltip += " [Hotkey: UNAVAILABLE]"

            # Select system stock icon based on state
            icon_flag = win32con.IDI_APPLICATION
            if self.state == TrayRuntimeState.KILL_SWITCHED:
                icon_flag = win32con.IDI_ERROR
            elif self.state in [TrayRuntimeState.DEGRADED, TrayRuntimeState.STOPPED]:
                icon_flag = win32con.IDI_WARNING
            elif self.state in [TrayRuntimeState.CAMERA_ACTIVE, TrayRuntimeState.SCREEN_ACTIVE]:
                icon_flag = win32con.IDI_INFORMATION

            hicon = win32gui.LoadIcon(0, icon_flag)
            nid = (self.hwnd, 0, win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP, WM_TRAYNOTIFY, hicon, tooltip)
            win32gui.Shell_NotifyIcon(win32gui.NIM_MODIFY, nid)
        except Exception as exc:
            logger.debug(f"WindowsTrayIcon: Error updating icon: {exc}")

    def create_window_and_run(self) -> None:
        """Initialize the Win32 window, register hotkey, and run STA message pump."""
        if platform.system() != "Windows":
            logger.info("WindowsTrayIcon: Running mock message loop on non-Windows.")
            self._is_running = True
            return

        try:
            import win32gui
            import win32con

            # Register Window Class
            wc = win32gui.WNDCLASS()
            wc.hInstance = win32gui.GetModuleHandle(None)
            wc.lpszClassName = "AuraTrayWindowClass"
            wc.lpfnWndProc = self._wnd_proc

            try:
                class_atom = win32gui.RegisterClass(wc)
            except Exception:
                class_atom = 1  # Already registered

            # Create Hidden Message Window
            self.hwnd = win32gui.CreateWindowEx(
                0,
                wc.lpszClassName,
                "AURA Tray Host",
                0,
                0, 0, 0, 0,
                0, 0, wc.hInstance, None
            )

            # Register Global Emergency Hotkey on this window's hWnd
            self.hotkey_manager.register_hotkey(self.hwnd)

            # Register with Taskbar Notification Area
            hicon = win32gui.LoadIcon(0, win32con.IDI_APPLICATION)
            nid = (self.hwnd, 0, win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP, WM_TRAYNOTIFY, hicon, f"AURA: {self.state.value}")
            win32gui.Shell_NotifyIcon(win32gui.NIM_ADD, nid)

            # Register for Windows Session Change Notifications
            self.session_manager.register_session_notification(self.hwnd)

            self._is_running = True
            logger.info(f"WindowsTrayIcon: Initialized with hWnd={self.hwnd}")

            # Win32 STA Message Pump
            win32gui.PumpMessages()

        except Exception as exc:
            logger.error(f"WindowsTrayIcon: Error in message pump: {exc}")
        finally:
            self._cleanup()

    def _wnd_proc(self, hwnd: int, msg: int, wparam: int, lparam: int) -> int:
        """Win32 Window Procedure handling tray callbacks, menus, and hotkeys."""
        try:
            import win32gui
            import win32con

            if msg == WM_TRAYNOTIFY:
                # lparam contains mouse message (e.g. WM_RBUTTONUP, WM_LBUTTONDBLCLK)
                if lparam == win32con.WM_RBUTTONUP:
                    self._show_context_menu()
                elif lparam == win32con.WM_LBUTTONDBLCLK:
                    if self.on_open_dashboard:
                        self.on_open_dashboard()
                return 0

            elif msg == WM_HOTKEY:
                # Forward to hotkey manager
                self.hotkey_manager.handle_hotkey_message(wparam)
                return 0

            elif msg == WM_COMMAND:
                cmd_id = wparam & 0xFFFF
                self._handle_menu_command(cmd_id)
                return 0

            elif msg == WM_WTSSESSION_CHANGE:
                self.session_manager.handle_wts_message(wparam, lparam)
                return 0

            elif msg == WM_DESTROY:
                self._cleanup()
                win32gui.PostQuitMessage(0)
                return 0

        except Exception as exc:
            logger.debug(f"WindowsTrayIcon: Error in WndProc: {exc}")

        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    def _show_context_menu(self) -> None:
        """Construct and display the live context menu."""
        if platform.system() != "Windows" or not self.hwnd:
            return

        try:
            import win32gui
            import win32con
            from app.daemon.autostart import AutostartManager

            menu = win32gui.CreatePopupMenu()

            # 1. Header & Status
            win32gui.AppendMenu(menu, win32con.MF_STRING | win32con.MF_DISABLED, CMD_INFO_HEADER, "AURA Agentic OS (v1.0.0)")
            win32gui.AppendMenu(menu, win32con.MF_STRING | win32con.MF_DISABLED, CMD_INFO_STATUS, f"Status: {self.state.value}")
            
            # Hotkey Status Badge
            hk_text = "Hotkey: ACTIVE (Ctrl+Alt+Shift+K)" if self.hotkey_manager.status == HotkeyRegistrationStatus.ACTIVE else "⚠️ Hotkey: UNAVAILABLE"
            win32gui.AppendMenu(menu, win32con.MF_STRING | win32con.MF_DISABLED, CMD_INFO_HOTKEY, hk_text)
            win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, "")

            # 2. Privacy & Sensing Indicators
            win32gui.AppendMenu(menu, win32con.MF_STRING | win32con.MF_DISABLED, CMD_INFO_CAM, f"• Live Camera: [{self.privacy_state.camera_state}]")
            win32gui.AppendMenu(menu, win32con.MF_STRING | win32con.MF_DISABLED, CMD_INFO_SCREEN, f"• Screen Sensing: [{self.privacy_state.screen_state}]")
            win32gui.AppendMenu(menu, win32con.MF_STRING | win32con.MF_DISABLED, CMD_INFO_MIC, f"• Microphone: [{self.privacy_state.mic_state}]")
            win32gui.AppendMenu(menu, win32con.MF_STRING | win32con.MF_DISABLED, CMD_INFO_OCR, f"• Local OCR: [{self.privacy_state.ocr_state}]")
            win32gui.AppendMenu(menu, win32con.MF_STRING | win32con.MF_DISABLED, CMD_INFO_VLM, f"• Moondream VLM: [{self.privacy_state.vlm_state}]")
            win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, "")

            # 3. Backend Lifecycle Controls
            win32gui.AppendMenu(menu, win32con.MF_STRING, CMD_START_BACKEND, "▶ Start Backend")
            win32gui.AppendMenu(menu, win32con.MF_STRING, CMD_STOP_BACKEND, "⏹ Stop Backend")
            win32gui.AppendMenu(menu, win32con.MF_STRING, CMD_RESTART_BACKEND, "🔄 Restart Backend")
            win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, "")

            # 4. Autostart Configuration
            autostart_mgr = AutostartManager()
            autostart_on = autostart_mgr.is_autostart_enabled()
            autostart_label = "🚀 Autostart: [ON] (Click to Disable)" if autostart_on else "🚀 Autostart: [OFF] (Click to Enable)"
            win32gui.AppendMenu(menu, win32con.MF_STRING, CMD_TOGGLE_AUTOSTART, autostart_label)
            win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, "")

            # 5. Emergency Actions
            kill_label = "🛑 EMERGENCY KILL SWITCH (Active)" if self.state == TrayRuntimeState.KILL_SWITCHED else "🛑 EMERGENCY KILL SWITCH"
            win32gui.AppendMenu(menu, win32con.MF_STRING, CMD_KILL_SWITCH, kill_label)
            win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, "")

            # 6. Standard Navigation
            win32gui.AppendMenu(menu, win32con.MF_STRING, CMD_OPEN_DASHBOARD, "🌐 Open Web Dashboard")
            win32gui.AppendMenu(menu, win32con.MF_STRING, CMD_VIEW_TELEMETRY, "📊 View Telemetry Summary")
            win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, "")
            win32gui.AppendMenu(menu, win32con.MF_STRING, CMD_EXIT_TRAY, "❌ Exit Tray")

            pos = win32gui.GetCursorPos()
            win32gui.SetForegroundWindow(self.hwnd)
            win32gui.TrackPopupMenu(menu, win32con.TPM_LEFTALIGN | win32con.TPM_RIGHTBUTTON, pos[0], pos[1], 0, self.hwnd, None)
            win32gui.PostMessage(self.hwnd, win32con.WM_NULL, 0, 0)

        except Exception as exc:
            logger.error(f"WindowsTrayIcon: Error displaying context menu: {exc}")

    def _handle_menu_command(self, cmd_id: int) -> None:
        """Dispatch selected context menu action."""
        if cmd_id == CMD_KILL_SWITCH:
            logger.warning("WindowsTrayIcon: User selected EMERGENCY KILL SWITCH from context menu.")
            self.set_state(TrayRuntimeState.KILL_SWITCHED)
            if self.on_kill_switch:
                self.on_kill_switch()

        elif cmd_id == CMD_START_BACKEND:
            logger.info("WindowsTrayIcon: User selected Start Backend.")
            if self.on_start_backend:
                self.on_start_backend()

        elif cmd_id == CMD_STOP_BACKEND:
            logger.info("WindowsTrayIcon: User selected Stop Backend.")
            if self.on_stop_backend:
                self.on_stop_backend()

        elif cmd_id == CMD_RESTART_BACKEND:
            logger.info("WindowsTrayIcon: User selected Restart Backend.")
            if self.on_restart_backend:
                self.on_restart_backend()

        elif cmd_id == CMD_TOGGLE_AUTOSTART:
            from app.daemon.autostart import AutostartManager
            mgr = AutostartManager()
            if mgr.is_autostart_enabled():
                mgr.disable_autostart()
                logger.info("WindowsTrayIcon: Autostart disabled by user.")
            else:
                mgr.enable_autostart()
                logger.info("WindowsTrayIcon: Autostart enabled by user.")
            if self.on_toggle_autostart:
                self.on_toggle_autostart()

        elif cmd_id == CMD_OPEN_DASHBOARD:
            if self.on_open_dashboard:
                self.on_open_dashboard()
            else:
                import webbrowser
                webbrowser.open("http://localhost:3000")

        elif cmd_id == CMD_VIEW_TELEMETRY:
            try:
                import webbrowser
                webbrowser.open("http://localhost:3000/telemetry")
            except Exception:
                pass

        elif cmd_id == CMD_EXIT_TRAY:
            logger.info("WindowsTrayIcon: User requested tray exit.")
            self.stop()
            if self.on_exit:
                self.on_exit()

    def _cleanup(self) -> None:
        """Unregister hotkeys, remove notify icon, and clean up GDI/window resources."""
        self.hotkey_manager.unregister_hotkey()
        if platform.system() == "Windows" and self.hwnd:
            try:
                import win32gui
                nid = (self.hwnd, 0)
                win32gui.Shell_NotifyIcon(win32gui.NIM_DELETE, nid)
            except Exception:
                pass
            self.hwnd = 0
        self._is_running = False

    def stop(self) -> None:
        """Trigger asynchronous window destruction and message loop exit."""
        if platform.system() == "Windows" and self.hwnd:
            try:
                import win32gui
                win32gui.PostMessage(self.hwnd, WM_DESTROY, 0, 0)
            except Exception:
                pass
        else:
            self._cleanup()
