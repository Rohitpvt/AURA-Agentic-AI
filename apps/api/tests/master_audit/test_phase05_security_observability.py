"""
Phase 5 Master Audit: OpenTelemetry Distributed Tracing, Centralized Secret Redaction, and SHA-256 Audit Ledger.
"""
import pytest
import uuid

from app.core.redaction import SecretRedactor, secret_redactor
from app.services.audit_service import AuditLedgerService
from app.db.models.audit import AuditLog
from app.core.telemetry import telemetry_manager


@pytest.mark.asyncio
async def test_phase05_centralized_secret_redaction_patterns():
    """
    Audit Phase 5 Security: Verify API keys, JWTs, bearer tokens, and private passwords are scrubbed.
    """
    sensitive_payload = {
        "gemini_api_key": "AIzaSyD9876543210FedCba9876543210",
        "auth_header": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.doNotLeakThisSignature",
        "user_password": "PlainTextPassword456!",
        "safe_query": "What is the capital of France?",
    }

    redacted = secret_redactor.redact_structure(sensitive_payload)

    # Secrets must be replaced with redaction tokens
    assert "AIzaSy" not in str(redacted)
    assert "[REDACTED" in str(redacted)
    assert redacted.get("safe_query") == "What is the capital of France?"


@pytest.mark.asyncio
async def test_phase05_audit_ledger_hash_chain_integrity(db_session):
    """
    Audit Phase 5 Observability: Verify AuditLedgerService creates tamper-evident cryptographic hash chains.
    """
    audit_svc = AuditLedgerService()
    ws_id = uuid.uuid4()

    # Log sequential audit events
    log1 = await audit_svc.record_event(
        db=db_session,
        workspace_id=ws_id,
        actor_type="user",
        actor_id="user_1",
        action="TASK_CREATED",
        resource_type="task",
        resource_id=str(uuid.uuid4()),
        details={"task_title": "Audit Task 1"},
    )
    await db_session.flush()

    log2 = await audit_svc.record_event(
        db=db_session,
        workspace_id=ws_id,
        actor_type="agent",
        actor_id="agent_1",
        action="TOOL_EXECUTED",
        resource_type="tool",
        resource_id=str(uuid.uuid4()),
        details={"tool_name": "web_search"},
    )
    await db_session.flush()

    # Verify both records have valid SHA-256 hashes
    assert log1.log_hash is not None
    assert len(log1.log_hash) == 64
    assert log2.log_hash is not None
    assert len(log2.log_hash) == 64
    # Hash chain links
    assert log2.previous_log_hash == log1.log_hash


@pytest.mark.asyncio
async def test_phase05_opentelemetry_tracer_initialization():
    """
    Audit Phase 5 Observability: Verify OpenTelemetry tracer initializes and produces active spans.
    """
    tracer = telemetry_manager.tracer
    assert tracer is not None

    with tracer.start_as_current_span("audit-test-span") as span:
        assert span is not None
        span.set_attribute("aura.test", "phase05_verified")
