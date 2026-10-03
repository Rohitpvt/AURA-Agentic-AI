"""Audit ledger inspection and cryptographic verification endpoints."""

from typing import Any, Dict
import uuid
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_current_user, get_db
from app.db.models.user import User
from app.services.audit_service import audit_service

router = APIRouter(prefix="/audit", tags=["Audit & Observability"])


@router.post("/verify", summary="Verify audit ledger cryptographic hash chain")
async def verify_audit_ledger(
    workspace_id: uuid.UUID = Query(..., description="Workspace ID to verify"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Cryptographically verify the SHA-256 hash chaining of audit logs for the workspace."""
    return await audit_service.verify_ledger(db=db, workspace_id=workspace_id)
