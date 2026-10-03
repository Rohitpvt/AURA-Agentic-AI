"""API Endpoints for Telegram Bot Integration and Operator Pairing."""

import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_workspace_membership
from app.db.models.user import User
from app.db.session import get_db_session
from app.schemas.telegram import (
    TelegramIntegrationCreateRequest,
    TelegramIntegrationResponse,
    TelegramIntegrationUpdateRequest,
    TelegramPairingGenerateRequest,
    TelegramPairingResponse,
    TelegramPairingTokenResponse,
    TelegramRotateTokenRequest,
)
from app.services.integrations.telegram_service import telegram_service

router = APIRouter()


# ==========================================
# 1. Telegram Integration Management
# ==========================================

@router.post("/integrations", response_model=TelegramIntegrationResponse, status_code=status.HTTP_201_CREATED)
async def create_telegram_integration(
    payload: TelegramIntegrationCreateRequest,
    workspace_id: uuid.UUID = Query(..., description="Target Workspace UUID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> TelegramIntegrationResponse:
    """Configure a new Telegram Bot integration for a workspace."""
    await get_workspace_membership(workspace_id=workspace_id, user_id=current_user.id, db=db)
    return await telegram_service.create_integration(
        db=db,
        payload=payload,
        workspace_id=workspace_id,
        user_id=current_user.id,
    )


@router.get("/integrations", response_model=List[TelegramIntegrationResponse])
async def list_telegram_integrations(
    workspace_id: uuid.UUID = Query(..., description="Target Workspace UUID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[TelegramIntegrationResponse]:
    """List Telegram Bot integrations for a workspace."""
    await get_workspace_membership(workspace_id=workspace_id, user_id=current_user.id, db=db)
    return await telegram_service.list_integrations(
        db=db,
        workspace_id=workspace_id,
    )


@router.get("/integrations/{integration_id}", response_model=TelegramIntegrationResponse)
async def get_telegram_integration(
    integration_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(..., description="Target Workspace UUID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> TelegramIntegrationResponse:
    """Retrieve metadata for a Telegram Bot integration."""
    await get_workspace_membership(workspace_id=workspace_id, user_id=current_user.id, db=db)
    return await telegram_service.get_integration(
        db=db,
        integration_id=integration_id,
        workspace_id=workspace_id,
    )


@router.patch("/integrations/{integration_id}", response_model=TelegramIntegrationResponse)
async def update_telegram_integration(
    integration_id: uuid.UUID,
    payload: TelegramIntegrationUpdateRequest,
    workspace_id: uuid.UUID = Query(..., description="Target Workspace UUID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> TelegramIntegrationResponse:
    """Update Telegram Bot integration configuration."""
    await get_workspace_membership(workspace_id=workspace_id, user_id=current_user.id, db=db)
    return await telegram_service.update_integration(
        db=db,
        integration_id=integration_id,
        workspace_id=workspace_id,
        payload=payload,
        user_id=current_user.id,
    )


@router.post("/integrations/{integration_id}/rotate-token", response_model=TelegramIntegrationResponse)
async def rotate_telegram_token(
    integration_id: uuid.UUID,
    payload: TelegramRotateTokenRequest,
    workspace_id: uuid.UUID = Query(..., description="Target Workspace UUID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> TelegramIntegrationResponse:
    """Rotate the Telegram Bot API token."""
    await get_workspace_membership(workspace_id=workspace_id, user_id=current_user.id, db=db)
    return await telegram_service.rotate_token(
        db=db,
        integration_id=integration_id,
        workspace_id=workspace_id,
        payload=payload,
        user_id=current_user.id,
    )


@router.delete("/integrations/{integration_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_telegram_integration(
    integration_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(..., description="Target Workspace UUID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """Soft-delete Telegram Bot integration."""
    await get_workspace_membership(workspace_id=workspace_id, user_id=current_user.id, db=db)
    await telegram_service.delete_integration(
        db=db,
        integration_id=integration_id,
        workspace_id=workspace_id,
        user_id=current_user.id,
    )


# ==========================================
# 2. Operator Chat Pairing
# ==========================================

@router.post("/integrations/{integration_id}/pairings", response_model=TelegramPairingTokenResponse)
async def generate_pairing_token(
    integration_id: uuid.UUID,
    payload: TelegramPairingGenerateRequest = TelegramPairingGenerateRequest(),
    workspace_id: uuid.UUID = Query(..., description="Target Workspace UUID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> TelegramPairingTokenResponse:
    """Generate a one-time 15-minute pairing token for an operator to link their Telegram chat."""
    await get_workspace_membership(workspace_id=workspace_id, user_id=current_user.id, db=db)
    return await telegram_service.generate_pairing_token(
        db=db,
        integration_id=integration_id,
        workspace_id=workspace_id,
        user_id=current_user.id,
        ttl_seconds=payload.ttl_seconds,
    )


@router.get("/integrations/{integration_id}/pairings", response_model=List[TelegramPairingResponse])
async def list_telegram_pairings(
    integration_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(..., description="Target Workspace UUID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[TelegramPairingResponse]:
    """List active paired Telegram chats for an integration."""
    await get_workspace_membership(workspace_id=workspace_id, user_id=current_user.id, db=db)
    return await telegram_service.list_pairings(
        db=db,
        integration_id=integration_id,
        workspace_id=workspace_id,
    )


@router.delete("/integrations/{integration_id}/pairings/{pairing_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_telegram_pairing(
    integration_id: uuid.UUID,
    pairing_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(..., description="Target Workspace UUID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """Revoke an active Telegram chat pairing."""
    await get_workspace_membership(workspace_id=workspace_id, user_id=current_user.id, db=db)
    await telegram_service.revoke_pairing(
        db=db,
        pairing_id=pairing_id,
        workspace_id=workspace_id,
        user_id=current_user.id,
    )
