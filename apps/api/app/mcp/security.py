"""MCP Subprocess Security Policy and Executable Boundary Enforcement."""

import os
from pathlib import Path
import re
import shutil
from typing import Dict, List, Optional
from app.core.errors import AuthorizationError, ValidationError
from app.core.logging import logger
from app.core.redaction import secret_redactor


class MCPSecurityPolicy:
    """Enforces execution boundaries and environment sanitization on MCP subprocesses."""

    # Approved runtime executables for local MCP servers
    APPROVED_EXECUTABLES = {
        "python", "python3", "python.exe", "python3.exe",
        "node", "node.exe",
        "npx", "npx.cmd", "npx.ps1",
        "uv", "uvx", "uv.exe", "uvx.exe",
        "deno", "deno.exe",
    }

    # Explicitly prohibited commands (Arbitrary shell invocation)
    PROHIBITED_COMMANDS = {
        "cmd", "cmd.exe",
        "powershell", "powershell.exe", "pwsh", "pwsh.exe",
        "sh", "bash", "zsh", "csh", "ksh",
        "sudo", "su",
        "curl", "wget", "nc", "netcat",
    }

    # Environment variables strictly stripped from MCP subprocesses
    PROHIBITED_ENV_PREFIXES = (
        "AURA_", "DATABASE_", "POSTGRES_", "JWT_", "SECRET_",
        "AWS_", "GOOGLE_", "GEMINI_", "OPENAI_", "ANTHROPIC_",
        "GITHUB_TOKEN", "SLACK_TOKEN",
    )

    @classmethod
    def validate_executable(cls, command: str) -> str:
        """Validate that the requested MCP command executable is permitted.

        Returns the resolved executable path or raises AuthorizationError.
        """
        if not command or not isinstance(command, str):
            raise ValidationError("MCP command cannot be empty")

        clean_cmd = command.strip()
        cmd_base = Path(clean_cmd).name.lower()

        # Check prohibited shell commands
        if cmd_base in cls.PROHIBITED_COMMANDS:
            logger.error(f"MCPSecurity: Prohibited shell interpreter requested: {command}")
            raise AuthorizationError(f"Execution of raw shell interpreter '{command}' as MCP server is prohibited")

        # Check if in approved executables
        if cmd_base in cls.APPROVED_EXECUTABLES:
            resolved_bin = shutil.which(clean_cmd)
            if resolved_bin:
                return resolved_bin
            return clean_cmd

        # If it's a specific binary path, verify it exists and is not an arbitrary shell
        if Path(clean_cmd).is_file():
            return clean_cmd

        logger.warning(f"MCPSecurity: Unrecognized MCP executable '{command}'. Rejecting.")
        raise AuthorizationError(f"Unapproved MCP executable '{command}'. Approved: {sorted(list(cls.APPROVED_EXECUTABLES))}")

    @classmethod
    def sanitize_environment(cls, user_env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """Strip sensitive host environment variables and merge safe user env vars."""
        # Start with standard clean base environment (PATH, SYSTEMROOT, TEMP)
        safe_keys = {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "HOME", "USERPROFILE", "LANG", "LC_ALL"}
        base_env = {k: v for k, v in os.environ.items() if k.upper() in safe_keys}

        # Filter out prohibited host variables
        filtered_env = {
            k: v for k, v in base_env.items()
            if not any(k.upper().startswith(p) for p in cls.PROHIBITED_ENV_PREFIXES)
        }

        # Merge user env vars after stripping prohibited keys and sensitive values
        if user_env:
            for k, v in user_env.items():
                k_upper = k.upper()
                if any(k_upper.startswith(p) for p in cls.PROHIBITED_ENV_PREFIXES):
                    logger.warning(f"MCPSecurity: Stripping prohibited user env var '{k}'")
                    continue
                if k.lower() in secret_redactor.SENSITIVE_KEY_NAMES:
                    logger.warning(f"MCPSecurity: Stripping sensitive user env var '{k}'")
                    continue
                filtered_env[k] = str(v)

        return filtered_env


mcp_security = MCPSecurityPolicy()
