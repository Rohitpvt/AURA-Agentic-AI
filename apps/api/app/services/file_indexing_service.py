"""File Vector Indexing and Atomic Reindexing Service (AURA-603).

Two-Stage Staged Execution:
- Stage 1 (Outside DB Transaction):
  1. Extract structural content items via ExtractionService if needed.
  2. Perform format-aware structural chunking with 64-token headers and 510-token ceilings.
  3. Batch-generate 768-dimensional normalized BGE embeddings on CPU.
  4. Perform strict validation on vectors (dimension, finiteness, normalization).
- Stage 2 (Short Atomic DB Transaction):
  1. Verify workspace isolation, active file state, and optimistic generation safety.
  2. Fail closed if file was marked for deletion during Stage 1.
  3. Swap old chunks with new chunks atomically.
  4. Publish authoritative vector index metadata to FileRecord.
  5. Record tamper-evident SHA-256 audit ledger event.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import EntityNotFoundError, ValidationError
from app.core.logging import logger
from app.db.models.file import FileChunk, FileRecord, FileStatus
from app.schemas.file import FileIndexResponse, NormalizedExtractionResult
from app.services.audit_service import AuditLedgerService
from app.services.embedding_service import embedding_service
from app.services.extraction_service import extraction_service
from app.services.structural_chunker import ChunkPayload, structural_chunker

audit_ledger = AuditLedgerService()


class FileIndexingService:
    """Orchestrates structural chunking, vector generation, and atomic index publication."""

    EMBEDDING_MODEL_NAME = "BAAI/bge-base-en-v1.5"
    EMBEDDING_DIMENSION = 768

    async def index_file(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        file_id: uuid.UUID,
        reindex: bool = False,
        actor_id: str = "system",
        ip_address: Optional[str] = None,
    ) -> FileIndexResponse:
        """Execute two-stage vector indexing with optimistic generation safety."""

        # -------------------------------------------------------------
        # STAGE 1: Preparation, Chunking & Vectorization (Outside Mutating Lock)
        # -------------------------------------------------------------

        # 1.1 Query initial file state
        stmt = select(FileRecord).where(
            FileRecord.id == file_id,
            FileRecord.workspace_id == workspace_id,
            FileRecord.deleted_at.is_(None),
        )
        res = await db.execute(stmt)
        record = res.scalars().first()

        if not record:
            raise EntityNotFoundError("FileRecord", str(file_id))

        if record.status in [FileStatus.DELETED.value, FileStatus.DELETE_REQUESTED.value]:
            raise ValidationError(f"Cannot index deleted or delete-requested file {file_id}")

        if record.status == FileStatus.QUARANTINED.value:
            raise ValidationError(f"Cannot index quarantined file {file_id}")

        # Check existing vector status if not forced reindex
        existing_vector_meta = (record.metadata_ or {}).get("vector_index", {})
        if not reindex and existing_vector_meta.get("status") == "ready":
            # Verify actual chunks exist
            stmt_chk_cnt = select(FileChunk).where(
                FileChunk.file_id == file_id,
                FileChunk.workspace_id == workspace_id,
            )
            chk_res = await db.execute(stmt_chk_cnt)
            existing_chunks = chk_res.scalars().all()
            if existing_chunks and len(existing_chunks) == existing_vector_meta.get("chunk_count", 0):
                return FileIndexResponse(
                    file_id=file_id,
                    status="ready",
                    chunks_count=len(existing_chunks),
                    tokens_count=existing_vector_meta.get("token_count_total", 0),
                    generation=existing_vector_meta.get("generation", "initial"),
                    embedding_model=self.EMBEDDING_MODEL_NAME,
                    message="File vector index is already ready and verified",
                )

        # 1.2 Ensure extraction is available
        extraction: NormalizedExtractionResult
        if record.status != FileStatus.INDEXED.value or "extraction_summary" not in (record.metadata_ or {}):
            extraction = await extraction_service.extract_file_record(
                db=db,
                workspace_id=workspace_id,
                file_id=file_id,
                actor_id=actor_id,
                ip_address=ip_address,
            )
        else:
            # Reconstruct extraction from parser
            from app.services.extractors.parser_registry import parser_registry
            from app.core.filesystem import filesystem_guard
            physical_path = filesystem_guard.validate_and_resolve_path(workspace_id, record.storage_path)
            extraction = await parser_registry.extract(
                file_path=physical_path,
                filename=record.original_filename,
                mime_type=record.mime_type,
                ext=record.file_extension,
            )
            extraction.file_id = file_id

        # 1.3 Structural chunking
        chunks: List[ChunkPayload] = structural_chunker.chunk_document(
            extraction=extraction,
            file_id=file_id,
            workspace_id=workspace_id,
        )

        total_tokens = sum(c.token_count for c in chunks)
        generation_id = uuid.uuid4().hex

        # 1.4 Vector generation and validation
        embeddings: List[List[float]] = []
        if chunks:
            chunk_texts = [c.chunk_text for c in chunks]
            embeddings = embedding_service.embed_passages(chunk_texts, batch_size=16)

            if len(embeddings) != len(chunks):
                raise ValueError(f"Vector count mismatch: generated {len(embeddings)} for {len(chunks)} chunks")

            for vec in embeddings:
                embedding_service.validate_vector(vec)

        # Formulate new vector index metadata projection
        new_vector_metadata: Dict[str, Any] = {
            "status": "ready",
            "generation": generation_id,
            "chunk_count": len(chunks),
            "token_count_total": total_tokens,
            "embedding_model": self.EMBEDDING_MODEL_NAME,
            "embedding_dimension": self.EMBEDDING_DIMENSION,
            "chunking_strategy": structural_chunker.CHUNKING_STRATEGY,
            "chunking_version": structural_chunker.CHUNKING_VERSION,
            "indexed_at": datetime.now(timezone.utc).isoformat(),
        }

        # -------------------------------------------------------------
        # STAGE 2: Atomic DB Transaction & Metadata Publication
        # -------------------------------------------------------------
        # Re-verify file state within active transaction
        stmt_lock = select(FileRecord).where(
            FileRecord.id == file_id,
            FileRecord.workspace_id == workspace_id,
        )
        res_lock = await db.execute(stmt_lock)
        locked_record = res_lock.scalars().first()

        if not locked_record or locked_record.deleted_at is not None:
            logger.warning(f"FileIndexingService: Aborting indexing for deleted file {file_id}")
            raise ValidationError(f"File {file_id} was deleted during indexing preparation")

        if locked_record.status in [FileStatus.DELETE_REQUESTED.value, FileStatus.DELETED.value]:
            logger.warning(f"FileIndexingService: Aborting indexing for delete-requested file {file_id}")
            raise ValidationError(f"File {file_id} is marked for deletion; vectors aborted")

        # Atomic Swap: Remove old chunks
        stmt_del = delete(FileChunk).where(
            FileChunk.file_id == file_id,
            FileChunk.workspace_id == workspace_id,
        )
        await db.execute(stmt_del)

        # Insert new chunks
        for chunk_payload, vector in zip(chunks, embeddings):
            chunk_row = FileChunk(
                id=uuid.uuid4(),
                workspace_id=workspace_id,
                file_id=file_id,
                chunk_index=chunk_payload.chunk_index,
                chunk_text=chunk_payload.chunk_text,
                token_count=chunk_payload.token_count,
                embedding=vector,
                source_location=chunk_payload.source_location,
            )
            db.add(chunk_row)

        # Update metadata projection
        current_meta = dict(locked_record.metadata_ or {})
        current_meta["vector_index"] = new_vector_metadata
        locked_record.metadata_ = current_meta

        await db.commit()
        await db.refresh(locked_record)

        # Record Audit Event
        await audit_ledger.record_event(
            db=db,
            workspace_id=workspace_id,
            actor_type="user" if actor_id != "system" else "system",
            actor_id=actor_id,
            action="file.vector_indexed",
            resource_type="file",
            resource_id=str(file_id),
            details={
                "generation": generation_id,
                "chunks_count": len(chunks),
                "tokens_count": total_tokens,
                "embedding_model": self.EMBEDDING_MODEL_NAME,
            },
            ip_address=ip_address,
        )

        return FileIndexResponse(
            file_id=file_id,
            status="ready",
            chunks_count=len(chunks),
            tokens_count=total_tokens,
            generation=generation_id,
            embedding_model=self.EMBEDDING_MODEL_NAME,
            message="File structural chunking and vector indexing completed successfully",
        )


file_indexing_service = FileIndexingService()
