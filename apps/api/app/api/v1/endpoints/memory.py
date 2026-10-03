"""Memory management and semantic recall API endpoints."""

import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_current_user, get_workspace_membership
from app.core.errors import EntityNotFoundError
from app.db.models.memory import MemoryRecord
from app.db.models.user import User
from app.db.session import get_db_session
from app.schemas.memory import (
    MemoryCreateRequest,
    MemoryRecallRequest,
    MemoryRecallResult,
    MemoryRecordResponse,
    MemoryTombstoneRequest,
    MemoryUpdateRequest,
)
from app.services.memory_service import memory_service

router = APIRouter()


@router.get("/records", response_model=List[MemoryRecordResponse])
async def list_memory_records(
    workspace_id: uuid.UUID = Query(...),
    category: Optional[str] = None,
    include_tombstoned: bool = False,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[MemoryRecordResponse]:
    """List memory records in a workspace with optional category filter."""
    await get_workspace_membership(workspace_id, current_user, db)

    stmt = select(MemoryRecord).where(
        MemoryRecord.workspace_id == workspace_id,
        MemoryRecord.deleted_at.is_(None),
    )
    if not include_tombstoned:
        stmt = stmt.where(MemoryRecord.is_tombstoned.is_(False))
    if category:
        stmt = stmt.where(MemoryRecord.category == category)

    res = await db.execute(stmt.order_by(MemoryRecord.created_at.desc()))
    records = res.scalars().all()

    return [
        MemoryRecordResponse(
            id=r.id,
            workspace_id=r.workspace_id,
            user_id=r.user_id,
            category=r.category,
            fact_statement=r.fact_statement,
            confidence_score=float(r.confidence_score),
            source_type=r.source_type,
            is_tombstoned=r.is_tombstoned,
            tombstoned_reason=r.tombstoned_reason,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in records
    ]


@router.post("/records", response_model=MemoryRecordResponse, status_code=status.HTTP_201_CREATED)
async def create_memory_record(
    payload: MemoryCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> MemoryRecordResponse:
    """Ingest a new factual memory statement into vector & relational storage."""
    await get_workspace_membership(payload.workspace_id, current_user, db)

    record = await memory_service.ingest_memory(
        db=db,
        workspace_id=payload.workspace_id,
        fact_statement=payload.fact_statement,
        category=payload.category,
        confidence_score=payload.confidence_score,
        source_type=payload.source_type,
        user_id=current_user.id,
        metadata=payload.metadata,
    )

    return MemoryRecordResponse(
        id=record.id,
        workspace_id=record.workspace_id,
        user_id=record.user_id,
        category=record.category,
        fact_statement=record.fact_statement,
        confidence_score=float(record.confidence_score),
        source_type=record.source_type,
        is_tombstoned=record.is_tombstoned,
        tombstoned_reason=record.tombstoned_reason,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


@router.get("/records/{id}", response_model=MemoryRecordResponse)
async def get_memory_record(
    id: uuid.UUID,
    workspace_id: uuid.UUID = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> MemoryRecordResponse:
    """Retrieve single memory record."""
    await get_workspace_membership(workspace_id, current_user, db)

    res = await db.execute(
        select(MemoryRecord).where(
            MemoryRecord.id == id,
            MemoryRecord.workspace_id == workspace_id,
            MemoryRecord.deleted_at.is_(None),
        )
    )
    rec = res.scalar_one_or_none()
    if not rec:
        raise EntityNotFoundError("MemoryRecord", str(id))

    return MemoryRecordResponse(
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


@router.delete("/records/{id}", response_model=MemoryRecordResponse)
async def tombstone_memory_record(
    id: uuid.UUID,
    workspace_id: uuid.UUID = Query(...),
    reason: str = Query(default="User directive"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> MemoryRecordResponse:
    """Tombstone / soft-delete a memory record."""
    await get_workspace_membership(workspace_id, current_user, db)

    record = await memory_service.tombstone_memory(
        db=db,
        memory_id=id,
        workspace_id=workspace_id,
        reason=reason,
    )

    return MemoryRecordResponse(
        id=record.id,
        workspace_id=record.workspace_id,
        user_id=record.user_id,
        category=record.category,
        fact_statement=record.fact_statement,
        confidence_score=float(record.confidence_score),
        source_type=record.source_type,
        is_tombstoned=record.is_tombstoned,
        tombstoned_reason=record.tombstoned_reason,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


@router.post("/recall", response_model=List[MemoryRecallResult])
async def recall_memories(
    payload: MemoryRecallRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[MemoryRecallResult]:
    """Execute semantic vector & hybrid lexical recall over workspace memories."""
    await get_workspace_membership(payload.workspace_id, current_user, db)

    results = await memory_service.recall_memories(
        db=db,
        workspace_id=payload.workspace_id,
        query=payload.query,
        top_k=payload.top_k,
        category=payload.category,
        include_tombstoned=payload.include_tombstoned,
        min_similarity=payload.min_similarity,
    )

    return results
