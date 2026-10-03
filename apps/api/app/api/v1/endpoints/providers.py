"""Model Provider Configuration Endpoints."""

import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.api.deps import get_current_user, get_workspace_membership
from app.core.errors import AuthorizationError, ConflictError, EntityNotFoundError
from app.db.models.provider import Credential, ProviderConfiguration
from app.db.models.user import User
from app.db.session import get_db_session
from app.schemas.provider import (
    ProviderCreateRequest,
    ProviderResponse,
    ProviderUpdateRequest,
)
from app.services.providers.router import model_router

router = APIRouter()


@router.get("", response_model=List[ProviderResponse])
async def list_providers(
    workspace_id: uuid.UUID = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[ProviderResponse]:
    """List configured model providers for a workspace."""
    await get_workspace_membership(workspace_id, current_user, db)

    res = await db.execute(
        select(ProviderConfiguration)
        .options(selectinload(ProviderConfiguration.credentials))
        .where(
            ProviderConfiguration.workspace_id == workspace_id,
            ProviderConfiguration.deleted_at.is_(None),
        )
    )
    configs = res.scalars().all()

    results = []
    for c in configs:
        has_creds = len(c.credentials) > 0
        fingerprint = c.credentials[0].key_fingerprint if has_creds else None
        results.append(
            ProviderResponse(
                id=c.id,
                workspace_id=c.workspace_id,
                provider_type=c.provider_type,
                display_name=c.display_name,
                is_enabled=c.is_enabled,
                is_default=c.is_default,
                routing_mode=c.routing_mode,
                default_model=c.default_model,
                api_endpoint=c.api_endpoint,
                config_options=c.config_options,
                billing_tier=c.billing_tier,
                has_credentials=has_creds,
                key_fingerprint=fingerprint,
                created_at=c.created_at,
            )
        )
    return results


@router.post("", response_model=ProviderResponse, status_code=status.HTTP_201_CREATED)
async def create_provider(
    payload: ProviderCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ProviderResponse:
    """Configure a model provider (Ollama Local, Gemini BYOK) in a workspace."""
    member = await get_workspace_membership(payload.workspace_id, current_user, db)
    if member.role not in ["owner", "admin"]:
        raise AuthorizationError("Only workspace Owners and Admins can configure model providers")

    # Check duplicate
    res = await db.execute(
        select(ProviderConfiguration).where(
            ProviderConfiguration.workspace_id == payload.workspace_id,
            ProviderConfiguration.provider_type == payload.provider_type,
            ProviderConfiguration.deleted_at.is_(None),
        )
    )
    if res.scalar_one_or_none():
        raise ConflictError(f"Provider '{payload.provider_type}' is already configured in this workspace")

    config = ProviderConfiguration(
        workspace_id=payload.workspace_id,
        provider_type=payload.provider_type,
        display_name=payload.display_name,
        routing_mode=payload.routing_mode,
        default_model=payload.default_model,
        api_endpoint=payload.api_endpoint,
        config_options=payload.config_options,
        billing_tier=payload.billing_tier,
        is_enabled=payload.is_enabled,
        is_default=payload.is_default,
    )
    db.add(config)
    await db.commit()
    await db.refresh(config)

    return ProviderResponse(
        id=config.id,
        workspace_id=config.workspace_id,
        provider_type=config.provider_type,
        display_name=config.display_name,
        is_enabled=config.is_enabled,
        is_default=config.is_default,
        routing_mode=config.routing_mode,
        default_model=config.default_model,
        api_endpoint=config.api_endpoint,
        config_options=config.config_options,
        billing_tier=config.billing_tier,
        has_credentials=False,
        key_fingerprint=None,
        created_at=config.created_at,
    )


@router.put("/{id}", response_model=ProviderResponse)
async def update_provider(
    id: uuid.UUID,
    payload: ProviderUpdateRequest,
    workspace_id: uuid.UUID = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ProviderResponse:
    """Update provider settings / routing mode."""
    member = await get_workspace_membership(workspace_id, current_user, db)
    if member.role not in ["owner", "admin"]:
        raise AuthorizationError("Only workspace Owners and Admins can update model providers")

    res = await db.execute(
        select(ProviderConfiguration)
        .options(selectinload(ProviderConfiguration.credentials))
        .where(
            ProviderConfiguration.id == id,
            ProviderConfiguration.workspace_id == workspace_id,
            ProviderConfiguration.deleted_at.is_(None),
        )
    )
    config = res.scalar_one_or_none()
    if not config:
        raise EntityNotFoundError("ProviderConfiguration", str(id))

    if payload.display_name is not None:
        config.display_name = payload.display_name
    if payload.routing_mode is not None:
        config.routing_mode = payload.routing_mode
    if payload.default_model is not None:
        config.default_model = payload.default_model
    if payload.api_endpoint is not None:
        config.api_endpoint = payload.api_endpoint
    if payload.config_options is not None:
        config.config_options = payload.config_options
    if payload.billing_tier is not None:
        config.billing_tier = payload.billing_tier
    if payload.is_enabled is not None:
        config.is_enabled = payload.is_enabled
    if payload.is_default is not None:
        config.is_default = payload.is_default

    await db.commit()
    await db.refresh(config)

    has_creds = len(config.credentials) > 0
    fingerprint = config.credentials[0].key_fingerprint if has_creds else None

    return ProviderResponse(
        id=config.id,
        workspace_id=config.workspace_id,
        provider_type=config.provider_type,
        display_name=config.display_name,
        is_enabled=config.is_enabled,
        is_default=config.is_default,
        routing_mode=config.routing_mode,
        default_model=config.default_model,
        api_endpoint=config.api_endpoint,
        config_options=config.config_options,
        billing_tier=config.billing_tier,
        has_credentials=has_creds,
        key_fingerprint=fingerprint,
        created_at=config.created_at,
    )
