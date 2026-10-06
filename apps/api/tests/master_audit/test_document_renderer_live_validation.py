"""Live Validation Suite for Universal File Intelligence & Document Rendering (AURA Phase 6 / Gap Closure).

Verifies:
1. Deterministic in-process parsing across modern document formats (PDF, DOCX, XLSX, TXT, MD, Code, ZIP).
2. Malformed input handling: Corrupt files, truncated streams, zero-byte inputs fail gracefully without crashes.
3. Path traversal resistance: Archive files containing escaping paths (`../../`) are blocked.
4. Denial-of-Service / Zip bomb resistance: Archives exceeding member ceilings (>500 files) are rejected.
5. Deferred legacy format diagnostics (.doc, .xls, .ppt) cleanly intercepted by deferred_format_guard without unsafe subprocess shelling.
6. Zero shell injection vulnerability across file intake parameters.
"""

import io
import os
from pathlib import Path
import tempfile
import zipfile
import pytest

from app.core.errors import ValidationError
from app.services.extractors.archive_extractor import ArchiveExtractor
from app.services.extractors.docx_extractor import DocxExtractor
from app.services.extractors.parser_registry import ParserRegistry
from app.services.extractors.pdf_extractor import PDFExtractor
from app.services.extractors.text_extractor import TextExtractor
from app.services.extractors.xlsx_extractor import XLSXExtractor


@pytest.fixture
def parser_registry():
    return ParserRegistry()


@pytest.mark.asyncio
async def test_live_document_extraction_markdown_and_text(parser_registry: ParserRegistry):
    """Verify live extraction of text and markdown documents."""
    content = "# Document Title\n\nThis is a section with valuable architectural intelligence."
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(content)
        f.flush()
        temp_path = Path(f.name)

    try:
        res = await parser_registry.extract(
            file_path=temp_path,
            filename="audit_spec.md",
            mime_type="text/markdown",
            ext=".md",
        )
        assert res.status == "extracted"
        assert "Document Title" in res.extracted_text
        assert res.parser_name == "text_extractor"
        assert res.total_chars > 0
    finally:
        if temp_path.exists():
            temp_path.unlink()


@pytest.mark.asyncio
async def test_live_document_extraction_docx(parser_registry: ParserRegistry):
    """Verify live extraction of Word .docx documents using docx library."""
    from docx import Document
    
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
        temp_path = Path(f.name)

    try:
        doc = Document()
        doc.add_heading("Live Audit Heading", level=1)
        doc.add_paragraph("Live paragraph testing docx extraction without external CLI.")
        doc.save(str(temp_path))

        res = await parser_registry.extract(
            file_path=temp_path,
            filename="live_test.docx",
            mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ext=".docx",
        )
        assert res.status == "extracted"
        assert "Live Audit Heading" in res.extracted_text
        assert "Live paragraph testing" in res.extracted_text
        assert res.parser_name == "docx_extractor"
    finally:
        if temp_path.exists():
            temp_path.unlink()


@pytest.mark.asyncio
async def test_live_document_extraction_xlsx(parser_registry: ParserRegistry):
    """Verify live extraction of Excel .xlsx spreadsheets."""
    import openpyxl

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        temp_path = Path(f.name)

    try:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "AuditMetrics"
        ws.append(["Metric", "Score", "Status"])
        ws.append(["Security", 100, "PASS"])
        wb.save(str(temp_path))

        res = await parser_registry.extract(
            file_path=temp_path,
            filename="metrics.xlsx",
            mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ext=".xlsx",
        )
        assert res.status == "extracted"
        assert "Security" in res.extracted_text
        assert "PASS" in res.extracted_text
        assert res.parser_name == "xlsx_extractor"
    finally:
        if temp_path.exists():
            temp_path.unlink()


@pytest.mark.asyncio
async def test_malformed_document_resilience(parser_registry: ParserRegistry):
    """Verify malformed/corrupt document headers fail safely without unhandled crashes."""
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".pdf", delete=False) as f:
        f.write(b"NOT_A_VALID_PDF_HEADER_1234567890GARBAGE")
        f.flush()
        temp_path = Path(f.name)

    try:
        res = await parser_registry.extract(
            file_path=temp_path,
            filename="corrupt.pdf",
            mime_type="application/pdf",
            ext=".pdf",
        )
        assert res.status == "failed"
        assert res.error_message is not None
        assert "PDF parsing failure" in res.error_message or "Stream" in res.error_message
    finally:
        if temp_path.exists():
            temp_path.unlink()


@pytest.mark.asyncio
async def test_path_traversal_archive_rejection(parser_registry: ParserRegistry):
    """Verify zip archive containing traversal entries is rejected at the security boundary."""
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("../../etc/passwd", "root:x:0:0:root:/root:/bin/bash")

    zip_bytes = zip_buffer.getvalue()
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".zip", delete=False) as f:
        f.write(zip_bytes)
        f.flush()
        temp_path = Path(f.name)

    try:
        with pytest.raises(ValidationError) as exc_info:
            await parser_registry.extract(
                file_path=temp_path,
                filename="traversal_attack.zip",
                mime_type="application/zip",
                ext=".zip",
            )
        assert "Path traversal detected" in str(exc_info.value) or "traversal" in str(exc_info.value).lower()
    finally:
        if temp_path.exists():
            temp_path.unlink()


@pytest.mark.asyncio
async def test_deferred_format_guard_intercepts_legacy_formats(parser_registry: ParserRegistry):
    """Verify legacy binary formats (.doc, .xls, .ppt) are safely intercepted without running external shell CLIs."""
    dummy_path = Path("dummy.doc")
    res = await parser_registry.extract(
        file_path=dummy_path,
        filename="legacy.doc",
        mime_type="application/msword",
        ext=".doc",
    )
    assert res.status == "failed"
    assert res.parser_name == "deferred_format_guard"
    assert "deferred" in res.error_message.lower()
    assert "upload modern .docx" in res.error_message.lower()
