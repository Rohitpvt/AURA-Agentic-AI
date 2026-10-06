"""Governed Browser Download & Upload Pipeline (AURA-1004).

Connects Playwright browser file transfers to Phase 6 Universal File Intake & Intelligence:
- Governed isolated quarantine downloads ({workspace}/downloads/.incoming_{uuid}/)
- Zero arbitrary host path access
- Automatic path traversal and disguise screening
- Bounded download sizes (<= 50 MB)
- Strict workspace-isolated upload authorization
- Sensitive file upload protection (.env, vault, keys, secrets)
- Complete provenance metadata and URL secret redaction
- Emergency kill-switch and action-budget enforcement
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import re
import shutil
import time
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from typing import Any, Dict, List, Optional, Tuple, Union
import uuid

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AuthorizationError, EntityNotFoundError, ValidationError
from app.core.filesystem import filesystem_guard
from app.core.logging import logger
from app.core.network import ssrf_guard
from app.db.models.file import FileRecord, FileStatus
from app.services.audit_service import AuditLedgerService
from app.services.browser.engine import browser_engine
from app.services.browser.governance import (
    action_budget_manager,
    freshness_store,
)
from app.services.browser.vault import normalize_origin
from app.services.file_service import FileService

audit_ledger = AuditLedgerService()
file_service = FileService()

MAX_DOWNLOAD_BYTES: int = 50 * 1024 * 1024  # 50 MB
DOWNLOAD_CHUNK_SIZE: int = 64 * 1024  # 64 KB

# Sensitive query parameter keys that must be redacted in audit / provenance URLs
SENSITIVE_URL_PARAM_PATTERNS = [
    re.compile(r"token", re.IGNORECASE),
    re.compile(r"auth", re.IGNORECASE),
    re.compile(r"key", re.IGNORECASE),
    re.compile(r"secret", re.IGNORECASE),
    re.compile(r"password", re.IGNORECASE),
    re.compile(r"pass", re.IGNORECASE),
    re.compile(r"session", re.IGNORECASE),
    re.compile(r"sig", re.IGNORECASE),
    re.compile(r"signature", re.IGNORECASE),
    re.compile(r"api_?key", re.IGNORECASE),
]

# Prohibited sensitive files for browser uploads
SENSITIVE_FILE_PATTERNS = [
    re.compile(r"^\.env", re.IGNORECASE),
    re.compile(r"master[-_]?key", re.IGNORECASE),
    re.compile(r"credential", re.IGNORECASE),
    re.compile(r"vault", re.IGNORECASE),
    re.compile(r"session", re.IGNORECASE),
    re.compile(r"id_rsa", re.IGNORECASE),
    re.compile(r"id_ed25519", re.IGNORECASE),
    re.compile(r"\.(key|pem|p12|pfx|pkcs12|sqlite|db|sqlite3|token|secret)$", re.IGNORECASE),
]


def _check_kill_switch(workspace_id: uuid.UUID) -> None:
    """Verify emergency kill switch state."""
    from app.services.kill_switch import kill_switch
    if kill_switch.is_active(workspace_id):
        raise AuthorizationError(f"Emergency Kill Switch is active for workspace {workspace_id}.")


def sanitize_url_provenance(url: str) -> str:
    """Redact sensitive query parameter values from URL for safe logging and provenance."""
    if not url or not isinstance(url, str):
        return ""
    try:
        parsed = urlparse(url)
        if not parsed.query:
            return url

        query_params = parse_qsl(parsed.query, keep_blank_values=True)
        sanitized_params: List[Tuple[str, str]] = []

        for k, v in query_params:
            is_sensitive = any(pat.search(k) for pat in SENSITIVE_URL_PARAM_PATTERNS)
            if is_sensitive:
                sanitized_params.append((k, "[REDACTED]"))
            else:
                sanitized_params.append((k, v))

        sanitized_query = urlencode(sanitized_params)
        return urlunparse(parsed._replace(query=sanitized_query))
    except Exception:
        return url


def is_sensitive_file(filename: str) -> bool:
    """Check if filename matches sensitive denylist."""
    if not filename:
        return False
    base_name = os.path.basename(filename)
    return any(pat.search(base_name) for pat in SENSITIVE_FILE_PATTERNS)


class BrowserFileTransferService:
    """Governed browser download and upload pipeline linking browser automation to Phase 6."""

    async def download_file(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        url: Optional[str] = None,
        click_element_id: Optional[int] = None,
        tab_id: Optional[str] = None,
        suggested_filename: Optional[str] = None,
        task_id: Optional[str] = None,
        user_id: Optional[uuid.UUID] = None,
        ip_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Download file via URL stream or interactive click into isolated quarantine, then hand off to Phase 6."""
        _check_kill_switch(workspace_id)
        action_budget_manager.consume_action(workspace_id, task_id, "browser_download_file")

        # 1. Setup isolated quarantine directory
        ws_root = filesystem_guard.get_workspace_root(workspace_id)
        quarantine_id = uuid.uuid4()
        quarantine_dir = ws_root / "downloads" / f".incoming_{quarantine_id}"
        quarantine_dir.mkdir(parents=True, exist_ok=True)

        staged_file_path: Optional[Path] = None
        source_url_clean = ""
        final_url_clean = ""
        resolved_filename = suggested_filename or "downloaded_file"
        content_type_header: Optional[str] = None

        try:
            if url:
                # 2A. Direct URL Streaming Download
                parsed = urlparse(url)
                scheme = parsed.scheme.lower()
                if scheme not in {"http", "https"}:
                    raise ValidationError(f"Disallowed download URL scheme '{scheme}'. Only http and https are permitted.")

                ssrf_guard.validate_url(url)
                source_url_clean = sanitize_url_provenance(url)

                # Extract filename candidate from URL path if not explicitly provided
                if not suggested_filename:
                    url_path = parsed.path.strip("/")
                    if url_path:
                        last_segment = url_path.split("/")[-1]
                        if last_segment:
                            resolved_filename = last_segment

                safe_temp_stem, _ = file_service.sanitize_filename(resolved_filename)
                staged_file_path = quarantine_dir / f"staged_{safe_temp_stem}"

                total_bytes = 0
                async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                    async with client.stream("GET", url) as resp:
                        if resp.status_code >= 400:
                            raise ValidationError(f"Download failed with HTTP status {resp.status_code}")

                        # Check redirect destination
                        final_url = str(resp.url)
                        final_url_clean = sanitize_url_provenance(final_url)
                        ssrf_guard.validate_url(final_url)

                        content_type_header = resp.headers.get("content-type")
                        content_disp = resp.headers.get("content-disposition", "")
                        if "filename=" in content_disp and not suggested_filename:
                            m = re.search(r'filename=["\']?([^"\';]+)["\']?', content_disp)
                            if m:
                                resolved_filename = m.group(1).strip()
                                safe_temp_stem, _ = file_service.sanitize_filename(resolved_filename)
                                staged_file_path = quarantine_dir / f"staged_{safe_temp_stem}"

                        with open(staged_file_path, "wb") as f_out:
                            async for chunk in resp.aiter_bytes(DOWNLOAD_CHUNK_SIZE):
                                _check_kill_switch(workspace_id)
                                total_bytes += len(chunk)
                                if total_bytes > MAX_DOWNLOAD_BYTES:
                                    raise ValidationError(
                                        f"File size exceeds maximum download limit of 50 MB ({MAX_DOWNLOAD_BYTES} bytes)"
                                    )
                                f_out.write(chunk)

                if total_bytes == 0:
                    raise ValidationError("Downloaded file is empty (0 bytes)")

            elif click_element_id is not None or tab_id is not None:
                # 2B. Interactive Browser Download Event Capture
                ws_ctx = await browser_engine.get_or_create_workspace_context(workspace_id)
                target_tab_id = tab_id or ws_ctx.active_tab_id
                if not target_tab_id:
                    raise ValidationError("No active browser tab found for download trigger")

                page = ws_ctx.get_page(target_tab_id)
                source_url_clean = sanitize_url_provenance(page.url or "")
                final_url_clean = source_url_clean

                if click_element_id is not None:
                    node = freshness_store.get_element(workspace_id, target_tab_id, click_element_id)
                    # Trigger download via expect_download
                    async with page.expect_download(timeout=15000) as download_info:
                        await page.locator(f'[data-aura-id="{click_element_id}"]').click()
                    download = await download_info.value
                else:
                    raise ValidationError("Neither a direct URL nor click_element_id was provided for download")

                resolved_filename = download.suggested_filename or resolved_filename
                safe_temp_stem, _ = file_service.sanitize_filename(resolved_filename)
                staged_file_path = quarantine_dir / f"staged_{safe_temp_stem}"
                await download.save_as(str(staged_file_path))

            else:
                raise ValidationError("Must provide either 'url' or 'click_element_id' to execute browser download")

            # 3. Hand off Staged File to Phase 6 File Intake
            _check_kill_switch(workspace_id)

            provenance = {
                "source_url": source_url_clean,
                "final_url": final_url_clean,
                "tab_id": tab_id,
                "task_id": task_id,
                "quarantine_id": str(quarantine_id),
            }

            intake_res = await file_service.intake_staged_file(
                db=db,
                workspace_id=workspace_id,
                staged_path=staged_file_path,
                original_filename=resolved_filename,
                user_id=user_id,
                source_url=source_url_clean,
                declared_mime=content_type_header,
                provenance_metadata=provenance,
                ip_address=ip_address,
            )

            rec = intake_res.file
            return {
                "status": "success",
                "action": "download_file",
                "file_id": str(rec.id),
                "filename": rec.safe_filename,
                "original_filename": rec.original_filename,
                "size_bytes": rec.size_bytes,
                "mime_type": rec.mime_type,
                "sha256_hash": rec.sha256_hash,
                "is_quarantined": rec.status == FileStatus.QUARANTINED.value,
                "is_duplicate": intake_res.is_duplicate,
                "security_flags": rec.security_flags,
                "source_url": source_url_clean,
                "is_untrusted_content": True,
            }

        except Exception as e:
            if not isinstance(e, (ValidationError, AuthorizationError)):
                logger.error(f"BrowserFileTransfer: Download failed with unexpected error: {e}", exc_info=True)
            raise
        finally:
            # 4. Clean up temporary quarantine staging directory
            if quarantine_dir.exists():
                try:
                    shutil.rmtree(str(quarantine_dir), ignore_errors=True)
                except Exception as clean_err:
                    logger.debug(f"BrowserFileTransfer: Quarantine cleanup notice: {clean_err}")

    async def upload_file(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        file_id: Union[str, uuid.UUID],
        element_id: Optional[int] = None,
        selector: Optional[str] = None,
        tab_id: Optional[str] = None,
        task_id: Optional[str] = None,
        user_id: Optional[uuid.UUID] = None,
        ip_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Upload an authorized workspace file into an active webpage file input element."""
        _check_kill_switch(workspace_id)
        action_budget_manager.consume_action(workspace_id, task_id, "browser_upload_file")

        try:
            file_uuid = uuid.UUID(str(file_id))
        except Exception as e:
            raise ValidationError(f"Invalid file_id UUID format: '{file_id}'") from e

        # 1. Look up FileRecord in DB verifying workspace ownership
        stmt = select(FileRecord).where(
            FileRecord.id == file_uuid,
            FileRecord.workspace_id == workspace_id,
            FileRecord.deleted_at.is_(None),
        )
        res = await db.execute(stmt)
        record = res.scalars().first()

        if not record:
            raise EntityNotFoundError("FileRecord", str(file_uuid))

        if record.status in [FileStatus.DELETED.value, FileStatus.DELETE_REQUESTED.value]:
            raise ValidationError(f"Cannot upload deleted file {file_uuid}")

        # 2. Sensitive File Denylist Check
        if is_sensitive_file(record.original_filename) or is_sensitive_file(record.safe_filename):
            logger.warning(
                f"BrowserFileTransfer: Blocked attempt to upload sensitive file '{record.original_filename}' (ID: {file_uuid})"
            )
            raise AuthorizationError(
                f"Upload of sensitive file '{record.original_filename}' is strictly blocked by security policy."
            )

        # 3. Resolve physical file path within workspace root
        physical_path = filesystem_guard.validate_and_resolve_path(
            workspace_id=workspace_id,
            target_path=record.storage_path,
            must_exist=True,
        )

        # 4. Resolve Active Browser Tab and Page
        ws_ctx = await browser_engine.get_or_create_workspace_context(workspace_id)
        target_tab_id = tab_id or ws_ctx.active_tab_id
        if not target_tab_id:
            raise ValidationError("No active browser tab open for file upload")

        page = ws_ctx.get_page(target_tab_id)
        page_url = page.url or "about:blank"
        target_origin = normalize_origin(page_url) if not page_url.startswith("about:") else "about:blank"

        # 5. Locate File Input Element
        locator = None
        if element_id is not None:
            # Validate element freshness
            node = freshness_store.get_element(workspace_id, target_tab_id, element_id)
            locator = page.locator(f'[data-aura-id="{element_id}"]').first
        elif selector:
            locator = page.locator(selector).first
        else:
            locator = page.locator('input[type="file"]').first

        if not locator:
            raise ValidationError("Could not resolve target file input element on active page")

        # 6. Apply Native Playwright File Upload
        _check_kill_switch(workspace_id)
        try:
            await locator.set_input_files(str(physical_path))
        except Exception as up_err:
            raise ValidationError(f"Failed setting input files on target element: {up_err}") from up_err

        # Invalidate page observation freshness
        freshness_store.invalidate(workspace_id, target_tab_id)

        # 7. Record Audit Event
        await audit_ledger.record_event(
            db=db,
            workspace_id=workspace_id,
            actor_type="user" if user_id else "system",
            actor_id=str(user_id) if user_id else "system",
            action="browser.file_uploaded",
            resource_type="file",
            resource_id=str(file_uuid),
            details={
                "file_id": str(file_uuid),
                "safe_filename": record.safe_filename,
                "original_filename": record.original_filename,
                "size_bytes": record.size_bytes,
                "mime_type": record.mime_type,
                "tab_id": target_tab_id,
                "destination_origin": target_origin,
                "destination_url": sanitize_url_provenance(page_url),
            },
            ip_address=ip_address,
        )

        return {
            "status": "success",
            "action": "upload_file",
            "file_id": str(record.id),
            "filename": record.safe_filename,
            "size_bytes": record.size_bytes,
            "mime_type": record.mime_type,
            "tab_id": target_tab_id,
            "destination_origin": target_origin,
            "is_untrusted_content": True,
        }


# Global Singleton Instance
browser_file_transfer_service = BrowserFileTransferService()
