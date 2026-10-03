"""Safe, Deterministic Text and Structured Data Extractor (AURA-602).

Supports:
- Plain text (.txt, .log)
- Markdown (.md, .markdown)
- CSV (.csv)
- JSON (.json)
- YAML (.yaml, .yml)
"""

import csv
import io
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
import yaml

from app.core.logging import logger
from app.schemas.file import ExtractedContentItem, NormalizedExtractionResult
from app.services.extractors.base import BaseExtractor


class TextExtractor(BaseExtractor):
    """Safe in-process extractor for plain text, markdown, CSV, JSON, and YAML documents."""

    PARSER_NAME = "text_extractor"
    PARSER_VERSION = "1.0.0"

    SUPPORTED_EXTENSIONS: Set[str] = {
        ".txt", ".log", ".md", ".markdown", ".csv", ".json", ".yaml", ".yml"
    }
    SUPPORTED_MIMES: Set[str] = {
        "text/plain", "text/markdown", "text/csv", "application/json", "application/x-yaml", "text/yaml"
    }

    async def extract(
        self,
        file_path: Path,
        filename: str,
        mime_type: str,
        ext: str,
        options: Optional[Dict[str, Any]] = None,
    ) -> NormalizedExtractionResult:
        """Read and normalize text/structured data into canonical extraction representation."""
        options = options or {}
        max_bytes = options.get("max_text_bytes", self.MAX_EXTRACTED_BYTES)
        warnings: List[str] = []
        security_flags: List[str] = []
        content_items: List[ExtractedContentItem] = []

        # 1. Read raw binary bytes
        try:
            raw_bytes = file_path.read_bytes()
        except Exception as read_err:
            logger.error(f"TextExtractor: Failed to read {file_path}: {read_err}")
            return self.build_result(
                filename=filename,
                mime_type=mime_type,
                ext=ext,
                status="failed",
                extracted_text="",
                content_items=[],
                error_message=f"File read error: {str(read_err)}",
                max_bytes=max_bytes,
            )

        # 2. Decode text safely (UTF-8 with fallbacks)
        text_content = ""
        try:
            text_content = raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text_content = raw_bytes.decode("cp1252")
                warnings.append("Decoded with Windows-1252 fallback due to UTF-8 decoding error.")
            except Exception:
                text_content = raw_bytes.decode("utf-8", errors="replace")
                warnings.append("Decoded with UTF-8 replacement characters due to encoding errors.")

        normalized_ext = ext.lower()

        # 3. Format-specific structured processing
        if normalized_ext == ".csv":
            return self._extract_csv(raw_text=text_content, filename=filename, mime_type=mime_type, ext=ext, max_bytes=max_bytes, warnings=warnings, security_flags=security_flags)
        elif normalized_ext == ".json":
            return self._extract_json(raw_text=text_content, filename=filename, mime_type=mime_type, ext=ext, max_bytes=max_bytes, warnings=warnings, security_flags=security_flags)
        elif normalized_ext in [".yaml", ".yml"]:
            return self._extract_yaml(raw_text=text_content, filename=filename, mime_type=mime_type, ext=ext, max_bytes=max_bytes, warnings=warnings, security_flags=security_flags)
        else:
            return self._extract_plain_or_markdown(raw_text=text_content, filename=filename, mime_type=mime_type, ext=ext, max_bytes=max_bytes, warnings=warnings, security_flags=security_flags)

    def _extract_plain_or_markdown(
        self,
        raw_text: str,
        filename: str,
        mime_type: str,
        ext: str,
        max_bytes: int,
        warnings: List[str],
        security_flags: List[str],
    ) -> NormalizedExtractionResult:
        """Extract lines and paragraphs from markdown or plain text files."""
        lines = raw_text.splitlines()
        content_items: List[ExtractedContentItem] = []
        current_paragraph: List[str] = []
        para_start = 1
        item_idx = 0

        for line_num, line in enumerate(lines, start=1):
            stripped = line.strip()
            if not stripped:
                if current_paragraph:
                    para_text = "\n".join(current_paragraph)
                    content_items.append(
                        ExtractedContentItem(
                            index=item_idx,
                            text=para_text,
                            item_type="paragraph",
                            source_location={"line_start": para_start, "line_end": line_num - 1},
                        )
                    )
                    item_idx += 1
                    current_paragraph = []
                continue

            if not current_paragraph:
                para_start = line_num

            # Check markdown heading
            if stripped.startswith("#"):
                if current_paragraph:
                    para_text = "\n".join(current_paragraph)
                    content_items.append(
                        ExtractedContentItem(
                            index=item_idx,
                            text=para_text,
                            item_type="paragraph",
                            source_location={"line_start": para_start, "line_end": line_num - 1},
                        )
                    )
                    item_idx += 1
                    current_paragraph = []

                content_items.append(
                    ExtractedContentItem(
                        index=item_idx,
                        text=stripped,
                        item_type="heading",
                        source_location={"line_start": line_num, "line_end": line_num, "heading_level": len(stripped) - len(stripped.lstrip("#"))},
                    )
                )
                item_idx += 1
                continue

            current_paragraph.append(line)

        if current_paragraph:
            para_text = "\n".join(current_paragraph)
            content_items.append(
                ExtractedContentItem(
                    index=item_idx,
                    text=para_text,
                    item_type="paragraph",
                    source_location={"line_start": para_start, "line_end": len(lines)},
                )
            )

        metadata = {
            "line_count": len(lines),
            "paragraph_count": len(content_items),
            "format": "markdown" if ext in [".md", ".markdown"] else "plain_text",
        }

        status = "extracted" if raw_text.strip() else "no_text_extracted"

        return self.build_result(
            filename=filename,
            mime_type=mime_type,
            ext=ext,
            status=status,
            extracted_text=raw_text,
            content_items=content_items,
            metadata=metadata,
            warnings=warnings,
            security_flags=security_flags,
            max_bytes=max_bytes,
        )

    def _extract_csv(
        self,
        raw_text: str,
        filename: str,
        mime_type: str,
        ext: str,
        max_bytes: int,
        warnings: List[str],
        security_flags: List[str],
    ) -> NormalizedExtractionResult:
        """Parse CSV safely into structured tabular data and rows."""
        content_items: List[ExtractedContentItem] = []
        rows: List[List[str]] = []
        item_idx = 0

        try:
            # Sniff dialect or fallback to standard comma
            sample = raw_text[:2048]
            delimiter = ","
            try:
                dialect = csv.Sniffer().sniff(sample)
                delimiter = dialect.delimiter
            except Exception:
                delimiter = ","

            reader = csv.reader(io.StringIO(raw_text), delimiter=delimiter)
            for row_idx, row in enumerate(reader):
                if not row:
                    continue
                rows.append(row)
                row_str = " | ".join(cell.strip() for cell in row)
                content_items.append(
                    ExtractedContentItem(
                        index=item_idx,
                        text=row_str,
                        item_type="table_row",
                        source_location={"row": row_idx, "column_count": len(row)},
                    )
                )
                item_idx += 1

                # Cap row parsing if excessive
                if row_idx >= 5000:
                    warnings.append("CSV row limit reached (5,000 rows max). Remaining rows truncated.")
                    break

        except Exception as csv_err:
            warnings.append(f"CSV tabular parsing encounter note: {csv_err}; fallback to raw text.")

        metadata = {
            "row_count": len(rows),
            "column_count": len(rows[0]) if rows else 0,
            "delimiter": delimiter,
            "format": "csv",
        }

        status = "extracted" if raw_text.strip() else "no_text_extracted"

        return self.build_result(
            filename=filename,
            mime_type=mime_type,
            ext=ext,
            status=status,
            extracted_text=raw_text,
            content_items=content_items,
            metadata=metadata,
            warnings=warnings,
            security_flags=security_flags,
            max_bytes=max_bytes,
        )

    def _extract_json(
        self,
        raw_text: str,
        filename: str,
        mime_type: str,
        ext: str,
        max_bytes: int,
        warnings: List[str],
        security_flags: List[str],
    ) -> NormalizedExtractionResult:
        """Parse JSON safely and extract structural key/value hierarchy."""
        content_items: List[ExtractedContentItem] = []
        metadata: Dict[str, Any] = {"format": "json"}

        try:
            parsed = json.loads(raw_text)
            metadata["is_valid_json"] = True
            metadata["root_type"] = type(parsed).__name__

            # Generate formatted normalized representation
            formatted_text = json.dumps(parsed, indent=2)

            if isinstance(parsed, dict):
                for idx, (k, v) in enumerate(parsed.items()):
                    val_str = json.dumps(v) if isinstance(v, (dict, list)) else str(v)
                    content_items.append(
                        ExtractedContentItem(
                            index=idx,
                            text=f"{k}: {val_str}",
                            item_type="json_property",
                            source_location={"json_key": str(k)},
                        )
                    )
            elif isinstance(parsed, list):
                for idx, item in enumerate(parsed[:500]):
                    content_items.append(
                        ExtractedContentItem(
                            index=idx,
                            text=json.dumps(item),
                            item_type="json_array_item",
                            source_location={"array_index": idx},
                        )
                    )

            return self.build_result(
                filename=filename,
                mime_type=mime_type,
                ext=ext,
                status="extracted",
                extracted_text=formatted_text,
                content_items=content_items,
                metadata=metadata,
                warnings=warnings,
                security_flags=security_flags,
                max_bytes=max_bytes,
            )

        except Exception as json_err:
            warnings.append(f"JSON syntax error ({json_err}); treating as raw text.")
            return self._extract_plain_or_markdown(
                raw_text=raw_text, filename=filename, mime_type=mime_type, ext=ext, max_bytes=max_bytes, warnings=warnings, security_flags=security_flags
            )

    def _extract_yaml(
        self,
        raw_text: str,
        filename: str,
        mime_type: str,
        ext: str,
        max_bytes: int,
        warnings: List[str],
        security_flags: List[str],
    ) -> NormalizedExtractionResult:
        """Parse YAML safely using SafeLoader without arbitrary object execution."""
        content_items: List[ExtractedContentItem] = []
        metadata: Dict[str, Any] = {"format": "yaml"}

        try:
            parsed = yaml.safe_load(raw_text)
            metadata["is_valid_yaml"] = True
            metadata["root_type"] = type(parsed).__name__

            if isinstance(parsed, dict):
                for idx, (k, v) in enumerate(parsed.items()):
                    val_str = str(v)
                    content_items.append(
                        ExtractedContentItem(
                            index=idx,
                            text=f"{k}: {val_str}",
                            item_type="yaml_property",
                            source_location={"yaml_key": str(k)},
                        )
                    )

            return self.build_result(
                filename=filename,
                mime_type=mime_type,
                ext=ext,
                status="extracted",
                extracted_text=raw_text,
                content_items=content_items,
                metadata=metadata,
                warnings=warnings,
                security_flags=security_flags,
                max_bytes=max_bytes,
            )

        except Exception as yaml_err:
            warnings.append(f"YAML parsing error ({yaml_err}); treating as plain text.")
            return self._extract_plain_or_markdown(
                raw_text=raw_text, filename=filename, mime_type=mime_type, ext=ext, max_bytes=max_bytes, warnings=warnings, security_flags=security_flags
            )
