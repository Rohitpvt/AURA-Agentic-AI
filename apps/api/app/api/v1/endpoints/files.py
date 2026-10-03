"""File Intake, Intelligence, and Secure Registry API Endpoints."""

import asyncio
import os
from typing import Optional
import uuid
from fastapi import APIRouter, Body, Depends, File, Header, Query, Request, UploadFile, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_workspace_membership
from app.core.errors import EntityNotFoundError, ValidationError
from app.core.logging import logger
from app.core.sanitization import PromptSanitizer
from app.db.models.file import FileChunk, FileRecord
from app.db.models.file_job import FileJobStatus, FileJobType
from app.db.models.memory import MemoryRecord
from app.db.models.user import User
from app.db import session as db_session_module
from app.db.session import get_db_session
from app.schemas.file import (
    CodebaseAnalysisRequest,
    CodebaseAnalysisResponse,
    FileChunkListResponse,
    FileDeleteResponse,
    FileExtractRequest,
    FileExtractionResponse,
    FileIndexRequest,
    FileIndexResponse,
    FileJobResponse,
    FileListResponse,
    FileMemoryPromoteRequest,
    FileMemoryPromoteResponse,
    FilePreviewResponse,
    FileReconcileResponse,
    FileRecordResponse,
    FileSearchRequest,
    FileSearchResponse,
    FileSummaryRequest,
    FileSummaryResponse,
    FileUploadResponse,
    JobSubmissionResponse,
    SpreadsheetAnalysisRequest,
    SpreadsheetAnalysisResponse,
)
from app.core.filesystem import filesystem_guard
from app.services.codebase_analysis_service import codebase_analysis_service
from app.services.document_synthesis_service import document_synthesis_service
from app.runtime.events import event_hub
from app.services.extraction_service import extraction_service
from app.services.file_indexing_service import file_indexing_service
from app.services.file_job_service import file_job_service
from app.services.file_search_service import file_search_service
from app.services.file_service import file_service
from app.services.memory_service import memory_service
from app.services.spreadsheet_analysis_service import spreadsheet_analysis_service

router = APIRouter()


def get_effective_workspace_id(
    workspace_id: Optional[uuid.UUID], x_workspace_id: Optional[uuid.UUID]
) -> uuid.UUID:
    """Extract target workspace ID from query parameter or header."""
    effective_id = workspace_id or x_workspace_id
    if not effective_id:
        raise ValidationError("Workspace ID must be provided via query parameter or X-Workspace-ID header")
    return effective_id


# ==========================================
# Background Job Execution Coroutines
# ==========================================

async def _run_async_extract(
    workspace_id: uuid.UUID,
    file_id: uuid.UUID,
    job_id: uuid.UUID,
    options: dict,
    actor_id: str,
) -> None:
    """Asynchronous extraction background task."""
    async with db_session_module.async_session_factory() as db:
        try:
            await file_job_service.update_job_status(
                db, job_id, status=FileJobStatus.PROCESSING.value, progress_pct=10
            )
            result = await extraction_service.extract_file_record(
                db=db,
                workspace_id=workspace_id,
                file_id=file_id,
                options=options,
                actor_id=actor_id,
            )
            await file_job_service.update_job_status(
                db,
                job_id,
                status=FileJobStatus.COMPLETED.value,
                progress_pct=100,
                result_metadata={"status": result.status, "total_chars": result.total_chars},
            )
            event_hub.publish(
                {"event_type": "file.job_updated", "workspace_id": str(workspace_id), "file_id": str(file_id), "job_id": str(job_id), "status": result.status}
            )
        except Exception as exc:
            logger.error(f"Async extract background job {job_id} failed: {exc}")
            await file_job_service.update_job_status(
                db, job_id, status=FileJobStatus.FAILED.value, error_summary=str(exc)
            )
            event_hub.publish(
                {"event_type": "file.job_updated", "workspace_id": str(workspace_id), "file_id": str(file_id), "job_id": str(job_id), "error": str(exc), "status": "failed"}
            )


async def _run_async_index(
    workspace_id: uuid.UUID,
    file_id: uuid.UUID,
    job_id: uuid.UUID,
    reindex: bool,
    actor_id: str,
) -> None:
    """Asynchronous vector indexing background task."""
    async with db_session_module.async_session_factory() as db:
        try:
            await file_job_service.update_job_status(
                db, job_id, status=FileJobStatus.PROCESSING.value, progress_pct=10
            )
            result = await file_indexing_service.index_file(
                db=db,
                workspace_id=workspace_id,
                file_id=file_id,
                reindex=reindex,
                actor_id=actor_id,
            )
            await file_job_service.update_job_status(
                db,
                job_id,
                status=FileJobStatus.COMPLETED.value,
                progress_pct=100,
                result_metadata={"chunks_count": result.chunks_count, "tokens_count": result.tokens_count},
            )
            event_hub.publish(
                {"event_type": "file.job_updated", "workspace_id": str(workspace_id), "file_id": str(file_id), "job_id": str(job_id), "chunks": result.chunks_count, "status": "completed"}
            )
        except Exception as exc:
            logger.error(f"Async index background job {job_id} failed: {exc}")
            await file_job_service.update_job_status(
                db, job_id, status=FileJobStatus.FAILED.value, error_summary=str(exc)
            )
            event_hub.publish(
                {"event_type": "file.job_updated", "workspace_id": str(workspace_id), "file_id": str(file_id), "job_id": str(job_id), "error": str(exc), "status": "failed"}
            )


# ==========================================
# Core File Endpoints
# ==========================================

@router.post("/upload", response_model=FileUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_file(
    request: Request,
    file: UploadFile = File(..., description="Binary file upload stream (max 50 MB)"),
    workspace_id: Optional[uuid.UUID] = Query(None, description="Target workspace ID"),
    x_workspace_id: Optional[uuid.UUID] = Header(None, alias="X-Workspace-ID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> FileUploadResponse:
    """Stream and register an untrusted file into the workspace-isolated secure file registry."""
    effective_ws_id = get_effective_workspace_id(workspace_id, x_workspace_id)
    await get_workspace_membership(workspace_id=effective_ws_id, user=current_user, db=db)
    client_ip = request.client.host if request.client else None

    return await file_service.upload_file(
        db=db,
        workspace_id=effective_ws_id,
        user_id=current_user.id,
        file=file,
        ip_address=client_ip,
    )


@router.get("", response_model=FileListResponse)
async def list_files(
    workspace_id: Optional[uuid.UUID] = Query(None, description="Target workspace ID"),
    x_workspace_id: Optional[uuid.UUID] = Header(None, alias="X-Workspace-ID"),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by file status"),
    mime_type: Optional[str] = Query(None, description="Filter by MIME type substring"),
    search: Optional[str] = Query(None, description="Search by original filename"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> FileListResponse:
    """List all registered files within the authenticated workspace."""
    effective_ws_id = get_effective_workspace_id(workspace_id, x_workspace_id)
    await get_workspace_membership(workspace_id=effective_ws_id, user=current_user, db=db)

    items, total = await file_service.list_files(
        db=db,
        workspace_id=effective_ws_id,
        status=status_filter,
        mime_type=mime_type,
        search=search,
        page=page,
        limit=limit,
    )
    return FileListResponse(items=items, total=total, page=page, limit=limit)


@router.get("/{file_id}", response_model=FileRecordResponse)
async def get_file_details(
    file_id: uuid.UUID,
    workspace_id: Optional[uuid.UUID] = Query(None, description="Target workspace ID"),
    x_workspace_id: Optional[uuid.UUID] = Header(None, alias="X-Workspace-ID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> FileRecordResponse:
    """Retrieve metadata and security status for a registered file."""
    effective_ws_id = get_effective_workspace_id(workspace_id, x_workspace_id)
    await get_workspace_membership(workspace_id=effective_ws_id, user=current_user, db=db)
    record = await file_service.get_file(db=db, workspace_id=effective_ws_id, file_id=file_id)
    return file_service._to_record_response(record)


@router.get("/{file_id}/preview", response_model=FilePreviewResponse)
async def preview_file(
    file_id: uuid.UUID,
    workspace_id: Optional[uuid.UUID] = Query(None, description="Target workspace ID"),
    x_workspace_id: Optional[uuid.UUID] = Header(None, alias="X-Workspace-ID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> FilePreviewResponse:
    """Retrieve safe, bounded, inert preview representation of document content (max 100 KB)."""
    effective_ws_id = get_effective_workspace_id(workspace_id, x_workspace_id)
    await get_workspace_membership(workspace_id=effective_ws_id, user=current_user, db=db)

    file_record = await file_service.get_file(db=db, workspace_id=effective_ws_id, file_id=file_id)

    # Determine preview mode by extension / mime
    ext = file_record.file_extension.lower().lstrip(".")
    preview_type = "text"
    if ext in ["md", "markdown"]:
        preview_type = "markdown"
    elif ext in ["py", "js", "ts", "json", "yaml", "yml", "sql", "html", "css", "go", "rs", "java", "c", "cpp"]:
        preview_type = "code"
    elif ext == "pdf":
        preview_type = "pdf_layout"
    elif ext in ["xlsx", "csv"]:
        preview_type = "spreadsheet_grid"

    # Read up to 100 KB text
    max_preview_bytes = 100 * 1024
    content = ""
    is_truncated = False

    physical_path = filesystem_guard.validate_and_resolve_path(effective_ws_id, file_record.storage_path)
    if physical_path.exists():
        if ext in ["txt", "md", "json", "yaml", "yml", "csv", "log", "py", "js", "ts", "html", "css", "sql"]:
            with open(physical_path, "r", encoding="utf-8", errors="replace") as f:
                raw_text = f.read(max_preview_bytes + 1)
                if len(raw_text) > max_preview_bytes:
                    content = raw_text[:max_preview_bytes]
                    is_truncated = True
                else:
                    content = raw_text
        else:
            # Non-plain text: extract text via extraction service
            extract_res = await extraction_service.extract_file_record(
                db=db, workspace_id=effective_ws_id, file_id=file_id
            )
            raw_text = extract_res.extracted_text or ""
            if len(raw_text) > max_preview_bytes:
                content = raw_text[:max_preview_bytes]
                is_truncated = True
            else:
                content = raw_text

    return FilePreviewResponse(
        file_id=file_record.id,
        original_filename=file_record.original_filename,
        mime_type=file_record.mime_type,
        preview_type=preview_type,
        content=content,
        is_truncated=is_truncated,
        total_bytes=file_record.size_bytes,
        security_badge="Untrusted External File Content — Active Scripts Inactive",
    )


@router.post("/{file_id}/extract", status_code=status.HTTP_200_OK)
async def extract_file(
    file_id: uuid.UUID,
    extract_req: Optional[FileExtractRequest] = Body(default=None),
    workspace_id: Optional[uuid.UUID] = Query(None, description="Target workspace ID"),
    x_workspace_id: Optional[uuid.UUID] = Header(None, alias="X-Workspace-ID"),
    async_mode: bool = Query(False, alias="async", description="If True, dispatches 202 Accepted background job"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Submit format extraction job (synchronous 200 OK or background 202 Accepted)."""
    effective_ws_id = get_effective_workspace_id(workspace_id, x_workspace_id)
    await get_workspace_membership(workspace_id=effective_ws_id, user=current_user, db=db)

    # 1. Verify file exists
    await file_service.get_file(db=db, workspace_id=effective_ws_id, file_id=file_id)
    req_options = extract_req.model_dump() if extract_req else {}

    if async_mode:
        # Atomically create job record (enforces active uniqueness -> 409 Conflict on dupe)
        job = await file_job_service.create_job(
            db=db,
            workspace_id=effective_ws_id,
            file_id=file_id,
            job_type=FileJobType.EXTRACT.value,
            user_id=current_user.id,
        )
        asyncio.create_task(
            _run_async_extract(
                workspace_id=effective_ws_id,
                file_id=file_id,
                job_id=job.id,
                options=req_options,
                actor_id=str(current_user.id),
            )
        )
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content=file_job_service.to_submission_response(job).model_dump(mode="json"),
        )

    # Synchronous extraction
    result = await extraction_service.extract_file_record(
        db=db,
        workspace_id=effective_ws_id,
        file_id=file_id,
        options=req_options,
        actor_id=str(current_user.id),
    )
    return FileExtractionResponse(
        file_id=file_id,
        status=result.status,
        extraction=result,
    )


@router.post("/{file_id}/index", status_code=status.HTTP_200_OK)
async def index_file(
    file_id: uuid.UUID,
    index_req: Optional[FileIndexRequest] = Body(default=None),
    workspace_id: Optional[uuid.UUID] = Query(None, description="Target workspace ID"),
    x_workspace_id: Optional[uuid.UUID] = Header(None, alias="X-Workspace-ID"),
    async_mode: bool = Query(True, alias="async", description="If True, dispatches 202 Accepted background job"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Submit structural chunking and vector indexing job (202 Accepted or 200 OK)."""
    effective_ws_id = get_effective_workspace_id(workspace_id, x_workspace_id)
    await get_workspace_membership(workspace_id=effective_ws_id, user=current_user, db=db)

    # 1. Verify file exists
    await file_service.get_file(db=db, workspace_id=effective_ws_id, file_id=file_id)
    reindex_flag = index_req.reindex if index_req else False

    if async_mode:
        # Atomically create job record (enforces active uniqueness -> 409 Conflict on dupe)
        job = await file_job_service.create_job(
            db=db,
            workspace_id=effective_ws_id,
            file_id=file_id,
            job_type=FileJobType.INDEX.value,
            user_id=current_user.id,
        )
        asyncio.create_task(
            _run_async_index(
                workspace_id=effective_ws_id,
                file_id=file_id,
                job_id=job.id,
                reindex=reindex_flag,
                actor_id=str(current_user.id),
            )
        )
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content=file_job_service.to_submission_response(job).model_dump(mode="json"),
        )

    # Synchronous indexing
    result = await file_indexing_service.index_file(
        db=db,
        workspace_id=effective_ws_id,
        file_id=file_id,
        reindex=reindex_flag,
        actor_id=str(current_user.id),
    )
    return result


@router.get("/jobs/{job_id}", response_model=FileJobResponse)
async def get_job_status(
    job_id: uuid.UUID,
    workspace_id: Optional[uuid.UUID] = Query(None, description="Target workspace ID"),
    x_workspace_id: Optional[uuid.UUID] = Header(None, alias="X-Workspace-ID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> FileJobResponse:
    """Authoritative persistent status lookup for asynchronous file jobs."""
    effective_ws_id = get_effective_workspace_id(workspace_id, x_workspace_id)
    await get_workspace_membership(workspace_id=effective_ws_id, user=current_user, db=db)

    job = await file_job_service.get_job(db=db, workspace_id=effective_ws_id, job_id=job_id)
    return file_job_service.to_job_response(job)


@router.post("/{file_id}/summary", response_model=FileSummaryResponse)
async def summarize_file(
    file_id: uuid.UUID,
    summary_req: Optional[FileSummaryRequest] = None,
    workspace_id: Optional[uuid.UUID] = Query(None, description="Target workspace ID"),
    x_workspace_id: Optional[uuid.UUID] = Header(None, alias="X-Workspace-ID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> FileSummaryResponse:
    """Synthesize structured executive summary with section/page citations."""
    effective_ws_id = get_effective_workspace_id(workspace_id, x_workspace_id)
    await get_workspace_membership(workspace_id=effective_ws_id, user=current_user, db=db)

    return await document_synthesis_service.summarize_file(
        db=db,
        workspace_id=effective_ws_id,
        file_id=file_id,
        request=summary_req,
        actor_id=str(current_user.id),
    )


@router.post("/{file_id}/spreadsheet/analyze", response_model=SpreadsheetAnalysisResponse)
async def analyze_spreadsheet(
    file_id: uuid.UUID,
    sheet_req: Optional[SpreadsheetAnalysisRequest] = None,
    workspace_id: Optional[uuid.UUID] = Query(None, description="Target workspace ID"),
    x_workspace_id: Optional[uuid.UUID] = Header(None, alias="X-Workspace-ID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SpreadsheetAnalysisResponse:
    """Inspect spreadsheet worksheets, column schemas, and formula statistics safely."""
    effective_ws_id = get_effective_workspace_id(workspace_id, x_workspace_id)
    await get_workspace_membership(workspace_id=effective_ws_id, user=current_user, db=db)

    return await spreadsheet_analysis_service.analyze_spreadsheet(
        db=db,
        workspace_id=effective_ws_id,
        file_id=file_id,
        request=sheet_req,
    )


@router.post("/{file_id}/codebase/analyze", response_model=CodebaseAnalysisResponse)
async def analyze_codebase(
    file_id: uuid.UUID,
    code_req: Optional[CodebaseAnalysisRequest] = None,
    workspace_id: Optional[uuid.UUID] = Query(None, description="Target workspace ID"),
    x_workspace_id: Optional[uuid.UUID] = Header(None, alias="X-Workspace-ID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> CodebaseAnalysisResponse:
    """Analyze codebase archive file hierarchy, AST symbols, and manifest dependencies."""
    effective_ws_id = get_effective_workspace_id(workspace_id, x_workspace_id)
    await get_workspace_membership(workspace_id=effective_ws_id, user=current_user, db=db)

    return await codebase_analysis_service.analyze_codebase(
        db=db,
        workspace_id=effective_ws_id,
        file_id=file_id,
        request=code_req,
    )


@router.post("/{file_id}/promote-memory", response_model=FileMemoryPromoteResponse)
async def promote_file_to_memory(
    file_id: uuid.UUID,
    promote_req: FileMemoryPromoteRequest,
    workspace_id: Optional[uuid.UUID] = Query(None, description="Target workspace ID"),
    x_workspace_id: Optional[uuid.UUID] = Header(None, alias="X-Workspace-ID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> FileMemoryPromoteResponse:
    """Explicit user-authorized promotion of a document finding to durable cognitive memory."""
    effective_ws_id = get_effective_workspace_id(workspace_id, x_workspace_id)
    await get_workspace_membership(workspace_id=effective_ws_id, user=current_user, db=db)

    file_record = await file_service.get_file(db=db, workspace_id=effective_ws_id, file_id=file_id)

    chunk = None
    if promote_req.chunk_id:
        stmt = select(FileChunk).where(
            FileChunk.id == promote_req.chunk_id,
            FileChunk.workspace_id == effective_ws_id,
            FileChunk.file_id == file_id,
        )
        res = await db.execute(stmt)
        chunk = res.scalar_one_or_none()

    if chunk:
        mem_rec = await memory_service.promote_chunk_to_memory(
            db=db,
            workspace_id=effective_ws_id,
            file_id=file_id,
            chunk_id=chunk.id,
            chunk_index=chunk.chunk_index,
            fact_statement=promote_req.fact_statement,
            source_location=chunk.source_location,
            file_hash=file_record.sha256_hash,
            user_id=current_user.id,
        )
    else:
        # File-level direct promotion
        from datetime import datetime, timezone
        provenance = {
            "workspace_id": str(effective_ws_id),
            "file_id": str(file_id),
            "chunk_id": None,
            "chunk_index": None,
            "source_location": {},
            "file_sha256": file_record.sha256_hash,
            "parser_version": "1.0.0",
            "chunking_version": "1.0.0",
            "embedding_model": "BAAI/bge-base-en-v1.5",
            "retrieval_score": None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        mem_rec = await memory_service.ingest_memory(
            db=db,
            workspace_id=effective_ws_id,
            fact_statement=promote_req.fact_statement,
            source_type="file_intelligence",
            user_id=current_user.id,
            provenance=provenance,
        )

    return FileMemoryPromoteResponse(
        memory_id=mem_rec.id,
        workspace_id=mem_rec.workspace_id,
        source_type=mem_rec.source_type,
        fact_statement=mem_rec.fact_statement,
        provenance=mem_rec.provenance or {},
        status="active",
    )


@router.get("/{file_id}/chunks", response_model=FileChunkListResponse)
async def list_file_chunks(
    file_id: uuid.UUID,
    workspace_id: Optional[uuid.UUID] = Query(None, description="Target workspace ID"),
    x_workspace_id: Optional[uuid.UUID] = Header(None, alias="X-Workspace-ID"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(50, ge=1, le=200, description="Items per page"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> FileChunkListResponse:
    """Retrieve persisted vector chunks and structural provenance for an indexed file."""
    effective_ws_id = get_effective_workspace_id(workspace_id, x_workspace_id)
    await get_workspace_membership(workspace_id=effective_ws_id, user=current_user, db=db)

    items, total = await file_service.get_file_chunks(
        db=db,
        workspace_id=effective_ws_id,
        file_id=file_id,
        page=page,
        limit=limit,
    )
    return FileChunkListResponse(items=items, total=total, page=page, limit=limit)


@router.post("/search", response_model=FileSearchResponse)
async def search_files(
    search_req: FileSearchRequest,
    workspace_id: Optional[uuid.UUID] = Query(None, description="Target workspace ID"),
    x_workspace_id: Optional[uuid.UUID] = Header(None, alias="X-Workspace-ID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> FileSearchResponse:
    """Execute hybrid semantic + lexical search across workspace documents."""
    effective_ws_id = get_effective_workspace_id(workspace_id, x_workspace_id)
    await get_workspace_membership(workspace_id=effective_ws_id, user=current_user, db=db)

    return await file_search_service.search(
        db=db,
        workspace_id=effective_ws_id,
        request=search_req,
    )


@router.delete("/{file_id}", response_model=FileDeleteResponse)
async def delete_file(
    request: Request,
    file_id: uuid.UUID,
    workspace_id: Optional[uuid.UUID] = Query(None, description="Target workspace ID"),
    x_workspace_id: Optional[uuid.UUID] = Header(None, alias="X-Workspace-ID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> FileDeleteResponse:
    """Execute the idempotent deletion lifecycle for a file and derived artifacts."""
    effective_ws_id = get_effective_workspace_id(workspace_id, x_workspace_id)
    await get_workspace_membership(workspace_id=effective_ws_id, user=current_user, db=db)
    client_ip = request.client.host if request.client else None

    return await file_service.delete_file(
        db=db,
        workspace_id=effective_ws_id,
        file_id=file_id,
        actor_id=str(current_user.id),
        ip_address=client_ip,
    )


@router.post("/reconcile", response_model=FileReconcileResponse)
async def reconcile_workspace_files(
    workspace_id: Optional[uuid.UUID] = Query(None, description="Target workspace ID"),
    x_workspace_id: Optional[uuid.UUID] = Header(None, alias="X-Workspace-ID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> FileReconcileResponse:
    """Reconcile unreferenced physical disk folders against the database registry."""
    effective_ws_id = get_effective_workspace_id(workspace_id, x_workspace_id)
    member = await get_workspace_membership(workspace_id=effective_ws_id, user=current_user, db=db)
    if member.role not in ["owner", "admin"]:
        from app.core.errors import AuthorizationError
        raise AuthorizationError("Only workspace owners and administrators can perform orphan reconciliation")

    return await file_service.reconcile_orphans(
        db=db,
        workspace_id=effective_ws_id,
        actor_id=str(current_user.id),
    )
