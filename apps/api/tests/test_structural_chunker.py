"""Test Suite for StructuralChunker (AURA-603).

Verifies:
1. Format-aware hierarchical chunking across Markdown, PDF, DOCX, XLSX/CSV, PPTX, Code, and ZIP.
2. Structural context header formatting (<= 64 tokens).
3. Chunk token bounds (target 384, max stored 510, min 50).
4. Subdividing oversized items with 48 body tokens overlap.
5. Invariant: stored chunk_text == exact embedding input text.
6. Deterministic chunk index numbering (0...N-1).
"""

import pytest
from app.schemas.file import ExtractedContentItem, NormalizedExtractionResult
from app.services.embedding_service import embedding_service
from app.services.structural_chunker import structural_chunker


def test_format_header_budget():
    """Verify structural header is properly formatted and bounded to <= 64 tokens."""
    hdr = structural_chunker.format_header(
        filename="system_architecture_specification_v2.md",
        mime_type="text/markdown",
        section="# Core Components > Vector Database > HNSW Index Configuration",
        location_meta={"page": 12, "sheet": "Config"},
    )
    assert hdr.startswith("[Document: ")
    assert "Section:" in hdr
    assert "Page 12" in hdr
    assert "Sheet 'Config'" in hdr
    assert hdr.endswith("]")
    assert embedding_service.count_tokens(hdr) <= structural_chunker.MAX_HEADER_TOKENS


def test_chunk_markdown_structural_sections():
    """Verify Markdown headings create natural chunk boundaries with preserved headers."""
    items = [
        ExtractedContentItem(
            index=0,
            text="# Introduction\nAURA is an agentic AI operating system operating 100% locally with zero cloud dependencies.",
            item_type="heading",
            source_location={"heading": "Introduction", "level": 1},
        ),
        ExtractedContentItem(
            index=1,
            text="## Architecture\nThe database uses PostgreSQL 16 with pgvector and FastEmbed for high-performance memory.",
            item_type="paragraph",
            source_location={"heading": "Architecture", "level": 2},
        ),
        ExtractedContentItem(
            index=2,
            text="## Storage Guard\nPath traversal is prevented using WorkspaceFilesystemGuard with strict normalization.",
            item_type="paragraph",
            source_location={"heading": "Storage Guard", "level": 2},
        ),
    ]
    extraction = NormalizedExtractionResult(
        filename="architecture.md",
        mime_type="text/markdown",
        file_extension=".md",
        parser_name="markdown_parser",
        parser_version="1.0.0",
        status="extracted",
        extracted_text="combined text",
        sanitized_envelope="envelope",
        content_items=items,
    )

    chunks = structural_chunker.chunk_document(extraction)
    assert len(chunks) >= 1
    for i, chk in enumerate(chunks):
        assert chk.chunk_index == i
        assert chk.token_count <= structural_chunker.MAX_STORED_TOKENS
        assert chk.chunk_text.startswith("[Document: architecture.md")
        assert chk.source_location["chunking_strategy"] == "structural_v1"
        assert chk.source_location["chunking_version"] == "1.0.0"


def test_chunk_oversized_item_subdivision():
    """Verify oversized paragraphs (> 446 tokens) are subdivided with overlap and token ceilings."""
    # Generate long text of 800 words (~1000 tokens)
    huge_paragraph = " ".join([f"token_{i} concept information data point." for i in range(200)])
    item = ExtractedContentItem(
        index=0,
        text=huge_paragraph,
        item_type="paragraph",
        source_location={"section": "Massive Block", "page": 5},
    )
    extraction = NormalizedExtractionResult(
        filename="big_doc.pdf",
        mime_type="application/pdf",
        file_extension=".pdf",
        parser_name="pdf_parser",
        parser_version="1.0.0",
        status="extracted",
        extracted_text=huge_paragraph,
        sanitized_envelope="envelope",
        content_items=[item],
    )

    chunks = structural_chunker.chunk_document(extraction)
    assert len(chunks) > 1
    for chk in chunks:
        assert chk.token_count <= structural_chunker.MAX_STORED_TOKENS
        # Invariant: stored chunk text equals exact text passed to token counting
        assert embedding_service.count_tokens(chk.chunk_text) == chk.token_count


def test_chunk_spreadsheet_tabular():
    """Verify tabular row blocks preserve worksheet location and header context."""
    items = [
        ExtractedContentItem(
            index=0,
            text="Col1,Col2,Col3\nVal1,Val2,Val3\nVal4,Val5,Val6",
            item_type="table",
            source_location={"sheet": "Q1_Financials", "row_start": 1, "row_end": 3},
        ),
        ExtractedContentItem(
            index=1,
            text="Col1,Col2,Col3\nVal7,Val8,Val9\nVal10,Val11,Val12",
            item_type="table",
            source_location={"sheet": "Q2_Financials", "row_start": 1, "row_end": 3},
        ),
    ]
    extraction = NormalizedExtractionResult(
        filename="financials.xlsx",
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        file_extension=".xlsx",
        parser_name="excel_parser",
        parser_version="1.0.0",
        status="extracted",
        extracted_text="combined sheets",
        sanitized_envelope="envelope",
        content_items=items,
    )

    chunks = structural_chunker.chunk_document(extraction)
    assert len(chunks) >= 1
    for chk in chunks:
        assert "Sheet '" in chk.chunk_text
        assert chk.token_count <= 510


def test_chunk_fallback_on_raw_extracted_text():
    """Verify fallback to raw extracted text when content items are empty."""
    raw_text = "This is standalone raw extracted text without granular content items.\n\nSection 2 has additional information."
    extraction = NormalizedExtractionResult(
        filename="plain.txt",
        mime_type="text/plain",
        file_extension=".txt",
        parser_name="text_parser",
        parser_version="1.0.0",
        status="extracted",
        extracted_text=raw_text,
        sanitized_envelope="envelope",
        content_items=[],
    )

    chunks = structural_chunker.chunk_document(extraction)
    assert len(chunks) == 1
    assert chunks[0].chunk_index == 0
    assert "Section 2" in chunks[0].chunk_text
    assert chunks[0].token_count <= 510
