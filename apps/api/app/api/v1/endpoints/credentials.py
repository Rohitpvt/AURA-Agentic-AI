"""Encrypted BYOK Credential Vault Endpoints."""

import uuid
from datetime import datetime, timezone
from typing import List
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_current_user, get_workspace_membership
from app.core.errors import AuthorizationError, EntityNotFoundError, ModelUnavailableError
from app.core.logging import logger
from app.core.security import decrypt_secret, encrypt_secret, generate_key_fingerprint
from app.db.models.provider import Credential, ProviderConfiguration
from app.db.models.user import User
from app.db.session import get_db_session
from app.schemas.provider import (
    CredentialCreateRequest,
    CredentialMetadataResponse,
)
from app.services.providers.gemini_provider import GeminiProvider
from app.services.providers.router import model_router

router = APIRouter()


@router.post("", response_model=CredentialMetadataResponse, status_code=status.HTTP_201_CREATED)
async def enroll_credential(
    payload: CredentialCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> CredentialMetadataResponse:
    """Securely enroll and encrypt a BYOK API key (Plaintext is NEVER returned or logged)."""
    member = await get_workspace_membership(payload.workspace_id, current_user, db)
    if member.role not in ["owner", "admin"]:
        raise AuthorizationError("Only workspace Owners and Admins can enroll BYOK credentials")

    # Check provider configuration exists
    res = await db.execute(
        select(ProviderConfiguration).where(
            ProviderConfiguration.id == payload.provider_config_id,
            ProviderConfiguration.workspace_id == payload.workspace_id,
            ProviderConfiguration.deleted_at.is_(None),
        )
    )
    provider_config = res.scalar_one_or_none()
    if not provider_config:
        raise EntityNotFoundError("ProviderConfiguration", str(payload.provider_config_id))

    # Test & Validate Key if Gemini
    is_valid = True
    validation_error = None
    if provider_config.provider_type == "gemini":
        gemini_probe = GeminiProvider(api_key=payload.secret, base_url=provider_config.api_endpoint)
        is_valid = await gemini_probe.validate_credentials()
        if not is_valid:
            logger.warning(f"Google Gemini key validation failed for workspace {payload.workspace_id}")
            validation_error = "Google Gemini API key validation failed (check key permissions or restrictions)"

    # Encrypt secret using AES-256-GCM
    encrypted_secret = encrypt_secret(payload.secret)
    fingerprint = generate_key_fingerprint(payload.secret)

    # Check if credential already exists for this provider config
    existing_res = await db.execute(
        select(Credential).where(
            Credential.provider_config_id == payload.provider_config_id,
            Credential.credential_type == payload.credential_type,
        )
    )
    cred = existing_res.scalar_one_or_none()
    if cred:
        cred.encrypted_secret = encrypted_secret
        cred.key_fingerprint = fingerprint
        cred.is_valid = is_valid
        cred.last_validated_at = datetime.now(timezone.utc)
        cred.last_validation_error = validation_error
    else:
        cred = Credential(
            workspace_id=payload.workspace_id,
            provider_config_id=payload.provider_config_id,
            credential_type=payload.credential_type,
            encrypted_secret=encrypted_secret,
            key_fingerprint=fingerprint,
            is_valid=is_valid,
            last_validated_at=datetime.now(timezone.utc),
            last_validation_error=validation_error,
        )
        db.add(cred)

    await db.commit()
    await db.refresh(cred)

    # Register live adapter in ModelRouter if valid
    if is_valid and provider_config.provider_type == "gemini":
        model_router.register_provider(
            "gemini",
            GeminiProvider(api_key=payload.secret, base_url=provider_config.api_endpoint),
        )

    logger.info(
        f"Enrolled encrypted credential for provider {provider_config.provider_type} in workspace {payload.workspace_id} (Fingerprint: {fingerprint})"
    )

    return CredentialMetadataResponse(
        id=cred.id,
        workspace_id=cred.workspace_id,
        provider_config_id=cred.provider_config_id,
        credential_type=cred.credential_type,
        key_fingerprint=cred.key_fingerprint,
        is_valid=cred.is_valid,
        last_validated_at=cred.last_validated_at,
        last_validation_error=cred.last_validation_error,
        created_at=cred.created_at,
    )


@router.get("", response_model=List[CredentialMetadataResponse])
async def list_credentials(
    workspace_id: uuid.UUID = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> List[CredentialMetadataResponse]:
    """List registered credential metadata (Key fingerprints and status ONLY; secrets are NEVER returned)."""
    await get_workspace_membership(workspace_id, current_user, db)

    res = await db.execute(select(Credential).where(Credential.workspace_id == workspace_id))
    creds = res.scalars().all()

    return [
        CredentialMetadataResponse(
            id=c.id,
            workspace_id=c.workspace_id,
            provider_config_id=c.provider_config_id,
            credential_type=c.credential_type,
            key_fingerprint=c.key_fingerprint,
            is_valid=c.is_valid,
            last_validated_at=c.last_validated_at,
            last_validation_error=c.last_validation_error,
            created_at=c.created_at,
        )
        for c in creds
    ]


@router.delete("/{id}", status_code=status.HTTP_200_OK)
async def revoke_credential(
    id: uuid.UUID,
    workspace_id: uuid.UUID = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """Revoke and permanently delete an encrypted credential."""
    member = await get_workspace_membership(workspace_id, current_user, db)
    if member.role not in ["owner", "admin"]:
        raise AuthorizationError("Only workspace Owners and Admins can revoke credentials")

    res = await db.execute(
        select(Credential).where(Credential.id == id, Credential.workspace_id == workspace_id)
    )
    cred = res.scalar_one_or_none()
    if not cred:
        raise EntityNotFoundError("Credential", str(id))

    await db.delete(cred)
    await db.commit()

    # Remove provider from router
    model_router.remove_provider("gemini")
    logger.info(f"Revoked and purged credential {id} from workspace {workspace_id}")

    return {"success": True, "message": "Credential revoked and deleted successfully"}
