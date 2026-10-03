"""Google Gemini BYOK Provider implementing ModelProvider interface."""

import json
from typing import Any, AsyncGenerator, List, Optional
import httpx
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

DEFAULT_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


# Centralized Google Gemini Model Catalog for AURA BYOK (October 1, 2026 Baseline)
GEMINI_MODEL_CATALOG: dict[str, dict[str, Any]] = {
    "gemini-2.5-flash": {
        "name": "Gemini 2.5 Flash",
        "family": "gemini-2.5",
        "lifecycle_status": "active_supported",
        "availability_access_notes": "Standard Google AI Studio API key access; subject to project quota and rate limits (RPM/TPM)",
        "context_limit": 1048576,
        "tool_support": True,
        "structured_output": True,
        "streaming": True,
        "cost_classification": "byok_free_tier",
        "recommended_use": "fast_multimodal_reasoning_and_tool_calling",
    },
    "gemini-2.5-pro": {
        "name": "Gemini 2.5 Pro",
        "family": "gemini-2.5",
        "lifecycle_status": "active_supported",
        "availability_access_notes": "Google AI Studio tier access; may require billing enablement for high token volumes",
        "context_limit": 2097152,
        "tool_support": True,
        "structured_output": True,
        "streaming": True,
        "cost_classification": "byok_potentially_billable",
        "recommended_use": "frontier_reasoning_code_and_complex_planning",
    },
}

# Decommissioned/retired legacy identifiers retained solely for audit reference
DECOMMISSIONED_GEMINI_MODELS: list[str] = [
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "gemini-1.5-pro",
    "gemini-1.0-pro",
    "gemini-pro-vision",
]


class GeminiProvider(ModelProvider):
    """Google Gemini Bring-Your-Own-Key (BYOK) cloud provider adapter."""

    def __init__(
        self,
        api_key: str,
        base_url: Optional[str] = None,
        timeout_seconds: float = 60.0,
    ):
        self.api_key = api_key
        self.base_url = (base_url or DEFAULT_GEMINI_BASE_URL).rstrip("/")
        self.timeout = timeout_seconds

    async def generate_chat(self, request: ChatRequest) -> ChatResponse:
        """Generate chat response using Google Gemini API."""
        model_name = request.model
        # Strip provider prefix if present
        if model_name.startswith("gemini/"):
            model_name = model_name.replace("gemini/", "")

        url = f"{self.base_url}/models/{model_name}:generateContent"

        # Convert normalized messages to Gemini contents format
        contents = []
        for msg in request.messages:
            role = "user" if msg.role in ["user", "system"] else "model"
            contents.append({"role": role, "parts": [{"text": msg.content}]})

        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": request.temperature,
            },
        }
        if request.max_tokens:
            payload["generationConfig"]["maxOutputTokens"] = request.max_tokens
        if request.json_mode:
            payload["generationConfig"]["responseMimeType"] = "application/json"

        headers = {
            "x-goog-api-key": self.api_key,
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                res = await client.post(url, headers=headers, json=payload)
                if res.status_code == 429:
                    logger.warning(f"Google Gemini rate limit / quota exceeded (HTTP 429)")
                    raise ModelUnavailableError("Google Gemini rate limit or quota exceeded (HTTP 429)")
                if res.status_code in [400, 401, 403]:
                    logger.error(f"Google Gemini authentication error ({res.status_code}): {res.text}")
                    raise ModelUnavailableError(f"Invalid or unauthorized Google Gemini API key ({res.status_code})")

                res.raise_for_status()
                data = res.json()
        except httpx.TimeoutException as e:
            logger.error(f"Google Gemini request timed out after {self.timeout}s: {e}")
            raise ModelUnavailableError(f"Google Gemini timed out after {self.timeout}s") from e
        except ModelUnavailableError:
            raise
        except Exception as e:
            logger.error(f"Google Gemini API error: {e}")
            raise ModelUnavailableError(f"Google Gemini request failed: {str(e)}") from e

        # Extract output text
        candidates = data.get("candidates", [])
        if not candidates:
            raise ModelUnavailableError("Google Gemini returned no candidate completions")

        first_cand = candidates[0]
        parts = first_cand.get("content", {}).get("parts", [])
        content = "".join([p.get("text", "") for p in parts])

        usage = data.get("usageMetadata", {})
        prompt_tokens = usage.get("promptTokenCount", 0)
        completion_tokens = usage.get("candidatesTokenCount", 0)
        total_tokens = usage.get("totalTokenCount", prompt_tokens + completion_tokens)

        return ChatResponse(
            model=model_name,
            content=content,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            provider="gemini_byok",
        )

    async def generate_stream(self, request: ChatRequest) -> AsyncGenerator[str, None]:
        """Stream tokens from Gemini API."""
        # For simplicity and robust error isolation in Phase 1, stream by chunking the completion
        response = await self.generate_chat(request)
        for token in response.content.split(" "):
            yield token + " "

    async def generate_structured(self, request: ChatRequest, response_model: Any) -> Any:
        """Generate structured response validated against Pydantic schema."""
        req = request.model_copy()
        req.json_mode = True
        schema_json = json.dumps(response_model.model_json_schema())
        req.messages.append(
            ChatMessage(
                role="user",
                content=f"Respond strictly in valid JSON matching this schema:\n{schema_json}",
            )
        )
        response = await self.generate_chat(req)
        try:
            data = json.loads(response.content)
            return response_model.model_validate(data)
        except Exception as e:
            raise ValueError(f"Gemini output could not be validated against schema: {e}") from e

    async def validate_credentials(self) -> bool:
        """Validate API key by querying /models endpoint."""
        url = f"{self.base_url}/models"
        headers = {"x-goog-api-key": self.api_key}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(url, headers=headers)
                return res.status_code == 200
        except Exception as e:
            logger.debug(f"Gemini key validation failed: {e}")
            return False

    async def health_check(self) -> ProviderHealthStatus:
        """Probe Gemini API health with current credentials."""
        is_valid = await self.validate_credentials()
        if is_valid:
            models = await self.list_models()
            return ProviderHealthStatus(
                provider_type="gemini",
                is_available=True,
                status="healthy",
                message="Google Gemini BYOK is connected and authenticated",
                available_models=[m.id for m in models],
            )
        return ProviderHealthStatus(
            provider_type="gemini",
            is_available=False,
            status="invalid_credentials",
            message="Google Gemini API key is invalid, revoked, or unreachable",
            error_category="authentication_failed",
        )

    async def list_models(self) -> List[ModelInfo]:
        """List verified current Google Gemini models from centralized catalog."""
        return [
            ModelInfo(
                id=model_id,
                name=meta["name"],
                provider="gemini",
                context_window=meta["context_limit"],
                is_local=False,
                billing_tier=meta["cost_classification"],
            )
            for model_id, meta in GEMINI_MODEL_CATALOG.items()
        ]
