"""Filesystem Isolation and Path Traversal Defense Module.

Protects against:
- Directory traversal attacks (../, ..\\)
- Absolute path injection outside workspace
- Windows drive-letter escapes (C:\\, D:\\)
- Windows UNC network paths (\\\\server\\share)
- Null-byte injection (%00, \\x00)
- Symlink and NTFS junction point breakout
- Encoded traversal (%2e%2e%2f)
"""

import os
from pathlib import Path
import re
from typing import Optional, Union
import uuid
from app.core.config import settings
from app.core.errors import AuthorizationError, ValidationError
from app.core.logging import logger


class WorkspaceFilesystemGuard:
    """Enforces strict filesystem boundary isolation scoped to workspace root directories."""

    def __init__(self, base_workspace_dir: Optional[str] = None):
        self.base_dir = Path(base_workspace_dir or settings.WORKSPACE_ROOT_DIR).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def get_workspace_root(self, workspace_id: Union[str, uuid.UUID]) -> Path:
        """Resolve the canonical root directory for a specific workspace."""
        ws_str = str(workspace_id)
        # Validate workspace_id is safe hex/uuid string
        if not re.match(r"^[0-9a-fA-F\-]{1,64}$", ws_str):
            raise ValidationError(f"Invalid workspace ID format: '{ws_str}'")
        ws_path = (self.base_dir / ws_str).resolve()
        ws_path.mkdir(parents=True, exist_ok=True)
        return ws_path

    def validate_and_resolve_path(
        self,
        workspace_id: Union[str, uuid.UUID],
        target_path: str,
        must_exist: bool = False,
    ) -> Path:
        """Validate that a target path strictly resolves inside the designated workspace root.

        Raises ValidationError or AuthorizationError on any breakout attempt.
        """
        if not target_path or not isinstance(target_path, str):
            raise ValidationError("Target path cannot be empty")

        # 1. Reject Null-byte injection
        if "\x00" in target_path or "%00" in target_path:
            logger.error(f"FilesystemGuard: Null byte injection detected in path: {repr(target_path)}")
            raise ValidationError("Null byte injection detected in path")

        # 2. Reject Windows UNC paths (\\server\share)
        if target_path.startswith("\\\\") or target_path.startswith("//"):
            logger.error(f"FilesystemGuard: UNC network path escape detected: {target_path}")
            raise AuthorizationError("UNC network paths are prohibited")

        # 3. Reject Windows Drive Letter escapes (e.g. C:\Windows, D:\data)
        if re.match(r"^[a-zA-Z]:[\\/]", target_path):
            logger.error(f"FilesystemGuard: Absolute drive letter escape detected: {target_path}")
            raise AuthorizationError("Absolute drive letter paths are prohibited")

        # 4. Canonicalize workspace root
        ws_root = self.get_workspace_root(workspace_id)

        # 5. Handle relative path joining
        clean_target = target_path.strip()
        # Strip leading slashes to prevent root-relative override
        clean_target = clean_target.lstrip("/\\")

        # Construct candidate path
        candidate_path = (ws_root / clean_target).resolve()

        # 6. Verify candidate resolves inside ws_root (Handles symlinks and .. traversal)
        try:
            # Check relative_to
            candidate_path.relative_to(ws_root)
        except ValueError:
            logger.error(f"FilesystemGuard: Path traversal attempt detected! Candidate: {candidate_path}, Root: {ws_root}")
            raise AuthorizationError("Access denied: Path resolves outside authorized workspace boundary")

        # 7. Check if file must exist
        if must_exist and not candidate_path.exists():
            raise ValidationError(f"Target file does not exist: {target_path}")

        # 8. Check if realpath of existing path breaks out (NTFS junction points / symlink target check)
        if candidate_path.exists():
            real_path = Path(os.path.realpath(candidate_path))
            try:
                real_path.relative_to(ws_root)
            except ValueError:
                logger.error(f"FilesystemGuard: Symlink/Junction escape detected! Realpath: {real_path}, Root: {ws_root}")
                raise AuthorizationError("Access denied: Symlink points outside authorized workspace boundary")

        return candidate_path


filesystem_guard = WorkspaceFilesystemGuard()
