"""Secret Redaction and Credential Leakage Protection Module.

Ensures that:
- Master encryption keys
- BYOK API keys (Gemini, OpenAI, Anthropic, OpenRouter)
- JWT access and refresh tokens
- User passwords and DB connection strings
never leak into logs, prompts, memory embeddings, or API responses.
"""

import re
from typing import Any, Dict, List, Union


class SecretRedactor:
    """Detects and redacts credentials, keys, and tokens across arbitrary data structures."""

    PATTERNS = [
        # Google Gemini / AI Studio keys (AQ.Ab8..., AIzaSy...)
        (re.compile(r"AQ\.[A-Za-z0-9\-_]{10,}", re.IGNORECASE), "[REDACTED_GEMINI_KEY]"),
        (re.compile(r"AIzaSy[A-Za-z0-9\-_]{20,}", re.IGNORECASE), "[REDACTED_GEMINI_KEY]"),
        # OpenAI style keys (sk-...)
        (re.compile(r"sk-[A-Za-z0-9\-_]{20,}", re.IGNORECASE), "[REDACTED_API_KEY]"),
        # JWT Tokens (eyJ...)
        (re.compile(r"eyJ[A-Za-z0-9\-_]+\.eyJ[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+", re.IGNORECASE), "[REDACTED_JWT_TOKEN]"),
        # Bearer Authorization headers
        (re.compile(r"(Bearer\s+)[A-Za-z0-9\-_.\/+=]{20,}", re.IGNORECASE), r"\1[REDACTED_TOKEN]"),
        # Generic Secret/Key assignments
        (re.compile(r'("(?:api_key|password|secret|access_token|credential|ticket|vision_ticket)":\s*")[^"]+(")', re.IGNORECASE), r'\1[REDACTED]\2'),
        (re.compile(r"((?:api_key|password|secret|access_token|credential|ticket|vision_ticket)\s*=\s*['\"])[^'\"]+(['\"])", re.IGNORECASE), r"\1[REDACTED]\2"),
        # Vision and Voice URL Ticket Query Parameters
        (re.compile(r"([?&]ticket=)[A-Za-z0-9\-_]{16,}", re.IGNORECASE), r"\1[REDACTED_TICKET]"),
        (re.compile(r"([?&]session_nonce=)[A-Za-z0-9\-_]{16,}", re.IGNORECASE), r"\1[REDACTED_NONCE]"),
        (re.compile(r"\b(?:vision_ticket_|voice_ticket_)[A-Za-z0-9\-_]{16,}\b", re.IGNORECASE), "[REDACTED_TICKET]"),
    ]

    SENSITIVE_KEY_NAMES = {
        "api_key", "password", "secret", "access_token", "refresh_token",
        "credential", "token", "master_key", "encryption_key", "authorization",
        "gemini_api_key", "openai_api_key", "anthropic_api_key", "ticket",
        "vision_ticket", "session_ticket", "session_nonce", "pairing_token"
    }

    @classmethod
    def redact_text(cls, text: str) -> str:
        """Redact sensitive patterns from a raw string."""
        if not text or not isinstance(text, str):
            return text
        redacted = text
        for pattern, replacement in cls.PATTERNS:
            redacted = pattern.sub(replacement, redacted)
        return redacted

    @classmethod
    def redact_structure(cls, data: Any) -> Any:
        """Recursively redact secrets in dictionaries, lists, or primitives."""
        if isinstance(data, dict):
            new_dict = {}
            for k, v in data.items():
                if isinstance(k, str) and (
                    k.lower() in cls.SENSITIVE_KEY_NAMES
                    or any(s in k.lower() for s in ("password", "secret", "token", "key", "credential", "auth"))
                ):
                    new_dict[k] = "[REDACTED]"
                else:
                    new_dict[k] = cls.redact_structure(v)
            return new_dict
        elif isinstance(data, list):
            return [cls.redact_structure(item) for item in data]
        elif isinstance(data, str):
            return cls.redact_text(data)
        else:
            return data


secret_redactor = SecretRedactor()
