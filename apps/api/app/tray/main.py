"""AURA-905 System Tray Main Process Entrypoint (python -m app.tray.main)."""

import ctypes
import os
import platform
import sys
import threading
import time
from typing import Optional

from app.core.logging import logger
from app.services.kill_switch import kill_switch
from app.tray.ipc import AuraNamedPipeClient
from app.tray.tray_icon import WindowsTrayIcon
from app.tray.types import (
    PrivacySensingState,
    TrayIPCCommand,
    TrayRuntimeState,
)

ERROR_ALREADY_EXISTS = 183


def get_session_id() -> str:
    """Get active Windows session ID."""
    if platform.system() == "Windows":
        try:
            sid = ctypes.c_ulong()
            if ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(sid)):
                return str(sid.value)
        except Exception:
            return "0"
    return "0"


def acquire_single_instance_mutex() -> Optional[int]:
    """Acquire session-scoped Named Mutex to guarantee single tray instance."""
    if platform.system() != "Windows":
        return 1

    try:
        kernel32 = ctypes.windll.kernel32
        mutex_name = f"Local\\AURA_TRAY_INSTANCE_MUTEX_{get_session_id()}"

        # CreateMutexW(lpMutexAttributes, bInitialOwner, lpName)
        handle = kernel32.CreateMutexW(None, False, mutex_name)
        last_err = kernel32.GetLastError()

        if last_err == ERROR_ALREADY_EXISTS:
            logger.info("AURA Tray: Another instance is already running in this session. Exiting cleanly.")
            kernel32.CloseHandle(handle)
            return None

        return handle
    except Exception as exc:
        logger.warning(f"AURA Tray: Error creating instance mutex: {exc}")
        return 1


class AuraTrayApplication:
    """Coordinator for System Tray lifecycle, state synchronization, and emergency controls."""

    def __init__(self):
        self.ipc_client = AuraNamedPipeClient()
        self.tray_icon = WindowsTrayIcon(
            on_kill_switch=self.trigger_emergency_kill,
            on_exit=self.shutdown,
        )
        self._running = False
        self._sync_thread: Optional[threading.Thread] = None

    def trigger_emergency_kill(self) -> None:
        """Dual-path emergency kill-switch trigger."""
        logger.warning("AuraTrayApplication: Triggering dual-path emergency kill sequence.")

        # Path 1: Instant Local Atomic State File Update (< 2.0 ms)
        try:
            kill_switch.set_active(True)
            logger.info("AuraTrayApplication: Path 1 (Local Disk State) updated to KILL_SWITCHED.")
        except Exception as exc:
            logger.error(f"AuraTrayApplication: Path 1 error: {exc}")

        # Path 2: IPC Notification to Backend (< 10.0 ms, non-blocking dispatch)
        def _notify_backend_ipc():
            try:
                resp = self.ipc_client.send_command_sync(
                    TrayIPCCommand.ACTIVATE_KILL_SWITCH,
                    {"reason": "Emergency stop triggered via System Tray / Global Hotkey"},
                    timeout_ms=500,
                )
                logger.info(f"AuraTrayApplication: Path 2 (IPC Dispatch) status: {resp.get('status')}")
            except Exception as exc:
                logger.debug(f"AuraTrayApplication: Path 2 IPC notice: {exc}")

        threading.Thread(target=_notify_backend_ipc, daemon=True, name="AuraKillIpcNotify").start()
        self.tray_icon.set_state(TrayRuntimeState.KILL_SWITCHED)

    def _state_sync_loop(self) -> None:
        """Background 1.0 Hz polling loop synchronizing runtime & sensing state from backend."""
        while self._running:
            try:
                # 1. Probe local kill switch file first
                if kill_switch.is_active():
                    self.tray_icon.set_state(TrayRuntimeState.KILL_SWITCHED)
                else:
                    # 2. Query IPC status
                    status_resp = self.ipc_client.send_command_sync(
                        TrayIPCCommand.GET_STATUS, timeout_ms=800
                    )
                    if status_resp.get("status") == "success":
                        data = status_resp.get("data", {})
                        rt_str = data.get("runtime_state", TrayRuntimeState.READY.value)
                        try:
                            self.tray_icon.set_state(TrayRuntimeState(rt_str))
                        except ValueError:
                            self.tray_icon.set_state(TrayRuntimeState.READY)
                    else:
                        # Degraded / Disconnected backend
                        self.tray_icon.set_state(TrayRuntimeState.DEGRADED)

                # 3. Query Privacy & Sensing state
                privacy_resp = self.ipc_client.send_command_sync(
                    TrayIPCCommand.GET_PRIVACY_STATE, timeout_ms=800
                )
                if privacy_resp.get("status") == "success":
                    p_data = privacy_resp.get("data", {})
                    self.tray_icon.set_privacy_state(
                        PrivacySensingState(
                            camera_state=p_data.get("camera_state", "INACTIVE"),
                            screen_state=p_data.get("screen_state", "INACTIVE"),
                            mic_state=p_data.get("mic_state", "IDLE"),
                            ocr_state=p_data.get("ocr_state", "READY"),
                            vlm_state=p_data.get("vlm_state", "IDLE"),
                            kill_switch_active=kill_switch.is_active(),
                        )
                    )

            except Exception as exc:
                logger.debug(f"AuraTrayApplication: State sync notice: {exc}")
                if not kill_switch.is_active():
                    self.tray_icon.set_state(TrayRuntimeState.DEGRADED)

            time.sleep(1.0)

    def run(self) -> None:
        """Start background sync and run the Win32 message pump."""
        self._running = True
        self._sync_thread = threading.Thread(target=self._state_sync_loop, daemon=True)
        self._sync_thread.start()

        # Run STA message pump on main thread
        self.tray_icon.create_window_and_run()

    def shutdown(self) -> None:
        """Clean application shutdown."""
        self._running = False
        self.tray_icon.stop()
        logger.info("AuraTrayApplication: Shutdown complete.")


def main():
    """Main process entrypoint with single-instance mutex enforcement."""
    mutex_handle = acquire_single_instance_mutex()
    if not mutex_handle:
        # Secondary instance detected, exit cleanly
        sys.exit(0)

    try:
        app = AuraTrayApplication()
        app.run()
    finally:
        if platform.system() == "Windows" and mutex_handle and mutex_handle != 1:
            try:
                ctypes.windll.kernel32.CloseHandle(mutex_handle)
            except Exception:
                pass


if __name__ == "__main__":
    main()
