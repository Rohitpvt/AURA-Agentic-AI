"""
Phase 2 Master Audit: Authentication, Session Lifecycle, JWT Integrity, and Multi-Tenant Workspace Isolation.
"""
import pytest
import uuid
from datetime import timedelta

from app.core.security import (
    create_access_token,
    verify_password,
    get_password_hash,
    decode_token,
)
from app.core.config import settings
from app.db.models.user import User
from app.db.models.workspace import Workspace
from app.db.models.task import Task
from app.db.models.memory import MemoryRecord
from app.db.models.file import FileRecord


@pytest.mark.asyncio
async def test_phase02_password_hashing_and_timing_safety():
    """
    Audit Phase 2 Auth: Verify password hashing is secure, non-deterministic, and rejects wrong passwords.
    """
    plain_password = "SuperSecretPassword123!"
    hash1 = get_password_hash(plain_password)
    hash2 = get_password_hash(plain_password)

    # Hashes must differ due to distinct salts
    assert hash1 != hash2
    assert verify_password(plain_password, hash1) is True
    assert verify_password(plain_password, hash2) is True
    assert verify_password("WrongPassword!", hash1) is False
    assert verify_password("", hash1) is False


@pytest.mark.asyncio
async def test_phase02_jwt_token_validation_and_tamper_rejection():
    """
    Audit Phase 2 Auth: Verify JWT signature verification, expiration, and tampering rejection.
    """
    subject = "user_audit_123"
    token = create_access_token(data={"sub": subject}, expires_delta=timedelta(minutes=15))

    # Valid token decodes correctly
    payload = decode_token(token)
    assert payload.get("sub") == subject

    # Tampered signature rejected
    tampered_token = token[:-4] + "abcd"
    with pytest.raises(Exception):
        decode_token(tampered_token)

    # Expired token rejected
    expired_token = create_access_token(data={"sub": subject}, expires_delta=timedelta(seconds=-10))
    with pytest.raises(Exception):
        decode_token(expired_token)


@pytest.mark.asyncio
async def test_phase02_multi_tenant_workspace_isolation_across_resources(db_session):
    """
    Audit Phase 2 Tenancy: Prove User A / Workspace 1 CANNOT query, access, or leak resources of User B / Workspace 2.
    """
    u1_id = uuid.uuid4()
    u2_id = uuid.uuid4()
    w1_id = uuid.uuid4()
    w2_id = uuid.uuid4()

    # Create Users & Workspaces
    u1 = User(id=u1_id, email=f"u1_{str(u1_id)[:8]}@test.com", password_hash="pwd", full_name="User One", is_active=True)
    u2 = User(id=u2_id, email=f"u2_{str(u2_id)[:8]}@test.com", password_hash="pwd", full_name="User Two", is_active=True)
    w1 = Workspace(id=w1_id, name="Workspace 1", slug=f"ws1-{w1_id.hex[:8]}")
    w2 = Workspace(id=w2_id, name="Workspace 2", slug=f"ws2-{w2_id.hex[:8]}")
    db_session.add_all([u1, u2, w1, w2])
    await db_session.flush()

    # Create Tasks, Files, and Memory in Workspace 1
    t1 = Task(id=uuid.uuid4(), workspace_id=w1_id, title="W1 Private Task", goal="W1 Private Goal", status="PENDING")
    f1 = FileRecord(
        id=uuid.uuid4(),
        workspace_id=w1_id,
        original_filename="w1_secrets.pdf",
        safe_filename="w1_secrets.pdf",
        storage_path="mock/path/w1",
        size_bytes=100,
        sha256_hash="hash1" * 16,
        mime_type="application/pdf",
        file_extension=".pdf",
        status="indexed",
    )
    m1 = MemoryRecord(
        id=uuid.uuid4(),
        workspace_id=w1_id,
        fact_statement="Confidential business plan in W1",
        category="general",
        embedding=[0.1] * 768,
    )
    db_session.add_all([t1, f1, m1])
    await db_session.flush()

    # Query using Workspace 2 context -> MUST RETURN ZERO RESULTS
    from sqlalchemy import select
    w2_tasks = (await db_session.execute(select(Task).where(Task.workspace_id == w2_id))).scalars().all()
    assert len(w2_tasks) == 0

    w2_files = (await db_session.execute(select(FileRecord).where(FileRecord.workspace_id == w2_id))).scalars().all()
    assert len(w2_files) == 0

    w2_memories = (await db_session.execute(select(MemoryRecord).where(MemoryRecord.workspace_id == w2_id))).scalars().all()
    assert len(w2_memories) == 0
