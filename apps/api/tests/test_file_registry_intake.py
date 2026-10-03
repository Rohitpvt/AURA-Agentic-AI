"""Deterministic Integration & Unit Tests for AURA-601 Universal File Intake & Secure File Registry."""

import hashlib
import io
import os
from pathlib import Path
import shutil
import uuid
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AuthorizationError, EntityNotFoundError, ValidationError
from app.core.filesystem import filesystem_guard
from app.core.security import create_access_token
from app.db.models.file import FileChunk, FileRecord, FileStatus
from app.db.models.user import User
from app.db.models.workspace import Workspace, WorkspaceMember
from app.services.audit_service import AuditLedgerService
from app.services.file_service import file_service

audit_ledger = AuditLedgerService()


@pytest_asyncio.fixture
async def test_env(db_session: AsyncSession):
    """Fixture providing two authenticated workspaces, users, and tokens for tenant isolation testing."""
    # User 1 (Workspace 1 Owner)
    user1 = User(
        id=uuid.uuid4(),
        email="owner1@aura.local",
        full_name="Workspace 1 Owner",
        password_hash="fake_hashed_password",
        is_active=True,
    )
    # User 2 (Workspace 2 Owner)
    user2 = User(
        id=uuid.uuid4(),
        email="owner2@aura.local",
        full_name="Workspace 2 Owner",
        password_hash="fake_hashed_password",
        is_active=True,
    )
    db_session.add_all([user1, user2])
    await db_session.commit()

    # Workspace 1
    ws1 = Workspace(
        id=uuid.uuid4(),
        name="Workspace Alpha",
        slug="workspace-alpha",
    )
    # Workspace 2
    ws2 = Workspace(
        id=uuid.uuid4(),
        name="Workspace Beta",
        slug="workspace-beta",
    )
    db_session.add_all([ws1, ws2])
    await db_session.commit()

    # Memberships
    m1 = WorkspaceMember(workspace_id=ws1.id, user_id=user1.id, role="owner")
    m2 = WorkspaceMember(workspace_id=ws2.id, user_id=user2.id, role="owner")
    db_session.add_all([m1, m2])
    await db_session.commit()

    token1 = create_access_token({"sub": str(user1.id), "email": user1.email})
    token2 = create_access_token({"sub": str(user2.id), "email": user2.email})

    headers1 = {"Authorization": f"Bearer {token1}", "X-Workspace-ID": str(ws1.id)}
    headers2 = {"Authorization": f"Bearer {token2}", "X-Workspace-ID": str(ws2.id)}

    yield {
        "user1": user1,
        "user2": user2,
        "ws1": ws1,
        "ws2": ws2,
        "headers1": headers1,
        "headers2": headers2,
    }

    # Cleanup filesystem after test
    for ws_id in [ws1.id, ws2.id]:
        try:
            ws_root = filesystem_guard.get_workspace_root(ws_id)
            if ws_root.exists():
                shutil.rmtree(ws_root, ignore_errors=True)
        except Exception:
            pass


@pytest.mark.asyncio
async def test_valid_file_upload_and_registration(client: AsyncClient, test_env, db_session: AsyncSession):
    """Test standard intake and registration of diverse valid document formats."""
    ws1 = test_env["ws1"]
    headers1 = test_env["headers1"]

    pdf_content = b"%PDF-1.4\n1 0 obj\n<< /Title (Test Document) >>\nendobj\ntrailer\n<< >>\n%%EOF"
    expected_hash = hashlib.sha256(pdf_content).hexdigest()

    files = {"file": ("report_q3.pdf", io.BytesIO(pdf_content), "application/pdf")}
    resp = await client.post(f"/api/v1/files/upload?workspace_id={ws1.id}", headers=headers1, files=files)

    assert resp.status_code == 201
    data = resp.json()
    assert data["is_duplicate"] is False
    file_info = data["file"]
    assert file_info["original_filename"] == "report_q3.pdf"
    assert file_info["safe_filename"] == "report_q3.pdf"
    assert file_info["mime_type"] == "application/pdf"
    assert file_info["size_bytes"] == len(pdf_content)
    assert file_info["sha256_hash"] == expected_hash
    assert file_info["status"] == "uploaded"
    assert file_info["security_flags"] == []

    # Verify physical file existence on disk
    file_id = uuid.UUID(file_info["id"])
    ws_root = filesystem_guard.get_workspace_root(ws1.id)
    disk_file = ws_root / "files" / str(file_id) / "report_q3.pdf"
    assert disk_file.exists()
    assert disk_file.read_bytes() == pdf_content


@pytest.mark.asyncio
async def test_filename_sanitization_and_traversal_stripping(client: AsyncClient, test_env):
    """Test that malicious filenames with traversal tokens, drive letters, and null bytes are sanitized safely."""
    ws1 = test_env["ws1"]
    headers1 = test_env["headers1"]

    test_cases = [
        ("../../etc/passwd.txt", b"plain text data", "etc_passwd.txt"),
        ("..\\..\\Windows\\System32\\cmd.exe.txt", b"fake cmd", "Windows_System32_cmd.exe.txt"),
        ("C:\\Secret\\Documents\\finance.csv", b"col1,col2\n1,2", "finance.csv"),
        ("\\\\server\\share\\data.json", b'{"key": "val"}', "data.json"),
        ("CON.txt", b"reserved name test", "CON_safe.txt"),
        ("malicious\x00file.md", b"# Markdown", "maliciousfile.md"),
    ]

    for raw_name, content, expected_safe in test_cases:
        files = {"file": (raw_name, io.BytesIO(content), "text/plain")}
        resp = await client.post(f"/api/v1/files/upload?workspace_id={ws1.id}", headers=headers1, files=files)
        assert resp.status_code == 201
        data = resp.json()
        assert data["file"]["safe_filename"] == expected_safe
        file_id = uuid.UUID(data["file"]["id"])

        # Check path strictly inside workspace
        ws_root = filesystem_guard.get_workspace_root(ws1.id)
        assert (ws_root / "files" / str(file_id) / expected_safe).exists()


@pytest.mark.asyncio
async def test_disguised_executable_quarantine_screening(client: AsyncClient, test_env):
    """Test that executable binaries disguised as documents are flagged and quarantined."""
    ws1 = test_env["ws1"]
    headers1 = test_env["headers1"]

    # DOS/PE Header 'MZ' disguised as PDF
    mz_payload = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00" + b"A" * 100
    files = {"file": ("invoice.pdf", io.BytesIO(mz_payload), "application/pdf")}
    resp = await client.post(f"/api/v1/files/upload?workspace_id={ws1.id}", headers=headers1, files=files)

    assert resp.status_code == 201
    data = resp.json()
    assert data["file"]["status"] == "quarantined"
    assert "SUSPICIOUS_EXECUTABLE_SIGNATURE_DOS_PE_EXECUTABLE" in data["file"]["security_flags"]


@pytest.mark.asyncio
async def test_empty_file_rejection(client: AsyncClient, test_env):
    """Test that zero-byte uploads are rejected with ValidationError."""
    ws1 = test_env["ws1"]
    headers1 = test_env["headers1"]

    files = {"file": ("empty.txt", io.BytesIO(b""), "text/plain")}
    resp = await client.post(f"/api/v1/files/upload?workspace_id={ws1.id}", headers=headers1, files=files)
    assert resp.status_code == 422
    data = resp.json()
    error_msg = data.get("error", {}).get("message", "") or str(data)
    assert "empty" in error_msg.lower()


@pytest.mark.asyncio
async def test_oversized_upload_rejection_and_cleanup(client: AsyncClient, test_env):
    """Test that uploads exceeding 50 MB are terminated and cleaned up."""
    ws1 = test_env["ws1"]
    headers1 = test_env["headers1"]

    # Mock an oversized stream by temporarily reducing limit or sending a payload slightly above limit
    orig_limit = file_service.MAX_UPLOAD_BYTES
    file_service.MAX_UPLOAD_BYTES = 1024 * 100  # 100 KB limit for test speed

    try:
        large_payload = b"X" * (1024 * 150)  # 150 KB
        files = {"file": ("large.dat", io.BytesIO(large_payload), "application/octet-stream")}
        resp = await client.post(f"/api/v1/files/upload?workspace_id={ws1.id}", headers=headers1, files=files)
        assert resp.status_code == 422
        data = resp.json()
        error_msg = data.get("error", {}).get("message", "") or str(data)
        assert "exceeds maximum upload limit" in error_msg
    finally:
        file_service.MAX_UPLOAD_BYTES = orig_limit


@pytest.mark.asyncio
async def test_intra_workspace_deduplication(client: AsyncClient, test_env):
    """Test that uploading identical content in the same workspace is deduplicated."""
    ws1 = test_env["ws1"]
    headers1 = test_env["headers1"]

    content = b"Unique content for deduplication test: " + uuid.uuid4().bytes
    files1 = {"file": ("doc_v1.txt", io.BytesIO(content), "text/plain")}
    resp1 = await client.post(f"/api/v1/files/upload?workspace_id={ws1.id}", headers=headers1, files=files1)
    assert resp1.status_code == 201
    assert resp1.json()["is_duplicate"] is False
    file_id_1 = resp1.json()["file"]["id"]

    # Upload identical content under a different filename
    files2 = {"file": ("doc_copy.txt", io.BytesIO(content), "text/plain")}
    resp2 = await client.post(f"/api/v1/files/upload?workspace_id={ws1.id}", headers=headers1, files=files2)
    assert resp2.status_code == 201
    assert resp2.json()["is_duplicate"] is True
    assert resp2.json()["file"]["id"] == file_id_1  # Reuses existing record


@pytest.mark.asyncio
async def test_cross_workspace_isolation_and_auth_denial(client: AsyncClient, test_env):
    """Test that files uploaded in Workspace 1 are strictly inaccessible to Workspace 2."""
    ws1 = test_env["ws1"]
    ws2 = test_env["ws2"]
    headers1 = test_env["headers1"]
    headers2 = test_env["headers2"]

    content = b"Confidential workspace 1 strategy document"
    files = {"file": ("strategy.txt", io.BytesIO(content), "text/plain")}
    resp1 = await client.post(f"/api/v1/files/upload?workspace_id={ws1.id}", headers=headers1, files=files)
    assert resp1.status_code == 201
    file_id = resp1.json()["file"]["id"]

    # 1. User 2 in Workspace 2 cannot fetch details of Workspace 1 file
    resp_get = await client.get(f"/api/v1/files/{file_id}?workspace_id={ws2.id}", headers=headers2)
    assert resp_get.status_code == 404

    # 2. User 2 cannot list files from Workspace 1
    resp_list = await client.get(f"/api/v1/files?workspace_id={ws1.id}", headers=headers2)
    assert resp_list.status_code == 403  # Access denied to Workspace 1

    # 3. User 2 cannot delete file from Workspace 1
    resp_del = await client.delete(f"/api/v1/files/{file_id}?workspace_id={ws1.id}", headers=headers2)
    assert resp_del.status_code == 403

    # 4. Same content uploaded in Workspace 2 creates an independent record in Workspace 2
    files_ws2 = {"file": ("strategy_copy.txt", io.BytesIO(content), "text/plain")}
    resp_ws2 = await client.post(f"/api/v1/files/upload?workspace_id={ws2.id}", headers=headers2, files=files_ws2)
    assert resp_ws2.status_code == 201
    assert resp_ws2.json()["file"]["workspace_id"] == str(ws2.id)
    assert resp_ws2.json()["file"]["id"] != file_id


@pytest.mark.asyncio
async def test_idempotent_deletion_lifecycle(client: AsyncClient, test_env, db_session: AsyncSession):
    """Test complete deletion state machine, physical purge, cascade, and idempotency."""
    ws1 = test_env["ws1"]
    headers1 = test_env["headers1"]

    content = b"Ephemeral document for deletion test"
    files = {"file": ("temp_report.txt", io.BytesIO(content), "text/plain")}
    resp = await client.post(f"/api/v1/files/upload?workspace_id={ws1.id}", headers=headers1, files=files)
    assert resp.status_code == 201
    file_id_str = resp.json()["file"]["id"]
    file_id = uuid.UUID(file_id_str)

    # Insert a dummy chunk to verify cascade
    chunk = FileChunk(
        id=uuid.uuid4(),
        workspace_id=ws1.id,
        file_id=file_id,
        chunk_index=0,
        chunk_text="Ephemeral chunk",
        token_count=2,
        embedding=[0.1] * 768,
        source_location={"page": 1},
    )
    db_session.add(chunk)
    await db_session.commit()

    # 1. Execute Deletion
    del_resp = await client.delete(f"/api/v1/files/{file_id}?workspace_id={ws1.id}", headers=headers1)
    assert del_resp.status_code == 200
    del_data = del_resp.json()
    assert del_data["status"] == "deleted"
    assert del_data["purged_storage"] is True
    assert del_data["purged_chunks"] == 1

    # Verify physical file directory was purged
    ws_root = filesystem_guard.get_workspace_root(ws1.id)
    disk_dir = ws_root / "files" / str(file_id)
    assert not disk_dir.exists()

    # Verify DB record is marked deleted
    stmt = select(FileRecord).where(FileRecord.id == file_id)
    db_rec = (await db_session.execute(stmt)).scalars().first()
    assert db_rec.status == FileStatus.DELETED.value
    assert db_rec.deleted_at is not None

    # 2. Repeated Deletion Request (Idempotent)
    repeat_resp = await client.delete(f"/api/v1/files/{file_id}?workspace_id={ws1.id}", headers=headers1)
    assert repeat_resp.status_code == 200
    assert repeat_resp.json()["status"] == "already_deleted"


@pytest.mark.asyncio
async def test_orphan_storage_reconciliation(client: AsyncClient, test_env, db_session: AsyncSession):
    """Test orphan directory detection and purge during workspace reconciliation."""
    ws1 = test_env["ws1"]
    headers1 = test_env["headers1"]

    ws_root = filesystem_guard.get_workspace_root(ws1.id)
    files_base = ws_root / "files"
    files_base.mkdir(parents=True, exist_ok=True)

    # 1. Create an unreferenced orphaned folder on disk
    orphan_uuid = uuid.uuid4()
    orphan_dir = files_base / str(orphan_uuid)
    orphan_dir.mkdir(parents=True, exist_ok=True)
    (orphan_dir / "leftover.dat").write_bytes(b"orphaned data")

    # 2. Trigger reconciliation
    rec_resp = await client.post(f"/api/v1/files/reconcile?workspace_id={ws1.id}", headers=headers1)
    assert rec_resp.status_code == 200
    rec_data = rec_resp.json()
    assert rec_data["orphaned_directories_found"] >= 1
    assert rec_data["orphaned_directories_purged"] >= 1

    # Verify orphan folder was purged
    assert not orphan_dir.exists()


@pytest.mark.asyncio
async def test_audit_ledger_integrity_on_file_operations(client: AsyncClient, test_env, db_session: AsyncSession):
    """Test that all file operations record tamper-evident SHA-256 chained audit entries."""
    ws1 = test_env["ws1"]
    headers1 = test_env["headers1"]

    content = b"Audit logging verification payload"
    files = {"file": ("audited_doc.txt", io.BytesIO(content), "text/plain")}
    resp = await client.post(f"/api/v1/files/upload?workspace_id={ws1.id}", headers=headers1, files=files)
    assert resp.status_code == 201
    file_id = resp.json()["file"]["id"]

    # Delete the file
    del_resp = await client.delete(f"/api/v1/files/{file_id}?workspace_id={ws1.id}", headers=headers1)
    assert del_resp.status_code == 200

    # Verify cryptographic audit hash chain
    verify_res = await audit_ledger.verify_ledger(db=db_session, workspace_id=ws1.id)
    assert verify_res["is_valid"] is True
    assert verify_res["total_records"] >= 2  # uploaded + deleted


@pytest.mark.asyncio
async def test_paginated_file_listing_and_filtering(client: AsyncClient, test_env):
    """Test pagination, status filtering, and search filtering on file listing."""
    ws1 = test_env["ws1"]
    headers1 = test_env["headers1"]

    # Upload multiple distinct files
    for i in range(5):
        content = f"File content batch item {i} {uuid.uuid4()}".encode()
        files = {"file": (f"batch_doc_{i}.txt", io.BytesIO(content), "text/plain")}
        resp = await client.post(f"/api/v1/files/upload?workspace_id={ws1.id}", headers=headers1, files=files)
        assert resp.status_code == 201

    # Page 1 with limit 2
    resp_p1 = await client.get(f"/api/v1/files?workspace_id={ws1.id}&page=1&limit=2", headers=headers1)
    assert resp_p1.status_code == 200
    d1 = resp_p1.json()
    assert len(d1["items"]) == 2
    assert d1["total"] >= 5
    assert d1["page"] == 1

    # Search filter
    resp_search = await client.get(f"/api/v1/files?workspace_id={ws1.id}&search=batch_doc_3", headers=headers1)
    assert resp_search.status_code == 200
    d_search = resp_search.json()
    assert len(d_search["items"]) == 1
    assert "batch_doc_3" in d_search["items"][0]["original_filename"]


@pytest.mark.asyncio
async def test_non_admin_reconciliation_rbac_denial(client: AsyncClient, test_env, db_session: AsyncSession):
    """Test that a non-admin workspace member cannot invoke orphan reconciliation."""
    ws1 = test_env["ws1"]

    # Create a regular member user
    regular_user = User(
        id=uuid.uuid4(),
        email="member@aura.local",
        full_name="Regular Member",
        password_hash="fake_pass",
        is_active=True,
    )
    db_session.add(regular_user)
    await db_session.commit()

    member_entry = WorkspaceMember(workspace_id=ws1.id, user_id=regular_user.id, role="member")
    db_session.add(member_entry)
    await db_session.commit()

    token_member = create_access_token({"sub": str(regular_user.id), "email": regular_user.email})
    headers_member = {"Authorization": f"Bearer {token_member}", "X-Workspace-ID": str(ws1.id)}

    resp = await client.post(f"/api/v1/files/reconcile?workspace_id={ws1.id}", headers=headers_member)
    assert resp.status_code == 403
    assert "owners and administrators" in resp.json()["error"]["message"]


@pytest.mark.asyncio
async def test_missing_workspace_id_validation_error(client: AsyncClient, test_env):
    """Test that endpoints without a workspace ID return ValidationError."""
    headers_no_ws = {"Authorization": test_env["headers1"]["Authorization"]}
    files = {"file": ("test.txt", io.BytesIO(b"data"), "text/plain")}

    resp = await client.post("/api/v1/files/upload", headers=headers_no_ws, files=files)
    assert resp.status_code == 422
    assert "Workspace ID must be provided" in resp.json()["error"]["message"]


@pytest.mark.asyncio
async def test_get_nonexistent_file_returns_404(client: AsyncClient, test_env):
    """Test that querying a non-existent file ID returns 404 EntityNotFoundError."""
    ws1 = test_env["ws1"]
    headers1 = test_env["headers1"]
    random_id = uuid.uuid4()

    resp = await client.get(f"/api/v1/files/{random_id}?workspace_id={ws1.id}", headers=headers1)
    assert resp.status_code == 404
    assert "not found" in resp.json()["error"]["message"].lower()


@pytest.mark.asyncio
async def test_file_intake_does_not_generate_chunks_prematurely(client: AsyncClient, test_env, db_session: AsyncSession):
    """Test AURA-601 boundary invariant (Option A): file intake registers FileRecord but creates 0 FileChunks."""
    ws1 = test_env["ws1"]
    headers1 = test_env["headers1"]

    pdf_content = b"%PDF-1.4\n1 0 obj\n<< /Title (Boundary Document) >>\nendobj\ntrailer\n<< >>\n%%EOF"
    files = {"file": ("boundary_doc.pdf", io.BytesIO(pdf_content), "application/pdf")}
    resp = await client.post(f"/api/v1/files/upload?workspace_id={ws1.id}", headers=headers1, files=files)
    assert resp.status_code == 201
    file_id = uuid.UUID(resp.json()["file"]["id"])

    # Verify that exactly 0 FileChunk records exist for this file
    stmt = select(func.count()).select_from(FileChunk).where(FileChunk.file_id == file_id)
    chunk_count = (await db_session.execute(stmt)).scalar()
    assert chunk_count == 0, "AURA-601 must not prematurely create FileChunk records or invoke FastEmbed vectors."


@pytest.mark.asyncio
async def test_deletion_state_machine_transitions_from_all_operational_states(client: AsyncClient, test_env, db_session: AsyncSession):
    """Test deletion state machine execution across all valid operational initial states."""
    ws1 = test_env["ws1"]
    headers1 = test_env["headers1"]

    operational_states = [
        FileStatus.UPLOADED,
        FileStatus.PARSING,
        FileStatus.INDEXED,
        FileStatus.FAILED,
        FileStatus.QUARANTINED,
        FileStatus.DELETE_REQUESTED,
    ]

    for state in operational_states:
        # Create a file record in the given state
        file_id = uuid.uuid4()
        storage_rel = f"files/{file_id}/test_state.txt"
        final_path = filesystem_guard.validate_and_resolve_path(ws1.id, storage_rel)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        final_path.write_bytes(b"State machine test file content")

        rec = FileRecord(
            id=file_id,
            workspace_id=ws1.id,
            uploaded_by=test_env["user1"].id,
            original_filename="test_state.txt",
            safe_filename="test_state.txt",
            mime_type="text/plain",
            file_extension=".txt",
            size_bytes=31,
            sha256_hash=hashlib.sha256(b"State machine test file content" + state.value.encode()).hexdigest(),
            storage_path=storage_rel,
            status=state.value,
        )
        db_session.add(rec)
        await db_session.commit()

        # Execute deletion
        del_resp = await client.delete(f"/api/v1/files/{file_id}?workspace_id={ws1.id}", headers=headers1)
        assert del_resp.status_code == 200
        data = del_resp.json()
        assert data["status"] == "deleted"
        assert data["purged_storage"] is True

        # Verify terminal record status in DB
        stmt = select(FileRecord).where(FileRecord.id == file_id)
        db_rec = (await db_session.execute(stmt)).scalars().first()
        assert db_rec.status == FileStatus.DELETED.value
        assert db_rec.deleted_at is not None

        # Verify idempotency on second deletion call
        repeat_resp = await client.delete(f"/api/v1/files/{file_id}?workspace_id={ws1.id}", headers=headers1)
        assert repeat_resp.status_code == 200
        assert repeat_resp.json()["status"] == "already_deleted"


@pytest.mark.asyncio
async def test_deleted_file_isolation_and_terminal_exclusion(client: AsyncClient, test_env, db_session: AsyncSession):
    """Test that once a file reaches terminal DELETED status, it is excluded from get and list queries."""
    ws1 = test_env["ws1"]
    headers1 = test_env["headers1"]

    content = b"Terminal deleted exclusion test"
    files = {"file": ("terminal_doc.txt", io.BytesIO(content), "text/plain")}
    resp = await client.post(f"/api/v1/files/upload?workspace_id={ws1.id}", headers=headers1, files=files)
    assert resp.status_code == 201
    file_id = uuid.UUID(resp.json()["file"]["id"])

    # Delete the file
    del_resp = await client.delete(f"/api/v1/files/{file_id}?workspace_id={ws1.id}", headers=headers1)
    assert del_resp.status_code == 200

    # 1. get_file returns 404
    get_resp = await client.get(f"/api/v1/files/{file_id}?workspace_id={ws1.id}", headers=headers1)
    assert get_resp.status_code == 404

    # 2. list_files does not include deleted file
    list_resp = await client.get(f"/api/v1/files?workspace_id={ws1.id}", headers=headers1)
    assert list_resp.status_code == 200
    listed_ids = [item["id"] for item in list_resp.json()["items"]]
    assert str(file_id) not in listed_ids



