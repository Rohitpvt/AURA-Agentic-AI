"""Tests for AURA-105: Model Provider Abstraction, Gemini BYOK, Credential Vault & Routing."""

import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.security import decrypt_secret, encrypt_secret, generate_key_fingerprint
from app.db.models.provider import Credential, ProviderConfiguration
from app.db.models.workspace import Workspace
from app.services.providers.base import ChatMessage, ChatRequest, ChatResponse
from app.services.providers.gemini_provider import GeminiProvider
from app.services.providers.ollama_provider import OllamaProvider
from app.services.providers.router import ModelRouter


def test_aes_256_gcm_encryption_and_decryption():
    """Verify AES-256-GCM encryption at rest, nonce randomness, and correct decryption."""
    secret = "AIzaSyD-TEST_GOOGLE_GEMINI_KEY_9876543210"
    encrypted1 = encrypt_secret(secret)
    encrypted2 = encrypt_secret(secret)

    # Different nonces produce different ciphertexts for the same plaintext
    assert encrypted1 != encrypted2

    # Both decrypt accurately to original plaintext
    assert decrypt_secret(encrypted1) == secret
    assert decrypt_secret(encrypted2) == secret

    # Fingerprint generation
    fingerprint = generate_key_fingerprint(secret)
    assert fingerprint.startswith("AIza...")
    assert len(fingerprint) <= 12


@pytest.mark.asyncio
async def test_ollama_provider_contract():
    """Verify OllamaProvider implements ModelProvider interface and lists models."""
    provider = OllamaProvider()
    models = await provider.list_models()
    assert len(models) >= 2
    assert any(m.is_local for m in models)


@pytest.mark.asyncio
async def test_model_router_policies_and_zero_cost_fallback(monkeypatch):
    """Test ModelRouter adheres to LOCAL_ONLY, BYOK_ONLY, and AUTO policies with safe local fallback."""
    router = ModelRouter()

    # Mock Ollama Provider
    class MockOllama(OllamaProvider):
        async def generate_chat(self, req: ChatRequest) -> ChatResponse:
            return ChatResponse(
                model=req.model,
                content="Response from Local Ollama",
                provider="ollama_local",
            )

    # Mock Gemini Provider that simulates rate-limiting error
    class MockFailingGemini(GeminiProvider):
        def __init__(self):
            super().__init__(api_key="mock_key")

        async def generate_chat(self, req: ChatRequest) -> ChatResponse:
            from app.core.errors import ModelUnavailableError
            raise ModelUnavailableError("Google Gemini rate limit exceeded (HTTP 429)")

    router.register_provider("ollama", MockOllama())
    router.register_provider("gemini", MockFailingGemini())

    chat_req = ChatRequest(
        model="qwen2.5:7b",
        messages=[ChatMessage(role="user", content="Hello")],
    )

    # 1. LOCAL_ONLY policy -> Routes to Ollama ($0.00)
    res_local = await router.execute_chat(chat_req, routing_mode="local_only")
    assert res_local.provider == "ollama_local"
    assert res_local.content == "Response from Local Ollama"

    # 2. BYOK_ONLY policy -> Fails clearly when Gemini fails (no silent switch)
    with pytest.raises(Exception) as exc_info:
        await router.execute_chat(chat_req, routing_mode="byok_only", preferred_provider="gemini")
    assert "rate limit exceeded" in str(exc_info.value)

    # 3. AUTO policy -> Automatically and safely falls back to Local Ollama on cloud failure
    res_auto = await router.execute_chat(chat_req, routing_mode="auto", preferred_provider="gemini")
    assert res_auto.provider == "ollama_local"
    assert res_auto.content == "Response from Local Ollama"


@pytest.mark.asyncio
async def test_credential_enrollment_api(client: AsyncClient):
    """Test enrolling a BYOK credential via API returns masked fingerprint and stores ciphertext."""
    # 1. Register User & get Workspace
    reg_res = await client.post(
        "/api/v1/auth/register",
        json={"email": "provider_admin@example.com", "username": "prov_admin", "password": "Password123!"},
    )
    token = reg_res.json()["access_token"]
    me_res = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    ws_id = me_res.json()["workspaces"][0]["id"]

    # 2. Configure Gemini Provider
    prov_res = await client.post(
        "/api/v1/providers",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "workspace_id": ws_id,
            "provider_type": "gemini",
            "display_name": "Google Gemini (BYOK)",
            "routing_mode": "auto",
            "default_model": "gemini-2.5-flash",
            "api_endpoint": "https://generativelanguage.googleapis.com/v1beta",
            "billing_tier": "byok_free_tier",
        },
    )
    assert prov_res.status_code == 201
    prov_id = prov_res.json()["id"]

    # 3. Enroll Credential
    raw_key = "AIzaSyD-DUMMY_CREDENTIAL_KEY_VAL_12345"
    cred_res = await client.post(
        "/api/v1/credentials",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "workspace_id": ws_id,
            "provider_config_id": prov_id,
            "credential_type": "api_key",
            "secret": raw_key,
        },
    )
    assert cred_res.status_code == 201
    cred_data = cred_res.json()
    # Plaintext secret is NEVER returned
    assert "secret" not in cred_data
    assert cred_data["key_fingerprint"].startswith("AIza...")
    cred_id = cred_data["id"]

    # 4. List Credentials -> masked metadata only
    list_res = await client.get(
        f"/api/v1/credentials?workspace_id={ws_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert list_res.status_code == 200
    assert len(list_res.json()) == 1
    assert list_res.json()[0]["key_fingerprint"].startswith("AIza...")

    # 5. Revoke Credential
    del_res = await client.delete(
        f"/api/v1/credentials/{cred_id}?workspace_id={ws_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert del_res.status_code == 200
    assert del_res.json()["success"] is True
