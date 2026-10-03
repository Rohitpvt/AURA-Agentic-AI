"""Base Parser Interface and Common Utilities for Multi-Format Extraction (AURA-602)."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
import uuid

from app.core.logging import logger
from app.core.sanitization import prompt_sanitizer
from app.schemas.file import ExtractedContentItem, NormalizedExtractionResult


class BaseExtractor(ABC):
    """Abstract base class for isolated, deterministic document and file extractors."""

    PARSER_NAME: str = "base_parser"
    PARSER_VERSION: str = "1.0.0"
    SUPPORTED_EXTENSIONS: Set[str] = set()
    SUPPORTED_MIMES: Set[str] = set()

    MAX_EXTRACTED_BYTES: int = 5 * 1024 * 1024  # 5 MB ceiling
    DEFAULT_TIMEOUT_SECONDS: float = 60.0

    @abstractmethod
    async def extract(
        self,
        file_path: Path,
        filename: str,
        mime_type: str,
        ext: str,
        options: Optional[Dict[str, Any]] = None,
    ) -> NormalizedExtractionResult:
        """Execute extraction on the target file and produce a NormalizedExtractionResult."""
        pass

    def can_handle(self, ext: str, mime_type: str) -> bool:
        """Check if this extractor supports the given extension or MIME type."""
        norm_ext = ext.lower() if ext.startswith(".") else f".{ext.lower()}"
        if norm_ext in self.SUPPORTED_EXTENSIONS:
            return True
        norm_mime = mime_type.lower().split(";")[0].strip()
        return norm_mime in self.SUPPORTED_MIMES

    def build_result(
        self,
        filename: str,
        mime_type: str,
        ext: str,
        status: str,
        extracted_text: str,
        content_items: List[ExtractedContentItem],
        metadata: Optional[Dict[str, Any]] = None,
        warnings: Optional[List[str]] = None,
        security_flags: Optional[List[str]] = None,
        error_message: Optional[str] = None,
        max_bytes: Optional[int] = None,
        file_id: Optional[uuid.UUID] = None,
    ) -> NormalizedExtractionResult:
        """Construct a standardized NormalizedExtractionResult with sanitization and bounded buffers."""
        effective_max = max_bytes or self.MAX_EXTRACTED_BYTES
        is_truncated = False

        # Enforce memory and text output bounds
        text_bytes = extracted_text.encode("utf-8")
        if len(text_bytes) > effective_max:
            # Truncate at nearest safe boundary
            truncated_bytes = text_bytes[:effective_max]
            extracted_text = truncated_bytes.decode("utf-8", errors="ignore") + "\n[CONTENT TRUNCATED AT 5 MB LIMIT]"
            is_truncated = True
            if warnings is None:
                warnings = []
            warnings.append(f"Extracted content exceeded {effective_max} bytes and was truncated.")

        # Wrap in canonical prompt sanitization envelope (<untrusted_external_content>)
        sanitized_envelope = prompt_sanitizer.wrap_untrusted_envelope(
            content=extracted_text,
            source_type=f"file_parser:{self.PARSER_NAME}:{ext}",
            max_length=effective_max + 1024,
        )

        # Scan for adversarial injection patterns in extracted text
        has_injection, detected_flags = prompt_sanitizer.detect_injection_signatures(extracted_text)
        all_security_flags = list(security_flags or [])
        if has_injection:
            all_security_flags.extend(detected_flags)

        return NormalizedExtractionResult(
            file_id=file_id,
            filename=filename,
            mime_type=mime_type,
            file_extension=ext,
            parser_name=self.PARSER_NAME,
            parser_version=self.PARSER_VERSION,
            status=status,
            extracted_text=extracted_text,
            sanitized_envelope=sanitized_envelope,
            metadata=metadata or {},
            content_items=content_items,
            warnings=warnings or [],
            security_flags=all_security_flags,
            error_message=error_message,
            total_chars=len(extracted_text),
            is_truncated=is_truncated,
        )
