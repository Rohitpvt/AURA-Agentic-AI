"""Inbound Webhook API Endpoints: Management & Public Ingress."""

import uuid
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_workspace_membership
from app.core.logging import logger
from app.db.models.user import User
from app.db.session import get_db_session
from app.schemas.webhook import (
    WebhookDeliveryResponse,
    WebhookEndpointCreatedResponse,
    WebhookEndpointCreateRequest,
    WebhookEndpointResponse,
    WebhookEndpointUpdateRequest,
    WebhookIngressResult,
)
from app.services.automations.webhook_service import webhook_service

router = APIRouter()


class ToggleWebhookRequest(BaseModel):
    is_active: bool


# ==========================================
# 1. Webhook Management Endpoints (Auth Required)
# ==========================================

@router.post("", response_model=WebhookEndpointCreatedResponse, status_code=status.HTTP_201_CREATED)
async def create_webhook_endpoint(
    payload: WebhookEndpointCreateRequest,
    workspace_id: uuid.UUID = Query(..., description="Target Workspace UUID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> WebhookEndpointCreatedResponse:
    """Create a new Webhook Endpoint configuration with a cryptographically generated secret."""
    await get_workspace_membership(workspace_id=workspace_id, user_id=current_user.id, db=db)
    return await webhook_service.create_endpoint(
        db=db,
        payload=payload,
        workspace_id=workspace_id,
        user_id=current_user.id,
    )


@router.get("", response_model=List[WebhookEndpointResponse])
async def list_webhook_endpoints(
    workspace_id: uuid.UUID = Query(..., description="Target Workspace UUID"),
    is_active: Optional[bool] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[WebhookEndpointResponse]:
    """List webhook endpoints for a workspace."""
    await get_workspace_membership(workspace_id=workspace_id, user_id=current_user.id, db=db)
    return await webhook_service.list_endpoints(
        db=db,
        workspace_id=workspace_id,
        is_active=is_active,
    )


@router.get("/{endpoint_id}", response_model=WebhookEndpointResponse)
async def get_webhook_endpoint(
    endpoint_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(..., description="Target Workspace UUID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> WebhookEndpointResponse:
    """Retrieve webhook endpoint metadata."""
    await get_workspace_membership(workspace_id=workspace_id, user_id=current_user.id, db=db)
    return await webhook_service.get_endpoint(
        db=db,
        endpoint_id=endpoint_id,
        workspace_id=workspace_id,
    )


@router.patch("/{endpoint_id}", response_model=WebhookEndpointResponse)
async def update_webhook_endpoint(
    endpoint_id: uuid.UUID,
    payload: WebhookEndpointUpdateRequest,
    workspace_id: uuid.UUID = Query(..., description="Target Workspace UUID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> WebhookEndpointResponse:
    """Update webhook endpoint properties."""
    await get_workspace_membership(workspace_id=workspace_id, user_id=current_user.id, db=db)
    return await webhook_service.update_endpoint(
        db=db,
        endpoint_id=endpoint_id,
        workspace_id=workspace_id,
        payload=payload,
        user_id=current_user.id,
    )


@router.post("/{endpoint_id}/rotate-secret", response_model=WebhookEndpointCreatedResponse)
async def rotate_webhook_secret(
    endpoint_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(..., description="Target Workspace UUID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> WebhookEndpointCreatedResponse:
    """Rotate the HMAC secret for a webhook endpoint."""
    await get_workspace_membership(workspace_id=workspace_id, user_id=current_user.id, db=db)
    return await webhook_service.rotate_secret(
        db=db,
        endpoint_id=endpoint_id,
        workspace_id=workspace_id,
        user_id=current_user.id,
    )


@router.post("/{endpoint_id}/toggle", response_model=WebhookEndpointResponse)
async def toggle_webhook_endpoint(
    endpoint_id: uuid.UUID,
    payload: ToggleWebhookRequest,
    workspace_id: uuid.UUID = Query(..., description="Target Workspace UUID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> WebhookEndpointResponse:
    """Enable or disable a webhook endpoint."""
    await get_workspace_membership(workspace_id=workspace_id, user_id=current_user.id, db=db)
    return await webhook_service.toggle_endpoint(
        db=db,
        endpoint_id=endpoint_id,
        workspace_id=workspace_id,
        is_active=payload.is_active,
        user_id=current_user.id,
    )


@router.delete("/{endpoint_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook_endpoint(
    endpoint_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(..., description="Target Workspace UUID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """Soft-delete a webhook endpoint."""
    await get_workspace_membership(workspace_id=workspace_id, user_id=current_user.id, db=db)
    await webhook_service.delete_endpoint(
        db=db,
        endpoint_id=endpoint_id,
        workspace_id=workspace_id,
        user_id=current_user.id,
    )


@router.get("/{endpoint_id}/deliveries", response_model=List[WebhookDeliveryResponse])
async def list_webhook_deliveries(
    endpoint_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(..., description="Target Workspace UUID"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[WebhookDeliveryResponse]:
    """Retrieve delivery history receipts for a webhook endpoint."""
    await get_workspace_membership(workspace_id=workspace_id, user_id=current_user.id, db=db)
    return await webhook_service.list_deliveries(
        db=db,
        endpoint_id=endpoint_id,
        workspace_id=workspace_id,
        limit=limit,
        offset=offset,
    )


# ==========================================
# 2. Public Ingress Endpoint (No User Auth)
# ==========================================

@router.post("/ingress/{public_id}", response_model=WebhookIngressResult)
async def ingress_webhook(
    public_id: str,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db_session),
) -> WebhookIngressResult:
    """Public Inbound Webhook Ingress Gateway.
    
    Verifies HMAC-SHA256 signature, enforces timestamp freshness (300s),
    applies idempotency deduplication, marks payload untrusted,
    hydrates task prompt template, and creates a governed AURA task.
    """
    raw_body = await request.body()
    headers_dict = {k.lower(): v for k, v in request.headers.items()}

    status_code, result = await webhook_service.process_inbound_webhook(
        db=db,
        public_id=public_id,
        raw_body=raw_body,
        headers=headers_dict,
    )
    response.status_code = status_code
    return result
