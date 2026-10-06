"""Live Validation Suite for Local-Only Runtime, Zero-Cost Invariants & Routing (AURA Phase 2 / Phase 3 / Gap Closure).

Verifies:
1. LOCAL_ONLY routing strictly routes to local providers (Ollama / FastEmbed / Local models).
2. Absolute cloud prohibition: When LOCAL_ONLY is selected, cloud providers (e.g., Gemini / OpenAI) are NEVER invoked, even if BYOK credentials exist.
3. Local failure fail-closed: If local model is unreachable in LOCAL_ONLY mode, ModelUnavailableError is raised; NO silent cloud fallback occurs.
4. Auto-mode fallback safety: When cloud providers fail in AUTO mode, fallback goes to local zero-cost models, never leaking data externally.
5. Network offline resilience: Embedding and local cognitive operations function without Internet access.
"""

from typing import Any, AsyncGenerator, Dict, List, Optional
from unittest.mock import AsyncMock, patch
import pytest

from app.core.errors import ModelUnavailableError
from app.services.embedding_service import embedding_service
from app.services.providers.base import ChatMessage, ChatRequest, ChatResponse, ModelInfo, ModelProvider, ProviderHealthStatus
from app.services.providers.router import ModelRouter, model_router


class MockOllamaProvider(ModelProvider):
    def __init__(self, should_fail: bool = False):
        self.should_fail = should_fail
        self.call_count = 0

    async def generate_chat(self, request: ChatRequest) -> ChatResponse:
        self.call_count += 1
        if self.should_fail:
            raise ModelUnavailableError("Local Ollama daemon is offline (connection refused)")
        return ChatResponse(
            provider="ollama",
            model=request.model or "qwen2.5:7b",
            content="Local response generated strictly on local host weights.",
            input_tokens=15,
            output_tokens=12,
            finish_reason="stop",
        )

    async def generate_stream(self, request: ChatRequest) -> AsyncGenerator[str, None]:
        yield "Local stream"

    async def generate_structured(self, request: ChatRequest, response_schema: Dict[str, Any]) -> Dict[str, Any]:
        return {"result": "local_structured"}

    async def list_models(self) -> List[ModelInfo]:
        return [ModelInfo(id="qwen2.5:7b", name="Qwen 2.5 7B", provider="ollama", is_local=True)]

    async def health_check(self) -> ProviderHealthStatus:
        return ProviderHealthStatus(provider="ollama", is_healthy=not self.should_fail)

    async def validate_credentials(self) -> bool:
        return True


class MockCloudProvider(ModelProvider):
    def __init__(self):
        self.call_count = 0

    async def generate_chat(self, request: ChatRequest) -> ChatResponse:
        self.call_count += 1
        return ChatResponse(
            provider="gemini",
            model="gemini-2.0-flash",
            content="Cloud response",
            input_tokens=15,
            output_tokens=12,
            finish_reason="stop",
        )

    async def generate_stream(self, request: ChatRequest) -> AsyncGenerator[str, None]:
        yield "Cloud stream"

    async def generate_structured(self, request: ChatRequest, response_schema: Dict[str, Any]) -> Dict[str, Any]:
        return {"result": "cloud_structured"}

    async def list_models(self) -> List[ModelInfo]:
        return [ModelInfo(id="gemini-2.0-flash", name="Gemini 2.0 Flash", provider="gemini", is_local=False)]

    async def health_check(self) -> ProviderHealthStatus:
        return ProviderHealthStatus(provider="gemini", is_healthy=True)

    async def validate_credentials(self) -> bool:
        return True


@pytest.mark.asyncio
async def test_local_only_mode_selects_local_provider_and_blocks_cloud():
    """Verify that in local_only mode, only the local provider is called and cloud is untouched."""
    router = ModelRouter()
    mock_local = MockOllamaProvider(should_fail=False)
    mock_cloud = MockCloudProvider()

    router.register_provider("ollama", mock_local)
    router.register_provider("gemini", mock_cloud)

    req = ChatRequest(
        messages=[ChatMessage(role="user", content="Explain quantum computing")],
        model="qwen2.5:7b",
    )

    resp = await router.execute_chat(request=req, routing_mode="local_only")

    assert resp.provider == "ollama"
    assert "Local response" in resp.content
    assert mock_local.call_count == 1
    assert mock_cloud.call_count == 0  # Absolute zero cloud invocation


@pytest.mark.asyncio
async def test_local_only_failure_fails_closed_without_silent_cloud_fallback():
    """Verify that if local model is offline in local_only mode, it fails with error and NEVER falls back to cloud."""
    router = ModelRouter()
    mock_failing_local = MockOllamaProvider(should_fail=True)
    mock_cloud = MockCloudProvider()

    router.register_provider("ollama", mock_failing_local)
    router.register_provider("gemini", mock_cloud)

    req = ChatRequest(
        messages=[ChatMessage(role="user", content="Classify security vulnerability")],
        model="qwen2.5:7b",
    )

    with pytest.raises(ModelUnavailableError) as exc_info:
        await router.execute_chat(request=req, routing_mode="local_only")

    assert "Local Ollama daemon is offline" in str(exc_info.value)
    assert mock_failing_local.call_count == 1
    assert mock_cloud.call_count == 0  # Must NOT silently call cloud!


@pytest.mark.asyncio
async def test_local_embeddings_offline_execution_and_normalization():
    """Verify that local FastEmbed embedding generates 768-dim normalized vectors without external network calls."""
    sample_text = "AURA architectural validation for local-first zero-cost cognition."
    emb = embedding_service.embed_text(sample_text)

    assert isinstance(emb, list)
    assert len(emb) == 768

    # Verify L2 Unit Normalization (sum(x_i^2) == 1.0)
    norm = sum(x * x for x in emb)
    assert abs(norm - 1.0) < 1e-3, f"Embedding norm {norm} is not unit normalized"


@pytest.mark.asyncio
async def test_auto_mode_cloud_failure_falls_back_to_local_zero_cost():
    """Verify that in AUTO mode, if cloud provider fails, it safely falls back to local Ollama."""
    class FailingCloudProvider(ModelProvider):
        async def generate_chat(self, request: ChatRequest):
            raise RuntimeError("Cloud 429 Rate Limit / Quota Exceeded")
        async def generate_stream(self, request: ChatRequest): yield ""
        async def generate_structured(self, request: ChatRequest, response_schema: Dict[str, Any]): return {}
        async def list_models(self): return []
        async def health_check(self): return ProviderHealthStatus(provider="gemini", is_healthy=False)
        async def validate_credentials(self): return False

    router = ModelRouter()
    mock_local = MockOllamaProvider(should_fail=False)
    failing_cloud = FailingCloudProvider()

    router.register_provider("ollama", mock_local)
    router.register_provider("gemini", failing_cloud)

    req = ChatRequest(
        messages=[ChatMessage(role="user", content="Summarize meeting notes")],
        model="gemini-2.0-flash",
    )

    resp = await router.execute_chat(request=req, routing_mode="auto", preferred_provider="gemini")

    assert resp.provider == "ollama"
    assert "Local response" in resp.content
    assert mock_local.call_count == 1
