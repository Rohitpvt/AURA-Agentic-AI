"""Performance Benchmarks for AURA-1004 Governed Browser File Transfers."""

import asyncio
from pathlib import Path
import time
import uuid
from unittest.mock import AsyncMock, patch
import pytest
import httpx

from app.core.filesystem import filesystem_guard
from app.db.models.file import FileRecord, FileStatus
from app.services.browser.file_transfer import (
    browser_file_transfer_service,
    is_sensitive_file,
    sanitize_url_provenance,
)


@pytest.mark.asyncio
async def test_benchmark_sanitize_url_provenance_performance():
    """Benchmark URL provenance sanitization under high iteration volume."""
    test_urls = [
        "https://example.com/api/v1/download?token=secret_jwt_token_12345&auth=bearer_9988&doc_id=123",
        "https://sub.domain.corp/files/report.pdf?key=abc123456789&sig=signature_hash_999",
        "https://public.cdn.org/images/logo.png",
        "https://portal.service.internal/fetch?user=alice&session=sess_abcdef123456&role=admin",
    ]

    iterations = 5000
    start = time.perf_counter()
    for i in range(iterations):
        url = test_urls[i % len(test_urls)]
        sanitized = sanitize_url_provenance(url)
        assert "%5BREDACTED%5D" in sanitized or "[REDACTED]" in sanitized or "public.cdn.org" in sanitized
    elapsed = time.perf_counter() - start

    mean_ms = (elapsed / iterations) * 1000
    print(f"\n[BENCHMARK] URL Provenance Sanitization: {mean_ms:.4f} ms/op ({iterations} iterations in {elapsed:.4f}s)")
    assert mean_ms < 0.1, f"Sanitization latency {mean_ms:.4f} ms exceeds 0.1 ms threshold"


@pytest.mark.asyncio
async def test_benchmark_sensitive_file_screening_performance():
    """Benchmark sensitive file pattern matching under high volume."""
    test_filenames = [
        ".env",
        ".env.production",
        "master_key.txt",
        "credential_vault.sqlite",
        "id_rsa",
        "annual_report.pdf",
        "dataset.csv",
        "script.py",
        "app.db",
        "notes.txt",
    ]

    iterations = 10000
    start = time.perf_counter()
    for i in range(iterations):
        fn = test_filenames[i % len(test_filenames)]
        _ = is_sensitive_file(fn)
    elapsed = time.perf_counter() - start

    mean_ms = (elapsed / iterations) * 1000
    print(f"\n[BENCHMARK] Sensitive File Denylist Screening: {mean_ms:.5f} ms/op ({iterations} iterations in {elapsed:.4f}s)")
    assert mean_ms < 0.05, f"Screening latency {mean_ms:.5f} ms exceeds 0.05 ms threshold"


@pytest.mark.asyncio
async def test_benchmark_download_and_phase6_intake_latency(db_session):
    """Benchmark end-to-end download streaming, staging, and Phase 6 intake latency."""
    ws_id = uuid.uuid4()
    sample_content = b"Benchmark file payload content line.\n" * 100  # ~3.7 KB

    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_resp.url = "https://example.com/data.txt"
    mock_resp.headers = {"content-type": "text/plain"}

    async def _aiter_bytes(chunk_size=65536):
        yield sample_content

    mock_resp.aiter_bytes = _aiter_bytes
    mock_stream_ctx = AsyncMock()
    mock_stream_ctx.__aenter__.return_value = mock_resp
    mock_stream_ctx.__aexit__.return_value = None

    with patch.object(httpx.AsyncClient, "stream", return_value=mock_stream_ctx), \
         patch("app.core.network.ssrf_guard.validate_url", return_value=True):

        iterations = 10
        start = time.perf_counter()
        for i in range(iterations):
            res = await browser_file_transfer_service.download_file(
                db=db_session,
                workspace_id=ws_id,
                url=f"https://example.com/data_{i}.txt",
                suggested_filename=f"bench_data_{i}_{uuid.uuid4().hex[:6]}.txt",
            )
            assert res["status"] == "success"
        elapsed = time.perf_counter() - start

        mean_ms = (elapsed / iterations) * 1000
        print(f"\n[BENCHMARK] Download & Phase 6 Intake Latency: {mean_ms:.2f} ms/op ({iterations} iterations in {elapsed:.2f}s)")
        assert mean_ms < 500, f"Mean intake latency {mean_ms:.2f} ms exceeds 500 ms threshold"
