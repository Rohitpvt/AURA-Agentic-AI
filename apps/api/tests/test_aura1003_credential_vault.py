"""Unit and Functional Tests for AURA-1003 Encrypted Web Session & Credential Vault."""

import asyncio
import os
import uuid
import pytest
from datetime import datetime, timedelta, timezone

from app.core.errors import AuthorizationError, EntityNotFoundError, ValidationError
from app.db.models.web_vault import WebCredential, WebSessionState
from app.services.browser.vault import (
    WebVaultService,
    decrypt_field,
    derive_vault_key,
    encrypt_field,
    extract_domain,
    generate_username_hint,
    normalize_origin,
    validate_origin_match,
    web_vault_service,
)


@pytest.mark.asyncio
async def test_key_derivation_determinism_and_isolation():
    """Verify AES-256 key derivation is deterministic and strongly scoped to workspace IDs."""
    ws_1 = uuid.uuid4()
    ws_2 = uuid.uuid4()

    key_1_a = derive_vault_key(master_key="test_master_key_123", workspace_id=ws_1)
    key_1_b = derive_vault_key(master_key="test_master_key_123", workspace_id=ws_1)
    key_2 = derive_vault_key(master_key="test_master_key_123", workspace_id=ws_2)
    key_unscoped = derive_vault_key(master_key="test_master_key_123", workspace_id=None)

    assert len(key_1_a) == 32
    assert key_1_a == key_1_b
    assert key_1_a != key_2  # Strong workspace key isolation
    assert key_1_a != key_unscoped


@pytest.mark.asyncio
async def test_aes_gcm_encrypt_decrypt_roundtrip():
    """Verify AES-256-GCM encryption/decryption roundtrip with random nonces."""
    ws_id = uuid.uuid4()
    secret = "SuperSecretP@ssw0rd!#2026"

    enc_1 = encrypt_field(secret, workspace_id=ws_id)
    enc_2 = encrypt_field(secret, workspace_id=ws_id)

    # Unique nonce per encryption
    assert enc_1 != enc_2

    # Decrypt succeeds
    dec_1 = decrypt_field(enc_1, workspace_id=ws_id)
    dec_2 = decrypt_field(enc_2, workspace_id=ws_id)
    assert dec_1 == secret
    assert dec_2 == secret


@pytest.mark.asyncio
async def test_aes_gcm_tamper_detection():
    """Verify any modification to ciphertext, nonce, or tag raises ValidationError."""
    import base64
    ws_id = uuid.uuid4()
    secret = "ConfidentialApiKey_xyz_987"
    enc = encrypt_field(secret, workspace_id=ws_id)

    raw = bytearray(base64.b64decode(enc.encode("ascii")))

    # Corrupt last byte (tag)
    raw_corrupt = bytearray(raw)
    raw_corrupt[-1] ^= 0x01
    enc_corrupt = base64.b64encode(raw_corrupt).decode("ascii")

    with pytest.raises(ValidationError, match="Ciphertext tampering or integrity verification failure"):
        decrypt_field(enc_corrupt, workspace_id=ws_id)

    # Corrupt first byte (nonce)
    raw_corrupt_nonce = bytearray(raw)
    raw_corrupt_nonce[0] ^= 0xFF
    enc_corrupt_nonce = base64.b64encode(raw_corrupt_nonce).decode("ascii")

    with pytest.raises(ValidationError, match="Ciphertext tampering or integrity verification failure"):
        decrypt_field(enc_corrupt_nonce, workspace_id=ws_id)

    # Truncated payload
    with pytest.raises(ValidationError, match="Ciphertext tampering or integrity verification failure"):
        decrypt_field(base64.b64encode(b"short").decode("ascii"), workspace_id=ws_id)


@pytest.mark.asyncio
async def test_aes_gcm_wrong_workspace_fails_decryption():
    """Verify ciphertext cannot be decrypted using a different workspace key."""
    ws_1 = uuid.uuid4()
    ws_2 = uuid.uuid4()
    secret = "Token_WS1_Secret_Value"

    enc = encrypt_field(secret, workspace_id=ws_1)

    with pytest.raises(ValidationError, match="Ciphertext tampering or integrity verification failure"):
        decrypt_field(enc, workspace_id=ws_2)


def test_username_masking_privacy_hint():
    """Verify privacy-preserving masked username hints."""
    assert generate_username_hint("admin@example.com") == "ad***@example.com"
    assert generate_username_hint("support@company.org") == "su***@company.org"
    assert generate_username_hint("a@b.com") == "a***@b.com"
    assert generate_username_hint("administrator") == "ad***"
    assert generate_username_hint("ro") == "ro***"
    assert generate_username_hint("x") == "x***"
    assert generate_username_hint("") == "anonymous"


def test_origin_normalization_and_domain_extraction():
    """Verify strict origin normalization and host/domain extraction."""
    assert normalize_origin("https://login.example.com/auth/login?ref=123") == "https://login.example.com"
    assert normalize_origin("http://127.0.0.1:8080/dashboard") == "http://127.0.0.1:8080"
    assert normalize_origin("https://secure.bank.com:8443/#section") == "https://secure.bank.com:8443"

    assert extract_domain("https://login.example.com") == "login.example.com"
    assert extract_domain("http://127.0.0.1:8080") == "127.0.0.1"


def test_origin_match_phishing_defenses():
    """Verify deterministic origin matching and phishing lookalike defenses."""
    cred_origin = "https://app.example.com"

    # Exact match passes
    assert validate_origin_match(cred_origin, "https://app.example.com/login") is True
    assert validate_origin_match(cred_origin, "https://app.example.com/settings") is True

    # Scheme mismatch fails (HTTPS required)
    assert validate_origin_match(cred_origin, "http://app.example.com/login") is False

    # Port mismatch fails
    assert validate_origin_match(cred_origin, "https://app.example.com:8443/login") is False

    # Lookalike domains FAIL
    assert validate_origin_match(cred_origin, "https://app.example.com.attacker.com/login") is False
    assert validate_origin_match(cred_origin, "https://app-example.com/login") is False
    assert validate_origin_match(cred_origin, "https://example.com.evil.com/login") is False
    assert validate_origin_match(cred_origin, "https://fakeapp.example.com/login") is False

    # Subdomain matching policy
    # When allow_subdomains is False: subdomains FAIL
    assert validate_origin_match("https://example.com", "https://sub.example.com/login", allow_subdomains=False) is False
    # When allow_subdomains is True: valid subdomains PASS
    assert validate_origin_match("https://example.com", "https://sub.example.com/login", allow_subdomains=True) is True
    assert validate_origin_match("https://example.com", "https://nested.sub.example.com/login", allow_subdomains=True) is True
    # Lookalikes still fail even with allow_subdomains=True
    assert validate_origin_match("https://example.com", "https://notexample.com/login", allow_subdomains=True) is False


@pytest.mark.asyncio
async def test_web_vault_service_credential_crud(db_session):
    """Verify WebVaultService full credential lifecycle: create, list, get, revoke, delete."""
    ws_id = uuid.uuid4()

    # 1. Create Credential
    cred_meta = await web_vault_service.create_credential(
        db=db_session,
        workspace_id=ws_id,
        name="Github Prod",
        target_origin="https://github.com/login",
        username="octocat_developer@github.com",
        password="TopSecretGithubPassword123!",
        allow_subdomains=True,
    )

    cred_id = uuid.UUID(cred_meta["id"])
    assert cred_meta["name"] == "Github Prod"
    assert cred_meta["target_origin"] == "https://github.com"
    assert cred_meta["username_hint"] == "oc***@github.com"
    assert cred_meta["is_active"] is True
    # Ensure plaintext password is NOT in response
    assert "password" not in cred_meta
    assert "TopSecretGithubPassword123!" not in str(cred_meta)

    # 2. List Credentials Metadata
    creds = await web_vault_service.list_credentials(db=db_session, workspace_id=ws_id)
    assert len(creds) == 1
    assert creds[0]["id"] == str(cred_id)
    assert "password" not in creds[0]

    # 3. Filter by Origin
    creds_github = await web_vault_service.list_credentials(
        db=db_session, workspace_id=ws_id, target_origin="https://github.com/settings"
    )
    assert len(creds_github) == 1
    creds_google = await web_vault_service.list_credentials(
        db=db_session, workspace_id=ws_id, target_origin="https://google.com"
    )
    assert len(creds_google) == 0

    # 4. Get Credential Metadata
    meta = await web_vault_service.get_credential_metadata(
        db=db_session, credential_id=cred_id, workspace_id=ws_id
    )
    assert meta["id"] == str(cred_id)
    assert "TopSecretGithubPassword123!" not in str(meta)

    # 5. Revoke Credential
    revoked = await web_vault_service.revoke_credential(
        db=db_session,
        credential_id=cred_id,
        workspace_id=ws_id,
        reason="Periodic security rotation",
    )
    assert revoked["is_active"] is False
    assert revoked["revoked_reason"] == "Periodic security rotation"

    # Listing active credentials excludes revoked ones
    active_creds = await web_vault_service.list_credentials(
        db=db_session, workspace_id=ws_id, include_revoked=False
    )
    assert len(active_creds) == 0

    # 6. Delete Credential
    deleted = await web_vault_service.delete_credential(
        db=db_session, credential_id=cred_id, workspace_id=ws_id
    )
    assert deleted is True

    with pytest.raises(EntityNotFoundError):
        await web_vault_service.get_credential_metadata(
            db=db_session, credential_id=cred_id, workspace_id=ws_id
        )


@pytest.mark.asyncio
async def test_web_vault_key_rotation(db_session):
    """Verify atomic key rotation re-encrypts stored records under new key."""
    ws_id = uuid.uuid4()
    old_key = "OldMasterEncryptionKey_2025_001"
    new_key = "NewMasterEncryptionKey_2026_002"

    # Create credential under old key
    cred_meta = await web_vault_service.create_credential(
        db=db_session,
        workspace_id=ws_id,
        name="AWS Console",
        target_origin="https://signin.aws.amazon.com",
        username="cloud_admin@enterprise.com",
        password="AWSMasterSecretKey!@#88",
        master_key=old_key,
    )
    cred_id = uuid.UUID(cred_meta["id"])

    # Rotate key
    rotation_report = await web_vault_service.rotate_encryption_key(
        db=db_session,
        workspace_id=ws_id,
        old_master_key=old_key,
        new_master_key=new_key,
    )
    assert rotation_report["status"] == "success"
    assert rotation_report["credentials_rotated"] == 1

    # Verify decryption with new key succeeds
    stmt = await db_session.get(WebCredential, cred_id)
    assert stmt is not None
    decrypted_pass = decrypt_field(stmt.password_ciphertext, master_key=new_key, workspace_id=ws_id)
    assert decrypted_pass == "AWSMasterSecretKey!@#" + "88"

    # Decryption with old key fails
    with pytest.raises(ValidationError):
        decrypt_field(stmt.password_ciphertext, master_key=old_key, workspace_id=ws_id)


@pytest.mark.asyncio
async def test_web_session_storage_state_persistence(db_session):
    """Verify encrypted storage state (cookies, session) save, get, expiry, and revocation."""
    ws_id = uuid.uuid4()
    origin = "https://app.dashboard.com"

    mock_storage_state = {
        "cookies": [
            {
                "name": "session_id",
                "value": "aura_sess_xyz_998877",
                "domain": "app.dashboard.com",
                "path": "/",
                "httpOnly": True,
                "secure": True,
            }
        ],
        "origins": [],
    }

    # 1. Save Session State
    saved = await web_vault_service.save_session_state(
        db=db_session,
        workspace_id=ws_id,
        session_name="main_session",
        target_origin=origin,
        storage_state=mock_storage_state,
        ttl_seconds=3600,
    )
    session_id = uuid.UUID(saved["session_id"])
    assert saved["session_name"] == "main_session"
    assert saved["target_origin"] == origin

    # Verify DB contains ciphertext, not plaintext cookie
    stmt = await db_session.get(WebSessionState, session_id)
    assert "aura_sess_xyz_998877" not in stmt.encrypted_storage_state

    # 2. Retrieve and Decrypt Session State
    retrieved_state = await web_vault_service.get_session_state(
        db=db_session,
        workspace_id=ws_id,
        target_origin=origin,
        session_name="main_session",
    )
    assert retrieved_state is not None
    assert retrieved_state["cookies"][0]["value"] == "aura_sess_xyz_998877"

    # 3. Expired Session returns None
    saved_expired = await web_vault_service.save_session_state(
        db=db_session,
        workspace_id=ws_id,
        session_name="expired_session",
        target_origin=origin,
        storage_state=mock_storage_state,
        ttl_seconds=-10,  # Already expired
    )
    expired_state = await web_vault_service.get_session_state(
        db=db_session,
        workspace_id=ws_id,
        target_origin=origin,
        session_name="expired_session",
    )
    assert expired_state is None

    # 4. Revoke Session State
    revoked = await web_vault_service.revoke_session_state(
        db=db_session, session_id=session_id, workspace_id=ws_id
    )
    assert revoked is True
    post_revoke_state = await web_vault_service.get_session_state(
        db=db_session,
        workspace_id=ws_id,
        target_origin=origin,
        session_name="main_session",
    )
    assert post_revoke_state is None
