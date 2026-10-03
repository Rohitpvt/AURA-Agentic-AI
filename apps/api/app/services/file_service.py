"""Universal File Intake, Secure Registry & Idempotent Deletion Service."""

from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import re
import shutil
from typing import Any, Dict, List, Optional, Tuple
import uuid

from fastapi import UploadFile
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AuthorizationError, EntityNotFoundError, ValidationError
from app.core.filesystem import filesystem_guard
from app.core.logging import logger
from app.core.telemetry import telemetry_manager
from app.db.models.file import FileChunk, FileRecord, FileStatus
from app.db.models.memory import MemoryRecord
from app.schemas.file import FileChunkResponse, FileDeleteResponse, FileRecordResponse, FileReconcileResponse, FileUploadResponse
from app.services.audit_service import AuditLedgerService

audit_ledger = AuditLedgerService()


class FileService:
    """Enterprise file intake, registry management, storage isolation, and deletion lifecycle."""

    MAX_UPLOAD_BYTES: int = 50 * 1024 * 1024  # 50 MB
    CHUNK_SIZE: int = 64 * 1024  # 64 KB streaming buffer

    # Known magic byte signatures
    MAGIC_SIGNATURES: Dict[str, bytes] = {
        "pdf": b"%PDF-",
        "png": b"\x89PNG\r\n\x1a\n",
        "jpg": b"\xff\xd8\xff",
        "jpeg": b"\xff\xd8\xff",
        "zip": b"PK\x03\x04",
        "docx": b"PK\x03\x04",
        "xlsx": b"PK\x03\x04",
        "pptx": b"PK\x03\x04",
    }

    # Prohibited executable headers disguised as document files
    EXECUTABLE_SIGNATURES: List[Tuple[str, bytes]] = [
        ("DOS/PE Executable", b"MZ"),
        ("ELF Binary", b"\x7fELF"),
    ]

    # Windows reserved device names
    WINDOWS_RESERVED_NAMES = {
        "CON", "PRN", "AUX", "NUL",
        "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
        "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"
    }

    def sanitize_filename(self, filename: str) -> Tuple[str, str]:
        """Sanitize client-provided filename into a safe, alphanumeric-bounded name and normalized extension."""
        if not filename or not isinstance(filename, str):
            filename = "unnamed_file"

        # 1. Strip directory traversal tokens and backslashes
        cleaned = re.sub(r"[\\/]+", "_", filename.strip())
        cleaned = re.sub(r"\x00|%00", "", cleaned)  # null byte strip

        # 2. Extract base and extension
        p = Path(cleaned)
        raw_ext = p.suffix.lower()
        # Clean extension: only allow alphanumeric up to 10 chars
        clean_ext = re.sub(r"[^a-z0-9]", "", raw_ext)
        ext = f".{clean_ext}" if clean_ext else ""

        stem = p.stem
        # Clean stem: allow alphanumeric, underscore, hyphen, dot
        clean_stem = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", stem)
        clean_stem = re.sub(r"_+", "_", clean_stem).strip("_.")
        if not clean_stem:
            clean_stem = "file"

        # Check Windows reserved names
        if clean_stem.upper() in self.WINDOWS_RESERVED_NAMES:
            clean_stem = f"{clean_stem}_safe"

        # Bounded stem length
        clean_stem = clean_stem[:80]
        safe_name = f"{clean_stem}{ext}" if ext else clean_stem
        return safe_name, ext

    def detect_and_screen_file(
        self,
        header_bytes: bytes,
        declared_mime: str,
        ext: str
    ) -> Tuple[str, List[str]]:
        """Screen initial magic bytes for executable disguises and validate against declared MIME."""
        security_flags: List[str] = []
        normalized_ext = ext.lstrip(".").lower()

        # 1. Check for disguised executables
        for name, sig in self.EXECUTABLE_SIGNATURES:
            if header_bytes.startswith(sig) and normalized_ext not in ["exe", "bin", "dll"]:
                logger.warning(f"FileService: Disguised {name} detected in upload with extension '{ext}'")
                security_flags.append(f"SUSPICIOUS_EXECUTABLE_SIGNATURE_{name.replace('/', '_').replace(' ', '_').upper()}")

        # 2. Signature-to-MIME verification
        detected_mime = declared_mime or "application/octet-stream"

        if header_bytes.startswith(b"%PDF-"):
            detected_mime = "application/pdf"
        elif header_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            detected_mime = "image/png"
        elif header_bytes.startswith(b"\xff\xd8\xff"):
            detected_mime = "image/jpeg"
        elif header_bytes.startswith(b"PK\x03\x04") or header_bytes.startswith(b"PK\x05\x06") or header_bytes.startswith(b"PK\x07\x08"):
            if normalized_ext == "docx":
                detected_mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            elif normalized_ext == "xlsx":
                detected_mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            elif normalized_ext == "pptx":
                detected_mime = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
            else:
                detected_mime = "application/zip"
        elif header_bytes.startswith(b"RIFF") and b"WAVE" in header_bytes[:16]:
            detected_mime = "audio/wav"
        elif header_bytes.startswith(b"ID3") or (len(header_bytes) >= 2 and header_bytes[0] == 0xFF and (header_bytes[1] & 0xE0) == 0xE0):
            detected_mime = "audio/mpeg"
        else:
            # Fallback for plain text / code / CSV
            try:
                header_bytes.decode("utf-8")
                if normalized_ext in ["csv"]:
                    detected_mime = "text/csv"
                elif normalized_ext in ["md", "markdown"]:
                    detected_mime = "text/markdown"
                elif normalized_ext in ["json"]:
                    detected_mime = "application/json"
                elif normalized_ext in ["py", "js", "ts", "rs", "go", "java", "c", "cpp", "html", "css", "sql"]:
                    detected_mime = "text/plain"
                elif not declared_mime or declared_mime == "application/octet-stream":
                    detected_mime = "text/plain"
            except UnicodeDecodeError:
                pass

        return detected_mime, security_flags

    async def upload_file(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        user_id: Optional[uuid.UUID],
        file: UploadFile,
        ip_address: Optional[str] = None,
    ) -> FileUploadResponse:
        """Stream an uploaded file to workspace storage, calculate SHA-256, deduplicate, and register."""
        original_name = file.filename or "unnamed_file"
        safe_name, ext = self.sanitize_filename(original_name)
        file_id = uuid.uuid4()

        # Workspace root resolution & verification
        ws_root = filesystem_guard.get_workspace_root(workspace_id)
        tmp_dir = ws_root / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = tmp_dir / f"upload_{file_id}.tmp"

        sha256 = hashlib.sha256()
        total_bytes = 0
        header_sample = bytearray()

        try:
            with open(tmp_path, "wb") as f_out:
                while True:
                    chunk = await file.read(self.CHUNK_SIZE)
                    if not chunk:
                        break

                    total_bytes += len(chunk)
                    if total_bytes > self.MAX_UPLOAD_BYTES:
                        logger.warning(
                            f"FileService: Upload aborted. Size {total_bytes} exceeded limit {self.MAX_UPLOAD_BYTES}"
                        )
                        raise ValidationError(
                            f"File size exceeds maximum upload limit of 50 MB ({self.MAX_UPLOAD_BYTES} bytes)"
                        )

                    sha256.update(chunk)
                    if len(header_sample) < 512:
                        needed = 512 - len(header_sample)
                        header_sample.extend(chunk[:needed])

                    f_out.write(chunk)

            if total_bytes == 0:
                raise ValidationError("Uploaded file is empty (0 bytes)")

            content_hash = sha256.hexdigest()
            mime_type, security_flags = self.detect_and_screen_file(
                bytes(header_sample), file.content_type or "application/octet-stream", ext
            )

            # Check for intra-workspace duplicate
            stmt_dupe = select(FileRecord).where(
                FileRecord.workspace_id == workspace_id,
                FileRecord.sha256_hash == content_hash,
                FileRecord.deleted_at.is_(None),
                FileRecord.status != FileStatus.DELETED.value,
            )
            res_dupe = await db.execute(stmt_dupe)
            existing = res_dupe.scalars().first()

            if existing:
                logger.info(
                    f"FileService: Content-duplicate detected for file {file_id} matching existing file {existing.id}"
                )
                if tmp_path.exists():
                    tmp_path.unlink(missing_ok=True)

                await audit_ledger.record_event(
                    db=db,
                    workspace_id=workspace_id,
                    actor_type="user" if user_id else "system",
                    actor_id=str(user_id) if user_id else "system",
                    action="file.duplicate_detected",
                    resource_type="file",
                    resource_id=str(existing.id),
                    details={
                        "original_filename": original_name,
                        "existing_file_id": str(existing.id),
                        "sha256_hash": content_hash,
                        "size_bytes": total_bytes,
                    },
                    ip_address=ip_address,
                )

                resp = self._to_record_response(existing)
                return FileUploadResponse(
                    file=resp,
                    is_duplicate=True,
                    message="File with identical content already registered in workspace",
                )

            # Move to canonical storage destination: {workspace_root}/files/{file_id}/{safe_name}
            storage_rel_path = f"files/{file_id}/{safe_name}"
            final_path = filesystem_guard.validate_and_resolve_path(workspace_id, storage_rel_path)
            final_path.parent.mkdir(parents=True, exist_ok=True)

            shutil.move(str(tmp_path), str(final_path))

            initial_status = (
                FileStatus.QUARANTINED.value
                if any("SUSPICIOUS" in f for f in security_flags)
                else FileStatus.UPLOADED.value
            )

            record = FileRecord(
                id=file_id,
                workspace_id=workspace_id,
                uploaded_by=user_id,
                original_filename=original_name,
                safe_filename=safe_name,
                mime_type=mime_type,
                file_extension=ext,
                size_bytes=total_bytes,
                sha256_hash=content_hash,
                storage_path=storage_rel_path,
                status=initial_status,
                metadata_={
                    "intake_timestamp": datetime.now(timezone.utc).isoformat(),
                    "client_declared_mime": file.content_type,
                },
                security_flags=security_flags,
            )
            db.add(record)
            await db.commit()
            await db.refresh(record)

            await audit_ledger.record_event(
                db=db,
                workspace_id=workspace_id,
                actor_type="user" if user_id else "system",
                actor_id=str(user_id) if user_id else "system",
                action="file.uploaded",
                resource_type="file",
                resource_id=str(file_id),
                details={
                    "original_filename": original_name,
                    "safe_filename": safe_name,
                    "size_bytes": total_bytes,
                    "sha256_hash": content_hash,
                    "mime_type": mime_type,
                    "security_flags": security_flags,
                },
                ip_address=ip_address,
            )

            resp = self._to_record_response(record)
            return FileUploadResponse(
                file=resp,
                is_duplicate=False,
                message="File uploaded and registered successfully",
            )

        except Exception as e:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            if not isinstance(e, (ValidationError, AuthorizationError)):
                logger.error(f"FileService: Unexpected error during upload: {str(e)}", exc_info=True)
            raise

    async def get_file(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        file_id: uuid.UUID,
    ) -> FileRecord:
        """Fetch file record verifying workspace ownership."""
        stmt = select(FileRecord).where(
            FileRecord.id == file_id,
            FileRecord.workspace_id == workspace_id,
            FileRecord.deleted_at.is_(None),
        )
        res = await db.execute(stmt)
        record = res.scalars().first()
        if not record:
            raise EntityNotFoundError("FileRecord", str(file_id))
        return record

    async def list_files(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        status: Optional[str] = None,
        mime_type: Optional[str] = None,
        search: Optional[str] = None,
        page: int = 1,
        limit: int = 20,
    ) -> Tuple[List[FileRecordResponse], int]:
        """List files for a workspace with pagination and filters."""
        base_stmt = select(FileRecord).where(
            FileRecord.workspace_id == workspace_id,
            FileRecord.deleted_at.is_(None),
        )

        if status:
            base_stmt = base_stmt.where(FileRecord.status == status)
        if mime_type:
            base_stmt = base_stmt.where(FileRecord.mime_type.ilike(f"%{mime_type}%"))
        if search:
            base_stmt = base_stmt.where(FileRecord.original_filename.ilike(f"%{search}%"))

        count_stmt = select(func.count()).select_from(base_stmt.subquery())
        total_count = (await db.execute(count_stmt)).scalar() or 0

        offset = max(0, (page - 1) * limit)
        paginated_stmt = base_stmt.order_by(FileRecord.created_at.desc()).offset(offset).limit(limit)
        res = await db.execute(paginated_stmt)
        records = res.scalars().all()

        return [self._to_record_response(r) for r in records], total_count

    async def delete_file(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        file_id: uuid.UUID,
        actor_id: str = "user",
        ip_address: Optional[str] = None,
    ) -> FileDeleteResponse:
        """Execute the idempotent deletion lifecycle state machine for a file."""
        stmt = select(FileRecord).where(
            FileRecord.id == file_id,
            FileRecord.workspace_id == workspace_id,
        )
        res = await db.execute(stmt)
        record = res.scalars().first()

        if not record or record.deleted_at is not None or record.status == FileStatus.DELETED.value:
            logger.info(f"FileService: Idempotent delete for non-existent or already deleted file {file_id}")
            return FileDeleteResponse(
                file_id=file_id,
                status="already_deleted",
                purged_storage=False,
                purged_chunks=0,
                message="File is already deleted or does not exist",
            )

        # 1. State: DELETE_REQUESTED
        record.status = FileStatus.DELETE_REQUESTED.value
        await db.commit()

        # 2. State: STORAGE_PURGED
        purged_storage = False
        try:
            ws_root = filesystem_guard.get_workspace_root(workspace_id)
            file_dir = ws_root / "files" / str(file_id)
            if file_dir.exists() and file_dir.is_dir():
                shutil.rmtree(file_dir, ignore_errors=True)
                purged_storage = True
            record.status = FileStatus.STORAGE_PURGED.value
            await db.commit()
        except Exception as storage_err:
            logger.error(f"FileService: Failed to purge disk storage for {file_id}: {storage_err}")
            # Keep record in DELETE_REQUESTED so it can be retried

        # 3. State: VECTORS_PURGED (Cascade file_chunks)
        stmt_del_chunks = delete(FileChunk).where(FileChunk.file_id == file_id)
        chunk_res = await db.execute(stmt_del_chunks)
        purged_chunks = chunk_res.rowcount or 0
        record.status = FileStatus.VECTORS_PURGED.value
        await db.commit()

        # 4. State: MEMORY_TOMBSTONED (Tombstone memory records linked to this file)
        try:
            # Query memory records where source_type is file_intelligence explicitly linked to this file
            stmt_mem = (
                update(MemoryRecord)
                .where(
                    MemoryRecord.workspace_id == workspace_id,
                    MemoryRecord.source_type == "file_intelligence",
                    MemoryRecord.is_tombstoned.is_(False),
                    MemoryRecord.provenance["file_id"].as_string() == str(file_id),
                )
                .values(
                    is_tombstoned=True,
                    tombstoned_reason=f"Originating file {file_id} was deleted",
                )
            )
            await db.execute(stmt_mem)
            record.status = FileStatus.MEMORY_TOMBSTONED.value
            await db.commit()
        except Exception as mem_err:
            logger.warning(f"FileService: Memory tombstone pass completed with note: {mem_err}")

        # 5. State: AUDITED
        await audit_ledger.record_event(
            db=db,
            workspace_id=workspace_id,
            actor_type="user",
            actor_id=actor_id,
            action="file.deleted",
            resource_type="file",
            resource_id=str(file_id),
            details={
                "original_filename": record.original_filename,
                "sha256_hash": record.sha256_hash,
                "purged_storage": purged_storage,
                "purged_chunks": purged_chunks,
            },
            ip_address=ip_address,
        )
        record.status = FileStatus.AUDITED.value
        await db.commit()

        # 6. State: DELETED
        record.status = FileStatus.DELETED.value
        record.deleted_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(record)

        return FileDeleteResponse(
            file_id=file_id,
            status="deleted",
            purged_storage=purged_storage,
            purged_chunks=purged_chunks,
            message="File and derived artifacts purged successfully",
        )

    async def reconcile_orphans(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        actor_id: str = "system",
    ) -> FileReconcileResponse:
        """Scan workspace storage directory and reconcile orphaned folders against DB registry."""
        ws_root = filesystem_guard.get_workspace_root(workspace_id)
        files_base = ws_root / "files"
        files_base.mkdir(parents=True, exist_ok=True)

        orphaned_found = 0
        orphaned_purged = 0
        missing_storage = 0

        # 1. Inspect on-disk directories
        for entry in os.scandir(files_base):
            if entry.is_dir():
                folder_name = entry.name
                try:
                    folder_uuid = uuid.UUID(folder_name)
                except ValueError:
                    # Non-UUID folder in files/ root is unreferenced
                    shutil.rmtree(entry.path, ignore_errors=True)
                    orphaned_purged += 1
                    continue

                stmt = select(FileRecord).where(
                    FileRecord.id == folder_uuid,
                    FileRecord.workspace_id == workspace_id,
                    FileRecord.deleted_at.is_(None),
                    FileRecord.status != FileStatus.DELETED.value,
                )
                res = await db.execute(stmt)
                db_record = res.scalars().first()

                if not db_record:
                    orphaned_found += 1
                    shutil.rmtree(entry.path, ignore_errors=True)
                    orphaned_purged += 1

        # 2. Check active DB records for missing disk files
        stmt_active = select(FileRecord).where(
            FileRecord.workspace_id == workspace_id,
            FileRecord.deleted_at.is_(None),
            FileRecord.status.in_([FileStatus.UPLOADED.value, FileStatus.INDEXED.value]),
        )
        active_records = (await db.execute(stmt_active)).scalars().all()

        for rec in active_records:
            expected_dir = files_base / str(rec.id)
            if not expected_dir.exists():
                missing_storage += 1
                rec.error_message = "Physical storage file is missing"
                rec.status = FileStatus.FAILED.value

        await db.commit()

        await audit_ledger.record_event(
            db=db,
            workspace_id=workspace_id,
            actor_type="system",
            actor_id=actor_id,
            action="file.reconciled",
            resource_type="workspace",
            resource_id=str(workspace_id),
            details={
                "orphaned_directories_found": orphaned_found,
                "orphaned_directories_purged": orphaned_purged,
                "missing_storage_records": missing_storage,
            },
        )

        return FileReconcileResponse(
            workspace_id=workspace_id,
            orphaned_directories_found=orphaned_found,
            orphaned_directories_purged=orphaned_purged,
            missing_storage_records=missing_storage,
            reconciled_at=datetime.now(timezone.utc),
        )

    async def get_file_chunks(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        file_id: uuid.UUID,
        page: int = 1,
        limit: int = 50,
    ) -> Tuple[List[FileChunkResponse], int]:
        """Fetch paginated persisted chunks for a workspace file."""
        # Verify file exists
        await self.get_file(db, workspace_id, file_id)

        base_stmt = select(FileChunk).where(
            FileChunk.workspace_id == workspace_id,
            FileChunk.file_id == file_id,
        )

        count_stmt = select(func.count()).select_from(base_stmt.subquery())
        total_count = (await db.execute(count_stmt)).scalar() or 0

        offset = max(0, (page - 1) * limit)
        paginated_stmt = base_stmt.order_by(FileChunk.chunk_index.asc()).offset(offset).limit(limit)
        res = await db.execute(paginated_stmt)
        records = res.scalars().all()

        return [self._to_chunk_response(c) for c in records], total_count

    def _to_chunk_response(self, c: FileChunk) -> FileChunkResponse:
        """Convert FileChunk ORM model to Pydantic response."""
        return FileChunkResponse(
            id=c.id,
            workspace_id=c.workspace_id,
            file_id=c.file_id,
            chunk_index=c.chunk_index,
            chunk_text=c.chunk_text,
            token_count=c.token_count,
            source_location=c.source_location or {},
            created_at=c.created_at,
        )

    def _to_record_response(self, r: FileRecord) -> FileRecordResponse:
        """Convert ORM model to Pydantic response."""
        return FileRecordResponse(
            id=r.id,
            workspace_id=r.workspace_id,
            uploaded_by=r.uploaded_by,
            original_filename=r.original_filename,
            safe_filename=r.safe_filename,
            mime_type=r.mime_type,
            file_extension=r.file_extension,
            size_bytes=r.size_bytes,
            sha256_hash=r.sha256_hash,
            status=r.status,
            error_message=r.error_message,
            metadata=r.metadata_ or {},
            security_flags=r.security_flags or [],
            created_at=r.created_at,
            updated_at=r.updated_at,
        )


file_service = FileService()
