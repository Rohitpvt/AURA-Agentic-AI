"""Governed File Intelligence Tool Handlers for Agent Runtime."""

from typing import Any, Dict, Optional
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.errors import EntityNotFoundError, ValidationError
from app.core.logging import logger
from app.core.sanitization import PromptSanitizer
from app.schemas.file import (
    CodebaseAnalysisRequest,
    FileSearchRequest,
    FileSummaryRequest,
    SpreadsheetAnalysisRequest,
)
from app.services.codebase_analysis_service import codebase_analysis_service
from app.services.document_synthesis_service import document_synthesis_service
from app.services.file_search_service import file_search_service
from app.services.file_service import file_service
from app.services.spreadsheet_analysis_service import spreadsheet_analysis_service


async def execute_inspect_file(
    workspace_id: uuid.UUID,
    arguments: Optional[Dict[str, Any]] = None,
    db: Optional[AsyncSession] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Execute inspect_file tool: returns file metadata, structural metrics, and vector index status."""
    args = dict(arguments or {})
    args.update(kwargs)
    file_id_raw = args.get("file_id")
    if not file_id_raw:
        raise ValidationError("Parameter 'file_id' is required for inspect_file")

    try:
        file_id = uuid.UUID(str(file_id_raw))
    except ValueError as exc:
        raise ValidationError(f"Invalid UUID format for file_id: {file_id_raw}") from exc

    file_record = await file_service.get_file(db=db, workspace_id=workspace_id, file_id=file_id)

    vector_info = file_record.metadata_.get("vector_index", {})
    vector_status = vector_info.get("status", "none")
    chunks_count = vector_info.get("chunks_count", 0)

    return {
        "file_id": str(file_record.id),
        "filename": file_record.original_filename,
        "mime_type": file_record.mime_type,
        "file_extension": file_record.file_extension,
        "size_bytes": file_record.size_bytes,
        "status": file_record.status,
        "vector_status": vector_status,
        "chunks_count": chunks_count,
        "metadata": file_record.metadata_,
        "security_flags": file_record.security_flags,
        "created_at": file_record.created_at.isoformat(),
    }


async def execute_summarize_document(
    workspace_id: uuid.UUID,
    arguments: Optional[Dict[str, Any]] = None,
    db: Optional[AsyncSession] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Execute summarize_document tool: returns executive summary with section/page citations."""
    args = dict(arguments or {})
    args.update(kwargs)
    file_id_raw = args.get("file_id")
    if not file_id_raw:
        raise ValidationError("Parameter 'file_id' is required for summarize_document")

    try:
        file_id = uuid.UUID(str(file_id_raw))
    except ValueError as exc:
        raise ValidationError(f"Invalid UUID format for file_id: {file_id_raw}") from exc

    max_tokens = args.get("max_tokens", 1024)
    focus_areas = args.get("focus_areas")

    req = FileSummaryRequest(max_tokens=max_tokens, focus_areas=focus_areas)
    resp = await document_synthesis_service.summarize_file(
        db=db,
        workspace_id=workspace_id,
        file_id=file_id,
        request=req,
        actor_id="agent_tool",
    )

    return {
        "file_id": str(resp.file_id),
        "title": resp.title,
        "executive_summary": resp.executive_summary,
        "key_takeaways": resp.key_takeaways,
        "citations": [c.model_dump() for c in resp.citations],
        "status": resp.status,
    }


async def execute_analyze_spreadsheet(
    workspace_id: uuid.UUID,
    arguments: Optional[Dict[str, Any]] = None,
    db: Optional[AsyncSession] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Execute analyze_spreadsheet tool: returns sheet structures, columns, and sample rows."""
    args = dict(arguments or {})
    args.update(kwargs)
    file_id_raw = args.get("file_id")
    if not file_id_raw:
        raise ValidationError("Parameter 'file_id' is required for analyze_spreadsheet")

    try:
        file_id = uuid.UUID(str(file_id_raw))
    except ValueError as exc:
        raise ValidationError(f"Invalid UUID format for file_id: {file_id_raw}") from exc

    sheet_name = args.get("sheet_name")
    sample_row_limit = args.get("sample_row_limit", 25)

    req = SpreadsheetAnalysisRequest(sheet_name=sheet_name, sample_row_limit=sample_row_limit)
    resp = await spreadsheet_analysis_service.analyze_spreadsheet(
        db=db,
        workspace_id=workspace_id,
        file_id=file_id,
        request=req,
    )

    return resp.model_dump()


async def execute_codebase_analysis(
    workspace_id: uuid.UUID,
    arguments: Optional[Dict[str, Any]] = None,
    db: Optional[AsyncSession] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Execute codebase_analysis tool: returns file hierarchy, AST symbols, and dependencies."""
    args = dict(arguments or {})
    args.update(kwargs)
    file_id_raw = args.get("file_id")
    if not file_id_raw:
        raise ValidationError("Parameter 'file_id' is required for codebase_analysis")

    try:
        file_id = uuid.UUID(str(file_id_raw))
    except ValueError as exc:
        raise ValidationError(f"Invalid UUID format for file_id: {file_id_raw}") from exc

    focus_paths = args.get("focus_paths")
    symbol_query = args.get("symbol_query")

    req = CodebaseAnalysisRequest(focus_paths=focus_paths, symbol_query=symbol_query)
    resp = await codebase_analysis_service.analyze_codebase(
        db=db,
        workspace_id=workspace_id,
        file_id=file_id,
        request=req,
    )

    return resp.model_dump()


async def execute_search_files(
    workspace_id: uuid.UUID,
    arguments: Optional[Dict[str, Any]] = None,
    db: Optional[AsyncSession] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Execute search_files tool: executes workspace-scoped hybrid dense + lexical search."""
    args = dict(arguments or {})
    args.update(kwargs)
    query = args.get("query")
    if not query:
        raise ValidationError("Parameter 'query' is required for search_files")

    top_k = args.get("top_k", 5)
    file_ids = None
    if args.get("file_id"):
        try:
            file_ids = [uuid.UUID(str(args.get("file_id")))]
        except ValueError as exc:
            raise ValidationError(f"Invalid UUID format for file_id: {args.get('file_id')}") from exc

    search_req = FileSearchRequest(
        query=query,
        top_k=top_k,
        file_ids=file_ids,
        min_similarity=args.get("min_similarity", 0.30),
    )

    search_resp = await file_search_service.search(
        db=db,
        workspace_id=workspace_id,
        request=search_req,
    )

    results = []
    for item in search_resp.results:
        results.append(
            {
                "chunk_id": str(item.chunk_id),
                "file_id": str(item.file_id),
                "original_filename": item.original_filename,
                "mime_type": item.mime_type,
                "snippet": PromptSanitizer.wrap_untrusted_content(
                    item.chunk_text,
                    source_type="file_search_result",
                    file_id=str(item.file_id),
                ),
                "source_location": item.source_location,
                "hybrid_score": round(item.hybrid_score, 4),
                "dense_score": round(item.dense_score, 4),
                "lexical_score": round(item.lexical_score, 4),
            }
        )

    return {
        "query": query,
        "total_candidates": search_resp.total_candidates,
        "returned_count": len(results),
        "results": results,
    }
