"""Model Router managing provider selection, routing modes, and safe fallbacks."""

from typing import Any, AsyncGenerator, Dict, List, Optional
from app.core.config import settings
from app.core.errors import ModelUnavailableError
from app.core.logging import logger
from app.services.providers.base import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ModelInfo,
    ModelProvider,
    ProviderHealthStatus,
)
from app.services.providers.ollama_provider import OllamaProvider


class ModelRouter:
    """Central router for model invocation with deterministic policy enforcement."""

    def __init__(self):
        self._providers: Dict[str, ModelProvider] = {
            "ollama": OllamaProvider(),
        }

    def register_provider(self, name: str, provider: ModelProvider) -> None:
        """Register or update a model provider instance."""
        self._providers[name.lower()] = provider
        logger.info(f"Registered model provider: {name}")

    def remove_provider(self, name: str) -> None:
        """Remove a provider (e.g. on credential deletion)."""
        self._providers.pop(name.lower(), None)
        logger.info(f"Removed model provider: {name}")

    def get_provider(self, name: str) -> Optional[ModelProvider]:
        """Retrieve registered provider by name."""
        return self._providers.get(name.lower())

    async def execute_chat(
        self,
        request: ChatRequest,
        routing_mode: str = "local_only",
        preferred_provider: Optional[str] = None,
    ) -> ChatResponse:
        """Execute chat completion based on routing policy with deterministic fallback."""
        mode = routing_mode.lower()

        # 1. LOCAL_ONLY Mode (Hard zero-cost invariant)
        if mode == "local_only" or preferred_provider == "ollama":
            ollama = self.get_provider("ollama")
            if not ollama:
                raise ModelUnavailableError("Local Ollama provider is not initialized")
            return await ollama.generate_chat(request)

        # 2. BYOK_ONLY Mode (User specified cloud provider)
        if mode == "byok_only":
            target_provider = preferred_provider or "gemini"
            provider = self.get_provider(target_provider)
            if not provider:
                raise ModelUnavailableError(
                    f"BYOK provider '{target_provider}' is not configured or credentials are missing"
                )
            return await provider.generate_chat(request)

        # 3. AUTO Mode (Smart routing with safe zero-cost local fallback)
        target_provider = preferred_provider or "ollama"
        if target_provider == "gemini" and "gemini" in self._providers:
            try:
                gemini = self.get_provider("gemini")
                return await gemini.generate_chat(request)
            except Exception as e:
                logger.warning(f"AUTO mode: Gemini request failed ({e}). Falling back safely to local Ollama.")
                # Safe Local Fallback
                req_fallback = request.model_copy()
                req_fallback.model = settings.LOCAL_MODEL_GENERAL
                ollama = self.get_provider("ollama")
                return await ollama.generate_chat(req_fallback)

        # Default fallback to Ollama
        ollama = self.get_provider("ollama")
        return await ollama.generate_chat(request)

    async def list_all_models(self) -> List[ModelInfo]:
        """Aggregate available models across all registered providers."""
        all_models = []
        for name, provider in self._providers.items():
            try:
                models = await provider.list_models()
                all_models.extend(models)
            except Exception as e:
                logger.debug(f"Could not list models from provider '{name}': {e}")
        return all_models

    async def check_all_health(self) -> List[ProviderHealthStatus]:
        """Check health of all registered providers."""
        statuses = []
        for name, provider in self._providers.items():
            status = await provider.health_check()
            statuses.append(status)
        return statuses


model_router = ModelRouter()
