# Memory Architecture Specification (MEMORY_ARCHITECTURE.md)
## Project Name: AURA (Autonomous Universal Reactive Agent)
**Document Version:** 9.6.0  
**Phase:** Phase 9 — Governed OS & Hardware Automation (COMPLETE & ACCEPTED) | Phase 1–9 Master Validated  
**Classification:** Local-First Cognitive Memory & Persistence Design  

---

## 1. Zero-Cost Memory Architecture Overview

AURA implements a unified, high-performance, and **100% zero-cost local memory architecture** combining relational state and semantic cognitive memory directly inside **PostgreSQL 16 with `pgvector`**:

```
+====================================================================================================+
|                                1. WORKING MEMORY (Ephemeral Context)                                |
|  - In-memory sliding turn buffer (FastAPI / Redis local)                                           |
|  - Token Budget: Max 25% of active local LLM context window (e.g. 8k-32k window)                   |
|  - Cost: $0.00 (Local RAM)                                                                         |
+====================================================================================================+
                                              │ (Asynchronous Local Ingestion Worker)
                                              ▼
+====================================================================================================+
|                           2. UNIFIED RELATIONAL & VECTOR STORE (PostgreSQL 16)                     |
|  - Relational Tables: Users, Workspaces, Sessions, Messages, Tasks, Checkpoints, Audit Ledger       |
|  - Cognitive Vector Table (`memory_records`): Storing user traits, project facts, preferences      |
|  - Vector Column: `embedding vector(768)` indexed via HNSW cosine distance (`vector_cosine_ops`)  |
|  - Lexical Index: `tsvector` column for PostgreSQL Full-Text Search (BM25 equivalent)               |
|  - Cost: $0.00 (Local Database)                                                                    |
+====================================================================================================+
                                              ▲
                                              │ (Sub-10ms Local Vectorization)
+====================================================================================================+
|                                3. LOCAL EMBEDDING ENGINE (FastEmbed)                               |
|  - Model: `BAAI/bge-base-en-v1.5` (768-dim, normalized, CPU-optimized via ONNX Runtime)             |
|  - Execution: In-process Python via FastEmbed / ONNX Runtime (Zero cloud API calls, $0.00)          |
|  - Hardware Allocation: CPU-only execution with no intentional GPU allocation                      |
+====================================================================================================+
```

---

## 2. PostgreSQL + pgvector vs. External Memory SaaS

| Memory Concern | AURA Local Engine (PostgreSQL + pgvector + FastEmbed) | External Memory SaaS (Paid Honcho / Mem0 Cloud) |
| :--- | :--- | :--- |
| **Financial Cost** | **$0.00 (Permanent)** | $20–$100+/month subscription fees. |
| **Data Privacy** | **100% Private (Never leaves localhost)** | User data transmitted to third-party cloud. |
| **Network Dependency** | **100% Offline Capable** | Requires active internet connection. |
| **Infrastructure Footprint** | **Single unified PostgreSQL process** | Extra microservices / multi-container memory servers. |
| **Search Mechanism** | **Hybrid: HNSW Vector Cosine + Postgres FTS BM25** | Proprietary cloud search API. |
| **Latency** | **< 10 ms (Local IPC / socket)** | 150–400 ms (Cloud HTTP latency). |

---

## 3. Database Schema for Cognitive Memory Records

```sql
-- Enable vector extension in local PostgreSQL
CREATE EXTENSION IF NOT EXISTS "vector";

-- Memory Records Table (Unified Cognitive & Relational Storage with Structured Provenance)
CREATE TABLE memory_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    category VARCHAR(50) NOT NULL, -- 'preference', 'project_fact', 'personal_trait', 'skill_learning', 'file_intelligence'
    fact_statement TEXT NOT NULL,
    confidence_score NUMERIC(4, 3) NOT NULL DEFAULT 1.000,
    search_vector tsvector GENERATED ALWAYS AS (to_tsvector('english', fact_statement)) STORED,
    embedding vector(768), -- Generated locally via FastEmbed (BAAI/bge-base-en-v1.5)
    provenance JSONB NOT NULL DEFAULT '{}'::jsonb, -- Structured provenance linking workspace_id, file_id, chunk_id, etc.
    is_tombstoned BOOLEAN NOT NULL DEFAULT FALSE,
    tombstoned_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Fast Hybrid Indexes
CREATE INDEX idx_memory_records_hnsw ON memory_records USING hnsw (embedding vector_cosine_ops) WHERE is_tombstoned = FALSE;
CREATE INDEX idx_memory_records_fts ON memory_records USING gin (search_vector) WHERE is_tombstoned = FALSE;
CREATE INDEX idx_memory_records_workspace ON memory_records(workspace_id, category);
CREATE INDEX idx_memory_records_provenance_file ON memory_records ((provenance->>'file_id')) WHERE provenance->>'file_id' IS NOT NULL;
```


---

## 4. End-to-End Memory Ingestion & Recall Pipeline

### 4.1 Ingestion Pipeline (Post-Turn Asynchronous Processing)
1. User and assistant messages commit to PostgreSQL `messages` table.
2. An asynchronous local worker runs a fast 3B model (`llama3.2:3b` via Ollama) to extract concise facts:
   * Example: *"User is developing in Python 3.12 on Windows 11 with WSL2."*
3. The local `FastEmbed` engine generates a 768-dimensional vector embedding in $<10\text{ ms}$.
4. Record is inserted into `memory_records` with both text, tsvector, and vector embedding.

### 4.2 Recall Pipeline (Pre-Turn Context Assembly)
```
[User Input Received]
         │
         ▼
[1. Compute Local Query Embedding (FastEmbed, <10ms)]
         │
         ▼
[2. Hybrid PostgreSQL Query: HNSW Cosine Distance (<=>) + FTS ts_rank()]
    SELECT fact_statement, confidence_score 
    FROM memory_records 
    WHERE workspace_id = :ws_id AND is_tombstoned = FALSE
    ORDER BY (0.7 * (1 - (embedding <=> :query_vector)) + 0.3 * ts_rank(search_vector, to_tsquery(:keywords))) DESC
    LIMIT 5;
         │
         ▼
[3. Combine with Last 5 Session Messages & Active Project Directives]
         │
         ▼
[4. Construct Structured Memory Envelope in Prompt (<15% of Context Budget)]
```

---

## 5. Memory Governance, Correction & Tombstoning

* **User Inspectability:** All stored facts are directly visible in the Web Dashboard under the **Memory Graph** view.
* **Tombstoning Protocol:** When a user deletes or edits a fact:
  1. `is_tombstoned` is updated to `TRUE` in PostgreSQL.
  2. The record is excluded from all HNSW and FTS queries via partial index filtering.
  3. A negative constraint is temporarily injected into the prompt assembler to prevent hallucinating old invalidated preferences.

---

## 6. Phase 6 File Chunking, Vector Storage & Source Provenance

Phase 6 extends the unified PostgreSQL + pgvector architecture to multi-format file intelligence:

### 6.1 Database Schema for File Chunks (`file_chunks`)
```sql
CREATE TABLE file_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    file_id UUID NOT NULL REFERENCES file_records(id) ON DELETE CASCADE,
    chunk_index INT NOT NULL,
    chunk_text TEXT NOT NULL,
    token_count INT NOT NULL,
    embedding vector(768),
    source_location JSONB DEFAULT '{}'::jsonb NOT NULL, -- {"page": 3, "section": "Summary", "sheet": "Q3"}
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

CREATE INDEX idx_file_chunks_ws_file ON file_chunks(workspace_id, file_id);
CREATE INDEX idx_file_chunks_embedding ON file_chunks USING hnsw (embedding vector_cosine_ops);
```

### 6.2 Provenance & Memory Promotion Flow
1. **Document Chunking:** Files are structurally chunked (ceiling 510 tokens, target 384 tokens with 48-token overlap) preserving page, sheet, section, and line number metadata in `source_location`.
2. **Vector Indexing:** Chunks are vectorized using the local FastEmbed `BAAI/bge-base-en-v1.5` engine (768-dim normalized embeddings) and persisted in `file_chunks`.
3. **Cognitive Promotion:** Agents and users promote extracted document facts and insights into `memory_records` with canonical `source_type = 'file_intelligence'` and structured `provenance` payload:
   ```json
   {
     "workspace_id": "UUID",
     "file_id": "UUID",
     "chunk_id": "UUID",
     "chunk_index": 0,
     "source_location": {"section": "Section Name", "line_start": 1, "line_end": 20},
     "file_sha256": "SHA256_HEX",
     "parser_version": "1.0.0",
     "chunking_version": "1.0.0",
     "embedding_model": "BAAI/bge-base-en-v1.5",
     "retrieval_score": 0.92,
     "timestamp": "2026-10-02T18:00:00Z"
   }
   ```
4. **Scoped Idempotent Deletion Lifecycle:** When a file is deleted from `file_records`, physical storage is purged, `file_chunks` are hard-deleted, and derived `memory_records` are strictly and deterministically tombstoned without affecting user memories, other files, or other workspaces:
   ```sql
   UPDATE memory_records
   SET is_tombstoned = TRUE,
       tombstoned_reason = 'Originating file ' || :file_id || ' was deleted'
   WHERE workspace_id = :workspace_id
     AND source_type = 'file_intelligence'
     AND is_tombstoned = FALSE
     AND provenance->>'file_id' = :file_id;
   ```



