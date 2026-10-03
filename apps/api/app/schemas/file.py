"""Pydantic schemas for File Intake, Registry, and Lifecycle Management."""

from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field


class FileRecordResponse(BaseModel):
    """File registry metadata response."""
    id: uuid.UUID = Field(..., description="Unique opaque file identifier")
    workspace_id: uuid.UUID = Field(..., description="Owning workspace ID")
    uploaded_by: Optional[uuid.UUID] = Field(None, description="Uploader user ID")
    original_filename: str = Field(..., description="Original client-supplied filename")
    safe_filename: str = Field(..., description="Sanitized safe filename on disk")
    mime_type: str = Field(..., description="Detected / declared MIME type")
    file_extension: str = Field(..., description="Normalized file extension")
    size_bytes: int = Field(..., description="File size in bytes")
    sha256_hash: str = Field(..., description="Cryptographic SHA-256 content hash")
    status: str = Field(..., description="Current processing/lifecycle status")
    error_message: Optional[str] = Field(None, description="Processing error message if failed")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Extracted structural metadata")
    security_flags: List[str] = Field(default_factory=list, description="Security screening audit flags")
    created_at: datetime = Field(..., description="Upload timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")

    model_config = {"from_attributes": True}


class FileUploadResponse(BaseModel):
    """Response returned upon successful file intake and registration."""
    file: FileRecordResponse = Field(..., description="Registered file record")
    is_duplicate: bool = Field(False, description="True if deduplicated against existing content in workspace")
    message: str = Field("File uploaded and registered successfully", description="Status summary message")


class FileListResponse(BaseModel):
    """Paginated list of workspace files."""
    items: List[FileRecordResponse] = Field(..., description="List of file records")
    total: int = Field(..., description="Total matching file count")
    page: int = Field(..., description="Current page number")
    limit: int = Field(..., description="Items per page")


class FileDeleteResponse(BaseModel):
    """Idempotent deletion lifecycle response."""
    file_id: uuid.UUID = Field(..., description="Target file ID")
    status: str = Field(..., description="Final deletion state ('deleted' or 'already_deleted')")
    purged_storage: bool = Field(..., description="True if physical files were purged from disk")
    purged_chunks: int = Field(..., description="Count of cascaded vector chunks removed")
    message: str = Field(..., description="Lifecycle operation summary")


class FileReconcileResponse(BaseModel):
    """Storage-to-Registry orphan reconciliation summary."""
    workspace_id: uuid.UUID = Field(..., description="Target workspace ID")
    orphaned_directories_found: int = Field(..., description="Number of unreferenced file directories found on disk")
    orphaned_directories_purged: int = Field(..., description="Number of orphaned directories purged")
    missing_storage_records: int = Field(..., description="Number of DB records flagged for missing disk files")
    reconciled_at: datetime = Field(..., description="Reconciliation execution timestamp")


class ExtractedContentItem(BaseModel):
    """Granular extracted section with structural source location."""
    index: int = Field(..., description="Zero-indexed content sequence position")
    text: str = Field(..., description="Extracted textual content")
    item_type: str = Field(..., description="Content structural classification (paragraph, heading, table, cell, formula, cached_formula_result, slide, ast_class, ast_function, code_block, archive_file, metadata)")
    source_location: Dict[str, Any] = Field(default_factory=dict, description="Structural location coordinates (page, sheet, cell, row, col, slide, line_start, line_end, archive_path)")
    is_formula: bool = Field(False, description="True if content is an inert spreadsheet formula expression")
    formula_expression: Optional[str] = Field(None, description="Raw un-evaluated formula expression string")


class NormalizedExtractionResult(BaseModel):
    """Normalized multi-format parser output contract."""
    file_id: Optional[uuid.UUID] = Field(None, description="Associated file registry ID")
    filename: str = Field(..., description="Source filename")
    mime_type: str = Field(..., description="Detected MIME type")
    file_extension: str = Field(..., description="Normalized file extension")
    parser_name: str = Field(..., description="Identifier of the executing parser engine")
    parser_version: str = Field("1.0.0", description="Parser engine version")
    status: str = Field(..., description="Extraction outcome status (extracted, partially_extracted, no_text_extracted, failed, quarantined)")
    extracted_text: str = Field(..., description="Aggregated raw extracted text (bounded to 5 MB)")
    sanitized_envelope: str = Field(..., description="Prompt-sanitized untrusted content envelope")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Structured document metadata (page count, dimensions, sheet names, ast summary)")
    content_items: List[ExtractedContentItem] = Field(default_factory=list, description="Ordered list of granular structural content items")
    warnings: List[str] = Field(default_factory=list, description="Non-fatal parsing warnings or diagnostics")
    security_flags: List[str] = Field(default_factory=list, description="Security screening audit flags")
    error_message: Optional[str] = Field(None, description="Error details if parsing failed")
    total_chars: int = Field(0, description="Total characters in extracted text")
    is_truncated: bool = Field(False, description="True if output was bounded due to size limits")


class FileExtractRequest(BaseModel):
    """Extraction execution options."""
    include_cached_formula_results: bool = Field(False, description="If True, performs separate data_only=True pass for creator-cached formula values")
    max_text_bytes: Optional[int] = Field(None, description="Optional custom byte limit for extracted text (defaults to 5 MB)")


class FileExtractionResponse(BaseModel):
    """API response for file extraction execution."""
    file_id: uuid.UUID = Field(..., description="Target file ID")
    status: str = Field(..., description="Final extraction status")
    extraction: NormalizedExtractionResult = Field(..., description="Normalized extraction result")
    message: str = Field("File extracted successfully", description="Status summary message")


class FileChunkResponse(BaseModel):
    """Structural chunk representation."""
    id: uuid.UUID = Field(..., description="Chunk ID")
    workspace_id: uuid.UUID = Field(..., description="Workspace ID")
    file_id: uuid.UUID = Field(..., description="File ID")
    chunk_index: int = Field(..., description="0-indexed sequence position")
    chunk_text: str = Field(..., description="Complete stored chunk text")
    token_count: int = Field(..., description="Exact non-special token count")
    source_location: Dict[str, Any] = Field(default_factory=dict, description="Structural location coordinates")
    created_at: datetime = Field(..., description="Chunk creation timestamp")

    model_config = {"from_attributes": True}


class FileChunkListResponse(BaseModel):
    """Paginated list of document chunks."""
    items: List[FileChunkResponse] = Field(..., description="List of file chunks")
    total: int = Field(..., description="Total chunks count")
    page: int = Field(..., description="Page number")
    limit: int = Field(..., description="Items per page")


class FileIndexRequest(BaseModel):
    """Vector indexing trigger request."""
    reindex: bool = Field(False, description="If True, forces generation increment and complete re-indexing")


class FileIndexResponse(BaseModel):
    """Vector indexing outcome response."""
    file_id: uuid.UUID = Field(..., description="Indexed file ID")
    status: str = Field(..., description="Vector indexing state (ready/failed)")
    chunks_count: int = Field(..., description="Number of vector chunks generated")
    tokens_count: int = Field(..., description="Total tokens vectorized")
    generation: str = Field(..., description="Optimistic index generation UUID")
    embedding_model: str = Field("BAAI/bge-base-en-v1.5", description="Embedding model used")
    message: str = Field("File chunking and vector indexing completed successfully", description="Status message")


class FileSearchRequest(BaseModel):
    """Hybrid semantic + lexical document search request."""
    query: str = Field(..., min_length=1, max_length=2000, description="Natural language or keyword search query")
    top_k: int = Field(5, ge=1, le=50, description="Maximum number of results to return")
    min_similarity: float = Field(0.30, ge=0.0, le=1.0, description="Minimum hybrid similarity threshold floor")
    file_ids: Optional[List[uuid.UUID]] = Field(None, description="Optional filter to restrict search to specific files")
    mime_types: Optional[List[str]] = Field(None, description="Optional filter to restrict search to specific MIME types")


class FileSearchResultItem(BaseModel):
    """Single hybrid search result item with source provenance and score breakdown."""
    chunk_id: uuid.UUID = Field(..., description="Matching FileChunk ID")
    file_id: uuid.UUID = Field(..., description="Originating FileRecord ID")
    workspace_id: uuid.UUID = Field(..., description="Workspace ID")
    chunk_index: int = Field(..., description="Sequence index of the chunk")
    chunk_text: str = Field(..., description="Stored chunk text")
    token_count: int = Field(..., description="Token count")
    source_location: Dict[str, Any] = Field(default_factory=dict, description="Structural location coordinates")
    dense_score: float = Field(..., description="Normalized dense cosine similarity [0.0, 1.0]")
    lexical_score: float = Field(..., description="Normalized full-text search rank [0.0, 1.0)")
    hybrid_score: float = Field(..., description="Weighted linear combination score [0.0, 1.0]")
    original_filename: str = Field(..., description="Originating document filename")
    mime_type: str = Field(..., description="Document MIME type")


class FileSearchResponse(BaseModel):
    """Hybrid search results response."""
    query: str = Field(..., description="Original user query")
    total_candidates: int = Field(..., description="Total candidate items evaluated before thresholding")
    returned_count: int = Field(..., description="Number of results surviving thresholding")
    results: List[FileSearchResultItem] = Field(default_factory=list, description="Ranked search results")


class JobSubmissionResponse(BaseModel):
    """Canonical 202 response schema for asynchronous job submissions."""
    job_id: uuid.UUID = Field(..., description="Unique persistent job identifier")
    workspace_id: uuid.UUID = Field(..., description="Target workspace ID")
    file_id: Optional[uuid.UUID] = Field(None, description="Associated file ID if applicable")
    job_type: str = Field(..., description="Job classification type")
    status: str = Field("queued", description="Initial job status (queued)")
    created_at: datetime = Field(..., description="Job creation timestamp")


class FileJobResponse(BaseModel):
    """Authoritative persistent file intelligence job record representation."""
    job_id: uuid.UUID = Field(..., description="Job ID")
    workspace_id: uuid.UUID = Field(..., description="Workspace ID")
    file_id: Optional[uuid.UUID] = Field(None, description="File ID")
    job_type: str = Field(..., description="Job type")
    status: str = Field(..., description="Deterministic state: queued, processing, completed, failed, cancelled")
    progress_pct: int = Field(0, description="Completion percentage (0-100)")
    error_summary: Optional[str] = Field(None, description="Sanitized failure description if failed")
    result_metadata: Dict[str, Any] = Field(default_factory=dict, description="Job completion metadata")
    started_at: Optional[datetime] = Field(None, description="Execution start timestamp")
    completed_at: Optional[datetime] = Field(None, description="Execution completion timestamp")
    created_at: datetime = Field(..., description="Creation timestamp")


class FileSummaryCitation(BaseModel):
    """Citation coordinate linking summary point to source coordinate."""
    section: Optional[str] = Field(None, description="Source section or heading")
    page: Optional[int] = Field(None, description="Page number if document")
    sheet: Optional[str] = Field(None, description="Sheet name if spreadsheet")
    chunk_id: Optional[uuid.UUID] = Field(None, description="Originating FileChunk ID")


class FileSummaryRequest(BaseModel):
    """Document synthesis request options."""
    max_tokens: Optional[int] = Field(1024, description="Target summary length budget")
    focus_areas: Optional[List[str]] = Field(None, description="Specific topics or sections to focus on")


class FileSummaryResponse(BaseModel):
    """Document synthesis outcome."""
    file_id: uuid.UUID = Field(..., description="Target file ID")
    title: str = Field(..., description="Document title or original filename")
    executive_summary: str = Field(..., description="Synthesized executive summary")
    key_takeaways: List[str] = Field(default_factory=list, description="Structured bullet takeaways")
    citations: List[FileSummaryCitation] = Field(default_factory=list, description="Source citations")
    status: str = Field("completed", description="Outcome status: completed or extractive_fallback")


class SpreadsheetAnalysisRequest(BaseModel):
    """Spreadsheet structural inspection options."""
    sheet_name: Optional[str] = Field(None, description="Optional specific worksheet to analyze")
    sample_row_limit: Optional[int] = Field(25, ge=1, le=100, description="Max sample rows per sheet")


class SpreadsheetSheetInfo(BaseModel):
    """Structural information for a single worksheet."""
    name: str = Field(..., description="Worksheet name")
    row_count: int = Field(..., description="Total rows in sheet")
    column_count: int = Field(..., description="Total columns in sheet")
    columns: List[str] = Field(default_factory=list, description="Header column names")
    sample_rows: List[Dict[str, Any]] = Field(default_factory=list, description="Sample row records")
    formulas_detected: int = Field(0, description="Number of inert formula cells detected")


class SpreadsheetAnalysisResponse(BaseModel):
    """Spreadsheet structural analysis outcome."""
    file_id: uuid.UUID = Field(..., description="Target file ID")
    total_sheets: int = Field(..., description="Number of worksheets")
    sheets: List[SpreadsheetSheetInfo] = Field(default_factory=list, description="Analyzed worksheets")
    has_macros: bool = Field(False, description="True if VBA macros were detected and neutralized")
    summary: Dict[str, Any] = Field(default_factory=dict, description="Aggregated workbook statistics")


class CodebaseSymbolInfo(BaseModel):
    """AST-extracted symbol definition."""
    name: str = Field(..., description="Symbol identifier name")
    type: str = Field(..., description="Symbol type: class, function, method, interface")
    file: str = Field(..., description="Relative file path within archive")
    line: Optional[int] = Field(None, description="Line number definition")
    docstring: Optional[str] = Field(None, description="Extracted docstring if present")


class CodebaseAnalysisRequest(BaseModel):
    """Codebase repository inspection options."""
    focus_paths: Optional[List[str]] = Field(None, description="Optional paths to filter analysis")
    symbol_query: Optional[str] = Field(None, description="Optional symbol name to search for")


class CodebaseAnalysisResponse(BaseModel):
    """Codebase repository analysis outcome."""
    file_id: uuid.UUID = Field(..., description="Target codebase archive file ID")
    total_files: int = Field(..., description="Total files unpacked in archive")
    languages: Dict[str, int] = Field(default_factory=dict, description="File count per language")
    file_tree: List[Dict[str, Any]] = Field(default_factory=list, description="Hierarchical directory structure")
    symbols: List[CodebaseSymbolInfo] = Field(default_factory=list, description="Discovered AST symbols")
    dependencies: List[str] = Field(default_factory=list, description="Detected manifest dependencies")


class FilePreviewResponse(BaseModel):
    """Inert preview representation of document content."""
    file_id: uuid.UUID = Field(..., description="Target file ID")
    original_filename: str = Field(..., description="Original filename")
    mime_type: str = Field(..., description="MIME type")
    preview_type: str = Field(..., description="Render mode: text, markdown, code, pdf_layout, spreadsheet_grid")
    content: str = Field(..., description="Inert preview text or structured layout string (max 100 KB)")
    is_truncated: bool = Field(False, description="True if content exceeded 100 KB limit")
    total_bytes: int = Field(..., description="Total file size in bytes")
    security_badge: str = Field("Untrusted External File Content — Active Scripts Inactive", description="Security indicator")


class FileMemoryPromoteRequest(BaseModel):
    """User cognitive memory promotion request."""
    chunk_id: Optional[uuid.UUID] = Field(None, description="Optional originating FileChunk ID")
    fact_statement: str = Field(..., min_length=5, max_length=5000, description="Cognitive memory fact statement")
    tags: Optional[List[str]] = Field(default_factory=list, description="Categorization tags")


class FileMemoryPromoteResponse(BaseModel):
    """Cognitive memory promotion outcome."""
    memory_id: uuid.UUID = Field(..., description="Created MemoryRecord ID")
    workspace_id: uuid.UUID = Field(..., description="Workspace ID")
    source_type: str = Field("file_intelligence", description="Canonical source type")
    fact_statement: str = Field(..., description="Persisted fact statement")
    provenance: Dict[str, Any] = Field(default_factory=dict, description="Structured 11-field provenance JSONB")
    status: str = Field("active", description="Memory record status")



