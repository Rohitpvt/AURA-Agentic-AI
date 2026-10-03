"""Pydantic schemas for Telegram Bot integration and operator pairing."""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class TelegramIntegrationCreateRequest(BaseModel):
    """Payload to configure a new Telegram Bot integration."""
    display_name: str = Field(default="Telegram Bot", min_length=1, max_length=255)
    bot_token: str = Field(min_length=20, max_length=255, description="Telegram Bot API token from @BotFather")
    is_active: bool = Field(default=True)


class TelegramIntegrationUpdateRequest(BaseModel):
    """Payload to update an existing Telegram Bot integration."""
    display_name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    is_active: Optional[bool] = None


class TelegramRotateTokenRequest(BaseModel):
    """Payload to rotate a Telegram Bot token."""
    bot_token: str = Field(min_length=20, max_length=255, description="New Telegram Bot API token")


class TelegramIntegrationResponse(BaseModel):
    """Public metadata representation of a Telegram Bot integration (token is never returned)."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    display_name: str
    bot_username: Optional[str] = None
    bot_id: Optional[str] = None
    is_active: bool
    polling_state: str
    last_update_id: int
    last_successful_poll_at: Optional[datetime] = None
    last_error_code: Optional[str] = None
    last_error_summary: Optional[str] = None
    total_messages_received: int = 0
    total_commands_processed: int = 0
    created_at: datetime
    updated_at: datetime


class TelegramPairingGenerateRequest(BaseModel):
    """Request to generate a one-time 15-minute pairing token."""
    ttl_seconds: int = Field(default=900, ge=60, le=3600, description="Token lifetime in seconds (default 15 minutes)")


class TelegramPairingTokenResponse(BaseModel):
    """One-time pairing token response for Telegram operator binding."""
    pairing_token: str = Field(description="One-time pairing token (displayed once)")
    expires_at: datetime
    bot_username: Optional[str] = None
    instructions: str = Field(description="Command to send to the Telegram bot: /start <token>")


class TelegramPairingResponse(BaseModel):
    """Metadata representation of an authorized Telegram chat pairing."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    integration_id: uuid.UUID
    telegram_chat_id: str
    telegram_user_id: Optional[str] = None
    telegram_username: Optional[str] = None
    is_active: bool
    paired_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None
    created_at: datetime


class TelegramBotValidationResponse(BaseModel):
    """Validation outcome for a Telegram Bot API token."""
    is_valid: bool
    bot_username: Optional[str] = None
    bot_id: Optional[str] = None
    error_message: Optional[str] = None
