"""Benchmark Performance Suite for AURA-1003 Encrypted Web Session & Credential Vault."""

import asyncio
import time
import uuid
import pytest

from app.services.browser.vault import (
    WebVaultService,
    decrypt_field,
    derive_vault_key,
    encrypt_field,
    web_vault_service,
)


@pytest.mark.asyncio
async def test_benchmark_key_derivation_performance():
    """Benchmark SHA-256 key derivation performance across 1,000 iterations."""
    ws_id = uuid.uuid4()
    iterations = 1000

    t0 = time.perf_counter()
    for _ in range(iterations):
        derive_vault_key(master_key="BenchmarkMasterKey_2026", workspace_id=ws_id)
    total_time = time.perf_counter() - t0

    avg_us = (total_time / iterations) * 1_000_000
    ops_per_sec = iterations / total_time

    print(f"\n[AURA-1003 Benchmark] Key Derivation: {avg_us:.2f} µs/op | {ops_per_sec:,.0f} ops/sec")
    assert avg_us < 200.0, f"Key derivation average latency ({avg_us:.2f}µs) exceeded 200µs threshold"


@pytest.mark.asyncio
async def test_benchmark_aes_gcm_encryption_performance():
    """Benchmark AES-256-GCM field encryption performance across 1,000 iterations."""
    ws_id = uuid.uuid4()
    secret = "ComplexSyntheticPass_xyz!@#998877"
    iterations = 1000

    t0 = time.perf_counter()
    for _ in range(iterations):
        encrypt_field(secret, workspace_id=ws_id)
    total_time = time.perf_counter() - t0

    avg_us = (total_time / iterations) * 1_000_000
    ops_per_sec = iterations / total_time

    print(f"\n[AURA-1003 Benchmark] AES-256-GCM Encrypt: {avg_us:.2f} µs/op | {ops_per_sec:,.0f} ops/sec")
    assert avg_us < 500.0, f"Encryption average latency ({avg_us:.2f}µs) exceeded 500µs threshold"


@pytest.mark.asyncio
async def test_benchmark_aes_gcm_decryption_performance():
    """Benchmark AES-256-GCM field decryption and tag verification across 1,000 iterations."""
    ws_id = uuid.uuid4()
    secret = "ComplexSyntheticPass_xyz!@#998877"
    ciphertext = encrypt_field(secret, workspace_id=ws_id)
    iterations = 1000

    t0 = time.perf_counter()
    for _ in range(iterations):
        decrypted = decrypt_field(ciphertext, workspace_id=ws_id)
    total_time = time.perf_counter() - t0

    avg_us = (total_time / iterations) * 1_000_000
    ops_per_sec = iterations / total_time

    assert decrypted == secret
    print(f"\n[AURA-1003 Benchmark] AES-256-GCM Decrypt: {avg_us:.2f} µs/op | {ops_per_sec:,.0f} ops/sec")
    assert avg_us < 500.0, f"Decryption average latency ({avg_us:.2f}µs) exceeded 500µs threshold"


@pytest.mark.asyncio
async def test_benchmark_vault_service_crud_and_storage_state(db_session):
    """Benchmark WebVaultService database operations and encrypted storage state cycles."""
    ws_id = uuid.uuid4()
    origin = "https://benchmark.corp.internal"

    # Benchmark Credential Creation
    t0 = time.perf_counter()
    cred_meta = await web_vault_service.create_credential(
        db=db_session,
        workspace_id=ws_id,
        name="Bench Cred",
        target_origin=origin,
        username="bench_user@corp.internal",
        password="BenchPassword9988!!",
    )
    t_create_ms = (time.perf_counter() - t0) * 1000.0

    # Benchmark Metadata List
    t0 = time.perf_counter()
    creds = await web_vault_service.list_credentials(db=db_session, workspace_id=ws_id)
    t_list_ms = (time.perf_counter() - t0) * 1000.0

    # Benchmark Session State Save & Encrypt
    mock_state = {"cookies": [{"name": f"c_{i}", "value": f"val_{i}"} for i in range(20)]}
    t0 = time.perf_counter()
    saved = await web_vault_service.save_session_state(
        db=db_session,
        workspace_id=ws_id,
        session_name="bench_session",
        target_origin=origin,
        storage_state=mock_state,
    )
    t_save_sess_ms = (time.perf_counter() - t0) * 1000.0

    # Benchmark Session State Get & Decrypt
    t0 = time.perf_counter()
    retrieved = await web_vault_service.get_session_state(
        db=db_session,
        workspace_id=ws_id,
        target_origin=origin,
        session_name="bench_session",
    )
    t_get_sess_ms = (time.perf_counter() - t0) * 1000.0

    assert len(creds) == 1
    assert len(retrieved["cookies"]) == 20

    print(
        f"\n[AURA-1003 Benchmark] DB Ops: Create Credential: {t_create_ms:.2f}ms | "
        f"List Metadata: {t_list_ms:.2f}ms | Save Session State: {t_save_sess_ms:.2f}ms | "
        f"Get/Decrypt Session: {t_get_sess_ms:.2f}ms"
    )

    assert t_create_ms < 200.0
    assert t_list_ms < 50.0
    assert t_save_sess_ms < 200.0
    assert t_get_sess_ms < 50.0
