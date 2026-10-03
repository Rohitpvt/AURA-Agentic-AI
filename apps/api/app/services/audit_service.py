"""Tamper-Evident Audit Ledger Verification and Management Service."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.logging import logger
from app.core.security import compute_sha256_hash
from app.db.models.audit import AuditLog


class AuditLedgerService:
    """Provides tamper-evident cryptographic hash-chain logging and verification."""

    GENESIS_HASH = "0" * 64

    async def record_event(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        actor_type: str,
        actor_id: str,
        action: str,
        resource_type: str,
        resource_id: str,
        details: Dict[str, Any],
        ip_address: Optional[str] = None,
    ) -> AuditLog:
        """Append a new tamper-evident audit entry cryptographically chained to the previous record."""
        # Find latest entry for this workspace
        stmt = (
            select(AuditLog)
            .where(AuditLog.workspace_id == workspace_id)
            .order_by(AuditLog.id.desc())
            .limit(1)
        )
        res = await db.execute(stmt)
        last_log = res.scalars().first()

        prev_hash = last_log.log_hash if last_log else self.GENESIS_HASH
        now = datetime.now(timezone.utc)
        # Format timestamp deterministically (seconds precision timestamp)
        ts_int = int(now.timestamp())
        payload_str = f"{prev_hash}|{workspace_id}|{actor_id}|{action}|{resource_type}|{resource_id}|{ts_int}"
        cur_hash = compute_sha256_hash(payload_str)

        # Sanitize details to ensure no credentials leaked
        from app.core.redaction import secret_redactor
        from app.core.telemetry import telemetry_manager
        
        clean_details = secret_redactor.redact_structure(details)
        active_trace_id = telemetry_manager.get_current_trace_id()
        if active_trace_id and "trace_id" not in clean_details:
            clean_details["trace_id"] = active_trace_id

        try:
            with telemetry_manager.start_span(
                name=f"audit.record {action}",
                span_type="audit",
                attributes={
                    "aura.audit_action": action,
                    "aura.resource_type": resource_type,
                    "aura.resource_id": resource_id,
                    "aura.workspace_id": str(workspace_id),
                    "aura.actor_id": actor_id,
                },
            ):
                pass
        except Exception as otel_err:
            logger.debug(f"AuditService: Telemetry span failed safely: {otel_err}")

        log_entry = AuditLog(
            workspace_id=workspace_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=clean_details,
            ip_address=ip_address,
            previous_log_hash=prev_hash,
            log_hash=cur_hash,
            created_at=now,
        )
        db.add(log_entry)
        await db.commit()
        await db.refresh(log_entry)
        return log_entry

    async def verify_ledger(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
    ) -> Dict[str, Any]:
        """Verify the integrity of the audit hash chain for a specific workspace.

        Detects:
        - Tampered payloads
        - Altered previous_log_hash fields
        - Missing or deleted entries
        - Reordered entries
        """
        stmt = (
            select(AuditLog)
            .where(AuditLog.workspace_id == workspace_id)
            .order_by(AuditLog.id.asc())
        )
        res = await db.execute(stmt)
        logs = list(res.scalars().all())

        if not logs:
            return {
                "status": "VALID",
                "total_records": 0,
                "workspace_id": str(workspace_id),
                "message": "Audit ledger is empty",
                "violations": [],
            }

        expected_prev_hash = self.GENESIS_HASH
        violations = []

        for idx, log in enumerate(logs):
            # 1. Check previous hash continuity
            if log.previous_log_hash != expected_prev_hash:
                violations.append({
                    "record_id": log.id,
                    "index": idx,
                    "issue": "BROKEN_HASH_CHAIN",
                    "expected_previous_hash": expected_prev_hash,
                    "actual_previous_hash": log.previous_log_hash,
                })

            # 2. Re-compute payload hash using deterministic UTC timestamp
            created_dt = log.created_at
            if created_dt.tzinfo is None:
                created_dt = created_dt.replace(tzinfo=timezone.utc)
            ts_int = int(created_dt.timestamp())
            payload_str = f"{log.previous_log_hash}|{log.workspace_id}|{log.actor_id}|{log.action}|{log.resource_type}|{log.resource_id}|{ts_int}"
            computed_hash = compute_sha256_hash(payload_str)

            if log.log_hash != computed_hash:
                violations.append({
                    "record_id": log.id,
                    "index": idx,
                    "issue": "MODIFIED_RECORD_HASH",
                    "recorded_hash": log.log_hash,
                    "computed_hash": computed_hash,
                })

            expected_prev_hash = log.log_hash

        is_valid = len(violations) == 0
        return {
            "status": "VALID" if is_valid else "COMPROMISED",
            "total_records": len(logs),
            "workspace_id": str(workspace_id),
            "is_valid": is_valid,
            "violations_count": len(violations),
            "violations": violations,
            "latest_log_hash": logs[-1].log_hash if logs else None,
        }


audit_service = AuditLedgerService()
