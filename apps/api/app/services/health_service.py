"""Health check service for AURA API, PostgreSQL, and local Ollama."""

from typing import Any, Dict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import logger
from app.services.ollama_client import ollama_client


class HealthService:
    """Service to evaluate system health across core local dependencies."""

    @staticmethod
    async def check_database(session: AsyncSession) -> Dict[str, Any]:
        """Verify PostgreSQL connectivity and extensions."""
        try:
            result = await session.execute(text("SELECT 1;"))
            row = result.scalar()
            if row == 1:
                # Check pgvector extension
                vec_check = await session.execute(
                    text("SELECT 1 FROM pg_extension WHERE extname = 'vector';")
                )
                has_vector = vec_check.scalar() == 1
                return {
                    "status": "healthy",
                    "connected": True,
                    "pgvector_available": has_vector,
                }
            return {"status": "degraded", "connected": False, "error": "Unexpected query response"}
        except Exception as exc:
            logger.warning(f"Database health check failed: {str(exc)}")
            return {
                "status": "unavailable",
                "connected": False,
                "error": str(exc),
            }

    @staticmethod
    async def check_ollama() -> Dict[str, Any]:
        """Verify local Ollama status and configured model availability."""
        try:
            is_active = await ollama_client.is_healthy()
            if not is_active:
                return {
                    "status": "unavailable",
                    "connected": False,
                    "endpoint": settings.OLLAMA_BASE_URL,
                    "message": "Local Ollama daemon is not responding",
                }

            models = await ollama_client.list_local_models()
            model_names = [m.name for m in models]
            configured_present = any(
                settings.LOCAL_MODEL_GENERAL in name or name in settings.LOCAL_MODEL_GENERAL
                for name in model_names
            )
            return {
                "status": "healthy" if configured_present else "degraded",
                "connected": True,
                "endpoint": settings.OLLAMA_BASE_URL,
                "configured_model": settings.LOCAL_MODEL_GENERAL,
                "configured_model_present": configured_present,
                "installed_models": model_names,
            }
        except Exception as exc:
            logger.warning(f"Ollama health check failed: {str(exc)}")
            return {
                "status": "unavailable",
                "connected": False,
                "endpoint": settings.OLLAMA_BASE_URL,
                "error": str(exc),
            }

    @classmethod
    async def get_system_health(cls, session: AsyncSession) -> Dict[str, Any]:
        """Aggregate system health status."""
        db_health = await cls.check_database(session)
        ollama_health = await cls.check_ollama()

        is_healthy = db_health.get("status") == "healthy" and ollama_health.get("status") in ["healthy", "degraded"]
        is_degraded = db_health.get("status") == "healthy" and ollama_health.get("status") == "unavailable"

        overall_status = "healthy" if is_healthy else ("degraded" if is_degraded else "unavailable")

        return {
            "status": overall_status,
            "environment": settings.AURA_ENV,
            "zero_cost_mode": True,
            "components": {
                "api": {"status": "healthy"},
                "database": db_health,
                "ollama": ollama_health,
            },
        }
