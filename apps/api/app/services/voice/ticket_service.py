"""AURA Phase 7 Voice Session Ticket and Nonce Transport Service (AURA-704).

Provides:
1. Short-lived (60s TTL), single-use, cryptographically secure voice session tickets.
2. Atomic single-use ticket consumption with replay prevention.
3. True 256-bit CSPRNG session nonce generation (secrets.token_bytes(32)).
4. Workspace tenancy binding and mismatch validation.
"""

import asyncio
import logging
import secrets
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

from app.core.errors import AuthenticationError, AuthorizationError, VoiceProcessingError

logger = logging.getLogger(__name__)


@dataclass
class VoiceTicket:
    """Represents a short-lived single-use authentication ticket for voice session WebSocket upgrade."""
    ticket_token: str
    user_id: uuid.UUID
    workspace_id: uuid.UUID
    expires_at: float
    created_at: float = field(default_factory=time.time)
    consumed_at: Optional[float] = None
    session_id: Optional[str] = None

    @property
    def is_expired(self) -> bool:
        return time.time() >= self.expires_at

    @property
    def is_consumed(self) -> bool:
        return self.consumed_at is not None


class VoiceTicketService:
    """Manages secure generation, validation, and single-use consumption of voice tickets."""

    DEFAULT_TTL_SECONDS: int = 60
    NONCE_BYTE_ENTROPY: int = 32  # 32 bytes = 256 bits

    def __init__(self, ttl_seconds: int = DEFAULT_TTL_SECONDS):
        self.ttl_seconds = ttl_seconds
        self._tickets: Dict[str, VoiceTicket] = {}
        self._lock = asyncio.Lock()

    def generate_session_nonce(self) -> Tuple[bytes, str]:
        """Generate a true 256-bit CSPRNG session nonce.
        
        Returns:
            Tuple[bytes, str]: Raw 32 bytes and 64-char hex-encoded representation.
        """
        raw_entropy = secrets.token_bytes(self.NONCE_BYTE_ENTROPY)
        hex_nonce = raw_entropy.hex()
        return raw_entropy, hex_nonce

    async def issue_ticket(
        self,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        ttl_seconds: Optional[int] = None,
    ) -> VoiceTicket:
        """Issue a short-lived, single-use ticket bound to an authorized user and workspace."""
        if not user_id or not workspace_id:
            raise AuthenticationError("User ID and Workspace ID are required to issue voice ticket")

        ttl = ttl_seconds or self.ttl_seconds
        now = time.time()
        # 32 bytes = 256-bit cryptographically secure token
        token = secrets.token_urlsafe(32)

        ticket = VoiceTicket(
            ticket_token=token,
            user_id=user_id,
            workspace_id=workspace_id,
            expires_at=now + ttl,
            created_at=now,
        )

        async with self._lock:
            self._prune_expired_tickets(now)
            self._tickets[token] = ticket

        logger.info(f"Issued voice session ticket for user={user_id}, workspace={workspace_id}, ttl={ttl}s")
        return ticket

    async def consume_ticket(
        self,
        ticket_token: str,
        expected_workspace_id: Optional[uuid.UUID] = None,
    ) -> VoiceTicket:
        """Atomically validate and consume a voice ticket.
        
        Rejects:
        - Missing or malformed tokens
        - Non-existent tickets
        - Expired tickets
        - Replayed / already consumed tickets
        - Workspace mismatches
        """
        if not ticket_token or not isinstance(ticket_token, str):
            raise AuthenticationError("Missing or malformed voice session ticket")

        now = time.time()

        async with self._lock:
            ticket = self._tickets.get(ticket_token)

            if ticket is None:
                logger.warning(f"Voice ticket consumption rejected: token not found or already purged")
                raise AuthenticationError("Invalid or expired voice session ticket")

            # Check single-use replay
            if ticket.is_consumed:
                logger.warning(f"Voice ticket replay attempt rejected for user={ticket.user_id}, ws={ticket.workspace_id}")
                # Remove from registry immediately
                self._tickets.pop(ticket_token, None)
                raise AuthenticationError("Voice session ticket has already been consumed (replay detected)")

            # Check expiration
            if now >= ticket.expires_at:
                logger.warning(f"Voice ticket expired for user={ticket.user_id}, ws={ticket.workspace_id}")
                self._tickets.pop(ticket_token, None)
                raise AuthenticationError("Voice session ticket has expired")

            # Check workspace binding if requested
            if expected_workspace_id is not None and ticket.workspace_id != expected_workspace_id:
                logger.warning(f"Voice ticket workspace mismatch: ticket_ws={ticket.workspace_id}, expected={expected_workspace_id}")
                self._tickets.pop(ticket_token, None)
                raise AuthorizationError(f"Voice session ticket is not valid for workspace {expected_workspace_id}")

            # Atomic consumption
            ticket.consumed_at = now
            # Pop ticket from active map so subsequent lookups instantly fail
            self._tickets.pop(ticket_token, None)

        logger.info(f"Successfully consumed voice ticket for user={ticket.user_id}, workspace={ticket.workspace_id}")
        return ticket

    def _prune_expired_tickets(self, now: float) -> None:
        """Internal cleanup of expired tickets."""
        expired_tokens = [token for token, t in self._tickets.items() if now >= t.expires_at or t.is_consumed]
        for token in expired_tokens:
            self._tickets.pop(token, None)

    async def get_active_ticket_count(self) -> int:
        """Get count of active unconsumed tickets."""
        async with self._lock:
            return len(self._tickets)


# Global singleton instance
voice_ticket_service = VoiceTicketService()
