"""Central Multi-Format Parser Registry and Dispatcher (AURA-602).

Manages all deterministic in-process extractors:
- Text & structured text (txt, md, csv, json, yaml, log)
- Documents (pdf, docx, pptx)
- Spreadsheets (xlsx with formula preservation)
- Codebases & source code (py, ts, js, go, rs, java, c, cpp, sql, html, css)
- Archives (zip)
- Visual & Audio metadata (png, jpg, webp, mp3, wav, m4a)

Enforces:
- 60-second processing timeout via asyncio.wait_for
- Deferred format diagnostics (.xls, .tar, .tar.gz)
- Memory and output bounds
"""

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.logging import logger
from app.schemas.file import NormalizedExtractionResult
from app.services.extractors.archive_extractor import ArchiveExtractor
from app.services.extractors.audio_extractor import AudioExtractor
from app.services.extractors.base import BaseExtractor
from app.services.extractors.code_extractor import CodeExtractor
from app.services.extractors.docx_extractor import DocxExtractor
from app.services.extractors.image_extractor import ImageExtractor
from app.services.extractors.pdf_extractor import PDFExtractor
from app.services.extractors.pptx_extractor import PPTXExtractor
from app.services.extractors.text_extractor import TextExtractor
from app.services.extractors.xlsx_extractor import XLSXExtractor


class ParserRegistry:
    """Central registry dispatching files to safe, isolated multi-format extractors."""

    PARSER_TIMEOUT_SECONDS: float = 60.0

    DEFERRED_FORMAT_MESSAGES: Dict[str, str] = {
        ".xls": "Legacy BIFF (.xls) format is deferred from Phase 6 support matrix. Please upload modern .xlsx.",
        ".tar": "TAR archive format is deferred from initial Phase 6 support. Please upload standard .zip archive.",
        ".tar.gz": "TAR.GZ compressed archive format is deferred from initial Phase 6 support. Please upload .zip.",
        ".tgz": "TGZ compressed archive format is deferred from initial Phase 6 support. Please upload .zip.",
        ".doc": "Legacy Word Binary (.doc) format is deferred. Please upload modern .docx.",
        ".ppt": "Legacy PowerPoint Binary (.ppt) format is deferred. Please upload modern .pptx.",
    }

    def __init__(self):
        # Register all active extractors in priority order
        self.extractors: List[BaseExtractor] = [
            TextExtractor(),
            PDFExtractor(),
            DocxExtractor(),
            XLSXExtractor(),
            PPTXExtractor(),
            CodeExtractor(),
            ArchiveExtractor(),
            ImageExtractor(),
            AudioExtractor(),
        ]

    def get_extractor_for_file(self, ext: str, mime_type: str) -> Optional[BaseExtractor]:
        """Find the matching extractor instance, prioritizing exact extension support over MIME fallback."""
        norm_ext = ext.lower() if ext.startswith(".") else f".{ext.lower()}"
        norm_mime = mime_type.lower().split(";")[0].strip() if mime_type else ""

        # Pass 1: Exact extension match (highest priority)
        for extractor in self.extractors:
            if norm_ext in extractor.SUPPORTED_EXTENSIONS:
                return extractor

        # Pass 2: MIME type match
        for extractor in self.extractors:
            if norm_mime and norm_mime in extractor.SUPPORTED_MIMES:
                return extractor

        return None

    async def extract(
        self,
        file_path: Path,
        filename: str,
        mime_type: str,
        ext: str,
        options: Optional[Dict[str, Any]] = None,
    ) -> NormalizedExtractionResult:
        """Dispatch target file to its registered extractor under a 60-second processing timeout."""
        options = options or {}
        norm_ext = ext.lower() if ext.startswith(".") else f".{ext.lower()}"

        # 1. Check for explicitly deferred formats
        if norm_ext in self.DEFERRED_FORMAT_MESSAGES:
            deferred_msg = self.DEFERRED_FORMAT_MESSAGES[norm_ext]
            return NormalizedExtractionResult(
                filename=filename,
                mime_type=mime_type,
                file_extension=ext,
                parser_name="deferred_format_guard",
                parser_version="1.0.0",
                status="failed",
                extracted_text="",
                sanitized_envelope="<untrusted_external_content>\n[DEFERRED FORMAT]\n</untrusted_external_content>",
                metadata={"deferred_format": True, "format": norm_ext},
                content_items=[],
                warnings=[deferred_msg],
                security_flags=["DEFERRED_FORMAT_REJECTED"],
                error_message=deferred_msg,
            )

        # 2. Match Extractor
        extractor = self.get_extractor_for_file(norm_ext, mime_type)
        if not extractor:
            # Fallback for plain text if extension is missing/unknown but MIME is text
            if mime_type.startswith("text/"):
                extractor = self.extractors[0]  # TextExtractor
            else:
                return NormalizedExtractionResult(
                    filename=filename,
                    mime_type=mime_type,
                    file_extension=ext,
                    parser_name="unsupported_format_guard",
                    parser_version="1.0.0",
                    status="failed",
                    extracted_text="",
                    sanitized_envelope="<untrusted_external_content>\n[UNSUPPORTED FORMAT]\n</untrusted_external_content>",
                    metadata={"unsupported_format": True},
                    content_items=[],
                    warnings=[f"Unsupported file format '{ext}' ({mime_type})."],
                    security_flags=[],
                    error_message=f"No safe extractor registered for extension '{ext}' or MIME '{mime_type}'.",
                )

        # 3. Execute with Timeout Guard (60.0s ceiling)
        timeout_seconds = float(options.get("timeout_seconds", self.PARSER_TIMEOUT_SECONDS))
        try:
            return await asyncio.wait_for(
                extractor.extract(
                    file_path=file_path,
                    filename=filename,
                    mime_type=mime_type,
                    ext=ext,
                    options=options,
                ),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.warning(
                f"ParserRegistry: Extraction timed out after {timeout_seconds}s for {filename} using {extractor.PARSER_NAME}"
            )
            return NormalizedExtractionResult(
                filename=filename,
                mime_type=mime_type,
                file_extension=ext,
                parser_name=extractor.PARSER_NAME,
                parser_version=extractor.PARSER_VERSION,
                status="failed",
                extracted_text="",
                sanitized_envelope="<untrusted_external_content>\n[TIMEOUT]\n</untrusted_external_content>",
                metadata={"timeout_seconds": timeout_seconds},
                content_items=[],
                warnings=[f"File extraction timed out after {timeout_seconds} seconds."],
                security_flags=["PARSER_TIMEOUT_EXCEEDED"],
                error_message=f"Extraction timed out after {timeout_seconds} seconds.",
            )


parser_registry = ParserRegistry()
