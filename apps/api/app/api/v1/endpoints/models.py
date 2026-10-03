"""Local model introspection API endpoints."""

from typing import Any, Dict, List
from fastapi import APIRouter
from app.core.config import settings
from app.services.ollama_client import OllamaModelInfo, ollama_client

router = APIRouter(prefix="/models", tags=["Models"])


@router.get("", summary="List Local Ollama Models")
async def list_models() -> Dict[str, Any]:
    """Retrieve list of locally installed Ollama models and active configuration."""
    installed = await ollama_client.list_local_models()
    return {
        "active_configuration": {
            "general_model": settings.LOCAL_MODEL_GENERAL,
            "fast_model": settings.LOCAL_MODEL_FAST,
            "embedding_model": settings.LOCAL_MODEL_EMBEDDING,
            "ollama_endpoint": settings.OLLAMA_BASE_URL,
            "zero_cost_mode": True,
        },
        "installed_models": [m.model_dump() for m in installed],
    }
