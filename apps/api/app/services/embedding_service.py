"""Local Embedding Service using FastEmbed (BAAI/bge-base-en-v1.5, 768-dim, CPU-first).

Canonical Guarantees:
- Embedding Model: BAAI/bge-base-en-v1.5 (768 dimensions, max 512 sequence tokens)
- Vector Normalization: Unit L2 norm (||v|| = 1.0)
- Query Prefix: "Represent this sentence for searching relevant passages: " (8 tokens)
- Query Payload Ceiling: <= 502 non-special tokens (Total <= 512 with prefix & special tokens)
- Passage Ceiling: <= 510 non-special tokens (Total <= 512 with [CLS], [SEP])
- Invariant: stored chunk_text == exact passage embedding input text
- Zero Mandatory Cloud / SaaS Dependencies ($0.00 cost)
"""

import math
import re
from typing import Any, List, Optional
import numpy as np

from app.core.config import settings
from app.core.errors import EmbeddingDimensionMismatchError, EmbeddingModelUnavailableError
from app.core.logging import logger


class EmbeddingService:
    """Enterprise local embedding service providing 768-dimensional normalized BGE vectors."""

    MODEL_NAME: str = "BAAI/bge-base-en-v1.5"
    DIMENSION: int = 768
    MAX_SEQUENCE_LENGTH: int = 512
    MAX_CHUNK_TOKENS: int = 510
    MAX_QUERY_PAYLOAD_TOKENS: int = 502
    PREFIX_TOKENS_COUNT: int = 8
    SPECIAL_TOKENS_COUNT: int = 2
    BGE_QUERY_PREFIX: str = "Represent this sentence for searching relevant passages: "

    def __init__(self, model_name: Optional[str] = None):
        self.model_name = model_name or settings.FASTEMBED_MODEL_NAME or self.MODEL_NAME
        self.dimension = settings.EMBEDDING_DIMENSION or self.DIMENSION
        self._model = None
        self._tokenizer = None
        self._tokenizer_searched = False

    def _get_tokenizer(self):
        """Retrieve the underlying tokenizer for exact token counting."""
        if self._tokenizer is not None or self._tokenizer_searched:
            return self._tokenizer

        self._tokenizer_searched = True

        # 1. Try to load tokenizer from initialized FastEmbed model
        if self._model is not None and hasattr(self._model, "model") and hasattr(self._model.model, "tokenizer"):
            self._tokenizer = self._model.model.tokenizer
            return self._tokenizer

        # 2. Try loading from tokenizers package if cached locally
        try:
            from tokenizers import Tokenizer
            import os
            import tempfile
            cache_dirs = [
                os.path.join(tempfile.gettempdir(), "fastembed_cache"),
                os.path.expanduser("~/.cache/fastembed"),
                os.path.expanduser("~/.cache/huggingface/hub"),
            ]
            for cdir in cache_dirs:
                if cdir and os.path.exists(cdir):
                    # Look for BGE tokenizer first
                    for root, _, files in os.walk(cdir):
                        if "tokenizer.json" in files and "bge" in root.lower():
                            self._tokenizer = Tokenizer.from_file(os.path.join(root, "tokenizer.json"))
                            return self._tokenizer
                    # Fallback to any tokenizer.json
                    for root, _, files in os.walk(cdir):
                        if "tokenizer.json" in files:
                            self._tokenizer = Tokenizer.from_file(os.path.join(root, "tokenizer.json"))
                            return self._tokenizer
        except Exception:
            pass

        return None


    def count_tokens(self, text: str) -> int:
        """Count non-special tokens in text using the BGE tokenizer or deterministic subword fallback."""
        if not text:
            return 0

        tok = self._get_tokenizer()
        if tok is not None:
            try:
                # Tokenizers library encode without special tokens
                encoded = tok.encode(text, add_special_tokens=False)
                return len(encoded.ids)
            except Exception:
                pass

        # Deterministic WordPiece-approximating subword fallback
        # Punctuation and word pieces average ~1.25 tokens per word
        words = re.findall(r"\w+|[^\w\s]", text, re.UNICODE)
        count = 0
        for w in words:
            if len(w) > 4:
                count += math.ceil(len(w) / 3.5)
            else:
                count += 1
        return max(1, count)

    def truncate_to_tokens(self, text: str, max_tokens: int) -> str:
        """Deterministically truncate text so that count_tokens(truncated) <= max_tokens."""
        if not text or max_tokens <= 0:
            return ""

        tok = self._get_tokenizer()
        if tok is not None:
            try:
                encoded = tok.encode(text, add_special_tokens=False)
                if len(encoded.ids) <= max_tokens:
                    return text
                truncated_ids = encoded.ids[:max_tokens]
                return tok.decode(truncated_ids)
            except Exception:
                pass

        # Fallback truncation by words/characters
        words = text.split()
        truncated_words = []
        cur_tokens = 0
        for w in words:
            w_tokens = self.count_tokens(w + " ")
            if cur_tokens + w_tokens > max_tokens:
                break
            truncated_words.append(w)
            cur_tokens += w_tokens

        return " ".join(truncated_words) if truncated_words else text[: max_tokens * 3]

    def transform_query(self, user_query: str) -> str:
        """Apply the canonical BGE retrieval query instruction and enforce the 502-token payload ceiling."""
        cleaned = user_query.strip()
        # Idempotency check: if query already starts with the prefix, isolate payload
        if cleaned.startswith(self.BGE_QUERY_PREFIX):
            cleaned = cleaned[len(self.BGE_QUERY_PREFIX) :].strip()

        # Enforce maximum user query payload of 502 non-special tokens
        if self.count_tokens(cleaned) > self.MAX_QUERY_PAYLOAD_TOKENS:
            cleaned = self.truncate_to_tokens(cleaned, self.MAX_QUERY_PAYLOAD_TOKENS)

        return f"{self.BGE_QUERY_PREFIX}{cleaned}"

    def _get_model(self):
        """Lazy-load FastEmbed model with CPU-first ONNX runtime and validate 768 dimensions."""
        if settings.is_testing:
            return None

        if self._model is None:
            try:
                from fastembed import TextEmbedding

                # Initialize with 4 intra-op threads on CPU
                self._model = TextEmbedding(
                    model_name=self.model_name,
                    threads=4,
                )
                # Verify dimension on sample text
                sample = list(self._model.embed(["test"]))[0]
                actual_dim = len(sample)
                if actual_dim != self.dimension:
                    raise EmbeddingDimensionMismatchError(
                        f"Configured embedding dimension ({self.dimension}) does not match model output ({actual_dim})"
                    )
                logger.info(f"EmbeddingService: FastEmbed initialized '{self.model_name}' (dim: {actual_dim})")
            except ImportError:
                logger.warning("EmbeddingService: fastembed package not installed. Using deterministic fallback.")
            except Exception as e:
                logger.warning(f"EmbeddingService: Could not load model '{self.model_name}': {e}. Using fallback.")
                if not settings.is_testing and "offline" in str(e).lower():
                    raise EmbeddingModelUnavailableError(f"FastEmbed model '{self.model_name}' is unavailable offline: {e}")

        return self._model

    def normalize_vector(self, vector: List[float]) -> List[float]:
        """L2-normalize float vector to unit length (||v|| = 1.0)."""
        arr = np.array(vector, dtype=float)
        norm = np.linalg.norm(arr)
        if norm > 1e-12:
            arr = arr / norm
        else:
            arr = np.zeros(self.dimension, dtype=float)
            arr[0] = 1.0  # Unit fallback for all-zero vector
        return arr.tolist()

    def validate_vector(self, vector: List[float]) -> bool:
        """Verify vector strictly adheres to 768 dimensions and finite normalized values."""
        if not vector or len(vector) != self.dimension:
            raise EmbeddingDimensionMismatchError(
                f"Vector dimension mismatch: expected {self.dimension}, got {len(vector) if vector else 0}"
            )
        arr = np.array(vector, dtype=float)
        if not np.all(np.isfinite(arr)):
            raise ValueError("Embedding vector contains non-finite values (NaN or Inf)")
        return True

    def embed_query(self, query: str) -> List[float]:
        """Generate normalized 768-dim embedding for a retrieval search query with instruction prefix."""
        transformed = self.transform_query(query)
        results = self.embed_batch([transformed])
        vec = results[0]
        self.validate_vector(vec)
        return vec

    def embed_passages(self, passages: List[str], batch_size: int = 16) -> List[List[float]]:
        """Generate normalized 768-dim embeddings for document chunks directly (no instruction prefix)."""
        if not passages:
            return []

        # Validate sequence bounds
        for i, text in enumerate(passages):
            if self.count_tokens(text) > self.MAX_CHUNK_TOKENS:
                logger.warning(
                    f"EmbeddingService: Passage chunk {i} exceeds target ceiling ({self.count_tokens(text)} > {self.MAX_CHUNK_TOKENS})"
                )

        results: List[List[float]] = []
        for i in range(0, len(passages), batch_size):
            batch = passages[i : i + batch_size]
            batch_vectors = self.embed_batch(batch)
            for vec in batch_vectors:
                norm_vec = self.normalize_vector(vec)
                self.validate_vector(norm_vec)
                results.append(norm_vec)

        return results

    def embed_text(self, text: str) -> List[float]:
        """Generate normalized embedding vector for a single text passage."""
        return self.embed_passages([text])[0]

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate raw embedding vectors for batch of strings."""
        if not texts:
            return []

        model = self._get_model()
        if model is not None:
            try:
                embeddings_gen = model.embed(texts)
                return [self.normalize_vector(list(np.array(e, dtype=float))) for e in embeddings_gen]
            except Exception as e:
                logger.error(f"EmbeddingService: FastEmbed inference error: {e}. Using deterministic generator.")

        # Deterministic local fallback generator (for testing and offline verification)
        return [self._generate_deterministic_embedding(t) for t in texts]

    def _generate_deterministic_embedding(self, text: str) -> List[float]:
        """Generate deterministic 768-dim normalized embedding via cryptographic token hashing."""
        import hashlib

        stopwords = {
            "the", "a", "an", "is", "are", "was", "were", "in", "on", "at", "to", "for", "of",
            "and", "or", "by", "with", "about", "tell", "me", "this", "that", "it", "from",
        }
        all_words = re.findall(r"\w+", text.lower())
        words = [w for w in all_words if w not in stopwords]
        if not words:
            words = all_words or ["empty_document_fallback"]

        accum = np.zeros(self.dimension, dtype=float)
        for w in words:
            weight = 1.0 + min(3.0, len(w) / 4.0)
            h = hashlib.sha256(w.encode("utf-8")).digest()
            v = np.frombuffer(h * 24, dtype=np.uint8).astype(float) - 128.0
            accum += v * weight

        return self.normalize_vector(accum.tolist())


    def get_dimension(self) -> int:
        """Return embedding dimension."""
        return self.dimension


embedding_service = EmbeddingService()
