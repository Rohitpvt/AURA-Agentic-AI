"""Hybrid Semantic + Lexical File Retrieval Service (AURA-603).

Canonical Retrieval Architecture:
1. Dense Candidate Pool (Top-50):
   - Query instruction prefixed: "Represent this sentence for searching relevant passages: "
   - Bounded to 768-dim L2-normalized vector.
   - HNSW Cosine Distance (vector_cosine_ops).
2. Lexical Candidate Pool (Top-50):
   - Canonical parser: websearch_to_tsquery('english', :raw_query)
   - Normalized ranking: ts_rank_cd / (1.0 + ts_rank_cd)
3. Symmetric Candidate Union (Up to 100 Candidates):
   - C_total = C_dense U C_lexical
   - On-demand true cosine similarity evaluation for lexical-only candidates.
4. Linear Hybrid Fusion:
   - S_hybrid = 0.70 * S_dense + 0.30 * S_lexical
5. Dual Quality Survival Gate:
   - S_hybrid >= min_similarity (default 0.30) OR S_lexical >= 0.50 (strong keyword match)
6. Deterministic Ordering:
   - ORDER BY S_hybrid DESC, chunk_id ASC
   - Bounded to top_k.
7. Strict Multi-Tenant Isolation & Quarantine Defense.
"""

from typing import Any, Dict, List, Optional
import re
import uuid
import numpy as np

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import logger
from app.db.models.file import FileChunk, FileRecord, FileStatus
from app.schemas.file import FileSearchRequest, FileSearchResponse, FileSearchResultItem
from app.services.embedding_service import embedding_service


class FileSearchService:
    """Enterprise hybrid search engine combining vector embeddings with full-text search."""

    DENSE_WEIGHT: float = 0.70
    LEXICAL_WEIGHT: float = 0.30
    CANDIDATE_POOL_LIMIT: int = 50
    STRONG_LEXICAL_GATE: float = 0.50

    async def search(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        request: FileSearchRequest,
    ) -> FileSearchResponse:
        """Execute symmetric hybrid retrieval over workspace-isolated document chunks."""

        # 1. Compute normalized query embedding with BGE query instruction
        raw_query = request.query.strip()
        query_vector = embedding_service.embed_query(raw_query)
        q_vec_arr = np.array(query_vector, dtype=float)

        # 2. Query candidates from database
        bind = db.bind
        is_postgresql = bind and bind.dialect.name == "postgresql"

        candidate_map: Dict[uuid.UUID, Dict[str, Any]] = {}

        if is_postgresql:
            # PostgreSQL Native Hybrid Execution with Materialized CTEs
            try:
                sql_query = text(
                    """
                    WITH dense_pool AS MATERIALIZED (
                        SELECT c.id, c.file_id, c.workspace_id, c.chunk_index, c.chunk_text, c.token_count, c.source_location,
                               c.embedding,
                               (1.0 - (c.embedding <=> CAST(:query_vec AS vector))) AS raw_dense_cos,
                               r.original_filename, r.mime_type
                        FROM file_chunks c
                        JOIN file_records r ON r.id = c.file_id AND r.workspace_id = c.workspace_id
                        WHERE c.workspace_id = :ws_id
                          AND r.deleted_at IS NULL
                          AND r.status NOT IN ('quarantined', 'delete_requested', 'deleted')
                          AND c.embedding IS NOT NULL
                        ORDER BY c.embedding <=> CAST(:query_vec AS vector)
                        LIMIT 50
                    ),
                    lexical_pool AS MATERIALIZED (
                        SELECT c.id, c.file_id, c.workspace_id, c.chunk_index, c.chunk_text, c.token_count, c.source_location,
                               c.embedding,
                               ts_rank_cd(to_tsvector('english', c.chunk_text), websearch_to_tsquery('english', :raw_query)) AS raw_lexical_rank,
                               r.original_filename, r.mime_type
                        FROM file_chunks c
                        JOIN file_records r ON r.id = c.file_id AND r.workspace_id = c.workspace_id
                        WHERE c.workspace_id = :ws_id
                          AND r.deleted_at IS NULL
                          AND r.status NOT IN ('quarantined', 'delete_requested', 'deleted')
                          AND to_tsvector('english', c.chunk_text) @@ websearch_to_tsquery('english', :raw_query)
                        ORDER BY raw_lexical_rank DESC
                        LIMIT 50
                    )
                    SELECT
                        COALESCE(d.id, l.id) AS chunk_id,
                        COALESCE(d.file_id, l.file_id) AS file_id,
                        COALESCE(d.workspace_id, l.workspace_id) AS workspace_id,
                        COALESCE(d.chunk_index, l.chunk_index) AS chunk_index,
                        COALESCE(d.chunk_text, l.chunk_text) AS chunk_text,
                        COALESCE(d.token_count, l.token_count) AS token_count,
                        COALESCE(d.source_location, l.source_location) AS source_location,
                        COALESCE(d.embedding, l.embedding) AS embedding,
                        d.raw_dense_cos,
                        l.raw_lexical_rank,
                        COALESCE(d.original_filename, l.original_filename) AS original_filename,
                        COALESCE(d.mime_type, l.mime_type) AS mime_type
                    FROM dense_pool d
                    FULL OUTER JOIN lexical_pool l ON d.id = l.id;
                    """
                )
                res = await db.execute(
                    sql_query,
                    {
                        "ws_id": workspace_id,
                        "query_vec": str(query_vector),
                        "raw_query": raw_query,
                    },
                )
                rows = res.fetchall()
                for row in rows:
                    cid = row.chunk_id
                    candidate_map[cid] = {
                        "chunk_id": cid,
                        "file_id": row.file_id,
                        "workspace_id": row.workspace_id,
                        "chunk_index": row.chunk_index,
                        "chunk_text": row.chunk_text,
                        "token_count": row.token_count,
                        "source_location": row.source_location,
                        "embedding": row.embedding,
                        "raw_dense_cos": row.raw_dense_cos,
                        "raw_lexical_rank": row.raw_lexical_rank or 0.0,
                        "original_filename": row.original_filename,
                        "mime_type": row.mime_type,
                    }
            except Exception as pg_err:
                logger.warning(f"FileSearchService: Native PostgreSQL query fallback: {pg_err}")
                is_postgresql = False

        if not is_postgresql:
            # Universal Portable SQLite / Python Hybrid Execution
            stmt = (
                select(
                    FileChunk.id,
                    FileChunk.file_id,
                    FileChunk.workspace_id,
                    FileChunk.chunk_index,
                    FileChunk.chunk_text,
                    FileChunk.token_count,
                    FileChunk.source_location,
                    FileChunk.embedding,
                    FileRecord.original_filename,
                    FileRecord.mime_type,
                )
                .join(FileRecord, FileRecord.id == FileChunk.file_id)
                .where(
                    FileChunk.workspace_id == workspace_id,
                    FileRecord.deleted_at.is_(None),
                    FileRecord.status.notin_([FileStatus.QUARANTINED.value, FileStatus.DELETE_REQUESTED.value, FileStatus.DELETED.value]),
                )
            )
            if request.file_ids:
                stmt = stmt.where(FileChunk.file_id.in_(request.file_ids))
            if request.mime_types:
                stmt = stmt.where(FileRecord.mime_type.in_(request.mime_types))

            res = await db.execute(stmt)
            all_chunks = res.all()

            if all_chunks:
                # Fast vectorized dense scoring
                embeddings_list = [row[7] if isinstance(row[7], list) else [0.0] * 768 for row in all_chunks]
                emb_matrix = np.array(embeddings_list, dtype=float)
                cos_sims = np.dot(emb_matrix, q_vec_arr)

                dense_scored = []
                lexical_scored = []

                stopwords = {
                    "the", "a", "an", "is", "are", "was", "were", "in", "on", "at", "to", "for", "of",
                    "and", "or", "by", "with", "about", "tell", "me", "this", "that", "it", "from",
                }
                raw_q_tokens = [w for w in re.findall(r"\w+", raw_query.lower()) if w not in stopwords]
                if not raw_q_tokens:
                    raw_q_tokens = re.findall(r"\w+", raw_query.lower())
                query_words = set(raw_q_tokens)

                for idx, row in enumerate(all_chunks):
                    cid, fid, wid, cidx, ctext, ctok, cloc, _, orig_name, mime = row
                    cos_sim = float(cos_sims[idx])
                    dense_scored.append((cos_sim, row))

                    # Lexical scoring with term importance
                    chunk_text_lower = ctext.lower()
                    matches = 0.0
                    for qw in query_words:
                        if qw in chunk_text_lower:
                            matches += 1.0 + min(3.0, len(qw) / 3.0)

                    if matches > 0:
                        rank_score = (matches / max(1.0, float(len(query_words)))) * 1.5
                        lexical_scored.append((rank_score, row))


                # Top-50 Dense
                dense_scored.sort(key=lambda x: x[0], reverse=True)
                top_dense = dense_scored[: self.CANDIDATE_POOL_LIMIT]

                # Top-50 Lexical
                lexical_scored.sort(key=lambda x: x[0], reverse=True)
                top_lexical = lexical_scored[: self.CANDIDATE_POOL_LIMIT]

                for cos_sim, row in top_dense:
                    cid, fid, wid, cidx, ctext, ctok, cloc, emb, orig_name, mime = row
                    candidate_map[cid] = {
                        "chunk_id": cid,
                        "file_id": fid,
                        "workspace_id": wid,
                        "chunk_index": cidx,
                        "chunk_text": ctext,
                        "token_count": ctok,
                        "source_location": cloc,
                        "embedding": emb,
                        "raw_dense_cos": cos_sim,
                        "raw_lexical_rank": 0.0,
                        "original_filename": orig_name,
                        "mime_type": mime,
                    }

                for rank_score, row in top_lexical:
                    cid, fid, wid, cidx, ctext, ctok, cloc, emb, orig_name, mime = row
                    if cid in candidate_map:
                        candidate_map[cid]["raw_lexical_rank"] = rank_score
                    else:
                        candidate_map[cid] = {
                            "chunk_id": cid,
                            "file_id": fid,
                            "workspace_id": wid,
                            "chunk_index": cidx,
                            "chunk_text": ctext,
                            "token_count": ctok,
                            "source_location": cloc,
                            "embedding": emb,
                            "raw_dense_cos": None,
                            "raw_lexical_rank": rank_score,
                            "original_filename": orig_name,
                            "mime_type": mime,
                        }

        # 3. Valuation, Score Normalization, Linear Fusion & Dual Quality Gating
        evaluated_results: List[FileSearchResultItem] = []

        for cid, data in candidate_map.items():
            # Calculate true dense cosine similarity if not present
            raw_dense = data.get("raw_dense_cos")
            if raw_dense is None:
                emb = data.get("embedding")
                if emb and isinstance(emb, list):
                    v_arr = np.array(emb, dtype=float)
                    raw_dense = float(np.dot(q_vec_arr, v_arr))
                else:
                    raw_dense = 0.0

            # Normalize dense: cosine similarity in [-1, 1] -> [0.0, 1.0]
            s_dense = max(0.0, min(1.0, (1.0 + raw_dense) / 2.0))

            # Normalize lexical: ts_rank in [0, inf) -> [0.0, 1.0)
            raw_lex = float(data.get("raw_lexical_rank") or 0.0)
            s_lexical = raw_lex / (1.0 + raw_lex) if raw_lex > 0 else 0.0

            # Linear hybrid score
            s_hybrid = (self.DENSE_WEIGHT * s_dense) + (self.LEXICAL_WEIGHT * s_lexical)

            # Dual Quality Gate: Survives if hybrid score >= min_similarity OR strong lexical match
            if s_hybrid >= request.min_similarity or s_lexical >= self.STRONG_LEXICAL_GATE:
                evaluated_results.append(
                    FileSearchResultItem(
                        chunk_id=cid,
                        file_id=data["file_id"],
                        workspace_id=data["workspace_id"],
                        chunk_index=data["chunk_index"],
                        chunk_text=data["chunk_text"],
                        token_count=data["token_count"],
                        source_location=data["source_location"] or {},
                        dense_score=round(s_dense, 4),
                        lexical_score=round(s_lexical, 4),
                        hybrid_score=round(s_hybrid, 4),
                        original_filename=data["original_filename"],
                        mime_type=data["mime_type"],
                    )
                )

        # 4. Final Deterministic Sort: hybrid_score DESC, chunk_id ASC
        evaluated_results.sort(key=lambda x: (-x.hybrid_score, str(x.chunk_id)))
        final_results = evaluated_results[: request.top_k]

        return FileSearchResponse(
            query=raw_query,
            total_candidates=len(candidate_map),
            returned_count=len(final_results),
            results=final_results,
        )


file_search_service = FileSearchService()
