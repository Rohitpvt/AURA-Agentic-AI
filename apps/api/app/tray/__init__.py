"""AURA-905 System Tray & Global Emergency Hotkey Package."""

from app.tray.hotkey import GlobalHotkeyManager
from app.tray.ipc import AuraIpcAuthManager, AuraNamedPipeClient, AuraNamedPipeServer
from app.tray.main import AuraTrayApplication
from app.tray.tray_icon import WindowsTrayIcon
from app.tray.types import (
    HotkeyRegistrationStatus,
    PrivacySensingState,
    TrayIPCCommand,
    TrayIPCRequest,
    TrayIPCResponse,
    TrayRuntimeState,
)

__all__ = [
    "AuraIpcAuthManager",
    "AuraNamedPipeClient",
    "AuraNamedPipeServer",
    "AuraTrayApplication",
    "GlobalHotkeyManager",
    "HotkeyRegistrationStatus",
    "PrivacySensingState",
    "TrayIPCCommand",
    "TrayIPCRequest",
    "TrayIPCResponse",
    "TrayRuntimeState",
    "WindowsTrayIcon",
]
