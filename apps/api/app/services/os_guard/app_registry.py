"""AURA-902 Canonical Application Registry & Allowlist Validation Engine.

Enforces:
1. Explicit application allowlist mapping (notepad, calc, mspaint, write)
2. Canonical executable identity verification & replacement defense
3. Structured argument validation (argument array, count, length, metacharacters, traversal, NUL)
4. Governed working directory policy & clean environment policy
5. Zero shell execution (shell=False strictly enforced)
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field

from app.services.os_guard.policy import LOLBINS_DENYLIST
from app.services.os_guard.types import OSRiskTier
from app.services.os_guard.validators import PathValidator


class ApplicationDefinition(BaseModel):
    """Canonical allowlisted application metadata."""

    application_id: str
    display_name: str
    canonical_executable_path: str
    max_argument_count: int = 2
    max_argument_length: int = 260
    allowed_argument_patterns: List[str] = Field(default_factory=list)
    working_directory_policy: str = "workspace"  # "workspace", "system", "none"
    environment_policy: str = "clean"  # "clean", "inherit_safe"
    risk_level: OSRiskTier = OSRiskTier.HIGH_RISK_SYSTEM_ACTION
    requires_hitl: bool = True


# Canonical System 32 / Windows Paths for benign productivity apps
_SYSTEM_ROOT = os.environ.get("SystemRoot", "C:\\Windows")
_SYSTEM32 = os.path.join(_SYSTEM_ROOT, "System32")

CANONICAL_ALLOWLIST: Dict[str, ApplicationDefinition] = {
    "notepad": ApplicationDefinition(
        application_id="notepad",
        display_name="Windows Notepad",
        canonical_executable_path=os.path.join(_SYSTEM32, "notepad.exe"),
        max_argument_count=2,
        max_argument_length=260,
        working_directory_policy="workspace",
        environment_policy="clean",
        risk_level=OSRiskTier.HIGH_RISK_SYSTEM_ACTION,
        requires_hitl=True,
    ),
    "calc": ApplicationDefinition(
        application_id="calc",
        display_name="Windows Calculator",
        canonical_executable_path=os.path.join(_SYSTEM32, "calc.exe"),
        max_argument_count=0,
        max_argument_length=0,
        working_directory_policy="none",
        environment_policy="clean",
        risk_level=OSRiskTier.HIGH_RISK_SYSTEM_ACTION,
        requires_hitl=True,
    ),
    "mspaint": ApplicationDefinition(
        application_id="mspaint",
        display_name="Paint",
        canonical_executable_path=os.path.join(_SYSTEM32, "mspaint.exe"),
        max_argument_count=2,
        max_argument_length=260,
        working_directory_policy="workspace",
        environment_policy="clean",
        risk_level=OSRiskTier.HIGH_RISK_SYSTEM_ACTION,
        requires_hitl=True,
    ),
    "write": ApplicationDefinition(
        application_id="write",
        display_name="WordPad / Write",
        canonical_executable_path=os.path.join(_SYSTEM32, "write.exe"),
        max_argument_count=2,
        max_argument_length=260,
        working_directory_policy="workspace",
        environment_policy="clean",
        risk_level=OSRiskTier.HIGH_RISK_SYSTEM_ACTION,
        requires_hitl=True,
    ),
}

# Dangerous Shell Metacharacters (Prohibited in arguments)
SHELL_METACHARS_REGEX = re.compile(r'[\&\|\;\>\<\`\$\%]')


class ApplicationRegistry:
    """Manages allowlisted application registry and launch parameter validation."""

    def __init__(self, allowlist: Optional[Dict[str, ApplicationDefinition]] = None):
        self._allowlist: Dict[str, ApplicationDefinition] = dict(allowlist or CANONICAL_ALLOWLIST)

    def get_application(self, application_id: str) -> Optional[ApplicationDefinition]:
        """Retrieve application definition by canonical ID."""
        if not application_id:
            return None
        return self._allowlist.get(application_id.strip().lower())

    def list_applications(self) -> List[Dict[str, Any]]:
        """List all allowlisted applications with safety metadata."""
        return [
            {
                "application_id": app.application_id,
                "display_name": app.display_name,
                "canonical_executable_path": app.canonical_executable_path,
                "max_argument_count": app.max_argument_count,
                "risk_level": app.risk_level.value,
                "requires_hitl": app.requires_hitl,
            }
            for app in self._allowlist.values()
        ]

    def validate_launch_request(
        self,
        application_id: str,
        arguments: Optional[List[str]] = None,
        working_directory: Optional[str] = None,
        workspace_root: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[ApplicationDefinition], List[str], Optional[str]]:
        """Validate launch request against allowlist, argument constraints, and working directory.
        
        Returns:
            (is_valid, error_message, app_def, clean_arguments, clean_working_dir)
        """
        if not application_id or not application_id.strip():
            return False, "Application ID is required", None, [], None

        clean_app_id = application_id.strip().lower()
        app_def = self.get_application(clean_app_id)
        if not app_def:
            return (
                False,
                f"Application '{application_id}' is not in the approved application allowlist. Approved applications: {list(self._allowlist.keys())}",
                None,
                [],
                None,
            )

        # 1. Validate Executable Path Identity
        path_valid, canonical_path, path_err = PathValidator.validate_executable_path(
            app_def.canonical_executable_path,
            allowlist=[a.canonical_executable_path for a in self._allowlist.values()],
            check_file_exists=False,  # Checked dynamically at execution
        )
        if not path_valid:
            return False, f"Executable path validation failed: {path_err}", app_def, [], None

        # 2. Validate Arguments
        args_list = list(arguments or [])

        # Check argument count limit
        if len(args_list) > app_def.max_argument_count:
            return (
                False,
                f"Application '{app_def.application_id}' accepts at most {app_def.max_argument_count} arguments (received {len(args_list)})",
                app_def,
                [],
                None,
            )

        clean_args: List[str] = []
        for i, raw_arg in enumerate(args_list):
            if not isinstance(raw_arg, str):
                return False, f"Argument {i} must be a string", app_def, [], None

            # Reject NUL bytes
            if "\x00" in raw_arg:
                return False, f"Argument {i} contains dangerous NUL byte", app_def, [], None

            # Check argument length
            if len(raw_arg) > app_def.max_argument_length:
                return (
                    False,
                    f"Argument {i} exceeds maximum length ({len(raw_arg)} > {app_def.max_argument_length})",
                    app_def,
                    [],
                    None,
                )

            # Reject shell metacharacters
            if SHELL_METACHARS_REGEX.search(raw_arg):
                return (
                    False,
                    f"Argument {i} contains prohibited shell metacharacters (&, |, ;, >, <, `, $, %)",
                    app_def,
                    [],
                    None,
                )

            # Reject path traversal in arguments
            if ".." in raw_arg:
                return False, f"Argument {i} contains prohibited path traversal sequence ('..')", app_def, [], None

            # Check argument against LOLBins (prevent passing powershell as argument to another binary)
            arg_basename = os.path.basename(raw_arg).lower()
            if arg_basename in LOLBINS_DENYLIST:
                return False, f"Argument {i} references prohibited LOLBin '{arg_basename}'", app_def, [], None

            clean_args.append(raw_arg.strip())

        # 3. Validate Working Directory
        clean_work_dir: Optional[str] = None
        if working_directory and working_directory.strip():
            raw_wd = working_directory.strip()
            if ".." in raw_wd:
                return False, "Working directory contains path traversal ('..')", app_def, [], None
            if "\x00" in raw_wd:
                return False, "Working directory contains NUL byte", app_def, [], None

            try:
                clean_work_dir = os.path.abspath(os.path.normpath(raw_wd))
            except Exception as e:
                return False, f"Invalid working directory path: {e}", app_def, [], None

            # If workspace root provided, ensure working directory is inside workspace
            if workspace_root:
                norm_root = os.path.abspath(os.path.normpath(workspace_root))
                if not clean_work_dir.startswith(norm_root):
                    return (
                        False,
                        f"Working directory '{clean_work_dir}' is outside authorized workspace root '{norm_root}'",
                        app_def,
                        [],
                        None,
                    )
        elif app_def.working_directory_policy == "workspace" and workspace_root:
            clean_work_dir = os.path.abspath(os.path.normpath(workspace_root))

        return True, "", app_def, clean_args, clean_work_dir


application_registry = ApplicationRegistry()
