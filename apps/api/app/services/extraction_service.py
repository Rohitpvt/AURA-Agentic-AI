"""Universal File Extraction Management Service (AURA-602).

Orchestrates:
1. File registry lookup and workspace tenant verification.
2. State transition: [UPLOADED / FAILED / INDEXED] -> PARSING -> INDEXED / FAILED / QUARANTINED.
3. Isolated in-process parser dispatching with 60s timeout.
4. Tamper-evident SHA-256 audit ledger recording.
5. Prompt sanitization envelope wrapping of untrusted extracted text.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AuthorizationError, EntityNotFoundError, ValidationError
from app.core.filesystem import filesystem_guard
from app.core.logging import logger
from app.db.models.file import FileRecord, FileStatus
from app.schemas.file import NormalizedExtractionResult
from app.services.audit_service import AuditLedgerService
from app.services.extractors.parser_registry import parser_registry

audit_ledger = AuditLedgerService()


class ExtractionService:
    """Service orchestrating multi-format extraction, status updates, and audit tracking."""

    async def extract_file_record(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        file_id: uuid.UUID,
        options: Optional[Dict[str, Any]] = None,
        actor_id: str = "system",
        ip_address: Optional[str] = None,
    ) -> NormalizedExtractionResult:
        """Execute safe extraction on a registered file record and update its state."""
        options = options or {}

        # 1. Fetch file record verifying workspace ownership
        stmt = select(FileRecord).where(
            FileRecord.id == file_id,
            FileRecord.workspace_id == workspace_id,
            FileRecord.deleted_at.is_(None),
        )
        res = await db.execute(stmt)
        record = res.scalars().first()

        if not record:
            raise EntityNotFoundError("FileRecord", str(file_id))

        if record.status == FileStatus.DELETED.value:
            raise ValidationError(f"Cannot extract deleted file {file_id}")

        # Check for quarantined executable disguises
        if record.status == FileStatus.QUARANTINED.value and any("SUSPICIOUS_EXECUTABLE" in f for f in record.security_flags):
            return NormalizedExtractionResult(
                file_id=file_id,
                filename=record.original_filename,
                mime_type=record.mime_type,
                file_extension=record.file_extension,
                parser_name="quarantine_guard",
                parser_version="1.0.0",
                status="quarantined",
                extracted_text="",
                sanitized_envelope="<untrusted_external_content>\n[QUARANTINED EXECUTABLE]\n</untrusted_external_content>",
                metadata={"quarantined": True},
                content_items=[],
                warnings=["File is quarantined due to suspicious executable signatures. Parsing is blocked."],
                security_flags=record.security_flags,
                error_message="Extraction blocked for quarantined file.",
            )

        # 2. State transition: PARSING
        record.status = FileStatus.PARSING.value
        record.error_message = None
        await db.commit()

        # 3. Resolve physical file path
        try:
            physical_path = filesystem_guard.validate_and_resolve_path(workspace_id, record.storage_path)
            if not physical_path.exists() or not physical_path.is_file():
                record.status = FileStatus.FAILED.value
                record.error_message = "Physical storage file is missing on disk"
                await db.commit()
                return NormalizedExtractionResult(
                    file_id=file_id,
                    filename=record.original_filename,
                    mime_type=record.mime_type,
                    file_extension=record.file_extension,
                    parser_name="filesystem_guard",
                    parser_version="1.0.0",
                    status="failed",
                    extracted_text="",
                    sanitized_envelope="<untrusted_external_content>\n[MISSING FILE]\n</untrusted_external_content>",
                    metadata={},
                    content_items=[],
                    warnings=["Physical storage file is missing."],
                    security_flags=[],
                    error_message="Physical storage file is missing on disk",
                )
        except Exception as path_err:
            record.status = FileStatus.FAILED.value
            record.error_message = f"Path resolution error: {str(path_err)}"
            await db.commit()
            raise

        # 4. Dispatch to Parser Registry
        result = await parser_registry.extract(
            file_path=physical_path,
            filename=record.original_filename,
            mime_type=record.mime_type,
            ext=record.file_extension,
            options=options,
        )
        result.file_id = file_id

        # 5. Update Database Record Status and Metadata
        merged_flags = list(set((record.security_flags or []) + (result.security_flags or [])))
        record.security_flags = merged_flags

        existing_meta = dict(record.metadata_ or {})
        existing_meta["extraction_summary"] = {
            "parser_name": result.parser_name,
            "parser_version": result.parser_version,
            "status": result.status,
            "total_chars": result.total_chars,
            "is_truncated": result.is_truncated,
            "items_count": len(result.content_items),
            "warnings_count": len(result.warnings),
            "extracted_at": datetime.now(timezone.utc).isoformat(),
        }
        if result.metadata:
            existing_meta["document_metadata"] = result.metadata

        record.metadata_ = existing_meta

        if result.status in ["extracted", "partially_extracted", "no_text_extracted"]:
            record.status = FileStatus.INDEXED.value
        elif result.status == "quarantined":
            record.status = FileStatus.QUARANTINED.value
        else:
            record.status = FileStatus.FAILED.value
            record.error_message = result.error_message

        await db.commit()
        await db.refresh(record)

        # 6. Record Tamper-Evident SHA-256 Audit Event
        await audit_ledger.record_event(
            db=db,
            workspace_id=workspace_id,
            actor_type="user" if actor_id != "system" else "system",
            actor_id=actor_id,
            action="file.extracted",
            resource_type="file",
            resource_id=str(file_id),
            details={
                "parser_name": result.parser_name,
                "status": result.status,
                "total_chars": result.total_chars,
                "is_truncated": result.is_truncated,
                "items_count": len(result.content_items),
                "warnings": result.warnings,
            },
            ip_address=ip_address,
        )

        return result


extraction_service = ExtractionService()
