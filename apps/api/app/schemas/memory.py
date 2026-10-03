"""Pydantic schemas for memory records and semantic recall."""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class MemoryCreateRequest(BaseModel):
    """Payload to create or ingest a memory record."""
    workspace_id: uuid.UUID
    category: str = Field(
        default="project_context",
        description="Category: preference, project_context, personal_fact, skill_learning, episodic, semantic, procedural",
    )
    fact_statement: str = Field(min_length=3, description="Clean factual or contextual statement")
    confidence_score: float = Field(default=1.0, ge=0.0, le=1.0)
    source_type: str = Field(default="user_directive", description="Source: user_directive, extracted_fact, agent_run")
    metadata: Dict[str, Any] = Field(default_factory=dict)


class MemoryUpdateRequest(BaseModel):
    """Payload to update an existing memory record."""
    fact_statement: Optional[str] = None
    category: Optional[str] = None
    confidence_score: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None


class MemoryTombstoneRequest(BaseModel):
    """Payload to tombstone/soft-delete a memory."""
    reason: str = Field(default="User directive", description="Reason for tombstoning")


class MemoryRecordResponse(BaseModel):
    """Memory record response."""
    id: uuid.UUID
    workspace_id: uuid.UUID
    user_id: Optional[uuid.UUID] = None
    category: str
    fact_statement: str
    confidence_score: float
    source_type: str
    is_tombstoned: bool
    tombstoned_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class MemoryRecallRequest(BaseModel):
    """Semantic recall query payload."""
    workspace_id: uuid.UUID
    query: str = Field(min_length=1, description="Semantic search query")
    category: Optional[str] = None
    top_k: int = Field(default=5, ge=1, le=50)
    include_tombstoned: bool = False
    min_similarity: float = Field(default=0.3, ge=0.0, le=1.0)


class MemoryRecallResult(BaseModel):
    """Individual recalled memory with score."""
    record: MemoryRecordResponse
    similarity_score: float
    lexical_match: bool = False
