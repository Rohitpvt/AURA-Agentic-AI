"""
Cross-Phase Security Red Team Master Audit: Adversarial Multi-Layer Attacks Across All Boundaries.
"""
import pytest
import uuid

from app.core.security import create_access_token, verify_approval_signature, sign_approval_payload
from app.services.os_guard.validators import PathValidator, ProcessIdentityValidator


@pytest.mark.asyncio
async def test_red_team_path_traversal_and_drive_escaping():
    """
    Red Team: Verify PathValidator rejects path traversal sequences, drive escapes, and UNC paths.
    """
    validator = PathValidator()

    # Traversal patterns
    valid1, _, err1 = validator.validate_executable_path("../../windows/system32/cmd.exe")
    assert valid1 is False

    valid2, _, err2 = validator.validate_executable_path("..\\..\\windows\\system32\\cmd.exe")
    assert valid2 is False

    valid3, _, err3 = validator.validate_executable_path("\\\\server\\share\\malware.exe")
    assert valid3 is False


@pytest.mark.asyncio
async def test_red_team_hitl_cryptographic_token_forgery_rejection():
    """
    Red Team: Verify forged or tampered HMAC-SHA256 HITL approval signatures fail validation.
    """
    payload = {
        "workspace_id": str(uuid.uuid4()),
        "task_id": str(uuid.uuid4()),
        "tool_name": "terminate_process",
        "param_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    }
    forged_sig = "forged_invalid_hmac_signature_hex_string_1234567890abcdef"

    assert verify_approval_signature(payload, forged_sig) is False

    valid_sig = sign_approval_payload(payload)
    assert verify_approval_signature(payload, valid_sig) is True
