"""AURA-1006 Controlled, Explicit Opt-In User-Session Autostart Manager."""

import json
import os
from pathlib import Path
import platform
import sys
from typing import Any, Dict, Optional

from app.core.logging import logger

AURA_AUTOSTART_KEY_NAME = "AuraAgentSupervisor"
AURA_REG_RUN_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"


class AutostartManager:
    """Manages explicit, opt-in Windows HKCU autostart persistence with zero secret exposure."""

    def __init__(self, state_dir: Optional[Path] = None):
        self.state_dir = state_dir or (Path(os.environ.get("AURA_STATE_DIR", Path.home() / ".aura")))
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._mock_file = self.state_dir / "autostart_state.json"
        self.is_windows = platform.system() == "Windows"

    def is_autostart_enabled(self) -> bool:
        """Check if autostart is currently enabled for the interactive user."""
        if self.is_windows:
            try:
                import winreg
                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    AURA_REG_RUN_PATH,
                    0,
                    winreg.KEY_READ,
                ) as key:
                    val, _ = winreg.QueryValueEx(key, AURA_AUTOSTART_KEY_NAME)
                    return bool(val and len(str(val).strip()) > 0)
            except FileNotFoundError:
                return False
            except Exception as exc:
                logger.debug(f"AutostartManager: Error reading HKCU Run key: {exc}")
                return False
        else:
            if self._mock_file.exists():
                try:
                    data = json.loads(self._mock_file.read_text(encoding="utf-8"))
                    return bool(data.get("enabled", False))
                except Exception:
                    return False
            return False

    def enable_autostart(self, custom_command: Optional[str] = None) -> bool:
        """Explicitly enable autostart in the interactive user's HKCU Run registry key."""
        # 1. Resolve safe launcher command
        if custom_command:
            command = custom_command.strip()
        else:
            python_exe = sys.executable
            command = f'"{python_exe}" -m app.daemon.main --start'

        # 2. Security validation: Ensure no secret canary in command
        for forbidden in ["AURA_MASTER_ENCRYPTION_KEY", "JWT_SECRET", "token", "password", "PRIVATE KEY"]:
            if forbidden in command:
                raise ValueError(f"Autostart command contains forbidden secret pattern: {forbidden}")

        if self.is_windows:
            try:
                import winreg
                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    AURA_REG_RUN_PATH,
                    0,
                    winreg.KEY_WRITE,
                ) as key:
                    winreg.SetValueEx(
                        key,
                        AURA_AUTOSTART_KEY_NAME,
                        0,
                        winreg.REG_SZ,
                        command,
                    )
                logger.info(f"AutostartManager: Enabled autostart in HKCU Run: {command}")
                return True
            except Exception as exc:
                logger.error(f"AutostartManager: Failed enabling autostart in HKCU: {exc}")
                return False
        else:
            try:
                self._mock_file.write_text(json.dumps({"enabled": True, "command": command}), encoding="utf-8")
                return True
            except Exception as exc:
                logger.error(f"AutostartManager: Failed saving mock autostart state: {exc}")
                return False

    def disable_autostart(self) -> bool:
        """Explicitly disable autostart, removing the HKCU Run registry value cleanly."""
        if self.is_windows:
            try:
                import winreg
                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    AURA_REG_RUN_PATH,
                    0,
                    winreg.KEY_WRITE,
                ) as key:
                    try:
                        winreg.DeleteValue(key, AURA_AUTOSTART_KEY_NAME)
                        logger.info("AutostartManager: Disabled autostart (deleted HKCU Run value)")
                    except FileNotFoundError:
                        pass
                return True
            except Exception as exc:
                logger.error(f"AutostartManager: Error deleting HKCU Run value: {exc}")
                return False
        else:
            try:
                if self._mock_file.exists():
                    self._mock_file.unlink(missing_ok=True)
                return True
            except Exception:
                return False

    def get_autostart_status(self) -> Dict[str, Any]:
        """Return truthful autostart configuration metadata."""
        enabled = self.is_autostart_enabled()
        command = None

        if enabled:
            if self.is_windows:
                try:
                    import winreg
                    with winreg.OpenKey(
                        winreg.HKEY_CURRENT_USER,
                        AURA_REG_RUN_PATH,
                        0,
                        winreg.KEY_READ,
                    ) as key:
                        val, _ = winreg.QueryValueEx(key, AURA_AUTOSTART_KEY_NAME)
                        command = str(val)
                except Exception:
                    pass
            else:
                if self._mock_file.exists():
                    try:
                        data = json.loads(self._mock_file.read_text(encoding="utf-8"))
                        command = data.get("command")
                    except Exception:
                        pass

        return {
            "enabled": enabled,
            "entry_type": "HKCU_RUN",
            "registry_path": f"HKEY_CURRENT_USER\\{AURA_REG_RUN_PATH}",
            "value_name": AURA_AUTOSTART_KEY_NAME,
            "command": command,
            "is_windows": self.is_windows,
        }
