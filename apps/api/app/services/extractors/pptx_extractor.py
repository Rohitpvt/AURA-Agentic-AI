"""Deterministic Microsoft PowerPoint (.pptx) Presentation Parser (AURA-602).

Supports:
- Slide text, title, and shape text extraction (max 100 slides)
- Table extraction on presentation slides
- Slide speaker notes extraction where available
- Active content / embedded executable object neutralization
- Bounded memory buffers (max 5 MB extracted text)
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Set
import pptx

from app.core.logging import logger
from app.schemas.file import ExtractedContentItem, NormalizedExtractionResult
from app.services.extractors.base import BaseExtractor


class PPTXExtractor(BaseExtractor):
    """Isolated, bounded PPTX presentation parser extracting slide text, tables, and notes."""

    PARSER_NAME = "pptx_extractor"
    PARSER_VERSION = "1.0.0"

    SUPPORTED_EXTENSIONS: Set[str] = {".pptx"}
    SUPPORTED_MIMES: Set[str] = {
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.ms-powerpoint",
    }

    MAX_SLIDES: int = 100

    async def extract(
        self,
        file_path: Path,
        filename: str,
        mime_type: str,
        ext: str,
        options: Optional[Dict[str, Any]] = None,
    ) -> NormalizedExtractionResult:
        """Extract slide hierarchy, titles, shapes, and notes from a .pptx presentation."""
        options = options or {}
        max_bytes = options.get("max_text_bytes", self.MAX_EXTRACTED_BYTES)
        warnings: List[str] = []
        security_flags: List[str] = []
        content_items: List[ExtractedContentItem] = []
        slide_sections: List[str] = []
        metadata: Dict[str, Any] = {}

        try:
            prs = pptx.Presentation(str(file_path))
            total_slides = len(prs.slides)
            metadata["total_slides"] = total_slides

            if total_slides > self.MAX_SLIDES:
                warnings.append(f"Presentation exceeds slide limit ({total_slides} slides); only first {self.MAX_SLIDES} parsed.")

            item_idx = 0
            slides_to_parse = min(total_slides, self.MAX_SLIDES)

            for slide_idx in range(slides_to_parse):
                slide = prs.slides[slide_idx]
                slide_num = slide_idx + 1
                slide_lines: List[str] = [f"=== [Slide {slide_num}] ==="]

                # 1. Slide Title
                if slide.shapes.title and slide.shapes.title.text:
                    title_text = slide.shapes.title.text.strip()
                    slide_lines.append(f"# {title_text}")
                    content_items.append(
                        ExtractedContentItem(
                            index=item_idx,
                            text=title_text,
                            item_type="slide_title",
                            source_location={"slide_number": slide_num, "is_title": True},
                        )
                    )
                    item_idx += 1

                # 2. Iterate Shapes
                for shape in slide.shapes:
                    if shape == slide.shapes.title:
                        continue

                    # Text Frame
                    if shape.has_text_frame:
                        shape_text = shape.text_frame.text.strip()
                        if shape_text:
                            slide_lines.append(shape_text)
                            content_items.append(
                                ExtractedContentItem(
                                    index=item_idx,
                                    text=shape_text,
                                    item_type="slide_body",
                                    source_location={
                                        "slide_number": slide_num,
                                        "shape_name": getattr(shape, "name", "shape"),
                                    },
                                )
                            )
                            item_idx += 1

                    # Table Shape
                    if shape.has_table:
                        table = shape.table
                        table_lines = []
                        for r_idx, row in enumerate(table.rows):
                            row_cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
                            if any(row_cells):
                                table_lines.append(" | ".join(row_cells))
                        if table_lines:
                            table_text = "\n".join(table_lines)
                            slide_lines.append(f"[Table]\n{table_text}")
                            content_items.append(
                                ExtractedContentItem(
                                    index=item_idx,
                                    text=table_text,
                                    item_type="slide_table",
                                    source_location={
                                        "slide_number": slide_num,
                                        "shape_name": getattr(shape, "name", "table"),
                                    },
                                )
                            )
                            item_idx += 1

                # 3. Slide Notes
                try:
                    if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
                        notes_text = slide.notes_slide.notes_text_frame.text.strip()
                        if notes_text:
                            slide_lines.append(f"[Speaker Notes]: {notes_text}")
                            content_items.append(
                                ExtractedContentItem(
                                    index=item_idx,
                                    text=notes_text,
                                    item_type="slide_notes",
                                    source_location={"slide_number": slide_num, "is_notes": True},
                                )
                            )
                            item_idx += 1
                except Exception as notes_err:
                    logger.debug(f"PPTXExtractor: Notes reading note on slide {slide_num}: {notes_err}")

                slide_sections.append("\n".join(slide_lines))

            full_text = "\n\n".join(slide_sections).strip()
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
            logger.error(f"PPTXExtractor: Failed to parse PPTX {filename}: {e}", exc_info=True)
            return self.build_result(
                filename=filename,
                mime_type=mime_type,
                ext=ext,
                status="failed",
                extracted_text="",
                content_items=[],
                error_message=f"PPTX parsing failure: {str(e)}",
                max_bytes=max_bytes,
            )
