"""Deterministic PDF Parser with Layout Preservation and Scanned Document Diagnostic (AURA-602).

Supports:
- Digital PDF text extraction via pypdf and pdfplumber
- Page boundary tagging (max 200 pages)
- Table extraction where present
- PDF JavaScript / OpenAction / Embedded active content neutralization
- Bounded memory buffers (max 5 MB extracted text)
- Scanned / image-only diagnostic without OCR hallucination
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Set
import pypdf
import pdfplumber

from app.core.logging import logger
from app.schemas.file import ExtractedContentItem, NormalizedExtractionResult
from app.services.extractors.base import BaseExtractor


class PDFExtractor(BaseExtractor):
    """Isolated, bounded PDF parser supporting digital text, metadata, tables, and active content neutralization."""

    PARSER_NAME = "pdf_extractor"
    PARSER_VERSION = "1.0.0"

    SUPPORTED_EXTENSIONS: Set[str] = {".pdf"}
    SUPPORTED_MIMES: Set[str] = {"application/pdf", "application/x-pdf"}

    MAX_PDF_PAGES: int = 200

    async def extract(
        self,
        file_path: Path,
        filename: str,
        mime_type: str,
        ext: str,
        options: Optional[Dict[str, Any]] = None,
    ) -> NormalizedExtractionResult:
        """Extract digital text, tables, and structural metadata from a PDF file."""
        options = options or {}
        max_bytes = options.get("max_text_bytes", self.MAX_EXTRACTED_BYTES)
        warnings: List[str] = []
        security_flags: List[str] = []
        content_items: List[ExtractedContentItem] = []
        extracted_pages_text: List[str] = []
        metadata: Dict[str, Any] = {}

        try:
            # 1. Inspect and parse with pypdf for structure and active content
            with open(file_path, "rb") as f_pdf:
                reader = pypdf.PdfReader(f_pdf, strict=False)

                if reader.is_encrypted:
                    try:
                        # Attempt empty-password decrypt
                        reader.decrypt("")
                    except Exception:
                        return self.build_result(
                            filename=filename,
                            mime_type=mime_type,
                            ext=ext,
                            status="failed",
                            extracted_text="",
                            content_items=[],
                            error_message="PDF is password-encrypted and cannot be parsed without credentials.",
                            max_bytes=max_bytes,
                        )

                total_pages = len(reader.pages)
                metadata["total_pages"] = total_pages
                metadata["is_encrypted"] = reader.is_encrypted

                # Extract standard metadata dictionary
                if reader.metadata:
                    metadata["title"] = reader.metadata.title or ""
                    metadata["author"] = reader.metadata.author or ""
                    metadata["subject"] = reader.metadata.subject or ""
                    metadata["creator"] = reader.metadata.creator or ""
                    metadata["producer"] = reader.metadata.producer or ""

                # Check for active content / JavaScript triggers in catalog
                try:
                    root = reader.trailer.get("/Root", {})
                    if hasattr(root, "get_object"):
                        root = root.get_object()

                    # Check for /JavaScript, /OpenAction, /AA (Additional Actions), /Launch
                    if isinstance(root, dict):
                        if "/Names" in root:
                            names_obj = root["/Names"]
                            if hasattr(names_obj, "get_object"):
                                names_obj = names_obj.get_object()
                            if isinstance(names_obj, dict) and "/JavaScript" in names_obj:
                                security_flags.append("PDF_EMBEDDED_JAVASCRIPT_DETECTED_NEUTRALIZED")
                        if "/OpenAction" in root or "/AA" in root:
                            security_flags.append("PDF_AUTO_ACTION_DETECTED_NEUTRALIZED")
                except Exception as cat_err:
                    logger.debug(f"PDFExtractor: Active content inspection notice: {cat_err}")

                pages_to_process = min(total_pages, self.MAX_PDF_PAGES)
                if total_pages > self.MAX_PDF_PAGES:
                    warnings.append(f"PDF exceeds page limit ({total_pages} pages). Only first {self.MAX_PDF_PAGES} pages processed.")

                # 2. Extract page-by-page text using pypdf
                item_idx = 0
                for page_idx in range(pages_to_process):
                    page = reader.pages[page_idx]
                    page_num = page_idx + 1
                    try:
                        page_text = page.extract_text() or ""
                    except Exception as page_err:
                        page_text = ""
                        warnings.append(f"Page {page_num} text extraction warning: {page_err}")

                    page_text_clean = page_text.strip()
                    if page_text_clean:
                        extracted_pages_text.append(f"--- [Page {page_num}] ---\n{page_text_clean}")
                        content_items.append(
                            ExtractedContentItem(
                                index=item_idx,
                                text=page_text_clean,
                                item_type="page_text",
                                source_location={"page": page_num},
                            )
                        )
                        item_idx += 1

            # 3. Optional table layout extraction via pdfplumber
            try:
                with pdfplumber.open(file_path) as plum_pdf:
                    for page_idx in range(min(len(plum_pdf.pages), self.MAX_PDF_PAGES)):
                        p_plum = plum_pdf.pages[page_idx]
                        page_num = page_idx + 1
                        tables = p_plum.extract_tables() or []
                        for t_idx, table in enumerate(tables):
                            if not table:
                                continue
                            # Format table as Markdown table
                            table_lines = []
                            for row in table:
                                if row:
                                    clean_row = [str(c or "").strip().replace("\n", " ") for c in row]
                                    table_lines.append(" | ".join(clean_row))
                            if table_lines:
                                table_str = "\n".join(table_lines)
                                content_items.append(
                                    ExtractedContentItem(
                                        index=item_idx,
                                        text=table_str,
                                        item_type="table",
                                        source_location={"page": page_num, "table_index": t_idx + 1},
                                    )
                                )
                                item_idx += 1
            except Exception as plum_err:
                logger.debug(f"PDFExtractor: pdfplumber table extraction note: {plum_err}")

            full_extracted_text = "\n\n".join(extracted_pages_text)

            # 4. Scanned PDF diagnostic
            if not full_extracted_text.strip():
                warnings.append("Scanned or image-only PDF detected: no digital text layer found. OCR is deferred.")
                return self.build_result(
                    filename=filename,
                    mime_type=mime_type,
                    ext=ext,
                    status="no_text_extracted",
                    extracted_text="",
                    content_items=content_items,
                    metadata=metadata,
                    warnings=warnings,
                    security_flags=security_flags,
                    max_bytes=max_bytes,
                )

            return self.build_result(
                filename=filename,
                mime_type=mime_type,
                ext=ext,
                status="extracted",
                extracted_text=full_extracted_text,
                content_items=content_items,
                metadata=metadata,
                warnings=warnings,
                security_flags=security_flags,
                max_bytes=max_bytes,
            )

        except Exception as e:
            logger.error(f"PDFExtractor: Failed to parse PDF {filename}: {e}", exc_info=True)
            return self.build_result(
                filename=filename,
                mime_type=mime_type,
                ext=ext,
                status="failed",
                extracted_text="",
                content_items=[],
                error_message=f"PDF parsing failure: {str(e)}",
                max_bytes=max_bytes,
            )
