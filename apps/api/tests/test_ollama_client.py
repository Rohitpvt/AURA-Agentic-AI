"""Ollama client service test suite."""

import pytest
import httpx
from app.core.errors import LocalModelUnavailableError, ModelTimeoutError
from app.services.ollama_client import OllamaClient


@pytest.mark.asyncio
async def test_ollama_client_health_check():
    """Test Ollama client health detection."""
    client = OllamaClient(base_url="http://127.0.0.1:11434")

    # Offline check (assuming nothing on dummy port or handles offline gracefully)
    dummy_client = OllamaClient(base_url="http://127.0.0.1:59999")
    is_healthy = await dummy_client.is_healthy()
    assert is_healthy is False


@pytest.mark.asyncio
async def test_ollama_client_offline_error_handling():
    """Test that client raises LocalModelUnavailableError without cloud fallback when offline."""
    dummy_client = OllamaClient(base_url="http://127.0.0.1:59999", timeout_seconds=1.0)

    with pytest.raises(LocalModelUnavailableError) as exc_info:
        await dummy_client.chat(
            messages=[{"role": "user", "content": "Hello AURA"}],
            model="qwen2.5:7b-instruct-q4_K_M",
        )

    assert "cloud fallback prohibited" in str(exc_info.value.message)


@pytest.mark.asyncio
async def test_ollama_client_mock_chat(monkeypatch):
    """Test successful chat execution through Ollama client."""
    client = OllamaClient(base_url="http://localhost:11434")

    # Mock response
    mock_payload = {
        "model": "qwen2.5:7b-instruct-q4_K_M",
        "message": {"role": "assistant", "content": '{"status": "plan_generated", "steps": 3}'},
        "total_duration": 1500000000,
        "prompt_eval_count": 50,
        "eval_count": 30,
        "done": True,
    }

    class MockResponse:
        status_code = 200
        def json(self):
            return mock_payload

    async def mock_post(*args, **kwargs):
        return MockResponse()

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    response = await client.chat(
        messages=[{"role": "user", "content": "Generate plan"}],
        model="qwen2.5:7b-instruct-q4_K_M",
        format_json=True,
    )

    assert response.model == "qwen2.5:7b-instruct-q4_K_M"
    assert response.message.role == "assistant"
    assert "plan_generated" in response.message.content
    assert response.total_duration_ms == 1500.0
