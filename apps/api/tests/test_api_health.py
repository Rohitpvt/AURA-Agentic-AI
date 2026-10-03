"""API health check endpoints test suite."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_root_health_endpoint(async_client: AsyncClient):
    """Test fast liveness endpoint."""
    response = await async_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "aura-control-plane"
    assert data["zero_cost_mode"] is True
    assert "X-Correlation-ID" in response.headers
    assert "X-Response-Time-Ms" in response.headers


@pytest.mark.asyncio
async def test_v1_health_endpoints(async_client: AsyncClient):
    """Test API v1 basic and detailed health probes."""
    # 1. Basic v1 health
    resp = await async_client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"

    # 2. Detailed v1 health
    resp_detailed = await async_client.get("/api/v1/health/detailed")
    assert resp_detailed.status_code == 200
    data = resp_detailed.json()
    assert "status" in data
    assert "components" in data
    assert "database" in data["components"]
    assert "ollama" in data["components"]


@pytest.mark.asyncio
async def test_v1_models_endpoint(async_client: AsyncClient, monkeypatch):
    """Test local model introspection endpoint."""
    from app.services.ollama_client import OllamaModelInfo, ollama_client

    async def mock_list_local_models():
        return [
            OllamaModelInfo(name="qwen2.5:7b-instruct-q4_K_M", size=4700000000),
            OllamaModelInfo(name="llama3.2:3b-instruct-q4_K_M", size=2000000000),
            OllamaModelInfo(name="BAAI/bge-base-en-v1.5", size=274000000),
        ]

    monkeypatch.setattr(ollama_client, "list_local_models", mock_list_local_models)

    response = await async_client.get("/api/v1/models")
    assert response.status_code == 200
    data = response.json()
    assert "active_configuration" in data
    assert data["active_configuration"]["zero_cost_mode"] is True
    assert len(data["installed_models"]) == 3
    assert data["installed_models"][0]["name"] == "qwen2.5:7b-instruct-q4_K_M"
