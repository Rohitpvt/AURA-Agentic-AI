"""Deterministic Image Metadata Extractor (AURA-602).

Supports:
- PNG, JPEG, WEBP visual format inspection via Pillow
- Dimension (width, height), color mode, and format extraction
- Sanitized EXIF tag decoding without binary payload execution
- No OCR in AURA-602 (OCR is explicitly deferred to Phase 8)
- Corrupted image and decompression bomb defense
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from PIL import Image, ExifTags, UnidentifiedImageError

from app.core.logging import logger
from app.schemas.file import ExtractedContentItem, NormalizedExtractionResult
from app.services.extractors.base import BaseExtractor


class ImageExtractor(BaseExtractor):
    """Isolated image inspector extracting dimensions, color profiles, and EXIF metadata without OCR."""

    PARSER_NAME = "image_extractor"
    PARSER_VERSION = "1.0.0"

    SUPPORTED_EXTENSIONS: Set[str] = {".png", ".jpg", ".jpeg", ".webp"}
    SUPPORTED_MIMES: Set[str] = {
        "image/png", "image/jpeg", "image/webp"
    }

    async def extract(
        self,
        file_path: Path,
        filename: str,
        mime_type: str,
        ext: str,
        options: Optional[Dict[str, Any]] = None,
    ) -> NormalizedExtractionResult:
        """Extract image dimensions, format metadata, and EXIF tags safely."""
        options = options or {}
        max_bytes = options.get("max_text_bytes", self.MAX_EXTRACTED_BYTES)
        warnings: List[str] = []
        security_flags: List[str] = []
        content_items: List[ExtractedContentItem] = []
        metadata: Dict[str, Any] = {}

        try:
            with Image.open(file_path) as img:
                # Basic Dimensions & Mode
                width, height = img.size
                format_name = img.format or ext.lstrip(".").upper()
                mode = img.mode

                metadata["width"] = width
                metadata["height"] = height
                metadata["format"] = format_name
                metadata["mode"] = mode
                metadata["is_animated"] = getattr(img, "is_animated", False)

                # EXIF metadata extraction
                exif_data = {}
                try:
                    raw_exif = img.getexif()
                    if raw_exif:
                        for tag_id, value in raw_exif.items():
                            tag_name = ExifTags.TAGS.get(tag_id, str(tag_id))
                            # Convert non-serializable binary values safely
                            if isinstance(value, bytes):
                                value_str = f"<binary {len(value)} bytes>"
                            else:
                                value_str = str(value)
                            exif_data[tag_name] = value_str
                except Exception as exif_err:
                    warnings.append(f"EXIF extraction notice: {exif_err}")

                metadata["exif"] = exif_data

                # Build summary representation
                summary_lines = [
                    f"Image Metadata for {filename}:",
                    f"- Format: {format_name}",
                    f"- Dimensions: {width} x {height} pixels",
                    f"- Color Mode: {mode}",
                ]
                if exif_data:
                    summary_lines.append("- EXIF Metadata:")
                    for k, v in list(exif_data.items())[:20]:
                        summary_lines.append(f"  * {k}: {v}")

                extracted_text = "\n".join(summary_lines)

                content_items.append(
                    ExtractedContentItem(
                        index=0,
                        text=extracted_text,
                        item_type="image_metadata",
                        source_location={"dimensions": f"{width}x{height}", "format": format_name},
                    )
                )

                warnings.append("Note: Image OCR is deferred to Phase 8. Only structural metadata was extracted.")

                return self.build_result(
                    filename=filename,
                    mime_type=mime_type,
                    ext=ext,
                    status="extracted",
                    extracted_text=extracted_text,
                    content_items=content_items,
                    metadata=metadata,
                    warnings=warnings,
                    security_flags=security_flags,
                    max_bytes=max_bytes,
                )

        except UnidentifiedImageError:
            return self.build_result(
                filename=filename,
                mime_type=mime_type,
                ext=ext,
                status="failed",
                extracted_text="",
                content_items=[],
                error_message="Corrupted or unrecognized image binary header.",
                max_bytes=max_bytes,
            )
        except Exception as e:
            logger.error(f"ImageExtractor: Failed to inspect image {filename}: {e}", exc_info=True)
            return self.build_result(
                filename=filename,
                mime_type=mime_type,
                ext=ext,
                status="failed",
                extracted_text="",
                content_items=[],
                error_message=f"Image inspection failure: {str(e)}",
                max_bytes=max_bytes,
            )
