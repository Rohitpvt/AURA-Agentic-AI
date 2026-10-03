"""Inbound Webhook Gateway and Reactive Event Ingress Service for AURA."""

import hashlib
import hmac
import json
import re
import secrets
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    EntityNotFoundError,
    ValidationError,
)
from app.core.logging import logger
from app.core.security import decrypt_secret, encrypt_secret
from app.db.models.task import Task
from app.db.models.webhook import WebhookDelivery, WebhookEndpoint
from app.schemas.task import TaskCreateRequest
from app.schemas.webhook import (
    WebhookDeliveryResponse,
    WebhookEndpointCreatedResponse,
    WebhookEndpointCreateRequest,
    WebhookEndpointResponse,
    WebhookEndpointUpdateRequest,
    WebhookIngressResult,
)
from app.services.audit_service import audit_service
from app.services.kill_switch import kill_switch
from app.services.task_service import TaskService


def _safe_get_nested(data: Any, path: List[str]) -> Any:
    """Safely traverse a nested dictionary or list without calling attributes or executing code."""
    curr = data
    for part in path:
        # Block dunder / private attribute traversal
        if part.startswith("_"):
            return None
        if isinstance(curr, dict):
            curr = curr.get(part)
        elif isinstance(curr, list) and part.isdigit():
            idx = int(part)
            curr = curr[idx] if 0 <= idx < len(curr) else None
        else:
            return None
        if curr is None:
            return None
    return curr


def hydrate_prompt_template(template: str, payload: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> str:
    """Hydrate prompt template with bounded placeholder substitution.
    
    Supports:
      - {payload.user.name} or {{payload.user.name}}
      - {event.id} or {{event.id}}
    Strictly forbids SSTI, code execution, eval, imports, and reflection.
    """
    ctx = {"payload": payload, "event": context or {}}

    # Pattern matches {expr} or {{expr}}
    pattern = re.compile(r"\{\{?\s*([^{}]+?)\s*\}?\}")

    def replacer(match: re.Match) -> str:
        raw_expr = match.group(1).strip()
        # Only simple dotted identifiers are permitted (e.g. payload.issue.id)
        if not re.match(r"^[a-zA-Z0-9_]+(?:\.[a-zA-Z0-9_]+)*$", raw_expr):
            return ""
        full_path = raw_expr.split(".")
        root = full_path[0]
        if root in ctx:
            val = _safe_get_nested(ctx[root], full_path[1:]) if len(full_path) > 1 else ctx[root]
            if val is not None:
                if isinstance(val, (dict, list)):
                    return json.dumps(val, ensure_ascii=False)
                return str(val)
        return ""

    result = pattern.sub(replacer, template)
    # Enforce maximum hydrated length
    if len(result) > 10000:
        result = result[:10000] + "... [TRUNCATED]"
    return result


class WebhookService:
    """Service managing inbound webhook endpoints, cryptographic HMAC validation, idempotency, and task dispatch."""

    def __init__(self, task_service: Optional[TaskService] = None):
        self.task_service = task_service or TaskService()
        self._rate_limits: Dict[str, List[float]] = {}

    def _check_rate_limit(self, public_id: str, limit_per_minute: int, now_ts: float) -> bool:
        """Sliding-window per-endpoint rate limiter."""
        window = 60.0
        if public_id not in self._rate_limits:
            self._rate_limits[public_id] = []
        cutoff = now_ts - window
        self._rate_limits[public_id] = [t for t in self._rate_limits[public_id] if t > cutoff]
        if len(self._rate_limits[public_id]) >= limit_per_minute:
            return False
        self._rate_limits[public_id].append(now_ts)
        return True

    # ==========================================
    # 1. Endpoint Configuration (CRUD)
    # ==========================================

    async def create_endpoint(
        self,
        db: AsyncSession,
        payload: WebhookEndpointCreateRequest,
        workspace_id: uuid.UUID,
        user_id: Optional[uuid.UUID] = None,
    ) -> WebhookEndpointCreatedResponse:
        """Create a new WebhookEndpoint, generating a secure secret and opaque public ID."""
        raw_secret = f"whsec_{secrets.token_urlsafe(32)}"
        public_id = f"whk_{secrets.token_urlsafe(16)}"
        secret_ciphertext = encrypt_secret(raw_secret)

        endpoint = WebhookEndpoint(
            workspace_id=workspace_id,
            created_by=user_id,
            public_id=public_id,
            name=payload.name,
            description=payload.description,
            secret_ciphertext=secret_ciphertext,
            prompt_template=payload.prompt_template,
            autonomy_level=min(payload.autonomy_level, 4),
            is_active=payload.is_active,
            rate_limit_per_minute=payload.rate_limit_per_minute,
        )
        db.add(endpoint)
        await db.flush()

        await audit_service.record_event(
            db=db,
            workspace_id=workspace_id,
            actor_type="user" if user_id else "system",
            actor_id=str(user_id) if user_id else "system",
            action="webhook.created",
            resource_type="webhook_endpoint",
            resource_id=str(endpoint.id),
            details={"name": endpoint.name, "public_id": public_id},
        )

        base_resp = WebhookEndpointResponse.model_validate(endpoint)
        return WebhookEndpointCreatedResponse(**base_resp.model_dump(), secret=raw_secret)

    async def list_endpoints(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        is_active: Optional[bool] = None,
    ) -> List[WebhookEndpointResponse]:
        """List webhook endpoints for a workspace."""
        stmt = select(WebhookEndpoint).where(
            WebhookEndpoint.workspace_id == workspace_id,
            WebhookEndpoint.deleted_at.is_(None),
        )
        if is_active is not None:
            stmt = stmt.where(WebhookEndpoint.is_active == is_active)
        stmt = stmt.order_by(WebhookEndpoint.created_at.desc())
        res = await db.execute(stmt)
        return [WebhookEndpointResponse.model_validate(ep) for ep in res.scalars().all()]

    async def get_endpoint(
        self,
        db: AsyncSession,
        endpoint_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> WebhookEndpointResponse:
        """Retrieve webhook endpoint metadata."""
        endpoint = await self._get_endpoint_entity(db, endpoint_id, workspace_id)
        return WebhookEndpointResponse.model_validate(endpoint)

    async def update_endpoint(
        self,
        db: AsyncSession,
        endpoint_id: uuid.UUID,
        workspace_id: uuid.UUID,
        payload: WebhookEndpointUpdateRequest,
        user_id: Optional[uuid.UUID] = None,
    ) -> WebhookEndpointResponse:
        """Update webhook endpoint properties."""
        endpoint = await self._get_endpoint_entity(db, endpoint_id, workspace_id)

        if payload.name is not None:
            endpoint.name = payload.name
        if payload.description is not None:
            endpoint.description = payload.description
        if payload.prompt_template is not None:
            endpoint.prompt_template = payload.prompt_template
        if payload.autonomy_level is not None:
            endpoint.autonomy_level = min(payload.autonomy_level, 4)
        if payload.is_active is not None:
            endpoint.is_active = payload.is_active
        if payload.rate_limit_per_minute is not None:
            endpoint.rate_limit_per_minute = payload.rate_limit_per_minute

        await db.flush()
        await audit_service.record_event(
            db=db,
            workspace_id=workspace_id,
            actor_type="user" if user_id else "system",
            actor_id=str(user_id) if user_id else "system",
            action="webhook.updated",
            resource_type="webhook_endpoint",
            resource_id=str(endpoint.id),
            details={"name": endpoint.name, "is_active": endpoint.is_active},
        )
        return WebhookEndpointResponse.model_validate(endpoint)

    async def rotate_secret(
        self,
        db: AsyncSession,
        endpoint_id: uuid.UUID,
        workspace_id: uuid.UUID,
        user_id: Optional[uuid.UUID] = None,
    ) -> WebhookEndpointCreatedResponse:
        """Rotate the cryptographic HMAC secret for a webhook endpoint."""
        endpoint = await self._get_endpoint_entity(db, endpoint_id, workspace_id)
        raw_secret = f"whsec_{secrets.token_urlsafe(32)}"
        endpoint.secret_ciphertext = encrypt_secret(raw_secret)
        await db.flush()

        await audit_service.record_event(
            db=db,
            workspace_id=workspace_id,
            actor_type="user" if user_id else "system",
            actor_id=str(user_id) if user_id else "system",
            action="webhook.secret_rotated",
            resource_type="webhook_endpoint",
            resource_id=str(endpoint.id),
            details={"public_id": endpoint.public_id},
        )

        base_resp = WebhookEndpointResponse.model_validate(endpoint)
        return WebhookEndpointCreatedResponse(**base_resp.model_dump(), secret=raw_secret)

    async def toggle_endpoint(
        self,
        db: AsyncSession,
        endpoint_id: uuid.UUID,
        workspace_id: uuid.UUID,
        is_active: bool,
        user_id: Optional[uuid.UUID] = None,
    ) -> WebhookEndpointResponse:
        """Enable or disable a webhook endpoint."""
        endpoint = await self._get_endpoint_entity(db, endpoint_id, workspace_id)
        endpoint.is_active = is_active
        await db.flush()

        await audit_service.record_event(
            db=db,
            workspace_id=workspace_id,
            actor_type="user" if user_id else "system",
            actor_id=str(user_id) if user_id else "system",
            action="webhook.enabled" if is_active else "webhook.disabled",
            resource_type="webhook_endpoint",
            resource_id=str(endpoint.id),
            details={"is_active": is_active},
        )
        return WebhookEndpointResponse.model_validate(endpoint)

    async def delete_endpoint(
        self,
        db: AsyncSession,
        endpoint_id: uuid.UUID,
        workspace_id: uuid.UUID,
        user_id: Optional[uuid.UUID] = None,
    ) -> None:
        """Soft-delete a webhook endpoint."""
        endpoint = await self._get_endpoint_entity(db, endpoint_id, workspace_id)
        endpoint.deleted_at = datetime.now(timezone.utc)
        endpoint.is_active = False
        await db.flush()

        await audit_service.record_event(
            db=db,
            workspace_id=workspace_id,
            actor_type="user" if user_id else "system",
            actor_id=str(user_id) if user_id else "system",
            action="webhook.deleted",
            resource_type="webhook_endpoint",
            resource_id=str(endpoint.id),
            details={"name": endpoint.name},
        )

    # ==========================================
    # 2. Cryptographic Ingress & Event Processing
    # ==========================================

    async def process_inbound_webhook(
        self,
        db: AsyncSession,
        public_id: str,
        raw_body: bytes,
        headers: Dict[str, str],
    ) -> Tuple[int, WebhookIngressResult]:
        """Process incoming external webhook with cryptographic HMAC, replay defense, and idempotency."""
        now = datetime.now(timezone.utc)

        # 1. Locate Webhook Endpoint by unguessable public_id
        stmt = select(WebhookEndpoint).where(
            WebhookEndpoint.public_id == public_id,
            WebhookEndpoint.deleted_at.is_(None),
        )
        res = await db.execute(stmt)
        endpoint = res.scalar_one_or_none()
        if not endpoint:
            logger.warning(f"WebhookIngress: Unknown endpoint '{public_id}'")
            return 404, WebhookIngressResult(status="rejected", message="Webhook endpoint not found", idempotency_key="")

        if not endpoint.is_active:
            logger.warning(f"WebhookIngress: Endpoint '{public_id}' is disabled")
            return 403, WebhookIngressResult(status="rejected", message="Webhook endpoint is inactive", idempotency_key="")

        # 2. Enforce Sliding-Window Rate Limit
        if not self._check_rate_limit(public_id, endpoint.rate_limit_per_minute, now.timestamp()):
            endpoint.total_failed += 1
            await db.flush()
            logger.warning(f"WebhookIngress: Rate limit exceeded for endpoint '{public_id}'")
            return 429, WebhookIngressResult(status="rejected", message="Rate limit exceeded for endpoint", idempotency_key="")

        # 3. Enforce Payload Size Limit (Max 1MB)
        if len(raw_body) > endpoint.max_payload_bytes:
            endpoint.total_failed += 1
            await db.flush()
            logger.warning(f"WebhookIngress: Payload {len(raw_body)} bytes exceeds max limit {endpoint.max_payload_bytes}")
            return 413, WebhookIngressResult(status="rejected", message="Payload exceeds maximum permitted size", idempotency_key="")

        # 4. Extract & Validate Timestamp
        timestamp_header = headers.get("x-aura-timestamp") or headers.get("x-timestamp")
        if not timestamp_header:
            endpoint.total_failed += 1
            await db.flush()
            return 400, WebhookIngressResult(status="rejected", message="Missing timestamp header", idempotency_key="")

        try:
            req_ts = float(timestamp_header)
            # Replay defense: 300-second freshness window
            if abs(now.timestamp() - req_ts) > 300.0:
                endpoint.total_failed += 1
                await db.flush()
                logger.warning(f"WebhookIngress: Stale timestamp {req_ts} (drift: {abs(now.timestamp() - req_ts):.1f}s)")
                return 400, WebhookIngressResult(status="rejected", message="Timestamp out of bounds (replay protection)", idempotency_key="")
        except (ValueError, TypeError):
            endpoint.total_failed += 1
            await db.flush()
            return 400, WebhookIngressResult(status="rejected", message="Invalid timestamp format", idempotency_key="")

        # 5. Verify HMAC-SHA256 Signature
        raw_secret = decrypt_secret(endpoint.secret_ciphertext)
        signature_header = headers.get("x-aura-signature") or headers.get("x-hub-signature-256")
        if not signature_header:
            endpoint.total_failed += 1
            await db.flush()
            return 401, WebhookIngressResult(status="rejected", message="Missing signature header", idempotency_key="")

        # Strip prefix if present (e.g. 'sha256=...')
        if signature_header.startswith("sha256="):
            actual_sig = signature_header[7:]
        else:
            actual_sig = signature_header

        # Canonical signature computation: HMAC_SHA256(secret, timestamp + "." + raw_body)
        signed_payload = f"{timestamp_header}.".encode("utf-8") + raw_body
        expected_sig = hmac.new(raw_secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()

        if not hmac.compare_digest(actual_sig, expected_sig):
            # Also check raw body only signature as fallback compatibility
            fallback_expected = hmac.new(raw_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(actual_sig, fallback_expected):
                endpoint.total_failed += 1
                await db.flush()
                logger.warning(f"WebhookIngress: Invalid HMAC signature for endpoint '{public_id}'")
                return 401, WebhookIngressResult(status="rejected", message="Invalid cryptographic signature", idempotency_key="")

        # 6. Extract Idempotency Key
        idempotency_key = (
            headers.get("x-aura-idempotency-key")
            or headers.get("x-idempotency-key")
            or headers.get("x-delivery-id")
        )
        payload_hash = hashlib.sha256(raw_body).hexdigest()

        if not idempotency_key:
            # Fallback to deterministic hash of timestamp + body
            idempotency_key = f"wh_{endpoint.id}_{int(req_ts)}_{payload_hash[:16]}"

        # 7. Idempotency Check
        stmt_dup = select(WebhookDelivery).where(
            WebhookDelivery.workspace_id == endpoint.workspace_id,
            WebhookDelivery.webhook_endpoint_id == endpoint.id,
            WebhookDelivery.idempotency_key == idempotency_key,
        )
        res_dup = await db.execute(stmt_dup)
        existing_delivery = res_dup.scalar_one_or_none()

        if existing_delivery:
            if existing_delivery.payload_hash != payload_hash:
                logger.warning(
                    f"WebhookIngress: Idempotency conflict for '{idempotency_key}' (differing payload hash)"
                )
                return 409, WebhookIngressResult(
                    status="conflict",
                    message="Idempotency key collision with differing payload content",
                    idempotency_key=idempotency_key,
                )
            logger.info(f"WebhookIngress: Duplicate delivery '{idempotency_key}' detected")
            return 200, WebhookIngressResult(
                status="duplicate",
                message="Webhook delivery already processed",
                idempotency_key=idempotency_key,
                task_id=existing_delivery.task_id,
            )

        # 7. Parse JSON Payload
        try:
            parsed_json = json.loads(raw_body.decode("utf-8")) if raw_body else {}
        except Exception as e:
            endpoint.total_failed += 1
            await db.flush()
            return 400, WebhookIngressResult(status="rejected", message=f"Invalid JSON payload: {e}", idempotency_key=idempotency_key)

        # 8. Check Emergency Kill Switch
        if kill_switch.is_active(endpoint.workspace_id):
            delivery = WebhookDelivery(
                webhook_endpoint_id=endpoint.id,
                workspace_id=endpoint.workspace_id,
                idempotency_key=idempotency_key,
                received_at=now,
                status="blocked_kill_switch",
                payload_hash=payload_hash,
                error_code="KILL_SWITCH_ACTIVE",
                error_summary="Autonomous execution suspended by Emergency Kill Switch",
            )
            db.add(delivery)
            endpoint.total_received += 1
            endpoint.last_received_at = now
            await db.flush()

            await audit_service.record_event(
                db=db,
                workspace_id=endpoint.workspace_id,
                actor_type="webhook",
                actor_id=endpoint.public_id,
                action="webhook.blocked_kill_switch",
                resource_type="webhook_delivery",
                resource_id=str(delivery.id),
                details={"idempotency_key": idempotency_key},
            )
            return 503, WebhookIngressResult(
                status="blocked",
                message="Execution suspended by Emergency Kill Switch",
                idempotency_key=idempotency_key,
            )

        # 9. Hydrate Prompt Template & Construct Structured Prompt with Untrusted Boundary
        hydrated_user_prompt = hydrate_prompt_template(endpoint.prompt_template, parsed_json)

        structured_task_goal = f"""[SYSTEM: UNTRUSTED WEBHOOK INGRESS EVENT]
Source Webhook: {endpoint.name} (Endpoint: {endpoint.public_id})
Received Timestamp: {now.isoformat()}
Authentication: HMAC-SHA256 VERIFIED
Security Classification: UNTRUSTED_EXTERNAL_INPUT (is_untrusted_content = True)

[USER TASK OBJECTIVE]
{hydrated_user_prompt}

[RAW WEBHOOK PAYLOAD (UNTRUSTED DATA)]
```json
{json.dumps(parsed_json, indent=2, ensure_ascii=False)[:4000]}
```
[END UNTRUSTED WEBHOOK DATA]"""

        # 10. Dispatch Governed Task via TaskService
        task_payload = TaskCreateRequest(
            workspace_id=endpoint.workspace_id,
            title=f"Webhook: {endpoint.name}",
            goal=structured_task_goal,
            autonomy_level=min(endpoint.autonomy_level, 4),
            timeout_seconds=300,  # 5 minutes L4 ceiling
            budget_max_tokens=4000,
            idempotency_key=f"wh_task_{endpoint.id}_{idempotency_key}",
        )

        task_resp = await self.task_service.create_task(
            db=db,
            payload=task_payload,
            user_id=endpoint.created_by,
        )

        # 11. Record Delivery Receipt & Update Telemetry
        delivery = WebhookDelivery(
            webhook_endpoint_id=endpoint.id,
            workspace_id=endpoint.workspace_id,
            idempotency_key=idempotency_key,
            received_at=now,
            status="dispatched",
            task_id=task_resp.id,
            payload_hash=payload_hash,
        )
        db.add(delivery)
        endpoint.total_received += 1
        endpoint.last_received_at = now
        await db.flush()

        await audit_service.record_event(
            db=db,
            workspace_id=endpoint.workspace_id,
            actor_type="webhook",
            actor_id=endpoint.public_id,
            action="webhook.task_dispatched",
            resource_type="webhook_delivery",
            resource_id=str(delivery.id),
            details={"task_id": str(task_resp.id), "idempotency_key": idempotency_key},
        )

        return 200, WebhookIngressResult(
            status="accepted",
            message="Webhook authenticated and governed task dispatched",
            idempotency_key=idempotency_key,
            task_id=task_resp.id,
        )

    async def list_deliveries(
        self,
        db: AsyncSession,
        endpoint_id: uuid.UUID,
        workspace_id: uuid.UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> List[WebhookDeliveryResponse]:
        """List delivery receipts for an endpoint."""
        await self._get_endpoint_entity(db, endpoint_id, workspace_id)
        stmt = (
            select(WebhookDelivery)
            .where(
                WebhookDelivery.webhook_endpoint_id == endpoint_id,
                WebhookDelivery.workspace_id == workspace_id,
            )
            .order_by(WebhookDelivery.received_at.desc())
            .limit(limit)
            .offset(offset)
        )
        res = await db.execute(stmt)
        return [WebhookDeliveryResponse.model_validate(d) for d in res.scalars().all()]

    async def _get_endpoint_entity(
        self,
        db: AsyncSession,
        endpoint_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> WebhookEndpoint:
        """Fetch endpoint enforcing workspace boundary."""
        stmt = select(WebhookEndpoint).where(
            WebhookEndpoint.id == endpoint_id,
            WebhookEndpoint.workspace_id == workspace_id,
            WebhookEndpoint.deleted_at.is_(None),
        )
        res = await db.execute(stmt)
        ep = res.scalar_one_or_none()
        if not ep:
            raise EntityNotFoundError("WebhookEndpoint", str(endpoint_id))
        return ep


webhook_service = WebhookService()
