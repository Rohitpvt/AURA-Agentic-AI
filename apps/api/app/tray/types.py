"""AURA-905 System Tray & Global Hotkeys Type Definitions."""

from enum import Enum
import time
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field


class TrayRuntimeState(str, Enum):
    """Authoritative runtime states visualizable in the system tray."""
    READY = "READY"
    AGENT_ACTIVE = "AGENT_ACTIVE"
    VOICE_ACTIVE = "VOICE_ACTIVE"
    CAMERA_ACTIVE = "CAMERA_ACTIVE"
    SCREEN_ACTIVE = "SCREEN_ACTIVE"
    KILL_SWITCHED = "KILL_SWITCHED"
    DEGRADED = "DEGRADED"
    STOPPED = "STOPPED"


class HotkeyRegistrationStatus(str, Enum):
    """Status of low-level Win32 global hotkey registration."""
    ACTIVE = "ACTIVE"
    UNAVAILABLE = "UNAVAILABLE"
    UNREGISTERED = "UNREGISTERED"
    ERROR = "ERROR"


class TrayIPCCommand(str, Enum):
    """Strict pre-approved command allowlist for Tray <-> Backend IPC."""
    GET_STATUS = "get_status"
    ACTIVATE_KILL_SWITCH = "activate_kill_switch"
    GET_PRIVACY_STATE = "get_privacy_state"
    GET_TELEMETRY = "get_telemetry"
    SHUTDOWN_TRAY = "shutdown_tray"


class PrivacySensingState(BaseModel):
    """Authoritative sensing privacy state indicators."""
    camera_state: str = Field(default="INACTIVE", description="Camera sensor state: ACTIVE, INACTIVE, STREAMING")
    screen_state: str = Field(default="INACTIVE", description="Screen sensing state: ACTIVE, INACTIVE, SCANNING")
    mic_state: str = Field(default="IDLE", description="Microphone audio state: IDLE, STREAMING, PROCESSING")
    ocr_state: str = Field(default="READY", description="Local OCR engine state: READY, SCANNING, IDLE")
    vlm_state: str = Field(default="IDLE", description="Local Moondream VLM state: IDLE, INFERRING, READY")
    kill_switch_active: bool = Field(default=False, description="Emergency kill switch active flag")
    timestamp: float = Field(default_factory=time.time, description="State evaluation timestamp")


class TrayIPCRequest(BaseModel):
    """Validated IPC request payload."""
    command: TrayIPCCommand = Field(..., description="Approved IPC command")
    token: str = Field(..., description="Shared local secret token for authentication")
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique request identifier")
    timestamp: float = Field(default_factory=time.time, description="Request generation timestamp")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Command parameters")


class TrayIPCResponse(BaseModel):
    """Validated IPC response payload."""
    status: str = Field(..., description="success or error")
    request_id: str = Field(..., description="Echo of request identifier")
    data: Dict[str, Any] = Field(default_factory=dict, description="Response payload")
    error: Optional[str] = Field(default=None, description="Error message if status is error")
    timestamp: float = Field(default_factory=time.time, description="Response generation timestamp")
