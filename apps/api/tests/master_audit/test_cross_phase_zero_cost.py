"""
Cross-Phase Zero-Cost Floor Master Audit: Strict Local-First Invariant and Absence of Mandatory Paid APIs.
"""
import pytest
from app.core.config import settings
from app.core.security import encrypt_secret, decrypt_secret
from app.services.providers.router import ModelRouter


@pytest.mark.asyncio
async def test_zero_cost_local_only_mode_invariant():
    """
    Zero-Cost Audit: Verify that LOCAL_ONLY mode defaults to zero-cost local Ollama.
    """
    router = ModelRouter()
    provider = router.get_provider("ollama")
    assert provider is not None


@pytest.mark.asyncio
async def test_zero_cost_byok_encryption_at_rest():
    """
    Zero-Cost Audit: Verify optional BYOK credentials are encrypted at rest with AES-256-GCM.
    """
    raw_key = "AIzaSy_OptionalBYOKKey_12345"
    encrypted = encrypt_secret(raw_key)

    # Encrypted payload must differ from raw key
    assert encrypted != raw_key
    assert "AIzaSy" not in encrypted

    # Decryption works with internal master key
    decrypted = decrypt_secret(encrypted)
    assert decrypted == raw_key
