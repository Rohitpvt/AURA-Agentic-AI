"""Ollama Local Model Provider implementing ModelProvider interface."""

import json
from typing import Any, AsyncGenerator, List, Optional
import httpx
from app.core.config import settings
from app.core.errors import OllamaUnavailableError
from app.core.logging import logger
from app.services.providers.base import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ModelInfo,
    ModelProvider,
    ProviderHealthStatus,
)


class OllamaProvider(ModelProvider):
    """Local-only zero-cost Ollama provider."""

    def __init__(self, base_url: Optional[str] = None, timeout_seconds: Optional[float] = None):
        self.base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        self.timeout = timeout_seconds or settings.OLLAMA_TIMEOUT_SECONDS

    async def generate_chat(self, request: ChatRequest) -> ChatResponse:
        """Execute chat completion against local Ollama daemon."""
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": request.model,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "stream": False,
            "options": {"temperature": request.temperature},
        }
        if request.json_mode:
            payload["format"] = "json"

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                res = await client.post(url, json=payload)
                res.raise_for_status()
                data = res.json()
        except httpx.ConnectError as e:
            logger.error(f"Local Ollama connection refused at {self.base_url}: {e}")
            raise OllamaUnavailableError(f"Ollama daemon is offline at {self.base_url}") from e
        except httpx.TimeoutException as e:
            logger.error(f"Ollama generation timed out after {self.timeout}s: {e}")
            raise OllamaUnavailableError(f"Ollama request timed out after {self.timeout}s") from e
        except Exception as e:
            logger.error(f"Unexpected error communicating with Ollama: {e}")
            raise OllamaUnavailableError(f"Ollama execution error: {str(e)}") from e

        content = data.get("message", {}).get("content", "")
        prompt_tokens = data.get("prompt_eval_count", 0)
        completion_tokens = data.get("eval_count", 0)

        return ChatResponse(
            model=request.model,
            content=content,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            provider="ollama_local",
        )

    async def generate_stream(self, request: ChatRequest) -> AsyncGenerator[str, None]:
        """Stream completion tokens from local Ollama daemon."""
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": request.model,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "stream": True,
            "options": {"temperature": request.temperature},
        }
        if request.json_mode:
            payload["format"] = "json"

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream("POST", url, json=payload) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if line:
                            try:
                                chunk = json.loads(line)
                                delta = chunk.get("message", {}).get("content", "")
                                if delta:
                                    yield delta
                            except json.JSONDecodeError:
                                continue
        except Exception as e:
            logger.error(f"Error in Ollama stream: {e}")
            raise OllamaUnavailableError(f"Ollama stream error: {str(e)}") from e

    async def generate_structured(self, request: ChatRequest, response_model: Any) -> Any:
        """Generate structured response validated against Pydantic model."""
        req = request.model_copy()
        req.json_mode = True
        schema_json = json.dumps(response_model.model_json_schema())
        req.messages.append(
            ChatMessage(
                role="system",
                content=f"Respond strictly in valid JSON conforming to this schema:\n{schema_json}",
            )
        )
        response = await self.generate_chat(req)
        try:
            data = json.loads(response.content)
            return response_model.model_validate(data)
        except Exception as e:
            logger.warning(f"Failed to parse structured response from Ollama: {e}")
            raise ValueError(f"Model output did not match schema: {e}") from e

    async def validate_credentials(self) -> bool:
        """Ollama is local and requires zero credentials."""
        return True

    async def health_check(self) -> ProviderHealthStatus:
        """Check if local Ollama daemon is reachable."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                res = await client.get(f"{self.base_url}/api/tags")
                if res.status_code == 200:
                    models = [m.get("name") for m in res.json().get("models", [])]
                    return ProviderHealthStatus(
                        provider_type="ollama",
                        is_available=True,
                        status="healthy",
                        message="Ollama local daemon is online",
                        available_models=models,
                    )
        except Exception as e:
            logger.debug(f"Ollama health probe offline: {e}")

        return ProviderHealthStatus(
            provider_type="ollama",
            is_available=False,
            status="unavailable",
            message=f"Local Ollama unreachable at {self.base_url}",
            error_category="connection_failed",
        )

    async def list_models(self) -> List[ModelInfo]:
        """List locally pulled Ollama models."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                res = await client.get(f"{self.base_url}/api/tags")
                if res.status_code == 200:
                    models = res.json().get("models", [])
                    return [
                        ModelInfo(
                            id=m.get("name"),
                            name=m.get("name"),
                            provider="ollama",
                            is_local=True,
                            billing_tier="zero_cost_local",
                        )
                        for m in models
                    ]
        except Exception:
            pass

        # Return configured defaults if daemon is offline
        return [
            ModelInfo(
                id=settings.LOCAL_MODEL_GENERAL,
                name=settings.LOCAL_MODEL_GENERAL,
                provider="ollama",
                is_local=True,
                billing_tier="zero_cost_local",
            ),
            ModelInfo(
                id=settings.LOCAL_MODEL_FAST,
                name=settings.LOCAL_MODEL_FAST,
                provider="ollama",
                is_local=True,
                billing_tier="zero_cost_local",
            ),
        ]
