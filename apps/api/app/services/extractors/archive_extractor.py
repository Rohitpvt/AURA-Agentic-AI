"""Deterministic and Hardened ZIP Codebase / Archive Extractor (AURA-602).

Enforces Strict Archive Defense Invariants:
1. Max Expanded Size: 100 MB ceiling across all uncompressed archive members.
2. Max Member Count: 500 file limit.
3. Max Expansion Ratio: 10:1 ratio check to neutralize Zip Bombs / 42.zip attacks.
4. Path Traversal Neutralization: Strips '../', absolute paths, Windows drive letters (C:), and UNC paths.
5. Symlink / Junction Defense: Blocks symlink creation to prevent directory escape.
6. Isolated Ephemeral Extraction: Unpacks only into isolated temp sandbox, cleans up immediately after text extraction.
7. Deferred Formats: TAR and TAR.GZ are cleanly rejected with deferred status.
"""

import os
from pathlib import Path
import re
import shutil
from typing import Any, Dict, List, Optional, Set
import uuid
import zipfile

from app.core.errors import ValidationError
from app.core.logging import logger
from app.schemas.file import ExtractedContentItem, NormalizedExtractionResult
from app.services.extractors.base import BaseExtractor


class ArchiveExtractor(BaseExtractor):
    """Hardened, bounded ZIP archive extractor protecting against zip-bombs, traversal, and resource exhaustion."""

    PARSER_NAME = "archive_extractor"
    PARSER_VERSION = "1.0.0"

    SUPPORTED_EXTENSIONS: Set[str] = {".zip"}
    SUPPORTED_MIMES: Set[str] = {
        "application/zip",
        "application/x-zip-compressed",
    }

    MAX_ARCHIVE_EXPANDED_BYTES: int = 100 * 1024 * 1024  # 100 MB
    MAX_ARCHIVE_MEMBERS: int = 500
    MAX_EXPANSION_RATIO: float = 10.0

    # Text / code extensions allowed for content extraction from within the archive
    EXTRACTABLE_TEXT_EXTENSIONS: Set[str] = {
        ".txt", ".md", ".json", ".yaml", ".yml", ".csv", ".log",
        ".py", ".ts", ".js", ".go", ".rs", ".java", ".c", ".cpp", ".h", ".hpp",
        ".html", ".css", ".sql", ".sh", ".toml", ".ini", ".env", ".xml"
    }

    async def extract(
        self,
        file_path: Path,
        filename: str,
        mime_type: str,
        ext: str,
        options: Optional[Dict[str, Any]] = None,
    ) -> NormalizedExtractionResult:
        """Inspect, validate, and safely extract text and structural file tree from a ZIP archive."""
        options = options or {}
        max_bytes = options.get("max_text_bytes", self.MAX_EXTRACTED_BYTES)
        warnings: List[str] = []
        security_flags: List[str] = []
        content_items: List[ExtractedContentItem] = []
        file_summaries: List[str] = []
        metadata: Dict[str, Any] = {}

        if not zipfile.is_zipfile(file_path):
            return self.build_result(
                filename=filename,
                mime_type=mime_type,
                ext=ext,
                status="failed",
                extracted_text="",
                content_items=[],
                error_message="Invalid ZIP archive structure or corrupted file header.",
                max_bytes=max_bytes,
            )

        temp_extract_dir: Optional[Path] = None

        try:
            with zipfile.ZipFile(file_path, "r") as zf:
                infolist = zf.infolist()
                total_members = len(infolist)
                metadata["total_members"] = total_members

                # 1. Member Count Ceiling
                if total_members > self.MAX_ARCHIVE_MEMBERS:
                    raise ValidationError(
                        f"ZIP archive member count ({total_members}) exceeds maximum limit of {self.MAX_ARCHIVE_MEMBERS} files."
                    )

                total_uncompressed = 0
                total_compressed = 0

                # 2. Inspect all members for Zip-Bomb & Traversal attacks
                valid_members = []
                for info in infolist:
                    total_uncompressed += info.file_size
                    total_compressed += info.compress_size
                    raw_name = info.filename

                    # Reject symlinks / junctions
                    is_symlink = (info.external_attr >> 16) & 0o170000 == 0o120000
                    if is_symlink:
                        security_flags.append(f"ARCHIVE_SYMLINK_REJECTED:{raw_name}")
                        raise ValidationError(
                            f"ZIP archive contains unsafe symlink member: '{raw_name}'. Archive extraction rejected."
                        )

                    # Check for Path Traversal, absolute, drive-letter, or UNC paths
                    if (
                        ".." in raw_name
                        or raw_name.startswith("/")
                        or raw_name.startswith("\\")
                        or re.match(r"^[a-zA-Z]:", raw_name)
                        or raw_name.startswith("//")
                        or raw_name.startswith("\\\\")
                        or "\x00" in raw_name
                    ):
                        security_flags.append(f"ARCHIVE_PATH_TRAVERSAL_REJECTED:{raw_name}")
                        raise ValidationError(
                            f"ZIP archive contains unsafe path traversal or absolute path member: '{raw_name}'. "
                            f"Silent mutation is disallowed; archive extraction rejected."
                        )

                    valid_members.append(info)

                # 3. Expanded Size Ceiling Check
                metadata["total_uncompressed_bytes"] = total_uncompressed
                metadata["total_compressed_bytes"] = total_compressed

                if total_uncompressed > self.MAX_ARCHIVE_EXPANDED_BYTES:
                    raise ValidationError(
                        f"ZIP archive expanded size ({total_uncompressed} bytes) exceeds maximum limit of 100 MB."
                    )

                # 4. Expansion Ratio (Zip Bomb) Check
                effective_comp = max(total_compressed, 1)
                ratio = total_uncompressed / effective_comp
                metadata["expansion_ratio"] = round(ratio, 2)

                if ratio > self.MAX_EXPANSION_RATIO:
                    security_flags.append("ZIP_BOMB_COMPRESSION_RATIO_EXCEEDED")
                    raise ValidationError(
                        f"Potential Zip Bomb detected: archive expansion ratio ({ratio:.1f}:1) exceeds limit of 10:1."
                    )

                # 5. Extract safely into ephemeral temp directory
                temp_extract_dir = file_path.parent / f"extracted_{uuid.uuid4().hex[:8]}"
                temp_extract_dir.mkdir(parents=True, exist_ok=True)

                for info in valid_members:
                    # Prevent directory creation outside temp_extract_dir
                    target_dest = (temp_extract_dir / info.filename).resolve()
                    if not str(target_dest).startswith(str(temp_extract_dir.resolve())):
                        security_flags.append(f"ARCHIVE_DESTINATION_OUTSIDE_ROOT_REJECTED:{info.filename}")
                        raise ValidationError(
                            f"Resolved destination '{target_dest}' escapes extraction root '{temp_extract_dir}'. "
                            f"Archive extraction rejected."
                        )

                    if info.is_dir():
                        target_dest.mkdir(parents=True, exist_ok=True)
                    else:
                        target_dest.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(info) as src, open(target_dest, "wb") as dst:
                            shutil.copyfileobj(src, dst)

                # 6. Traverse extracted codebase tree and build structured representations
                item_idx = 0
                extracted_file_paths = []
                total_text_bytes_accumulated = 0

                for root, _, files in os.walk(temp_extract_dir):
                    for fname in files:
                        full_fpath = Path(root) / fname
                        rel_path = full_fpath.relative_to(temp_extract_dir).as_posix()
                        fext = full_fpath.suffix.lower()
                        fsize = full_fpath.stat().st_size
                        extracted_file_paths.append(rel_path)

                        # Extract text content if extension is supported
                        if fext in self.EXTRACTABLE_TEXT_EXTENSIONS and total_text_bytes_accumulated < max_bytes:
                            try:
                                f_bytes = full_fpath.read_bytes()
                                try:
                                    f_text = f_bytes.decode("utf-8")
                                except UnicodeDecodeError:
                                    f_text = f_bytes.decode("utf-8", errors="replace")

                                total_text_bytes_accumulated += len(f_text.encode("utf-8"))
                                file_summaries.append(f"=== [File: {rel_path}] ===\n{f_text}")

                                content_items.append(
                                    ExtractedContentItem(
                                        index=item_idx,
                                        text=f"=== [File: {rel_path}] ===\n{f_text}",
                                        item_type="archive_file",
                                        source_location={"archive_path": rel_path, "size_bytes": fsize},
                                    )
                                )
                                item_idx += 1
                            except Exception as file_read_err:
                                logger.debug(f"ArchiveExtractor: Notice reading {rel_path}: {file_read_err}")

                metadata["extracted_files_count"] = len(extracted_file_paths)
                metadata["manifest"] = extracted_file_paths[:100]  # Cap manifest preview

            full_text = "\n\n".join(file_summaries).strip()
            status = "extracted" if full_text or extracted_file_paths else "no_text_extracted"

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

        except ValidationError:
            raise
        except Exception as e:
            logger.error(f"ArchiveExtractor: Failed to extract ZIP {filename}: {e}", exc_info=True)
            return self.build_result(
                filename=filename,
                mime_type=mime_type,
                ext=ext,
                status="failed",
                extracted_text="",
                content_items=[],
                error_message=f"ZIP archive extraction failure: {str(e)}",
                max_bytes=max_bytes,
            )
        finally:
            if temp_extract_dir and temp_extract_dir.exists():
                shutil.rmtree(temp_extract_dir, ignore_errors=True)
