"""AURA Phase 8 Vision Session Ticket and Nonce Transport Service (AURA-803).

Provides:
1. Short-lived (60s TTL), single-use, cryptographically secure vision/camera session tickets.
2. Atomic single-use ticket consumption with replay prevention.
3. True 256-bit CSPRNG session nonce generation (secrets.token_bytes(32)).
4. Workspace tenancy binding, purpose scoping, and kill switch validation.
"""

import asyncio
import logging
import secrets
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

from app.core.errors import AuthenticationError, AuthorizationError, VisionProcessingError

logger = logging.getLogger(__name__)


def _is_kill_switch_active(workspace_id: Optional[str] = None) -> bool:
    """Lazy check for kill switch state to prevent circular import chain."""
    try:
        from app.services.kill_switch import kill_switch
        return kill_switch.is_active(workspace_id=workspace_id)
    except Exception:
        return False


@dataclass
class VisionTicket:
    """Represents a short-lived single-use authentication ticket for vision/camera WebSocket upgrade."""
    ticket_token: str
    user_id: uuid.UUID
    workspace_id: uuid.UUID
    purpose: str
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


class VisionTicketService:
    """Manages secure generation, validation, and single-use consumption of vision/camera tickets."""

    DEFAULT_TTL_SECONDS: int = 60
    NONCE_BYTE_ENTROPY: int = 32  # 32 bytes = 256 bits

    def __init__(self, ttl_seconds: int = DEFAULT_TTL_SECONDS):
        self.ttl_seconds = ttl_seconds
        self._tickets: Dict[str, VisionTicket] = {}
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
        purpose: str = "camera_stream",
        ttl_seconds: Optional[int] = None,
    ) -> VisionTicket:
        """Issue a short-lived, single-use ticket bound to an authorized user, workspace, and purpose."""
        if not user_id or not workspace_id:
            raise AuthenticationError("User ID and Workspace ID are required to issue vision ticket")

        if _is_kill_switch_active(workspace_id=str(workspace_id)):
            raise AuthorizationError("Emergency Kill Switch is ACTIVE: Vision operations are suspended.")

        ttl = ttl_seconds or self.ttl_seconds
        now = time.time()
        # 32 bytes = 256-bit cryptographically secure token
        token = secrets.token_urlsafe(32)

        ticket = VisionTicket(
            ticket_token=token,
            user_id=user_id,
            workspace_id=workspace_id,
            purpose=purpose,
            expires_at=now + ttl,
            created_at=now,
        )

        async with self._lock:
            self._prune_expired_tickets(now)
            self._tickets[token] = ticket

        logger.info(
            f"Issued vision session ticket for user={user_id}, workspace={workspace_id}, "
            f"purpose={purpose}, ttl={ttl}s"
        )
        return ticket

    async def consume_ticket(
        self,
        ticket_token: str,
        expected_workspace_id: Optional[uuid.UUID] = None,
        expected_purpose: Optional[str] = None,
    ) -> VisionTicket:
        """Atomically validate and consume a vision ticket.
        
        Enforces:
        1. Ticket token existence.
        2. Non-expired state (within TTL window).
        3. Single-use consumption (replays are rejected).
        4. Workspace tenant binding match (if provided).
        5. Purpose binding match (if provided).
        6. Workspace Emergency Kill Switch check.
        """
        if not ticket_token:
            raise AuthenticationError("Missing vision session ticket token")

        now = time.time()
        async with self._lock:
            ticket = self._tickets.get(ticket_token)
            if not ticket:
                logger.warning(f"Rejected invalid or non-existent vision ticket: {ticket_token[:8]}...")
                raise AuthenticationError("Invalid or non-existent vision session ticket")

            if ticket.is_expired:
                self._tickets.pop(ticket_token, None)
                logger.warning(f"Rejected expired vision ticket: {ticket_token[:8]}...")
                raise AuthenticationError("Vision session ticket has expired")

            self._prune_expired_tickets(now)

            if ticket.is_consumed:
                logger.warning(
                    f"Rejected replayed vision ticket: {ticket_token[:8]}... "
                    f"(already consumed at {ticket.consumed_at})"
                )
                raise AuthenticationError("Vision session ticket has already been consumed (replay rejected)")

            if expected_workspace_id and ticket.workspace_id != expected_workspace_id:
                logger.warning(
                    f"Rejected workspace mismatch for vision ticket: "
                    f"ticket_ws={ticket.workspace_id}, expected_ws={expected_workspace_id}"
                )
                raise AuthorizationError("Vision ticket workspace mismatch: cross-tenant access denied")

            if expected_purpose and ticket.purpose != expected_purpose:
                logger.warning(
                    f"Rejected purpose mismatch for vision ticket: "
                    f"ticket_purpose={ticket.purpose}, expected_purpose={expected_purpose}"
                )
                raise AuthorizationError(
                    f"Vision ticket purpose mismatch: expected '{expected_purpose}', got '{ticket.purpose}'"
                )

            # Check kill switch state for the bound workspace
            if _is_kill_switch_active(workspace_id=str(ticket.workspace_id)):
                raise AuthorizationError(
                    f"Emergency Kill Switch is ACTIVE for workspace '{ticket.workspace_id}'. Ticket consumed but blocked."
                )

            # Mark as consumed atomically
            ticket.consumed_at = now
            logger.info(
                f"Consumed vision ticket {ticket_token[:8]}... for user={ticket.user_id}, "
                f"workspace={ticket.workspace_id}, purpose={ticket.purpose}"
            )
            return ticket

    def _prune_expired_tickets(self, now: float) -> None:
        """Internal helper to prune expired tickets from memory buffer."""
        expired_keys = [k for k, v in self._tickets.items() if v.is_expired]
        for k in expired_keys:
            self._tickets.pop(k, None)


# Global singleton instance
vision_ticket_service = VisionTicketService()
