"""Memory Pipeline Service for ingestion, semantic recall, and governance."""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import numpy as np
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.errors import EntityNotFoundError
from app.core.logging import logger
from app.db.models.memory import MemoryRecord
from app.schemas.memory import MemoryRecallResult, MemoryRecordResponse
from app.services.embedding_service import embedding_service


def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """Compute cosine similarity between two float vectors."""
    a = np.array(v1, dtype=float)
    b = np.array(v2, dtype=float)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


class MemoryService:
    """Service managing memory write pipeline, recall, and governance."""

    async def ingest_memory(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        fact_statement: str,
        category: str = "project_context",
        confidence_score: float = 1.0,
        source_type: str = "user_directive",
        user_id: Optional[uuid.UUID] = None,
        metadata: Optional[Dict[str, Any]] = None,
        provenance: Optional[Dict[str, Any]] = None,
    ) -> MemoryRecord:
        """Write pipeline: Normalize, compute local embedding, persist memory record."""
        cleaned_statement = fact_statement.strip()
        embedding = embedding_service.embed_text(cleaned_statement)

        record = MemoryRecord(
            workspace_id=workspace_id,
            user_id=user_id,
            source_type=source_type,
            category=category,
            fact_statement=cleaned_statement,
            confidence_score=confidence_score,
            embedding=embedding,
            provenance=provenance or {},
            is_tombstoned=False,
        )
        db.add(record)
        await db.commit()
        await db.refresh(record)
        logger.info(f"Ingested memory record {record.id} in workspace {workspace_id} (category: {category})")
        return record

    async def promote_chunk_to_memory(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        file_id: uuid.UUID,
        chunk_id: uuid.UUID,
        chunk_index: int,
        fact_statement: str,
        category: str = "file_insight",
        confidence_score: float = 1.0,
        source_location: Optional[Dict[str, Any]] = None,
        file_hash: Optional[str] = None,
        retrieval_score: Optional[float] = None,
        parser_version: str = "1.0.0",
        chunking_version: str = "1.0.0",
        embedding_model: str = "BAAI/bge-base-en-v1.5",
        user_id: Optional[uuid.UUID] = None,
    ) -> MemoryRecord:
        """Promote an extracted document fact/insight into cognitive memory with structured source provenance."""
        provenance_data = {
            "workspace_id": str(workspace_id),
            "file_id": str(file_id),
            "chunk_id": str(chunk_id),
            "chunk_index": chunk_index,
            "source_location": source_location or {},
            "file_sha256": file_hash or "",
            "parser_version": parser_version,
            "chunking_version": chunking_version,
            "embedding_model": embedding_model,
            "retrieval_score": retrieval_score,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        return await self.ingest_memory(
            db=db,
            workspace_id=workspace_id,
            fact_statement=fact_statement,
            category=category,
            confidence_score=confidence_score,
            source_type="file_intelligence",
            user_id=user_id,
            provenance=provenance_data,
        )

    async def recall_memories(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        query: str,
        top_k: int = 5,
        category: Optional[str] = None,
        include_tombstoned: bool = False,
        min_similarity: float = 0.25,
    ) -> List[MemoryRecallResult]:
        """Recall pipeline: Embed query, compute semantic similarity, apply lexical match & filters."""
        query_embedding = embedding_service.embed_text(query.strip())

        stmt = select(MemoryRecord).where(
            MemoryRecord.workspace_id == workspace_id,
            MemoryRecord.deleted_at.is_(None),
        )
        if not include_tombstoned:
            stmt = stmt.where(MemoryRecord.is_tombstoned.is_(False))
        if category:
            stmt = stmt.where(MemoryRecord.category == category)

        res = await db.execute(stmt)
        records = res.scalars().all()

        results: List[MemoryRecallResult] = []
        for rec in records:
            if rec.embedding is None:
                continue

            similarity = cosine_similarity(query_embedding, rec.embedding)

            # Check lexical overlap (BM25 surrogate)
            query_tokens = set(query.lower().split())
            fact_tokens = set(rec.fact_statement.lower().split())
            lexical_match = bool(query_tokens.intersection(fact_tokens))

            # Bonus for lexical match and confidence
            weighted_score = (similarity * 0.8) + (0.2 if lexical_match else 0.0) * float(rec.confidence_score)

            if similarity >= min_similarity or lexical_match:
                record_response = MemoryRecordResponse(
                    id=rec.id,
                    workspace_id=rec.workspace_id,
                    user_id=rec.user_id,
                    category=rec.category,
                    fact_statement=rec.fact_statement,
                    confidence_score=float(rec.confidence_score),
                    source_type=rec.source_type,
                    is_tombstoned=rec.is_tombstoned,
                    tombstoned_reason=rec.tombstoned_reason,
                    created_at=rec.created_at,
                    updated_at=rec.updated_at,
                )
                results.append(
                    MemoryRecallResult(
                        record=record_response,
                        similarity_score=round(weighted_score, 4),
                        lexical_match=lexical_match,
                    )
                )

        # Sort by similarity score descending and take top_k
        results.sort(key=lambda r: r.similarity_score, reverse=True)
        return results[:top_k]

    async def tombstone_memory(
        self, db: AsyncSession, memory_id: uuid.UUID, workspace_id: uuid.UUID, reason: str = "User directive"
    ) -> MemoryRecord:
        """Tombstone (soft-delete with reason) a memory record so it is excluded from future retrieval."""
        res = await db.execute(
            select(MemoryRecord).where(
                MemoryRecord.id == memory_id,
                MemoryRecord.workspace_id == workspace_id,
                MemoryRecord.deleted_at.is_(None),
            )
        )
        record = res.scalar_one_or_none()
        if not record:
            raise EntityNotFoundError("MemoryRecord", str(memory_id))

        record.is_tombstoned = True
        record.tombstoned_reason = reason
        await db.commit()
        await db.refresh(record)
        logger.info(f"Tombstoned memory record {memory_id}: {reason}")
        return record

    async def update_memory(
        self,
        db: AsyncSession,
        memory_id: uuid.UUID,
        workspace_id: uuid.UUID,
        fact_statement: Optional[str] = None,
        category: Optional[str] = None,
        confidence_score: Optional[float] = None,
    ) -> MemoryRecord:
        """Update an existing memory record, re-computing vector embeddings if text changed."""
        res = await db.execute(
            select(MemoryRecord).where(
                MemoryRecord.id == memory_id,
                MemoryRecord.workspace_id == workspace_id,
                MemoryRecord.deleted_at.is_(None),
            )
        )
        record = res.scalar_one_or_none()
        if not record:
            raise EntityNotFoundError("MemoryRecord", str(memory_id))

        if fact_statement:
            record.fact_statement = fact_statement.strip()
            record.embedding = embedding_service.embed_text(record.fact_statement)
        if category:
            record.category = category
        if confidence_score is not None:
            record.confidence_score = confidence_score

        await db.commit()
        await db.refresh(record)
        return record


memory_service = MemoryService()
