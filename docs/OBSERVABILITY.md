# Observability & Tracing Specification (OBSERVABILITY.md)
## Project Name: AURA (Autonomous Universal Reactive Agent)
**Document Version:** 9.6.0  
**Phase:** Phase 9 — Governed OS & Hardware Automation (COMPLETE & ACCEPTED) | Phase 1–9 Master Validated  
**Classification:** Telemetry, Tracing & Audit Architecture  

---

## 1. Agent Execution Trace Hierarchy

Every cognitive run in AURA is captured as a hierarchical OpenTelemetry-compatible trace:

```
+====================================================================================================+
| TRACE: Task Execution (TaskID: 4a12ec21..., UserGoal: "Audit Repository Security")                 |
+====================================================================================================+
  ├── SPAN 1: Context Assembly & Memory Recall (Duration: 45ms)
  │   ├── Sub-span: FastEmbed Hybrid Search (Vector cosine top-k=5, Postgres FTS top-k=5)
  │   └── Sub-span: PostgreSQL Session History Hydration
  │
  ├── SPAN 2: Supervisor Planning DAG Generation (Duration: 1.2s, Model: qwen2.5:7b-instruct)
  │   ├── Token Usage: 850 in / 320 out (Cost: $0.00 / Local)
  │   └── Output: 3 DAG Steps Generated
  │
  ├── SPAN 3: Step 1 Execution - Scan Directory (Duration: 420ms)
  │   ├── Sub-span: Risk Policy Evaluation (Result: LOW, Auto-Approved)
  │   └── Sub-span: Tool Call: list_dir(path="./src") -> Sandbox
  │
  ├── SPAN 4: Step 2 Execution - Check Dependencies (Duration: 3.2s)
  │   ├── Sub-span: Tool Call: read_file(path="package.json")
  │   ├── Sub-span: Model Step Verification (Passed)
  │   └── Sub-span: Tool Call: sandboxed_linter()
  │
  ├── SPAN 5: Step 3 Execution - Generate Summary Report (Duration: 2.1s)
  │   └── Sub-span: Tool Call: write_file(path="./audit/security.md")
  │
  ├── SPAN 6: Step Verification & Post-Conditions Check (Duration: 650ms)
  │
  └── SPAN 7: Memory Writeback & Telemetry Flush (Duration: 80ms)
      ├── Sub-span: FastEmbed Memory Ingestion & Vector Indexing
      └── Sub-span: PostgreSQL Task State Transition to COMPLETED
```

---

## 2. Key Metrics & Telemetry Dimensions

```
+----------------------------------------------------------------------------------------------------+
|                                      CORE TELEMETRY METRICS                                        |
+------------------------------------+-----------------------------+---------------------------------+
| METRIC NAME                        | TYPE                        | DESCRIPTION                     |
+------------------------------------+-----------------------------+---------------------------------+
| `aura_task_duration_seconds`       | Histogram                   | End-to-end task duration.       |
| `aura_tokens_total`                | Counter (Labels: in, out)   | Total LLM token consumption.    |
| `aura_cost_cents_total`            | Counter (Label: model)      | Total financial expenditure.    |
| `aura_tool_execution_duration_ms`  | Histogram (Label: tool)     | Latency per tool invocation.    |
| `aura_tool_error_rate`             | Gauge (Label: tool)         | Error rate per tool.            |
| `aura_approval_wait_seconds`       | Histogram                   | Time spent waiting for HITL.    |
| `aura_memory_recall_relevance`     | Histogram                   | Semantic relevance score.       |
| `aura_kill_switch_events_total`    | Counter                     | Emergency circuit breaker count.|
+------------------------------------+-----------------------------+---------------------------------+
```

---

## 3. Privacy, PII & Secret Redaction Pipeline

Before any trace, prompt log, or tool output is persisted to PostgreSQL, Langfuse, or external telemetry collectors, it passes through an automated **Redaction Sanitizer**:

```
[Raw Tool Output / LLM Generation]
                 │
                 ▼
[1. Regex Redactor: API Keys, Bearer Tokens, Passwords, SSH Keys]
    - Replaced with `[REDACTED_SECRET]`
                 │
                 ▼
[2. PII Entity Detector (Presidio / Fast Named Entity Regex)]
    - Detects: Credit Card numbers, SSNs, Private Phone Numbers
    - Replaced with `[REDACTED_PII]`
                 │
                 ▼
[3. User Privacy Boundary Check]
    - If `workspace.settings.privacy_mode == "strict"`, prompt bodies are hashed and only token counts are saved.
                 │
                 ▼
[Persisted to Telemetry Storage / Web Dashboard]
```

---

## 4. Phase 6 File Ingestion Tracing & Audit Events

Phase 6 instruments the entire file lifecycle with OpenTelemetry distributed spans and immutable SHA-256 audit ledger events:

### 4.1 Telemetry Spans
* `file.upload` — File size, MIME type, SHA-256 hash (file contents never exported to spans).
* `file.extract` — Parser type (`pypdf`, `python-docx`, `openpyxl`, `Pillow`), extraction duration, page count / cell count.
* `file.chunk` — Chunk count, token distribution, chunking strategy.
* `file.embed` — FastEmbed batch size, ONNX inference latency, embedding dimensions (768-dim).
* `file.search` — Hybrid query latency, top-k results, similarity distribution.

### 4.2 Immutable Audit Ledger Actions
* `file.uploaded` — Record creation with original filename, safe filename, size, and hash.
* `file.parsed` — Extraction completion with parser version, status, and metadata.
* `file.quarantined` — Security screening flags (e.g. zip-bomb detection, oversized payload).
* `file.indexed` — Vector embedding generation and chunk persistence in `file_chunks`.
* `file.deleted` — File deletion, physical disk purge, and vector cascade deletion.

