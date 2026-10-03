"""Prompt injection isolation envelopes for spoken and multimodal ingress."""

import re
from datetime import datetime, timezone
from typing import Optional


def format_untrusted_spoken_envelope(
    text: str,
    session_id: Optional[str] = None,
    timestamp: Optional[str] = None,
    language: Optional[str] = "en",
) -> str:
    """Format transcribed spoken audio into an untrusted content envelope."""
    ts = timestamp or datetime.now(timezone.utc).isoformat()
    sid = session_id or "ephemeral_session"
    clean_text = text.strip() if text else ""
    return (
        f'<untrusted_spoken_content origin="voice_stream" session_id="{sid}" timestamp="{ts}" lang="{language}">\n'
        f"{clean_text}\n"
        f"</untrusted_spoken_content>"
    )


def extract_untrusted_spoken_content(envelope_text: str) -> str:
    """Extract raw transcribed text from an untrusted spoken envelope."""
    if not envelope_text:
        return ""
    pattern = re.compile(
        r'<untrusted_spoken_content[^>]*>\s*(.*?)\s*<\/untrusted_spoken_content>',
        re.DOTALL | re.IGNORECASE,
    )
    match = pattern.search(envelope_text)
    if match:
        return match.group(1).strip()
    return envelope_text.strip()
