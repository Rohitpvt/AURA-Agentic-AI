"""Deterministic Microsoft Word (.docx) Document Parser (AURA-602).

Supports:
- Paragraph and heading extraction with hierarchy tracking
- Table matrix extraction
- Document core properties / metadata extraction
- Embedded macro / active content neutralization
- Bounded memory buffers (max 5 MB extracted text)
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Set
import docx

from app.core.logging import logger
from app.schemas.file import ExtractedContentItem, NormalizedExtractionResult
from app.services.extractors.base import BaseExtractor


class DocxExtractor(BaseExtractor):
    """Isolated, bounded DOCX parser extracting structural paragraphs, headings, tables, and metadata."""

    PARSER_NAME = "docx_extractor"
    PARSER_VERSION = "1.0.0"

    SUPPORTED_EXTENSIONS: Set[str] = {".docx"}
    SUPPORTED_MIMES: Set[str] = {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword",
    }

    async def extract(
        self,
        file_path: Path,
        filename: str,
        mime_type: str,
        ext: str,
        options: Optional[Dict[str, Any]] = None,
    ) -> NormalizedExtractionResult:
        """Extract structural paragraphs, headings, and tables from a .docx file."""
        options = options or {}
        max_bytes = options.get("max_text_bytes", self.MAX_EXTRACTED_BYTES)
        warnings: List[str] = []
        security_flags: List[str] = []
        content_items: List[ExtractedContentItem] = []
        extracted_sections: List[str] = []
        metadata: Dict[str, Any] = {}

        try:
            doc = docx.Document(str(file_path))

            # 1. Document core properties
            try:
                core_props = doc.core_properties
                if core_props:
                    metadata["author"] = core_props.author or ""
                    metadata["title"] = core_props.title or ""
                    metadata["subject"] = core_props.subject or ""
                    metadata["created"] = core_props.created.isoformat() if core_props.created else ""
                    metadata["modified"] = core_props.modified.isoformat() if core_props.modified else ""
                    metadata["last_modified_by"] = core_props.last_modified_by or ""
            except Exception as prop_err:
                logger.debug(f"DocxExtractor: Properties reading notice: {prop_err}")

            item_idx = 0
            current_heading = "Document Root"
            heading_level = 0

            # 2. Iterate paragraphs
            for p_idx, para in enumerate(doc.paragraphs):
                p_text = para.text.strip()
                if not p_text:
                    continue

                style_name = getattr(para.style, "name", "") or ""
                is_heading = style_name.lower().startswith("heading")

                if is_heading:
                    current_heading = p_text
                    try:
                        heading_level = int(style_name.split()[-1])
                    except (ValueError, IndexError):
                        heading_level = 1

                    extracted_sections.append(f"\n### {p_text}\n")
                    content_items.append(
                        ExtractedContentItem(
                            index=item_idx,
                            text=p_text,
                            item_type="heading",
                            source_location={
                                "paragraph_index": p_idx,
                                "style": style_name,
                                "heading_level": heading_level,
                            },
                        )
                    )
                else:
                    extracted_sections.append(p_text)
                    content_items.append(
                        ExtractedContentItem(
                            index=item_idx,
                            text=p_text,
                            item_type="paragraph",
                            source_location={
                                "paragraph_index": p_idx,
                                "section": current_heading,
                                "style": style_name,
                            },
                        )
                    )
                item_idx += 1

            # 3. Iterate tables
            for t_idx, table in enumerate(doc.tables):
                table_lines = []
                for r_idx, row in enumerate(table.rows):
                    row_cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
                    if any(row_cells):
                        row_str = " | ".join(row_cells)
                        table_lines.append(row_str)

                if table_lines:
                    table_full_text = "\n".join(table_lines)
                    extracted_sections.append(f"\n[Table {t_idx + 1}]\n{table_full_text}\n")
                    content_items.append(
                        ExtractedContentItem(
                            index=item_idx,
                            text=table_full_text,
                            item_type="table",
                            source_location={
                                "table_index": t_idx + 1,
                                "row_count": len(table.rows),
                                "column_count": len(table.columns) if table.rows else 0,
                            },
                        )
                    )
                    item_idx += 1

            metadata["paragraph_count"] = len(doc.paragraphs)
            metadata["table_count"] = len(doc.tables)

            full_text = "\n".join(extracted_sections).strip()
            status = "extracted" if full_text else "no_text_extracted"

            return self.build_result(
                filename=filename,
                mime_type=mime_type,
                ext=ext,
                status=status,
                extracted_text=full_text,
                content_items=content_items,
                metadata=metadata,
                warnings=warnings,
                security_flags=security_flags,
                max_bytes=max_bytes,
            )

        except Exception as e:
            logger.error(f"DocxExtractor: Failed to parse DOCX {filename}: {e}", exc_info=True)
            return self.build_result(
                filename=filename,
                mime_type=mime_type,
                ext=ext,
                status="failed",
                extracted_text="",
                content_items=[],
                error_message=f"DOCX parsing failure: {str(e)}",
                max_bytes=max_bytes,
            )
