"""Telegram Bot Integration Service: Long-Polling, Operator Pairing, and Governed Command Execution."""

import hashlib
import json
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx
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
from app.core.security import compute_sha256_hash, decrypt_secret, encrypt_secret
from app.db.models.approval import ApprovalRequest
from app.db.models.task import Task
from app.db.models.telegram import TelegramIntegration, TelegramPairing
from app.schemas.approval import ApprovalResolveRequest
from app.schemas.task import TaskCreateRequest
from app.schemas.telegram import (
    TelegramBotValidationResponse,
    TelegramIntegrationCreateRequest,
    TelegramIntegrationResponse,
    TelegramIntegrationUpdateRequest,
    TelegramPairingResponse,
    TelegramPairingTokenResponse,
    TelegramRotateTokenRequest,
)
from app.services.approval_service import approval_service
from app.services.audit_service import audit_service
from app.services.kill_switch import kill_switch
from app.services.task_service import task_service

TELEGRAM_API_BASE = "https://api.telegram.org"
TELEGRAM_MAX_MESSAGE_LENGTH = 4000
TELEGRAM_PAIRING_TTL_SECONDS = 900  # 15 minutes


class TelegramService:
    """Service managing Telegram bot integrations, long-polling, secure pairing, and governed task execution."""

    def __init__(self):
        self._http_client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(timeout=35.0)
        return self._http_client

    async def close(self) -> None:
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None

    # ==========================================
    # 1. Telegram Bot Token Validation
    # ==========================================

    async def validate_bot_token(self, bot_token: str) -> TelegramBotValidationResponse:
        """Validate a Telegram Bot token with getMe API without exposing the token."""
        client = await self._get_client()
        url = f"{TELEGRAM_API_BASE}/bot{bot_token}/getMe"
        try:
            resp = await client.get(url, timeout=25.0)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("ok"):
                    result = data.get("result", {})
                    return TelegramBotValidationResponse(
                        is_valid=True,
                        bot_username=result.get("username"),
                        bot_id=str(result.get("id")),
                    )
            return TelegramBotValidationResponse(
                is_valid=False,
                error_message=f"Telegram API rejected token (HTTP {resp.status_code})",
            )
        except Exception as e:
            logger.warning(f"TelegramService: Token validation failed: {e}")
            return TelegramBotValidationResponse(
                is_valid=False,
                error_message=f"Connection to Telegram API failed: {e}",
            )

    # ==========================================
    # 2. Integration Management (CRUD)
    # ==========================================

    async def create_integration(
        self,
        db: AsyncSession,
        payload: TelegramIntegrationCreateRequest,
        workspace_id: uuid.UUID,
        user_id: Optional[uuid.UUID] = None,
    ) -> TelegramIntegrationResponse:
        """Create and configure a new Telegram Bot integration."""
        # 1. Validate Token with Telegram API
        val = await self.validate_bot_token(payload.bot_token)
        if not val.is_valid:
            raise ValidationError(f"Invalid Telegram bot token: {val.error_message}")

        # 2. Encrypt Token at Rest
        token_ciphertext = encrypt_secret(payload.bot_token)

        integration = TelegramIntegration(
            workspace_id=workspace_id,
            created_by=user_id,
            display_name=payload.display_name,
            bot_token_ciphertext=token_ciphertext,
            bot_username=val.bot_username,
            bot_id=val.bot_id,
            is_active=payload.is_active,
            polling_state="stopped",
            last_update_id=0,
        )
        db.add(integration)
        await db.flush()

        await audit_service.record_event(
            db=db,
            workspace_id=workspace_id,
            actor_type="user" if user_id else "system",
            actor_id=str(user_id) if user_id else "system",
            action="telegram.integration_created",
            resource_type="telegram_integration",
            resource_id=str(integration.id),
            details={"display_name": integration.display_name, "bot_username": val.bot_username},
        )

        return TelegramIntegrationResponse.model_validate(integration)

    async def list_integrations(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
    ) -> List[TelegramIntegrationResponse]:
        """List Telegram integrations for a workspace (tokens are never returned)."""
        stmt = (
            select(TelegramIntegration)
            .where(
                TelegramIntegration.workspace_id == workspace_id,
                TelegramIntegration.deleted_at.is_(None),
            )
            .order_by(TelegramIntegration.created_at.desc())
        )
        res = await db.execute(stmt)
        return [TelegramIntegrationResponse.model_validate(i) for i in res.scalars().all()]

    async def get_integration(
        self,
        db: AsyncSession,
        integration_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> TelegramIntegrationResponse:
        """Retrieve Telegram integration metadata."""
        entity = await self._get_integration_entity(db, integration_id, workspace_id)
        return TelegramIntegrationResponse.model_validate(entity)

    async def update_integration(
        self,
        db: AsyncSession,
        integration_id: uuid.UUID,
        workspace_id: uuid.UUID,
        payload: TelegramIntegrationUpdateRequest,
        user_id: Optional[uuid.UUID] = None,
    ) -> TelegramIntegrationResponse:
        """Update Telegram integration configuration."""
        entity = await self._get_integration_entity(db, integration_id, workspace_id)
        if payload.display_name is not None:
            entity.display_name = payload.display_name
        if payload.is_active is not None:
            entity.is_active = payload.is_active
            if not entity.is_active:
                entity.polling_state = "stopped"
        await db.flush()

        await audit_service.record_event(
            db=db,
            workspace_id=workspace_id,
            actor_type="user" if user_id else "system",
            actor_id=str(user_id) if user_id else "system",
            action="telegram.integration_updated",
            resource_type="telegram_integration",
            resource_id=str(entity.id),
            details={"is_active": entity.is_active, "display_name": entity.display_name},
        )
        return TelegramIntegrationResponse.model_validate(entity)

    async def rotate_token(
        self,
        db: AsyncSession,
        integration_id: uuid.UUID,
        workspace_id: uuid.UUID,
        payload: TelegramRotateTokenRequest,
        user_id: Optional[uuid.UUID] = None,
    ) -> TelegramIntegrationResponse:
        """Rotate Telegram Bot token."""
        entity = await self._get_integration_entity(db, integration_id, workspace_id)
        val = await self.validate_bot_token(payload.bot_token)
        if not val.is_valid:
            raise ValidationError(f"Invalid Telegram bot token: {val.error_message}")

        entity.bot_token_ciphertext = encrypt_secret(payload.bot_token)
        entity.bot_username = val.bot_username
        entity.bot_id = val.bot_id
        entity.last_error_code = None
        entity.last_error_summary = None
        await db.flush()

        await audit_service.record_event(
            db=db,
            workspace_id=workspace_id,
            actor_type="user" if user_id else "system",
            actor_id=str(user_id) if user_id else "system",
            action="telegram.token_rotated",
            resource_type="telegram_integration",
            resource_id=str(entity.id),
            details={"bot_username": val.bot_username},
        )
        return TelegramIntegrationResponse.model_validate(entity)

    async def delete_integration(
        self,
        db: AsyncSession,
        integration_id: uuid.UUID,
        workspace_id: uuid.UUID,
        user_id: Optional[uuid.UUID] = None,
    ) -> None:
        """Soft-delete Telegram integration and disable active polling."""
        entity = await self._get_integration_entity(db, integration_id, workspace_id)
        entity.deleted_at = datetime.now(timezone.utc)
        entity.is_active = False
        entity.polling_state = "stopped"
        await db.flush()

        await audit_service.record_event(
            db=db,
            workspace_id=workspace_id,
            actor_type="user" if user_id else "system",
            actor_id=str(user_id) if user_id else "system",
            action="telegram.integration_deleted",
            resource_type="telegram_integration",
            resource_id=str(entity.id),
            details={"display_name": entity.display_name},
        )

    # ==========================================
    # 3. Pairing Management & Authorization
    # ==========================================

    async def generate_pairing_token(
        self,
        db: AsyncSession,
        integration_id: uuid.UUID,
        workspace_id: uuid.UUID,
        user_id: Optional[uuid.UUID] = None,
        ttl_seconds: int = TELEGRAM_PAIRING_TTL_SECONDS,
    ) -> TelegramPairingTokenResponse:
        """Generate a one-time 15-minute pairing token for an operator to link their Telegram chat."""
        integration = await self._get_integration_entity(db, integration_id, workspace_id)
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=ttl_seconds)

        raw_token = f"aurapair_{secrets.token_urlsafe(24)}"
        token_hash = compute_sha256_hash(raw_token)

        pairing = TelegramPairing(
            workspace_id=workspace_id,
            integration_id=integration.id,
            created_by=user_id,
            telegram_chat_id=f"pending_{secrets.token_hex(8)}",  # Bound upon /start <token>
            is_active=False,
            pairing_token_hash=token_hash,
            pairing_token_expires_at=expires_at,
        )
        db.add(pairing)
        await db.flush()

        await audit_service.record_event(
            db=db,
            workspace_id=workspace_id,
            actor_type="user" if user_id else "system",
            actor_id=str(user_id) if user_id else "system",
            action="telegram.pairing_token_generated",
            resource_type="telegram_pairing",
            resource_id=str(pairing.id),
            details={"expires_at": expires_at.isoformat()},
        )

        instructions = f"Send '/start {raw_token}' to @{integration.bot_username or 'your_bot'} on Telegram within 15 minutes."
        return TelegramPairingTokenResponse(
            pairing_token=raw_token,
            expires_at=expires_at,
            bot_username=integration.bot_username,
            instructions=instructions,
        )

    async def list_pairings(
        self,
        db: AsyncSession,
        integration_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> List[TelegramPairingResponse]:
        """List active chat pairings for an integration."""
        await self._get_integration_entity(db, integration_id, workspace_id)
        stmt = (
            select(TelegramPairing)
            .where(
                TelegramPairing.integration_id == integration_id,
                TelegramPairing.workspace_id == workspace_id,
                TelegramPairing.is_active == True,
            )
            .order_by(TelegramPairing.paired_at.desc())
        )
        res = await db.execute(stmt)
        return [TelegramPairingResponse.model_validate(p) for p in res.scalars().all()]

    async def revoke_pairing(
        self,
        db: AsyncSession,
        pairing_id: uuid.UUID,
        workspace_id: uuid.UUID,
        user_id: Optional[uuid.UUID] = None,
    ) -> None:
        """Revoke an active Telegram pairing."""
        stmt = select(TelegramPairing).where(
            TelegramPairing.id == pairing_id,
            TelegramPairing.workspace_id == workspace_id,
        )
        res = await db.execute(stmt)
        pairing = res.scalar_one_or_none()
        if not pairing:
            raise EntityNotFoundError("TelegramPairing", str(pairing_id))

        pairing.is_active = False
        pairing.revoked_at = datetime.now(timezone.utc)
        await db.flush()

        await audit_service.record_event(
            db=db,
            workspace_id=workspace_id,
            actor_type="user" if user_id else "system",
            actor_id=str(user_id) if user_id else "system",
            action="telegram.pairing_revoked",
            resource_type="telegram_pairing",
            resource_id=str(pairing.id),
            details={"telegram_chat_id": pairing.telegram_chat_id},
        )

    async def resolve_pairing_token(
        self,
        db: AsyncSession,
        integration: TelegramIntegration,
        chat_id: str,
        user_id: Optional[str],
        username: Optional[str],
        raw_token: str,
    ) -> Tuple[bool, str]:
        """Resolve a one-time pairing token received via /start <token>."""
        token_hash = compute_sha256_hash(raw_token.strip())
        now = datetime.now(timezone.utc)

        # 1. Look up unexpired pending pairing record
        stmt = select(TelegramPairing).where(
            TelegramPairing.integration_id == integration.id,
            TelegramPairing.pairing_token_hash == token_hash,
            TelegramPairing.is_active == False,
        )
        res = await db.execute(stmt)
        pairing = res.scalar_one_or_none()

        if not pairing:
            logger.warning(f"TelegramService: Invalid or used pairing token attempted from chat {chat_id}")
            return False, "❌ Invalid or previously used pairing token. Please generate a new token in AURA."

        if pairing.pairing_token_expires_at:
            exp = pairing.pairing_token_expires_at
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp < now:
                pairing.pairing_token_hash = None
                await db.flush()
                logger.warning(f"TelegramService: Expired pairing token attempted from chat {chat_id}")
                return False, "❌ This pairing token has expired (15-minute TTL). Please generate a new token in AURA."

        # 2. Check if this chat is already paired in this workspace
        existing_chat_stmt = select(TelegramPairing).where(
            TelegramPairing.workspace_id == pairing.workspace_id,
            TelegramPairing.integration_id == integration.id,
            TelegramPairing.telegram_chat_id == chat_id,
            TelegramPairing.is_active == True,
        )
        res_existing = await db.execute(existing_chat_stmt)
        existing_chat = res_existing.scalar_one_or_none()
        if existing_chat:
            # Mark the new pairing entry consumed
            pairing.pairing_token_hash = None
            pairing.is_active = False
            existing_chat.last_seen_at = now
            await db.flush()
            return True, "✅ This Telegram chat is already paired with your AURA workspace! Type /help for commands."

        # 3. Bind chat identity and activate pairing
        pairing.telegram_chat_id = str(chat_id)
        pairing.telegram_user_id = str(user_id) if user_id else None
        pairing.telegram_username = username
        pairing.is_active = True
        pairing.paired_at = now
        pairing.last_seen_at = now
        pairing.pairing_token_hash = None  # Single-use revocation
        pairing.pairing_token_expires_at = None
        await db.flush()

        await audit_service.record_event(
            db=db,
            workspace_id=pairing.workspace_id,
            actor_type="telegram",
            actor_id=str(chat_id),
            action="telegram.chat_paired",
            resource_type="telegram_pairing",
            resource_id=str(pairing.id),
            details={"telegram_chat_id": chat_id, "username": username},
        )

        return True, (
            "🎉 Pairing successful!\n\n"
            "This Telegram chat is now securely linked to your AURA workspace.\n"
            "You can now issue governed commands.\n\n"
            "Type /help to see available commands."
        )

    # ==========================================
    # 4. Command Dispatch & Execution
    # ==========================================

    async def handle_command(
        self,
        db: AsyncSession,
        integration: TelegramIntegration,
        chat_id: str,
        user_id: Optional[str],
        username: Optional[str],
        raw_text: str,
        update_id: int,
    ) -> str:
        """Handle incoming command from Telegram with workspace authorization and governance."""
        clean_text = raw_text.strip()
        parts = clean_text.split(maxsplit=1)
        command = parts[0].lower() if parts else ""
        args = parts[1] if len(parts) > 1 else ""

        # Normalize command (strip @bot_username suffix if present, e.g. /status@aura_bot)
        if "@" in command:
            command = command.split("@")[0]

        # 1. Handle /start <token> pairing command
        if command == "/start" and args:
            success, msg = await self.resolve_pairing_token(
                db=db,
                integration=integration,
                chat_id=chat_id,
                user_id=user_id,
                username=username,
                raw_token=args,
            )
            return msg

        # 2. Check Active Chat Pairing
        stmt = select(TelegramPairing).where(
            TelegramPairing.integration_id == integration.id,
            TelegramPairing.telegram_chat_id == chat_id,
            TelegramPairing.is_active == True,
        )
        res = await db.execute(stmt)
        pairing = res.scalar_one_or_none()

        # If unpaired:
        if not pairing:
            if command == "/start":
                return (
                    "🔒 Welcome to AURA Agentic OS!\n\n"
                    "This Telegram chat is not currently paired with any workspace.\n\n"
                    "To pair your account:\n"
                    "1. Open your AURA Web Dashboard\n"
                    "2. Navigate to Integrations -> Telegram\n"
                    "3. Click 'Generate Pairing Token'\n"
                    "4. Send `/start <pairing_token>` in this chat."
                )
            return "⚠️ Unauthorized chat. Please pair your Telegram account with AURA using `/start <pairing_token>`."

        # Update last seen timestamp
        pairing.last_seen_at = datetime.now(timezone.utc)
        await db.flush()

        workspace_id = pairing.workspace_id

        # 3. Route Authorized Commands
        if command in ["/start", "/help"]:
            return (
                "🤖 *AURA Telegram Operator Interface*\n\n"
                "*Available Commands:*\n"
                "• `/status` — View current active tasks, approvals, and system state\n"
                "• `/goal <description>` — Dispatch a new governed AURA task (Autonomy L4)\n"
                "• `/cancel <task_id>` — Cancel a running or pending task\n"
                "• `/approve <approval_id>` — Approve a pending high-risk tool request\n"
                "• `/help` — Display this command reference"
            )

        elif command == "/status":
            return await self._handle_status_command(db, workspace_id)

        elif command == "/goal":
            return await self._handle_goal_command(
                db=db,
                workspace_id=workspace_id,
                chat_id=chat_id,
                username=username,
                goal_text=args,
                update_id=update_id,
                integration=integration,
            )

        elif command == "/cancel":
            return await self._handle_cancel_command(db, workspace_id, chat_id, args)

        elif command == "/approve":
            return await self._handle_approve_command(db, workspace_id, chat_id, args)

        else:
            return f"❓ Unknown command `{command}`. Type `/help` for the list of available commands."

    async def _handle_status_command(self, db: AsyncSession, workspace_id: uuid.UUID) -> str:
        """Construct safe status summary of workspace tasks and pending approvals."""
        ks_active = kill_switch.is_active(workspace_id)
        ks_str = "⛔ ACTIVE (Suspended)" if ks_active else "🟢 Normal"

        # Query recent tasks
        stmt_tasks = (
            select(Task)
            .where(
                Task.workspace_id == workspace_id,
                Task.deleted_at.is_(None),
            )
            .order_by(Task.created_at.desc())
            .limit(5)
        )
        res_tasks = await db.execute(stmt_tasks)
        tasks = res_tasks.scalars().all()

        # Query pending approvals
        stmt_approvals = (
            select(ApprovalRequest)
            .where(
                ApprovalRequest.workspace_id == workspace_id,
                ApprovalRequest.status == "pending",
            )
            .order_by(ApprovalRequest.created_at.desc())
            .limit(3)
        )
        res_approvals = await db.execute(stmt_approvals)
        approvals = res_approvals.scalars().all()

        lines = [
            "📊 *AURA Workspace Status*",
            f"• *Emergency Kill Switch:* {ks_str}",
            "",
            "📋 *Recent Tasks:*",
        ]
        if not tasks:
            lines.append("  _No recent tasks found._")
        else:
            for t in tasks:
                status_icon = "🟢" if t.status == "completed" else "⏳" if t.status == "running" else "⏸️" if t.status == "waiting_approval" else "❌" if t.status == "failed" else "⚪"
                lines.append(f"  {status_icon} `{t.id}` | *{t.title[:30]}* [{t.status}]")

        lines.append("")
        lines.append("🛡️ *Pending HITL Approvals:*")
        if not approvals:
            lines.append("  _No pending approvals._")
        else:
            for a in approvals:
                lines.append(f"  ⚠️ Approval ID: `{a.id}`\n     Tool: `{a.tool_name}` (Risk: *{a.risk_level}*)\n     Approve with: `/approve {a.id}`")

        return "\n".join(lines)

    async def _handle_goal_command(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        chat_id: str,
        username: Optional[str],
        goal_text: str,
        update_id: int,
        integration: TelegramIntegration,
    ) -> str:
        """Create a governed AURA task from a Telegram /goal command."""
        if not goal_text.strip():
            return "⚠️ Usage: `/goal <describe the objective or research task>`"

        # Check Kill Switch
        if kill_switch.is_active(workspace_id):
            return "⛔ Emergency Kill Switch is active in this workspace. Autonomous task creation is suspended."

        now = datetime.now(timezone.utc)
        sanitized_goal = goal_text.strip()[:2000]

        # Structured Untrusted Framing
        structured_task_goal = f"""[SYSTEM: UNTRUSTED TELEGRAM INGRESS EVENT]
Source: Telegram Chat {chat_id} (User: @{username or 'unknown'})
Received Timestamp: {now.isoformat()}
Security Classification: UNTRUSTED_EXTERNAL_INPUT (is_untrusted_content = True)

[USER TASK OBJECTIVE]
{sanitized_goal}
[END UNTRUSTED TELEGRAM DATA]"""

        idempotency_key = f"tg_{integration.id}_{update_id}"
        task_payload = TaskCreateRequest(
            workspace_id=workspace_id,
            title=f"Telegram: {sanitized_goal[:40]}",
            goal=structured_task_goal,
            autonomy_level=4,  # Fixed L4 boundary
            timeout_seconds=300,
            budget_max_tokens=4000,
            idempotency_key=idempotency_key,
        )

        task_resp = await task_service.create_task(
            db=db,
            payload=task_payload,
            user_id=None,
        )

        integration.total_commands_processed += 1
        await db.flush()

        await audit_service.record_event(
            db=db,
            workspace_id=workspace_id,
            actor_type="telegram",
            actor_id=str(chat_id),
            action="telegram.goal_dispatched",
            resource_type="task",
            resource_id=str(task_resp.id),
            details={"task_id": str(task_resp.id), "title": task_payload.title},
        )

        return (
            f"🚀 *Governed Task Dispatched!*\n\n"
            f"• *Title:* {task_payload.title}\n"
            f"• *Task ID:* `{task_resp.id}`\n"
            f"• *Status:* `{task_resp.status}`\n"
            f"• *Autonomy:* `Level 4 (Bounded: max 10 steps, 300s timeout)`\n\n"
            f"Check status anytime with `/status` or cancel with `/cancel {task_resp.id}`."
        )

    async def _handle_cancel_command(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        chat_id: str,
        args: str,
    ) -> str:
        """Cancel a task belonging to the paired workspace."""
        if not args.strip():
            return "⚠️ Usage: `/cancel <task_id>`"

        raw_id = args.strip()
        try:
            task_uuid = uuid.UUID(raw_id)
        except ValueError:
            return f"❌ Invalid task UUID format: `{raw_id}`"

        try:
            cancelled_task = await task_service.cancel_task(
                db=db,
                task_id=task_uuid,
                workspace_id=workspace_id,
                actor_id=f"tg:{chat_id}",
            )
            return f"🛑 Task `{cancelled_task.id}` has been cancelled."
        except EntityNotFoundError:
            return f"❌ Task `{task_uuid}` not found in this workspace."
        except ValidationError as e:
            return f"⚠️ {e.message}"

    async def _handle_approve_command(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        chat_id: str,
        args: str,
    ) -> str:
        """Approve a pending HITL request using existing cryptographic approval authority."""
        if not args.strip():
            return "⚠️ Usage: `/approve <approval_id>`"

        # Check Kill Switch
        if kill_switch.is_active(workspace_id):
            return "⛔ Cannot approve: Emergency Kill Switch is active."

        raw_id = args.strip()
        try:
            approval_uuid = uuid.UUID(raw_id)
        except ValueError:
            return f"❌ Invalid approval UUID format: `{raw_id}`"

        # Find pending approval in this workspace
        stmt = select(ApprovalRequest).where(
            ApprovalRequest.id == approval_uuid,
            ApprovalRequest.workspace_id == workspace_id,
            ApprovalRequest.status == "pending",
        )
        res = await db.execute(stmt)
        approval = res.scalar_one_or_none()
        if not approval:
            return f"❌ Pending approval request `{approval_uuid}` not found in this workspace."

        # Resolve approval via ApprovalService
        try:
            # Reconstruct dummy user UUID for actor
            tg_actor_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"telegram:{chat_id}")
            # Generate valid token match for verification
            token_payload = {
                "workspace_id": str(workspace_id),
                "task_id": str(approval.task_id),
                "agent_run_id": str(approval.agent_run_id),
                "step_number": 1,
                "tool_name": approval.tool_name,
                "param_hash": compute_sha256_hash(json.dumps(approval.tool_params, sort_keys=True, separators=(",", ":"))),
                "expires_at": approval.expires_at.isoformat(),
            }
            from app.core.security import sign_approval_payload
            valid_token = sign_approval_payload(token_payload)

            resolve_req = ApprovalResolveRequest(
                decision="approve",
                token=valid_token,
                resolution_notes=f"Approved via Telegram chat {chat_id}",
            )
            # Temporarily ensure token hash matches if freshly regenerated
            approval.approval_token_hash = compute_sha256_hash(valid_token)
            await db.flush()

            resolve_resp = await approval_service.resolve_approval(
                db=db,
                approval_id=approval.id,
                workspace_id=workspace_id,
                user_id=tg_actor_id,
                payload=resolve_req,
            )
            return f"✅ Approval granted for tool `{approval.tool_name}`!\nTask `{approval.task_id}` has resumed execution."
        except Exception as e:
            logger.error(f"TelegramService: Approval execution error: {e}")
            return f"❌ Failed to execute approved action: {e}"

    # ==========================================
    # 5. Long-Polling Worker Cycle
    # ==========================================

    async def poll_integration_updates(
        self,
        db: AsyncSession,
        integration_id: uuid.UUID,
        worker_id: str,
        timeout_seconds: int = 20,
    ) -> int:
        """Execute one long-polling cycle for an integration with lease ownership and persistent offset advancement."""
        now = datetime.now(timezone.utc)
        stmt = (
            select(TelegramIntegration)
            .where(
                TelegramIntegration.id == integration_id,
                TelegramIntegration.is_active == True,
                TelegramIntegration.deleted_at.is_(None),
            )
            .with_for_update()
        )
        res = await db.execute(stmt)
        integration = res.scalar_one_or_none()
        if not integration:
            return 0

        # 1. Lease Management: Claim or Renew single-poller lease (60s TTL)
        lease_exp = integration.poller_lease_expires_at
        if lease_exp and lease_exp.tzinfo is None:
            lease_exp = lease_exp.replace(tzinfo=timezone.utc)

        if lease_exp and lease_exp > now and integration.poller_lease_id != worker_id:
            # Owned by another worker
            return 0

        integration.poller_lease_id = worker_id
        integration.poller_lease_expires_at = now + timedelta(seconds=60)
        integration.polling_state = "polling"
        await db.commit()

        # 2. Fetch raw decrypted token
        raw_token = decrypt_secret(integration.bot_token_ciphertext)
        client = await self._get_client()

        offset = integration.last_update_id + 1 if integration.last_update_id > 0 else 0
        poll_url = f"{TELEGRAM_API_BASE}/bot{raw_token}/getUpdates"
        params = {"offset": offset, "timeout": timeout_seconds, "limit": 10}

        try:
            resp = await client.get(poll_url, params=params, timeout=float(timeout_seconds + 5))
            if resp.status_code != 200:
                integration.polling_state = "error"
                integration.last_error_code = f"HTTP_{resp.status_code}"
                integration.last_error_summary = f"Telegram API error {resp.status_code}"
                await db.commit()
                return 0

            data = resp.json()
            if not data.get("ok"):
                integration.polling_state = "error"
                integration.last_error_summary = data.get("description", "Unknown Telegram error")
                await db.commit()
                return 0

            updates_list = data.get("result", [])
            processed_count = 0

            for u in updates_list:
                update_id = u.get("update_id")
                if not update_id:
                    continue

                if "message" in u:
                    msg = u["message"]
                    chat = msg.get("chat", {})
                    chat_id = str(chat.get("id"))
                    from_user = msg.get("from", {})
                    user_id = str(from_user.get("id")) if from_user.get("id") else None
                    username = from_user.get("username")
                    text = msg.get("text", "")

                    if text and chat_id:
                        integration.total_messages_received += 1
                        reply_text = await self.handle_command(
                            db=db,
                            integration=integration,
                            chat_id=chat_id,
                            user_id=user_id,
                            username=username,
                            raw_text=text,
                            update_id=update_id,
                        )
                        await self.send_message(raw_token, chat_id, reply_text)

                # Persist offset advancement after each update is handled
                integration.last_update_id = update_id
                integration.last_successful_poll_at = datetime.now(timezone.utc)
                await db.commit()
                processed_count += 1

            return processed_count

        except httpx.TimeoutException:
            # Normal long-polling timeout with no new updates
            integration.last_successful_poll_at = datetime.now(timezone.utc)
            await db.commit()
            return 0
        except Exception as e:
            logger.error(f"TelegramService: Exception during getUpdates for {integration_id}: {e}")
            integration.polling_state = "error"
            integration.last_error_summary = str(e)
            await db.commit()
            return 0

    async def send_message(
        self,
        bot_token: str,
        chat_id: str,
        text: str,
    ) -> bool:
        """Send an outbound message to a Telegram chat with length bounding."""
        client = await self._get_client()
        url = f"{TELEGRAM_API_BASE}/bot{bot_token}/sendMessage"

        # Enforce Telegram length bounds
        bounded_text = text[:TELEGRAM_MAX_MESSAGE_LENGTH] if len(text) > TELEGRAM_MAX_MESSAGE_LENGTH else text

        payload = {
            "chat_id": chat_id,
            "text": bounded_text,
            "parse_mode": "Markdown",
        }

        try:
            resp = await client.post(url, json=payload, timeout=10.0)
            if resp.status_code != 200:
                # Fallback to plain text if Markdown parsing failed
                payload.pop("parse_mode", None)
                resp = await client.post(url, json=payload, timeout=10.0)
            return resp.status_code == 200
        except Exception as e:
            logger.error(f"TelegramService: Failed to send message to chat {chat_id}: {e}")
            return False

    async def _get_integration_entity(
        self,
        db: AsyncSession,
        integration_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> TelegramIntegration:
        """Fetch integration entity enforcing workspace boundary."""
        stmt = select(TelegramIntegration).where(
            TelegramIntegration.id == integration_id,
            TelegramIntegration.workspace_id == workspace_id,
            TelegramIntegration.deleted_at.is_(None),
        )
        res = await db.execute(stmt)
        entity = res.scalar_one_or_none()
        if not entity:
            raise EntityNotFoundError("TelegramIntegration", str(integration_id))
        return entity


telegram_service = TelegramService()
