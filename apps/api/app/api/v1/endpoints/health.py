"""Health check API endpoints."""

from typing import Any, Dict
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.health_service import HealthService

router = APIRouter(prefix="/health", tags=["Health"])


@router.get("", summary="Basic Liveness Probe")
async def basic_health() -> Dict[str, str]:
    """Return fast status code for application uptime."""
    return {"status": "healthy", "service": "aura-control-plane"}


@router.get("/detailed", summary="Detailed Readiness Probe")
async def detailed_health(db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """Inspect PostgreSQL and local Ollama dependency health."""
    return await HealthService.get_system_health(db)
