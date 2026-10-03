"""Local Ollama client abstraction for zero-cost model execution."""

import json
from typing import Any, Dict, List, Optional
import httpx
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.errors import LocalModelUnavailableError, ModelTimeoutError
from app.core.logging import logger


class OllamaModelInfo(BaseModel):
    name: str
    size: Optional[int] = None
    digest: Optional[str] = None
    modified_at: Optional[str] = None


class OllamaChatMessage(BaseModel):
    role: str  # 'system', 'user', 'assistant', 'tool'
    content: str
    name: Optional[str] = None


class OllamaChatResponse(BaseModel):
    model: str
    message: OllamaChatMessage
    total_duration_ms: Optional[float] = None
    prompt_eval_count: Optional[int] = None
    eval_count: Optional[int] = None
    done: bool = True


class OllamaClient:
    """Zero-cost local LLM client interacting with local Ollama runtime."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        default_model: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
    ):
        self.base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        self.default_model = default_model or settings.LOCAL_MODEL_GENERAL
        self.timeout_seconds = timeout_seconds or settings.OLLAMA_TIMEOUT_SECONDS

    async def is_healthy(self) -> bool:
        """Check if local Ollama daemon is active and responding."""
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(f"{self.base_url}/api/version")
                return response.status_code == 200
        except Exception:
            return False

    async def list_local_models(self) -> List[OllamaModelInfo]:
        """Fetch list of local models installed in Ollama."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                if response.status_code != 200:
                    raise LocalModelUnavailableError(
                        f"Ollama returned status {response.status_code} on model listing."
                    )
                data = response.json()
                models = data.get("models", [])
                return [
                    OllamaModelInfo(
                        name=m.get("name", ""),
                        size=m.get("size"),
                        digest=m.get("digest"),
                        modified_at=m.get("modified_at"),
                    )
                    for m in models
                ]
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            logger.warning(f"Failed to connect to local Ollama at {self.base_url}: {str(exc)}")
            raise LocalModelUnavailableError(
                message=f"Cannot connect to local Ollama at {self.base_url}. Ensure 'ollama serve' is running."
            ) from exc
        except httpx.TimeoutException as exc:
            raise ModelTimeoutError(message="Timed out waiting for local Ollama model listing.") from exc

    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        format_json: bool = False,
        temperature: float = 0.7,
    ) -> OllamaChatResponse:
        """Execute chat completion against local Ollama model."""
        selected_model = model or self.default_model
        payload = {
            "model": selected_model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
            },
        }
        if format_json:
            payload["format"] = "json"

        from app.core.telemetry import telemetry_manager

        prompt_char_count = sum(len(m.get("content", "")) for m in messages)
        async with telemetry_manager.start_async_span(
            name=f"model.chat {selected_model}",
            span_type="model.inference",
            attributes={
                "gen_ai.system": "ollama",
                "gen_ai.request.model": selected_model,
                "aura.prompt_messages_count": len(messages),
                "aura.prompt_char_count": prompt_char_count,
                "aura.format_json": format_json,
            },
        ) as span:
            try:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    response = await client.post(f"{self.base_url}/api/chat", json=payload)

                    if response.status_code != 200:
                        error_detail = response.text
                        logger.error(f"Ollama execution error [{response.status_code}]: {error_detail}")
                        raise LocalModelUnavailableError(
                            message=f"Local model execution failed with status {response.status_code}: {error_detail}"
                        )

                    data = response.json()
                    msg = data.get("message", {})
                    content = msg.get("content", "")
                    span.set_attribute("gen_ai.response.model", data.get("model", selected_model))
                    span.set_attribute("aura.completion_char_count", len(content))
                    if data.get("eval_count"):
                        span.set_attribute("gen_ai.usage.completion_tokens", data.get("eval_count"))
                    if data.get("prompt_eval_count"):
                        span.set_attribute("gen_ai.usage.prompt_tokens", data.get("prompt_eval_count"))

                    return OllamaChatResponse(
                        model=data.get("model", selected_model),
                        message=OllamaChatMessage(role=msg.get("role", "assistant"), content=content),
                        total_duration_ms=data.get("total_duration", 0) / 1_000_000,
                        prompt_eval_count=data.get("prompt_eval_count"),
                        eval_count=data.get("eval_count"),
                        done=data.get("done", True),
                    )
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                logger.error(f"Ollama connection refused at {self.base_url}")
                raise LocalModelUnavailableError(
                    message=f"Local Ollama is offline at {self.base_url}. Zero-cost invariant: cloud fallback prohibited."
                ) from exc
            except httpx.TimeoutException as exc:
                logger.error(f"Ollama execution timed out after {self.timeout_seconds}s for model {selected_model}")
                raise ModelTimeoutError(
                    message=f"Local model '{selected_model}' timed out after {self.timeout_seconds} seconds."
                ) from exc


# Global client instance
ollama_client = OllamaClient()
