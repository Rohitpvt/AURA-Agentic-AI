"""OpenTelemetry Local Distributed Tracing Endpoints (AURA-505).

Provides workspace-isolated, RBAC-governed inspection of local in-memory traces.
"""

import uuid
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_workspace_membership, require_workspace_roles
from app.core.errors import EntityNotFoundError
from app.core.telemetry import telemetry_manager
from app.db.models.user import User
from app.db.session import get_db_session

router = APIRouter(prefix="/telemetry", tags=["Telemetry & Traces"])


@router.get("/status", summary="OpenTelemetry Tracer Status")
async def get_telemetry_status(
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Retrieve local OpenTelemetry status and finished span counts."""
    spans = telemetry_manager.get_in_memory_spans()
    return {
        "enabled": telemetry_manager.is_enabled,
        "exporter_type": "in_memory",
        "finished_spans_count": len(spans),
        "active_trace_id": telemetry_manager.get_current_trace_id(),
        "zero_cost_mode": True,
    }


@router.get("/spans", summary="Query Workspace Finished Spans")
async def list_spans(
    workspace_id: uuid.UUID = Query(..., description="Target workspace ID for tenancy isolation"),
    trace_id: Optional[str] = Query(None, description="Filter spans by 32-char hex trace ID"),
    task_id: Optional[uuid.UUID] = Query(None, description="Filter spans by AURA task UUID"),
    span_type: Optional[str] = Query(None, description="Filter spans by aura.span_type"),
    limit: int = Query(100, ge=1, le=500, description="Max spans to return"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    """List finished in-memory OpenTelemetry spans with strict workspace tenancy isolation."""
    await get_workspace_membership(workspace_id=workspace_id, user=current_user, db=db)

    spans = telemetry_manager.query_spans(
        workspace_id=str(workspace_id),
        trace_id=trace_id,
        task_id=str(task_id) if task_id else None,
        span_type=span_type,
        limit=limit,
    )

    return {
        "workspace_id": str(workspace_id),
        "count": len(spans),
        "spans": spans,
    }


@router.get("/traces/{trace_id}", summary="Get Full Workspace Trace by ID")
async def get_trace(
    trace_id: str,
    workspace_id: uuid.UUID = Query(..., description="Target workspace ID for tenancy isolation"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    """Retrieve all correlated spans belonging to a specific trace_id for authorized workspace."""
    await get_workspace_membership(workspace_id=workspace_id, user=current_user, db=db)

    trace_data = telemetry_manager.get_trace_by_id(trace_id=trace_id, workspace_id=str(workspace_id))
    if not trace_data:
        raise EntityNotFoundError("Trace", trace_id)

    return trace_data


@router.post("/clear", summary="Clear Workspace In-Memory Spans Buffer")
async def clear_spans(
    workspace_id: uuid.UUID = Query(..., description="Target workspace ID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    """Clear local in-memory trace buffer for authorized workspace (Owner/Admin only)."""
    membership = await get_workspace_membership(workspace_id=workspace_id, user=current_user, db=db)
    if membership.role not in ["owner", "admin"]:
        from app.core.errors import AuthorizationError
        raise AuthorizationError("Only workspace owners and admins can clear telemetry buffers")

    telemetry_manager.clear_in_memory_spans(workspace_id=str(workspace_id))
    return {
        "status": "cleared",
        "workspace_id": str(workspace_id),
    }
