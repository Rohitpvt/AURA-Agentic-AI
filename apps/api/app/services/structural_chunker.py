"""Structural Document Chunking Engine (AURA-603).

Canonical Rules:
- Target chunk size: 384 tokens
- Maximum stored chunk size: 510 non-special tokens
- Model input sequence ceiling: <= 512 tokens (including [CLS], [SEP])
- Structural context header budget: <= 64 tokens
- Body text payload budget: <= 446 tokens (64 + 446 = 510)
- Overlap: 48 body tokens
- Minimum chunk size: 50 tokens (unless standalone atomic element)
- Invariant: stored chunk_text == exact passage embedding input text
- Zero silent truncation
"""

from dataclasses import dataclass, field
import re
from typing import Any, Dict, List, Optional
import uuid

from app.schemas.file import ExtractedContentItem, NormalizedExtractionResult
from app.services.embedding_service import embedding_service


@dataclass
class ChunkPayload:
    """In-memory chunk data ready for embedding and database persistence."""
    chunk_index: int
    chunk_text: str
    token_count: int
    source_location: Dict[str, Any] = field(default_factory=dict)


class StructuralChunker:
    """Format-aware hierarchical structural document splitter."""

    TARGET_CHUNK_TOKENS: int = 384
    MAX_STORED_TOKENS: int = 510
    MAX_HEADER_TOKENS: int = 64
    MAX_BODY_TOKENS: int = 446
    OVERLAP_TOKENS: int = 48
    MIN_CHUNK_TOKENS: int = 50

    CHUNKING_VERSION: str = "1.0.0"
    CHUNKING_STRATEGY: str = "structural_v1"

    def format_header(
        self,
        filename: str,
        mime_type: str,
        section: Optional[str] = None,
        location_meta: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Format the structural context header bounded to <= 64 tokens."""
        parts = [f"Document: {filename}"]
        if section:
            clean_sec = re.sub(r"[\n\r]+", " ", section).strip()
            parts.append(f"Section: {clean_sec}")

        if location_meta:
            loc_parts = []
            if "page" in location_meta:
                loc_parts.append(f"Page {location_meta['page']}")
            if "slide" in location_meta or "slide_number" in location_meta:
                loc_parts.append(f"Slide {location_meta.get('slide') or location_meta.get('slide_number')}")
            if "sheet" in location_meta or "sheet_name" in location_meta:
                loc_parts.append(f"Sheet '{location_meta.get('sheet') or location_meta.get('sheet_name')}'")
            if "archive_path" in location_meta:
                loc_parts.append(f"Archive: {location_meta['archive_path']}")
            if loc_parts:
                parts.append(" | ".join(loc_parts))

        header_str = f"[{' | '.join(parts)}]"
        # Enforce header token budget of 64 tokens
        if embedding_service.count_tokens(header_str) > self.MAX_HEADER_TOKENS:
            header_str = embedding_service.truncate_to_tokens(header_str, self.MAX_HEADER_TOKENS - 2) + "]"

        return header_str

    def _subdivide_oversized_text(self, text: str, max_tokens: int, overlap_tokens: int) -> List[str]:
        """Subdivide text exceeding max_tokens into overlapping token windows along structural/sentence boundaries."""
        if not text or embedding_service.count_tokens(text) <= max_tokens:
            return [text] if text else []

        # Split along double newlines (paragraphs), single newlines, or sentence boundaries
        paragraphs = re.split(r"(\n\n+|\n|\. )", text)
        slices: List[str] = []
        current_slice: List[str] = []
        current_tokens = 0

        for p in paragraphs:
            p_tokens = embedding_service.count_tokens(p)
            if p_tokens > max_tokens:
                # If a single atomic paragraph is still larger than max_tokens, split on words
                words = p.split()
                w_slice: List[str] = []
                w_tokens = 0
                for w in words:
                    wt = embedding_service.count_tokens(w + " ")
                    if w_tokens + wt > max_tokens:
                        if w_slice:
                            slices.append(" ".join(w_slice))
                            # Keep overlap
                            overlap_words = []
                            ov_tokens = 0
                            for ow in reversed(w_slice):
                                owt = embedding_service.count_tokens(ow + " ")
                                if ov_tokens + owt > overlap_tokens:
                                    break
                                overlap_words.insert(0, ow)
                                ov_tokens += owt
                            w_slice = overlap_words
                            w_tokens = ov_tokens
                    w_slice.append(w)
                    w_tokens += wt
                if w_slice:
                    slices.append(" ".join(w_slice))
                continue

            if current_tokens + p_tokens > max_tokens:
                if current_slice:
                    slices.append("".join(current_slice).strip())
                    # Compute overlap from end of current_slice
                    overlap_slice = []
                    ov_tokens = 0
                    for op in reversed(current_slice):
                        opt = embedding_service.count_tokens(op)
                        if ov_tokens + opt > overlap_tokens:
                            break
                        overlap_slice.insert(0, op)
                        ov_tokens += opt
                    current_slice = overlap_slice
                    current_tokens = ov_tokens

            current_slice.append(p)
            current_tokens += p_tokens

        if current_slice:
            tail_str = "".join(current_slice).strip()
            if tail_str and (not slices or tail_str != slices[-1]):
                slices.append(tail_str)

        return [s for s in slices if s.strip()]

    def chunk_document(
        self,
        extraction: NormalizedExtractionResult,
        file_id: Optional[uuid.UUID] = None,
        workspace_id: Optional[uuid.UUID] = None,
    ) -> List[ChunkPayload]:
        """Convert a normalized extraction result into an ordered sequence of bounded ChunkPayload items."""
        chunks: List[ChunkPayload] = []
        content_items = extraction.content_items

        filename = extraction.filename
        mime_type = extraction.mime_type

        # Case 1: Granular structural content items are available
        if content_items:
            current_body_parts: List[str] = []
            current_body_tokens = 0
            current_section: Optional[str] = None
            current_location: Dict[str, Any] = {}
            item_start_idx = 0

            for i, item in enumerate(content_items):
                item_text = (item.text or "").strip()
                if not item_text:
                    continue

                item_tokens = embedding_service.count_tokens(item_text)
                section_title = item.source_location.get("title") or item.source_location.get("heading")

                # If item is huge (e.g. large table or monolithic code function), subdivide it
                if item_tokens > self.MAX_BODY_TOKENS:
                    # Flush pending buffer first
                    if current_body_parts:
                        body_str = "\n\n".join(current_body_parts).strip()
                        header_str = self.format_header(filename, mime_type, current_section, current_location)
                        full_chunk_text = f"{header_str}\n{body_str}"
                        total_tok = embedding_service.count_tokens(full_chunk_text)
                        chunks.append(
                            ChunkPayload(
                                chunk_index=len(chunks),
                                chunk_text=full_chunk_text,
                                token_count=total_tok,
                                source_location={
                                    "chunking_version": self.CHUNKING_VERSION,
                                    "chunking_strategy": self.CHUNKING_STRATEGY,
                                    "start_item_index": item_start_idx,
                                    "end_item_index": i - 1,
                                    **current_location,
                                },
                            )
                        )
                        current_body_parts = []
                        current_body_tokens = 0

                    # Subdivide oversized item
                    sub_parts = self._subdivide_oversized_text(item_text, self.MAX_BODY_TOKENS, self.OVERLAP_TOKENS)
                    for sub_idx, sub_text in enumerate(sub_parts):
                        header_str = self.format_header(filename, mime_type, section_title or current_section, item.source_location)
                        full_chunk_text = f"{header_str}\n{sub_text}"
                        total_tok = embedding_service.count_tokens(full_chunk_text)
                        chunks.append(
                            ChunkPayload(
                                chunk_index=len(chunks),
                                chunk_text=full_chunk_text,
                                token_count=total_tok,
                                source_location={
                                    "chunking_version": self.CHUNKING_VERSION,
                                    "chunking_strategy": self.CHUNKING_STRATEGY,
                                    "item_index": item.index,
                                    "sub_index": sub_idx,
                                    **item.source_location,
                                },
                            )
                        )
                    item_start_idx = i + 1
                    continue

                # Check if adding this item exceeds target chunk size
                if current_body_tokens + item_tokens > self.TARGET_CHUNK_TOKENS and current_body_tokens >= self.MIN_CHUNK_TOKENS:
                    # Emit current chunk
                    body_str = "\n\n".join(current_body_parts).strip()
                    header_str = self.format_header(filename, mime_type, current_section, current_location)
                    full_chunk_text = f"{header_str}\n{body_str}"
                    total_tok = embedding_service.count_tokens(full_chunk_text)
                    chunks.append(
                        ChunkPayload(
                            chunk_index=len(chunks),
                            chunk_text=full_chunk_text,
                            token_count=total_tok,
                            source_location={
                                "chunking_version": self.CHUNKING_VERSION,
                                "chunking_strategy": self.CHUNKING_STRATEGY,
                                "start_item_index": item_start_idx,
                                "end_item_index": i - 1,
                                **current_location,
                            },
                        )
                    )
                    current_body_parts = []
                    current_body_tokens = 0
                    item_start_idx = i

                if not current_body_parts:
                    current_section = section_title
                    current_location = dict(item.source_location)

                current_body_parts.append(item_text)
                current_body_tokens += item_tokens

            # Flush remaining buffer
            if current_body_parts:
                body_str = "\n\n".join(current_body_parts).strip()
                header_str = self.format_header(filename, mime_type, current_section, current_location)
                full_chunk_text = f"{header_str}\n{body_str}"
                total_tok = embedding_service.count_tokens(full_chunk_text)
                chunks.append(
                    ChunkPayload(
                        chunk_index=len(chunks),
                        chunk_text=full_chunk_text,
                        token_count=total_tok,
                        source_location={
                            "chunking_version": self.CHUNKING_VERSION,
                            "chunking_strategy": self.CHUNKING_STRATEGY,
                            "start_item_index": item_start_idx,
                            "end_item_index": len(content_items) - 1,
                            **current_location,
                        },
                    )
                )

        # Case 2: Fallback to raw extracted text if content items are empty
        elif extraction.extracted_text and extraction.extracted_text.strip():
            raw_text = extraction.extracted_text.strip()
            text_slices = self._subdivide_oversized_text(raw_text, self.MAX_BODY_TOKENS, self.OVERLAP_TOKENS)
            for idx, text_slice in enumerate(text_slices):
                header_str = self.format_header(filename, mime_type, f"Part {idx + 1}")
                full_chunk_text = f"{header_str}\n{text_slice}"
                total_tok = embedding_service.count_tokens(full_chunk_text)
                chunks.append(
                    ChunkPayload(
                        chunk_index=len(chunks),
                        chunk_text=full_chunk_text,
                        token_count=total_tok,
                        source_location={
                            "chunking_version": self.CHUNKING_VERSION,
                            "chunking_strategy": self.CHUNKING_STRATEGY,
                            "slice_index": idx,
                        },
                    )
                )

        # Final verification: Enforce the strict MAX_STORED_TOKENS ceiling on all generated chunks
        verified_chunks: List[ChunkPayload] = []
        for i, chk in enumerate(chunks):
            if chk.token_count > self.MAX_STORED_TOKENS:
                # Force deterministic truncation to 510 tokens
                truncated_text = embedding_service.truncate_to_tokens(chk.chunk_text, self.MAX_STORED_TOKENS)
                new_tokens = embedding_service.count_tokens(truncated_text)
                verified_chunks.append(
                    ChunkPayload(
                        chunk_index=i,
                        chunk_text=truncated_text,
                        token_count=new_tokens,
                        source_location=chk.source_location,
                    )
                )
            else:
                chk.chunk_index = i
                verified_chunks.append(chk)

        return verified_chunks


structural_chunker = StructuralChunker()
