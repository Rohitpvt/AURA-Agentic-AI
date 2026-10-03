"""Unified AgentRuntimeEngine facade encapsulating the Hermes cognitive substrate."""

import uuid
from typing import Any, Callable, Dict, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.runtime.events import RuntimeEvent
from app.runtime.loop import execution_loop
from app.schemas.agent import AgentGoalRequest, AgentRunResponse
from app.services.ollama_client import ollama_client


class AgentRuntimeEngine:
    """Primary control-plane entry point for autonomous agent execution."""

    def __init__(self):
        self._loop = execution_loop

    async def submit_goal(
        self,
        db: AsyncSession,
        request: AgentGoalRequest,
        actor_id: str,
        event_callback: Optional[Callable[[RuntimeEvent], None]] = None,
    ) -> AgentRunResponse:
        """Submit a user goal for autonomous planning and multi-step DAG execution."""
        return await self._loop.execute_goal(
            db=db,
            request=request,
            actor_id=actor_id,
            event_callback=event_callback,
        )

    def cancel_run(self, run_id: uuid.UUID) -> None:
        """Cancel an ongoing agent run instance."""
        self._loop.cancel_run(run_id)

    async def health_check(self) -> Dict[str, Any]:
        """Verify local runtime engine and model substrate readiness."""
        ollama_ok = await ollama_client.is_healthy()
        return {
            "status": "ready" if ollama_ok else "degraded",
            "substrate": "aura_native_substrate",
            "default_model": settings.LOCAL_MODEL_GENERAL,
            "fast_model": settings.LOCAL_MODEL_FAST,
            "embedding_model": settings.FASTEMBED_MODEL_NAME,
            "ollama_available": ollama_ok,
        }


agent_engine = AgentRuntimeEngine()
