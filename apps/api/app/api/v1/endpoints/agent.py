import asyncio
import json
import uuid
from typing import Any, AsyncGenerator, Dict
from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_current_user, get_workspace_membership
from app.db.models.user import User
from app.db.session import get_db_session
from app.runtime.engine import agent_engine
from app.runtime.events import event_hub
from app.schemas.agent import AgentGoalRequest, AgentRunResponse

router = APIRouter()


@router.post("/run", response_model=AgentRunResponse, status_code=status.HTTP_200_OK)
async def run_agent_goal(
    payload: AgentGoalRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> AgentRunResponse:
    """Submit a goal for autonomous DAG planning, tool execution, and verification."""
    await get_workspace_membership(workspace_id=payload.workspace_id, user_id=current_user.id, db=db)
    return await agent_engine.submit_goal(
        db=db,
        request=payload,
        actor_id=str(current_user.id),
        event_callback=event_hub.publish,
    )


@router.get("/events/stream", summary="Stream real-time agent runtime events via SSE")
async def stream_agent_events(
    workspace_id: uuid.UUID = Query(..., description="Workspace ID to subscribe to"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    """Server-Sent Events (SSE) stream for live DAG updates, tools, approvals, and subagents."""
    await get_workspace_membership(workspace_id=workspace_id, user_id=current_user.id, db=db)

    async def event_generator() -> AsyncGenerator[str, None]:
        q = event_hub.subscribe()
        try:
            # Yield initial connection ping
            yield f"event: ping\ndata: {json.dumps({'status': 'connected', 'workspace_id': str(workspace_id)})}\n\n"
            while True:
                try:
                    event_data = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"event: runtime_event\ndata: {json.dumps(event_data)}\n\n"
                except asyncio.TimeoutError:
                    # Heartbeat keep-alive
                    yield ": keepalive\n\n"
        finally:
            event_hub.unsubscribe(q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/health", response_model=Dict[str, Any])
async def get_runtime_health() -> Dict[str, Any]:
    """Inspect local agent runtime and model substrate readiness."""
    return await agent_engine.health_check()


@router.post("/runs/{run_id}/cancel", status_code=status.HTTP_200_OK)
async def cancel_agent_run(
    run_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    """Request cooperative cancellation for an active agent run."""
    await get_workspace_membership(workspace_id=workspace_id, user_id=current_user.id, db=db)
    agent_engine.cancel_run(run_id)
    return {"success": True, "message": f"Cancellation requested for agent run {run_id}"}
