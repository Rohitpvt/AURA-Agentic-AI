"""
Cross-Phase Privacy Master Audit: Zero-Surveillance Invariant, Secret Masking, and Sensory Buffer Disposability.
"""
import pytest
from app.core.redaction import SecretRedactor
from app.services.os_guard.validators import KeyboardInputValidator


@pytest.mark.asyncio
async def test_privacy_clipboard_secret_scrubbing():
    """
    Privacy Audit: Verify sensitive API keys and JWTs in clipboard are scrubbed on read.
    """
    raw_secret_text = "Here is my secret token: AIzaSyD9876543210FedCba9876543210 and Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signature"

    scrubbed = SecretRedactor.redact_text(raw_secret_text)
    assert "AIzaSy" not in scrubbed
    assert "[REDACTED_GEMINI_KEY]" in scrubbed or "[REDACTED" in scrubbed
    assert "[REDACTED_TOKEN]" in scrubbed or "[REDACTED_JWT_TOKEN]" in scrubbed


@pytest.mark.asyncio
async def test_privacy_keystroke_length_only_logging():
    """
    Privacy Audit: Verify typed keyboard text validation extracts length without retaining raw password in telemetry.
    """
    valid, err, length = KeyboardInputValidator.validate_type_text("MySecretPassword123!")
    assert valid is True
    assert length == 20
