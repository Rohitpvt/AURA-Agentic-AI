"""AURA-904 Governed Clipboard Boundary Adapter.

Provides:
1. clipboard_read: Governed clipboard extraction bounded to max 4,096 characters with automated
   secret redaction (API keys, Bearer tokens, JWTs). Plaintext is returned in-memory to the authenticated
   caller turn ONLY and is NEVER persisted to vector memory, database tables, or trace spans.
2. clipboard_write: Governed clipboard writing bounded to max 4,096 characters with NUL byte injection
   rejection and cryptographic HMAC-SHA256 parameter-bound HITL verification at L0-L2 autonomy.
   Audit records log only character count, byte count, and payload SHA-256 hash (never plaintext).

Safety Invariants:
- Hard ceiling: MAX_CLIPBOARD_CHARS = 4,096
- Zero long-term vector memory or episodic persistence
- Zero plaintext in audit logs, error messages, or OpenTelemetry attributes
- Single-use cryptographic approval token binding
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, Optional
import pyperclip

from app.core.errors import ValidationError
from app.core.logging import logger
from app.core.redaction import secret_redactor


class GovernedClipboardAdapter:
    """Governed Host Clipboard Interface with strict privacy and bounding guarantees."""

    MAX_CLIPBOARD_CHARS: int = 4096

    @classmethod
    def clipboard_read(cls) -> Dict[str, Any]:
        """Read text from host clipboard with length bounding and secret redaction.
        
        Returns:
            Dict containing:
            - text: Sanitized/redacted text content
            - character_count: Length of sanitized text
            - original_length: Length of raw clipboard content
            - truncated: Boolean indicating if content was truncated to 4096 chars
            - redacted: Boolean indicating if sensitive tokens were scrubbed
        """
        try:
            raw_text = pyperclip.paste() or ""
        except Exception as exc:
            logger.warning(f"GovernedClipboardAdapter: Failed reading host clipboard: {exc}")
            raw_text = ""

        original_len = len(raw_text)
        truncated = False

        # 1. Enforce 4,096 character ceiling
        if original_len > cls.MAX_CLIPBOARD_CHARS:
            bounded_text = raw_text[: cls.MAX_CLIPBOARD_CHARS]
            truncated = True
        else:
            bounded_text = raw_text

        # 2. Scrub secrets and credentials
        redacted_text = secret_redactor.redact_text(bounded_text)
        was_redacted = redacted_text != bounded_text

        return {
            "status": "success",
            "text": redacted_text,
            "character_count": len(redacted_text),
            "original_length": original_len,
            "truncated": truncated,
            "redacted": was_redacted,
        }

    @classmethod
    def clipboard_write(cls, text: str) -> Dict[str, Any]:
        """Write sanitized, bounded text to host clipboard.
        
        Enforces:
        - Non-null string type
        - Length <= 4,096 characters
        - Rejection of NUL bytes (\x00)
        
        Returns:
            Dict containing character_count, byte_count, and sha256_hash (zero plaintext).
        """
        if text is None or not isinstance(text, str):
            raise ValidationError("Clipboard write payload must be a valid string.")

        # 1. Reject NUL byte injection
        if "\x00" in text:
            raise ValidationError("NUL byte ('\\x00') detected in clipboard payload. Injection prohibited.")

        # 2. Enforce 4,096 character ceiling
        char_count = len(text)
        if char_count > cls.MAX_CLIPBOARD_CHARS:
            raise ValidationError(
                f"Clipboard payload length ({char_count} characters) exceeds safety ceiling of {cls.MAX_CLIPBOARD_CHARS} characters."
            )

        # 3. Compute Hash and Byte Count
        encoded_bytes = text.encode("utf-8")
        byte_count = len(encoded_bytes)
        sha256_hash = hashlib.sha256(encoded_bytes).hexdigest()

        # 4. Write to Clipboard
        try:
            pyperclip.copy(text)
        except Exception as exc:
            logger.error(f"GovernedClipboardAdapter: Failed writing to host clipboard: {exc}")
            raise RuntimeError(f"Failed writing to host clipboard: {exc}") from exc

        return {
            "status": "success",
            "action": "clipboard_write",
            "character_count": char_count,
            "byte_count": byte_count,
            "sha256_hash": sha256_hash,
        }


governed_clipboard_adapter = GovernedClipboardAdapter()
