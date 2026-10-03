"""Security, hashing, and token signing utilities."""

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
import jwt
from passlib.context import CryptContext
from app.core.config import settings

# Password hashing context (bcrypt)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Revoked token blacklist (in-memory tracker; can be backed by DB/Redis)
_revoked_tokens: set[str] = set()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify plain password against bcrypt hash."""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Generate bcrypt hash for password."""
    return pwd_context.hash(password)


def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """Create a signed JWT access token with unique jti."""
    import uuid
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "iat": now, "type": "access", "jti": uuid.uuid4().hex})
    return jwt.encode(to_encode, settings.AURA_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """Create a signed JWT refresh token with unique jti."""
    import uuid
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "iat": now, "type": "refresh", "jti": uuid.uuid4().hex})
    return jwt.encode(to_encode, settings.AURA_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def compute_token_hash(token: str) -> str:
    """Compute SHA-256 hash of a JWT for persistent revocation lookup."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def decode_token(token: str) -> Dict[str, Any]:
    """Decode and validate a signed JWT token."""
    token_hash = compute_token_hash(token)
    if token in _revoked_tokens or token_hash in _revoked_tokens:
        raise ValueError("Token has been revoked")
    try:
        payload = jwt.decode(token, settings.AURA_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        return payload
    except jwt.PyJWTError as e:
        raise ValueError(f"Invalid token: {str(e)}") from e


def revoke_token(token: str) -> None:
    """Add token and its hash to fast in-memory revocation set."""
    _revoked_tokens.add(token)
    _revoked_tokens.add(compute_token_hash(token))


def clear_in_memory_revocations() -> None:
    """Clear in-memory revocation cache (for crash/restart simulation testing)."""
    _revoked_tokens.clear()


def sign_approval_payload(payload: Dict[str, Any], secret_key: Optional[str] = None) -> str:
    """Sign an approval payload using HMAC-SHA256."""
    key = (secret_key or settings.AURA_SECRET_KEY).encode("utf-8")
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac.new(key, serialized, hashlib.sha256).hexdigest()


def verify_approval_signature(payload: Dict[str, Any], signature: str, secret_key: Optional[str] = None) -> bool:
    """Verify HMAC-SHA256 signature of an approval payload."""
    expected = sign_approval_payload(payload, secret_key)
    return hmac.compare_digest(expected, signature)


def compute_sha256_hash(data: str) -> str:
    """Compute standard SHA-256 hexadecimal digest."""
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def generate_key_fingerprint(secret: str) -> str:
    """Generate masked key fingerprint (e.g. AIza...4f8a) without exposing full secret."""
    if not secret:
        return "empty"
    digest = hashlib.sha256(secret.encode("utf-8")).hexdigest()
    prefix = secret[:4] if len(secret) >= 4 else "key"
    suffix = digest[:4]
    return f"{prefix}...{suffix}"


def _get_encryption_key(master_key: Optional[str] = None) -> bytes:
    """Derive 32-byte key from master key using SHA-256."""
    raw_key = master_key or settings.AURA_MASTER_ENCRYPTION_KEY
    return hashlib.sha256(raw_key.encode("utf-8")).digest()


def encrypt_secret(plaintext: str, master_key: Optional[str] = None) -> str:
    """Encrypt a secret using AES-256-GCM with authenticated tag and nonce."""
    import base64
    import os
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key = _get_encryption_key(master_key)
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)  # 96-bit nonce for GCM
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    # Combine nonce + ciphertext and base64 encode
    payload = nonce + ciphertext
    return base64.b64encode(payload).decode("utf-8")


def decrypt_secret(encrypted_b64: str, master_key: Optional[str] = None) -> str:
    """Decrypt AES-256-GCM ciphertext."""
    import base64
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key = _get_encryption_key(master_key)
    aesgcm = AESGCM(key)
    payload = base64.b64decode(encrypted_b64.encode("utf-8"))
    nonce = payload[:12]
    ciphertext = payload[12:]
    decrypted_bytes = aesgcm.decrypt(nonce, ciphertext, None)
    return decrypted_bytes.decode("utf-8")

