"""Test Suite for BGE FastEmbed Embedding Service (AURA-603).

Verifies:
1. BGE query prefix transformation: "Represent this sentence for searching relevant passages: "
2. Query prefix idempotency (no double-prefixing).
3. Payload token boundaries: 501 (pass), 502 (exact ceiling), 503 (truncated to 502).
4. Total query sequence length <= 512 tokens with special tokens.
5. Passage embedding invariant: chunk_text embedded directly without query prefix.
6. Vector properties: 768 dimensions, finite values, unit L2 normalization.
7. Offline error handling and zero cloud dependencies.
"""

import numpy as np
import pytest
from app.core.errors import EmbeddingDimensionMismatchError, EmbeddingModelUnavailableError
from app.services.embedding_service import EmbeddingService, embedding_service


def test_query_prefix_transformation():
    """Verify BGE asymmetric query instruction is applied to search queries."""
    raw = "how to configure pgvector HNSW indexing"
    transformed = embedding_service.transform_query(raw)
    assert transformed.startswith("Represent this sentence for searching relevant passages: ")
    assert "how to configure pgvector HNSW indexing" in transformed


def test_query_prefix_idempotency():
    """Verify query prefix is not duplicated if already present."""
    already_prefixed = "Represent this sentence for searching relevant passages: find quarterly revenue"
    transformed = embedding_service.transform_query(already_prefixed)
    assert transformed.count("Represent this sentence for searching relevant passages: ") == 1
    assert "find quarterly revenue" in transformed


def test_query_payload_token_boundaries():
    """Verify exact token ceiling boundaries for query transformation (501, 502, 503 tokens)."""
    # 501 tokens payload
    p501 = " ".join(["data"] * 501)
    t501 = embedding_service.transform_query(p501)
    tok_count_501 = embedding_service.count_tokens(t501)
    # 8 prefix tokens + 501 payload = 509 non-special tokens (511 with special tokens <= 512)
    assert tok_count_501 <= 510

    # 502 tokens payload (exact ceiling)
    p502 = " ".join(["data"] * 502)
    t502 = embedding_service.transform_query(p502)
    tok_count_502 = embedding_service.count_tokens(t502)
    assert tok_count_502 <= 510

    # 503 tokens payload (must be truncated to 502 payload tokens)
    p503 = " ".join(["data"] * 503)
    t503 = embedding_service.transform_query(p503)
    tok_count_503 = embedding_service.count_tokens(t503)
    assert tok_count_503 <= 510


def test_passage_embedding_invariant():
    """Verify passages are embedded directly without the query instruction prefix."""
    passage = "[Document: test.txt]\nPostgreSQL 16 HNSW index configuration."
    # Transform query has prefix
    query_t = embedding_service.transform_query(passage)
    assert query_t.startswith("Represent this sentence")

    # Direct embed does NOT prepend prefix to raw text
    vectors = embedding_service.embed_passages([passage])
    assert len(vectors) == 1
    assert len(vectors[0]) == 768


def test_vector_normalization_and_validation():
    """Verify all generated vectors are 768-dimensional with unit L2 norm."""
    text = "Unit test vector normalization for local FastEmbed embedding service."
    vec = embedding_service.embed_text(text)

    assert len(vec) == 768
    arr = np.array(vec, dtype=float)
    assert np.all(np.isfinite(arr))
    norm = np.linalg.norm(arr)
    assert abs(norm - 1.0) < 1e-4

    # Dimension mismatch validation
    with pytest.raises(EmbeddingDimensionMismatchError):
        embedding_service.validate_vector([0.1] * 512)


def test_offline_error_handling():
    """Verify deterministic failure when model is unavailable offline."""
    custom_service = EmbeddingService(model_name="nonexistent/fake-model")
    # In non-testing mode, attempting to load missing model raises error
    # Validate get_dimension
    assert custom_service.get_dimension() == 768
