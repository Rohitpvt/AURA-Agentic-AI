# Project Memory & Architectural Index (PROJECT_MEMORY.md)
## Project Name: AURA (Autonomous Universal Reactive Agent)
**Document Version:** 3.0.0  
**Phase:** Phase 1 — Core Control Plane, Local DB, Memory, BYOK & Task Engine (COMPLETED)  
**Classification:** Living Architectural Knowledge Base  

---

## 1. Project Identity & Mission

* **Name:** AURA (Autonomous Universal Reactive Agent)
* **Tagline:** The Personal Agentic AI Operating System
* **Mission:** To empower individuals and teams with a proactive, self-learning, and secure cognitive operating system capable of autonomous task execution, multi-agent orchestration, and persistent contextual memory under strict deterministic human governance.

---

## 2. Core Architectural Invariants (Non-Negotiables)

1. **THE ZERO-COST INVARIANT (Hard Non-Negotiable):** The complete AURA core system must be buildable, runnable, and fully functional on consumer hardware without requiring any paid API, paid SaaS subscription, paid cloud platform, or per-use paid service. All cloud models and paid platforms are strictly optional Tier-3 adapters.
2. **Deterministic Safety over LLM Autonomy:** Large Language Models propose actions, generate plans, and synthesize findings. Code written in deterministic Python/SQL enforces permissions, risk boundaries, rate limits, and approvals. **The LLM never approves its own tools.**
3. **Decoupled Control Plane & Agent Runtime:** The Control Plane (FastAPI + PostgreSQL) owns state, users, auth, approvals, tasks, and scheduling. The Agent Runtime (Hermes Substrate) owns prompt formatting, reasoning loops, sub-agent spawning, and tool execution.
4. **Zero Secret Leakage:** No raw credentials, API keys, or private certificates may ever enter LLM context windows or prompt templates. Secrets are injected at the network proxy layer.
5. **Unified Local Relational & Vector Memory:** Local PostgreSQL 16 + `pgvector` + FastEmbed (`BAAI/bge-base-en-v1.5`, 768-dim) is the single source of truth for deterministic application state, task DAGs, and cognitive semantic recall.
6. **No Infinite Recursion or Unbounded Budgets:** Sub-agents are hard-capped at depth 2 and a maximum of 4 concurrent workers per task. Every task has strict local execution timeouts.
7. **Provider-Neutral Interface & Optional Secure BYOK:** The Agent Core communicates strictly with the abstract `ModelProvider` interface (`OllamaProvider` [default/zero-cost], `GeminiProvider` [optional BYOK]). BYOK credentials are encrypted at rest with AES-256-GCM, never exposed to clients or prompts, and subject to deterministic routing (`LOCAL_ONLY`, `BYOK_ONLY`, `AUTO`) with automatic fallback to local Ollama.

---

## 3. Standard Terminology & Glossary

* **Tool:** An atomic, stateless capability that takes structured input and produces deterministic output or an external side-effect (e.g., `web_search`, `read_file`, `github_create_issue`).
* **Skill:** A versioned procedural recipe (`SKILL.md`) that guides multi-turn reasoning and tool orchestration to achieve a complex goal (e.g., `repository_security_audit`).
* **Sub-Agent:** A specialized, isolated cognitive worker instance dispatched with a bounded budget and scoped tool access to execute a discrete sub-task.
* **HITL (Human-in-the-Loop):** A security gateway requiring an authorized user to cryptographically sign an approval token before a High or Critical risk tool can execute.
* **Autonomy Level (L0–L5):** The degree of unattended execution permitted for a task or automation, ranging from L0 (Chat Only) to L5 (Controlled Meta-Evolution).
* **MCP (Model Context Protocol):** The standardized open protocol used by AURA to discover, connect to, and execute external tool servers over `stdio` and `SSE`.

---

## 4. Codebase Directory Conventions (Planned Implementation)

```
/
├── apps/
│   ├── api/                 # FastAPI Control Plane Application
│   │   ├── app/
│   │   │   ├── api/v1/      # REST, SSE & Webhook Endpoints
│   │   │   ├── core/        # Config, Security, Policy Engine, Auth
│   │   │   ├── db/          # PostgreSQL SQLAlchemy Models & Alembic Migrations
│   │   │   ├── services/    # Memory (Honcho), Tasks, Tools, Skills, Approvals
│   │   │   └── workers/     # Background Scheduler & Task Queues (pg_boss)
│   │   └── tests/           # Unit & Integration Test Suites
│   │
│   ├── runtime/             # Agent Runtime Engine (Hermes Substrate)
│   │   ├── supervisor/      # Planner Agent & DAG Orchestrator
│   │   ├── subagents/       # Research, Coding, Analysis, Synthesis Workers
│   │   ├── gateway/         # LiteLLM Multi-Tier Model Router
│   │   ├── mcp/             # MCP Host Manager (stdio & SSE clients)
│   │   └── sandbox/         # Docker / Firejail Execution Interceptor
│   │
│   └── web/                 # Next.js 15 Web Dashboard
│       ├── app/             # App Router Pages (12 Core Views)
│       ├── components/      # UI Primitives (Radix/Shadcn) & DAG Visualizers
│       ├── hooks/           # Real-Time SSE Streams & TanStack Query Hooks
│       └── lib/             # API Client, Types, Zustand Stores
│
├── docs/                    # Master Architectural Specifications & Guides (26 Files)
└── packages/                # Shared Types, Tool Schemas, and Utilities
```

---

## 5. Canonical Documentation Map

| Domain / Responsibility | Canonical Authoritative Document |
| :--- | :--- |
| **Product Vision, Requirements & Scope** | [**docs/PRD.md**](file:///C:/Users/rghos/OneDrive%20-%20Vivekananda%20Institute%20of%20Professional%20Studies/PROJECTS/Agentic%20AI/docs/PRD.md) |
| **Software Design & State Machines** | [**docs/SDD.md**](file:///C:/Users/rghos/OneDrive%20-%20Vivekananda%20Institute%20of%20Professional%20Studies/PROJECTS/Agentic%20AI/docs/SDD.md) |
| **System Architecture & Topology** | [**docs/ARCHITECTURE.md**](file:///C:/Users/rghos/OneDrive%20-%20Vivekananda%20Institute%20of%20Professional%20Studies/PROJECTS/Agentic%20AI/docs/ARCHITECTURE.md) |
| **Technology Stack & Dependencies** | [**docs/TECH_STACK.md**](file:///C:/Users/rghos/OneDrive%20-%20Vivekananda%20Institute%20of%20Professional%20Studies/PROJECTS/Agentic%20AI/docs/TECH_STACK.md) |
| **Technical Requirements & Protocol Constraints** | [**docs/TRD.md**](file:///C:/Users/rghos/OneDrive%20-%20Vivekananda%20Institute%20of%20Professional%20Studies/PROJECTS/Agentic%20AI/docs/TRD.md) |
| **Database Schema & DDL** | [**docs/DATABASE_SCHEMA.md**](file:///C:/Users/rghos/OneDrive%20-%20Vivekananda%20Institute%20of%20Professional%20Studies/PROJECTS/Agentic%20AI/docs/DATABASE_SCHEMA.md) |
| **Agent Cognitive Loop & Subagents** | [**docs/AGENT_ARCHITECTURE.md**](file:///C:/Users/rghos/OneDrive%20-%20Vivekananda%20Institute%20of%20Professional%20Studies/PROJECTS/Agentic%20AI/docs/AGENT_ARCHITECTURE.md) |
| **Multi-Layer Cognitive Memory** | [**docs/MEMORY_ARCHITECTURE.md**](file:///C:/Users/rghos/OneDrive%20-%20Vivekananda%20Institute%20of%20Professional%20Studies/PROJECTS/Agentic%20AI/docs/MEMORY_ARCHITECTURE.md) |
| **Tool Registry & Execution Sandboxes** | [**docs/TOOL_ARCHITECTURE.md**](file:///C:/Users/rghos/OneDrive%20-%20Vivekananda%20Institute%20of%20Professional%20Studies/PROJECTS/Agentic%20AI/docs/TOOL_ARCHITECTURE.md) |
| **Procedural Skills & Evolution** | [**docs/SKILL_ARCHITECTURE.md**](file:///C:/Users/rghos/OneDrive%20-%20Vivekananda%20Institute%20of%20Professional%20Studies/PROJECTS/Agentic%20AI/docs/SKILL_ARCHITECTURE.md) |
| **Autonomy Levels (L0–L5) & Safety** | [**docs/AUTONOMY_MODEL.md**](file:///C:/Users/rghos/OneDrive%20-%20Vivekananda%20Institute%20of%20Professional%20Studies/PROJECTS/Agentic%20AI/docs/AUTONOMY_MODEL.md) |
| **Security, Threat Model & HITL** | [**docs/SECURITY_MODEL.md**](file:///C:/Users/rghos/OneDrive%20-%20Vivekananda%20Institute%20of%20Professional%20Studies/PROJECTS/Agentic%20AI/docs/SECURITY_MODEL.md) |
| **REST, SSE & Webhook API Contracts** | [**docs/API_SPECIFICATION.md**](file:///C:/Users/rghos/OneDrive%20-%20Vivekananda%20Institute%20of%20Professional%20Studies/PROJECTS/Agentic%20AI/docs/API_SPECIFICATION.md) |
| **Event & Automation Scheduling** | [**docs/EVENT_AND_AUTOMATION.md**](file:///C:/Users/rghos/OneDrive%20-%20Vivekananda%20Institute%20of%20Professional%20Studies/PROJECTS/Agentic%20AI/docs/EVENT_AND_AUTOMATION.md) |
| **Telemetry, Traces & Audit Ledger** | [**docs/OBSERVABILITY.md**](file:///C:/Users/rghos/OneDrive%20-%20Vivekananda%20Institute%20of%20Professional%20Studies/PROJECTS/Agentic%20AI/docs/OBSERVABILITY.md) |
| **Frontend Information Architecture & State** | [**docs/FRONTEND_ARCHITECTURE.md**](file:///C:/Users/rghos/OneDrive%20-%20Vivekananda%20Institute%20of%20Professional%20Studies/PROJECTS/Agentic%20AI/docs/FRONTEND_ARCHITECTURE.md) |
| **Frontend Visual Styling & Design System** | [**docs/FRONTEND_STYLE_ARCHITECTURE.md**](file:///C:/Users/rghos/OneDrive%20-%20Vivekananda%20Institute%20of%20Professional%20Studies/PROJECTS/Agentic%20AI/docs/FRONTEND_STYLE_ARCHITECTURE.md) |
| **Third-Party Integrations & MCP Protocol** | [**docs/INTEGRATION_PLAN.md**](file:///C:/Users/rghos/OneDrive%20-%20Vivekananda%20Institute%20of%20Professional%20Studies/PROJECTS/Agentic%20AI/docs/INTEGRATION_PLAN.md) |
| **User & System Interaction Flows** | [**docs/APP_FLOW.md**](file:///C:/Users/rghos/OneDrive%20-%20Vivekananda%20Institute%20of%20Professional%20Studies/PROJECTS/Agentic%20AI/docs/APP_FLOW.md) |
| **Phased Development Roadmap** | [**docs/ROADMAP.md**](file:///C:/Users/rghos/OneDrive%20-%20Vivekananda%20Institute%20of%20Professional%20Studies/PROJECTS/Agentic%20AI/docs/ROADMAP.md) |
| **Granular Work Breakdown Structure** | [**docs/TASK_BREAKDOWN.md**](file:///C:/Users/rghos/OneDrive%20-%20Vivekananda%20Institute%20of%20Professional%20Studies/PROJECTS/Agentic%20AI/docs/TASK_BREAKDOWN.md) |
| **Local Development Setup** | [**docs/SETUP_GUIDE.md**](file:///C:/Users/rghos/OneDrive%20-%20Vivekananda%20Institute%20of%20Professional%20Studies/PROJECTS/Agentic%20AI/docs/SETUP_GUIDE.md) |
| **Production Deployment & Operations** | [**docs/DEPLOYMENT_GUIDE.md**](file:///C:/Users/rghos/OneDrive%20-%20Vivekananda%20Institute%20of%20Professional%20Studies/PROJECTS/Agentic%20AI/docs/DEPLOYMENT_GUIDE.md) |
| **Pre-Release Browser QA Protocol** | [**docs/FINAL_BROWSER_CHECKLIST.md**](file:///C:/Users/rghos/OneDrive%20-%20Vivekananda%20Institute%20of%20Professional%20Studies/PROJECTS/Agentic%20AI/docs/FINAL_BROWSER_CHECKLIST.md) |
| **Architecture Decision Records (ADRs)** | [**docs/ARCHITECTURE_DECISIONS.md**](file:///C:/Users/rghos/OneDrive%20-%20Vivekananda%20Institute%20of%20Professional%20Studies/PROJECTS/Agentic%20AI/docs/ARCHITECTURE_DECISIONS.md) |
| **Project Entry Point** | [**README.md**](file:///C:/Users/rghos/OneDrive%20-%20Vivekananda%20Institute%20of%20Professional%20Studies/PROJECTS/Agentic%20AI/README.md) |

---

* **Phase 0 Status:** COMPLETED.
* **Phase 0.5 Status:** COMPLETED (Full Cross-Document Consistency Audit & Traceability Matrix verified).
* **Phase 1 Control Plane (AURA-101 to AURA-107):** **COMPLETED** (PostgreSQL 16 + pgvector schema, FastAPI Control Plane, JWT Auth & Tenancy, FastEmbed Memory, Multi-Tier Model Providers + Gemini BYOK Vault, Tool Registry + DDG Search, Task DAG & Checkpointing).
* **Phase 2A (AURA-201 & AURA-202):** **COMPLETED** (AURA-Native Cognitive Execution Engine, Supervisor Planner & DAG Generation, Agent Tool Governance Bridge, Observe-Decide-Act-Verify Loop, Local Ollama Default).
* **Phase 2B (AURA-203, AURA-204, AURA-205):** **COMPLETED** (Local MCP Host Subprocess Manager, Cryptographic HITL State Suspension & Resumption Engine, Bounded Local Sub-Agent Worker Pool, 57/57 tests passing).
* **Phase 2C (AURA-501 & AURA-503 Advance):** **COMPLETED** (Security & Runtime Hardening: Ephemeral Container Sandbox, Fail-Closed Host Policy, Filesystem Traversal Guard, SSRF Shield, MCP Executable Allowlist, Secret Redaction, SHA-256 Audit Ledger Verifier, Sub-15ms Emergency Kill Switch, 67/67 tests passing).
* **Phase 3 (AURA-301 to AURA-305):** **COMPLETED & VALIDATED** (Next.js 15 App Router Web Dashboard, 12 Core Views, SSE Streaming, HITL Drawer, Memory Editor, 12/12 Vitest passing, Static Prerender build passing).
* **Phase 4 Preflight:** **COMPLETED & CORRECTED** (Gemini model catalog locked, Next.js 15.1.7 security patch locked, PostgreSQL scheduler concurrency model refined, Webhook L4 autonomy bound, Telegram long-polling & Playwright SSRF boundaries locked).
* **Phase 4.1 (AURA-401):** **COMPLETED & ACCEPTED** (PostgreSQL Transactional Cron Scheduler, `FOR UPDATE SKIP LOCKED`, 15-minute lease model with orphan recovery, 3-strike circuit breaker with manual reset, exponential jitter retries, bounded missed-run policy, governed downstream Task DAG dispatch via `AgentToolBridge`, 82/82 backend tests passing).
* **Phase 4.2 (AURA-402):** **COMPLETED & ACCEPTED** (Inbound Webhook Reactive Gateway, HMAC-SHA256 signature verification, 300s freshness replay defense, 1MB payload ceiling, `(workspace, endpoint, idempotency_key)` deduplication, SSTI-safe template hydration, L4 autonomy containment, kill-switch suspension, 92/92 backend tests passing).
* **Phase 4.3 (AURA-403):** **COMPLETED & ACCEPTED** (Telegram Bot Long-Polling Integration, official Telegram Bot API zero-cost adapter, 15-minute one-time pairing, persistent update ID tracking, poller lease locks, governed `/goal`, `/status`, `/cancel`, and cryptographic `/approve`, live round-trip verified with `@Aura_Agentic_Bot`, 110/110 backend tests passing).
* **Phase 4.4 (AURA-404):** **COMPLETED & ACCEPTED** (Local Playwright Headless Web Extraction Tool `web_extract`, Chromium lifecycle pooling, multi-layer SSRF protection, streaming HTML-to-Markdown cleaner, 5MB response budget enforcement, untrusted output framing, 119/119 backend tests passing).
* **Phase 4 Master Release Gate:** **RELEASE VALIDATED** (All cross-layer integration, multi-tenancy, kill-switch, secret isolation, and regression tests passed: 119/119 backend pytest, 12/12 frontend vitest, 4/4 Next.js production pages built).
* **Phase 5 Preflight (AURA-505 to AURA-508):** **CORRECTED & LOCKED** (Reconciled milestone collisions with Phase 2C, mapped genuine remaining scope: AURA-505 Local OTel Tracing, AURA-506 Container Sandbox Hardening, AURA-507 Kill Switch Multi-Process Benchmarking, AURA-508 Indirect Prompt Injection Red-Teaming; locked Phases 6–10 long-term Jarvis capability roadmap).
* **Phase 5.1 (AURA-505):** **COMPLETED & ACCEPTED** (Local OpenTelemetry Distributed Tracing & Local Exporters, W3C traceparent propagation, centralized secret redaction & bounded attributes, fail-safe isolation, bidirectional audit correlation, canonical runtime path verification, 134/134 backend tests passing, 12/12 frontend tests passing, Next.js build passing).
* **Phase 5.2 (AURA-506):** **COMPLETED & ACCEPTED** (Production Docker / WSL2 Sandbox Operational Hardening; live target Windows 11 Docker Desktop + WSL2 runtime acceptance validated; cgroups v2 resource quotas, CPU/RAM/PID enforcement, fail-closed probes, read-only rootfs, isolated workspace volume mounts, and orphan reaper; 159/159 backend tests passing).
* **Phase 5.3 (AURA-507):** **COMPLETED & ACCEPTED** (Emergency Kill Switch Multi-Process Abort & Recovery Operational Hardening; cross-process persistent authority file synchronization, deep Windows 11 recursive process-tree termination for Python, Node.js, and Playwright Chromium with multi-pass sweeps, PID reuse protection, race condition immunity across tools/subagents/scheduler/retries/HITL/ingress, multi-cycle recovery state machine, endpoint RBAC authorization; 181/181 backend tests passing, 12/12 frontend tests passing, Next.js build passing).
* **Phase 5.4 (AURA-508):** **COMPLETED & ACCEPTED** (Adversarial Prompt-Injection Red-Team & Stress QA; 18-case version-controlled adversarial corpus, behavioral direct prompt-injection enforcement, cross-source attack chains covering Web search, Playwright DOM, Telegram /goal, Webhook SSTI, MCP JSON-RPC protocol integration, tool-output injection, and Memory poisoning; NFKC homoglyph normalization, zero-width steganography stripping, delimiter breakout neutralization, cryptographic HITL defense, canary secret redaction across all 9 channels, OTel and SHA-256 audit ledger, 50 deterministic fuzzer mutations; 209/209 backend tests passing, 12/12 frontend tests passing, Next.js build passing).
* **Phase 6 Preflight:** **COMPLETED & READY FOR IMPLEMENTATION** (Universal File Intelligence & Multi-Format Ingestion architecture blueprint locked: AURA-601 to AURA-604, untrusted file ingestion pipeline, zip-bomb defenses, FastEmbed 768-dim vector indexing in pgvector, workspace tenancy isolation, deletion cascades, zero mandatory cloud cost; docs/PHASE_6_PREFLIGHT_REPORT.md created).
* **Phase 6.1 (AURA-601):** **COMPLETED & RECONCILED** (Universal File Intake & Secure File Registry; `FileRecord` and foundational `FileChunk` schema reservation in Alembic migration 007, streaming upload intake bounded to 50 MB, SHA-256 progressive hashing, magic byte & executable header screening, safe filename normalization and path traversal defense via `WorkspaceFilesystemGuard`, workspace tenant isolation, intra-workspace deduplication, idempotent deletion lifecycle state machine `[UPLOADED / PARSING / INDEXED / FAILED / QUARANTINED]` $\rightarrow$ `DELETE_REQUESTED` $\rightarrow$ `STORAGE_PURGED` $\rightarrow$ `VECTORS_PURGED` $\rightarrow$ `MEMORY_TOMBSTONED` $\rightarrow$ `AUDITED` $\rightarrow$ `DELETED`, orphan storage directory reconciliation, `/api/v1/files/*` REST endpoints, tamper-evident SHA-256 audit ledger integration; deterministic verification proving zero premature chunking/FastEmbed invocation; 226/226 backend tests passing, 12/12 frontend tests passing, Next.js build passing).
* **Phase 6.2 (AURA-602):** **COMPLETED & RECONCILED** (Multi-Format Extraction & Parser Isolation; isolated deterministic extractors for text/markdown/CSV/JSON via Python stdlib and YAML via `PyYAML` `safe_load`, digital PDF via `pypdf`/`pdfplumber` with 200-page limit and scanned PDF no-text diagnostic without OCR, Word `.docx` paragraphs/headings/tables, PowerPoint `.pptx` slides/shapes/notes with 100-slide limit, Excel `.xlsx` with non-negotiable `data_only=False` formula preservation and optional `cached_formula_result` separate pass with zero formula execution, source code inert structural extraction via Python AST and multi-language symbol parsers without code execution, ZIP codebase archive extractor with 100 MB / 500 member / 10:1 ratio zip-bomb defense and explicit rejection of traversal/absolute/drive/UNC/symlink members to prevent collision attacks, visual & audio metadata extractors without OCR/STT, prompt-sanitization envelope wrapping, deferred format rejection for `.xls` and `.tar`/`.tar.gz`, `POST /api/v1/files/{file_id}/extract` endpoint, tamper-evident SHA-256 audit ledger integration; semantic invariant that `FileStatus.INDEXED` denotes successful extraction and file registry metadata cataloging while vector chunking/embeddings/pgvector are strictly deferred to AURA-603; 244/244 backend tests passing, 12/12 frontend tests passing, Next.js build passing).
* **Phase 6.3 (AURA-603):** **COMPLETED & ACCEPTED** (Structural Chunking, FastEmbed 768-dim Vectors & Memory Provenance; Alembic Migration 008 operationalizing `file_chunks` with `UniqueConstraint('workspace_id', 'file_id', 'chunk_index')`, PostgreSQL HNSW cosine index `m=16, ef_construction=64`, GIN FTS index, and `memory_records.provenance` JSONB column with index; format-aware structural chunker with $\le 64$-token context header, 510-token ceiling, 384-token target, and 48-token overlap; FastEmbed `BAAI/bge-base-en-v1.5` local CPU ONNX runtime producing normalized 768-dim embeddings with query prefix transformation; invariant `stored chunk_text == exact embedding input`; two-stage optimistic generation re-indexing with fail-closed deletion race prevention; symmetric hybrid retrieval Top-50 Dense + Top-50 Lexical (`websearch_to_tsquery`) candidate union with linear fusion $0.70 \cdot S_{\text{dense}} + 0.30 \cdot S_{\text{lexical}}$, dual quality gate $S_{\text{hybrid}} \ge 0.30 \lor S_{\text{lexical}} \ge 0.50$, and deterministic sort `ORDER BY hybrid_score DESC, chunk_id ASC`; structured memory provenance with canonical `source_type = 'file_intelligence'` and workspace-scoped deletion tombstoning; real PostgreSQL 16.15 / pgvector 0.8.7 multi-tenant benchmark 650 chunks / 5 workspaces / 100 queries achieving 99.00% Recall@5 and zero tenant leakage; 264/264 backend tests passing, 12/12 frontend tests passing, Next.js 15.5.27 build passing).
* **Phase 6.4 (AURA-604):** **COMPLETED & ACCEPTED** (File Intelligence API, Next.js UI & Governed Agent Integration; dedicated `FileJob` persistent background authority in Alembic migration 009 with PostgreSQL partial unique index `uq_active_file_job` enforcing active job uniqueness and returning `409 Conflict` on duplicates; asynchronous `202 Accepted` + polling lifecycle for extraction, indexing, and synthesis; zero-cost local LLM summarization with deterministic extractive fallback; safe spreadsheet structure and formula detection; codebase AST symbol parsing; inert document preview modal with 100 KB budget and untrusted security banner; user-authorized cognitive memory promotion with structured 11-field provenance; 5 governed agent tools registered in `BUILTIN_TOOLS` and routed through `AgentToolBridge` with zero direct database/filesystem access; 282/282 backend tests passing, 18/18 frontend tests passing, Next.js 15.5.27 production build passing).
* **Phase 6 Master Status:** **PHASE 6 COMPLETE & ACCEPTED** (`AURA-601 ✅`, `AURA-602 ✅`, `AURA-603 ✅`, `AURA-604 ✅`).
* **Phase 7.1 (AURA-701):** **COMPLETED & ACCEPTED** (Silero VAD & CPU-Optimized Faster-Whisper Speech-to-Text Pipeline; ONNX Runtime Silero VAD v4 with circular pre-speech ring buffer and energy-based fallback; Faster-Whisper `whisper-small` int8 CPU quantization via CTranslate2; zero-cost local substrate; prompt-injection `<untrusted_spoken_content>` envelope wrapping; 298/298 backend tests passing).
* **Phase 7.2 (AURA-702):** **COMPLETED & ACCEPTED** (Low-Latency Piper-TTS Speech Synthesis & Streaming; Kokoro/Piper ONNX runtime with chunked sentence-level synthesis, linear resampling to 16 kHz, Int16 PCM streaming, sub-250ms TTFA benchmark, 308/308 backend tests passing).
* **Phase 7.3 (AURA-703):** **COMPLETED & ACCEPTED** (Voice Session Protocol & Cooperative Barge-In Engine; `VoiceSessionManager`, bi-directional speech turn-taking, <50ms VAD interruption trigger [measured p99 = 0.4888 ms], atomic cancellation of active TTS audio streaming and LLM token generation, 316/316 backend tests passing).
* **Phase 7.4 (AURA-704):** **COMPLETED & ACCEPTED** (Authenticated WebSocket Gateway & Session Ticket Transport; short-lived single-use ticket handshake `/api/v1/voice/ticket`, binary WebSocket framing `/api/v1/voice/stream`, 256-bit session nonce, strict `workspace_id` tenant isolation, replay protection, 333/333 backend tests passing).
* **Phase 7.5 (AURA-705):** **COMPLETED & ACCEPTED** (Static Multimodal Vision & Image Inspection; `VisionService` with `Moondream2` default local VLM, static image validation and downscaling [max 2048x2048, 10MB], prompt-injection `<untrusted_multimodal_content>` envelope wrapping, local OCR degraded fallback, zero cloud fallback, 352/352 backend tests passing).
* **Phase 7.6 (AURA-706):** **COMPLETED & ACCEPTED** (Long-Horizon Checkpoint/Recovery & Next.js Voice HUD; `TaskRecoveryService`, deterministic `resume_task(task_id)` from last verified completed step with zero destructive replay, FastAPI lifespan `StartupRecoverySweep` for orphaned `RUNNING` tasks, strict budget & timeout preservation across restarts, active kill-switch enforcement, Next.js Voice HUD component with Web Audio API, frequency spectrum `<canvas>` visualizer, barge-in controls, multimodal static context attachment, and HITL resumption linkage; 360/360 backend tests passing, 23/23 frontend tests passing, Next.js production build passing).
* **Phase 8.2 (AURA-802):** **COMPLETED & ACCEPTED** (Continuous Local OCR & Text Bounding Extraction; `ContinuousOCRService`, RapidOCR with ONNX Runtime on CPU [$0.00 zero-cost floor, zero cloud OCR API, zero mandatory Tesseract dependency, zero cloud fallback], strict 1 Hz rate ceiling [`OCR_MAX_FPS = 1.0`, `OCR_MIN_INTERVAL = 1.0s`] with newest-frame-wins and queue depth = 1, geometric bounding boxes `[x, y, w, h]`, 4-point polygon coordinates, normalized coordinates in `captured_frame` space, confidence scores, prompt-injection `<untrusted_multimodal_content origin="screen_ocr" model="rapidocr_onnx">` XML containment envelopes, volatile depth-1 caching [0.35 ms access], change-aware gating, graceful degraded mode fallback on engine error without throwing, workspace isolation, Emergency Kill Switch immediate abort & cache purge, `/api/v1/vision/ocr/*` authenticated REST endpoints, 17/17 AURA-802 unit/integration tests passing, 393/393 full backend regression passing, 23/23 frontend vitest passing, Next.js production build passing).
* **Phase 8.3 (AURA-803):** **COMPLETED & ACCEPTED** (Live Camera Ingestion & Duplex Vision Transport; `CameraVisionService`, `VisionTicketService` [60s TTL, 256-bit CSPRNG session nonce, single-use ticket handshake `POST /api/v1/vision/ticket`, replay protection, tenant isolation], authenticated duplex WebSocket `/api/v1/vision/stream?ticket=...`, canonical 26-byte Big-Endian binary header `>BBIQIII` [stream_type 1B, source_id 1B, sequence_number 4B, timestamp_ns 8B, width 4B, height 4B, payload_length 4B], WebP payload validation, default 2.0 FPS sampling, hard server ceiling 5.0 FPS with newest-frame-wins and depth-1 volatile ephemeral memory buffer, Emergency Kill Switch immediate streaming abort and depth-1 buffer purge, ephemeral in-memory privacy invariants [zero disk files, zero DB records, zero raw pixel logging or telemetry], Next.js `VisionCamera` component with native `getUserMedia` browser permission boundary, canvas frame grabber, WebP encoder, and DataView binary header generator; 13/13 AURA-803 unit/integration tests passing, 406/406 full backend regression passing, 28/28 frontend vitest passing, Next.js 15.5.27 production build passing).
* **Phase 8.4 (AURA-804):** **COMPLETED & ACCEPTED** (Real-Time Screen VLM, Governed Vision Tools & Next.js Vision HUD; `VisionVLMService` with Moondream2 / Qwen2-VL 2B running strictly on CPU [$0.00 zero-cost floor, zero cloud VLM/OCR API, zero cloud fallback], 0.2 FPS rate ceiling [5.0s min interval], single-worker inference lock, depth-1 newest-frame memory buffer, multi-source integration [AURA-801 ScreenCaptureService, AURA-802 ContinuousOCRService, AURA-803 CameraVisionService], 4 Governed Vision Tools [`inspect_current_screen`, `inspect_active_window`, `inspect_camera_frame`, `query_visible_text`] registered in `BUILTIN_TOOLS` with `risk_level: "low"` executing through `ToolRegistryService` and `AgentToolBridge`, prompt-injection `<untrusted_multimodal_content origin="..." model="...">` XML envelopes with active injection scanning, Emergency Kill Switch immediate abort & volatile cache purge, ticket URL parameter redaction `[REDACTED_TICKET]`, Next.js `VisionHUD` component with privacy indicators; 13/13 AURA-804 unit/integration tests passing, 419/419 full backend regression passing, 33/33 frontend vitest passing, Next.js 15.5.27 production build passing).
* **Phase 8 Master Status:** **PHASE 8 COMPLETE & ACCEPTED** (`AURA-801 ✅`, `AURA-802 ✅`, `AURA-803 ✅`, `AURA-804 ✅`).
* **Phase 9 Preflight:** **COMPLETED & ACCEPTED** (Governed Operating System & Hardware Control Automation architecture blueprint locked: AURA-901 to AURA-906, coordinate safety layer, stale observation TTL $\le 5\text{s}$, executable allowlist, LOLBins denial, PID+create_time verification, cryptographic HMAC-SHA256 HITL tokens, bounded volume/brightness controls, `pystray` system tray indicator, Win32 `Ctrl+Alt+Shift+K` physical emergency hotkey, sub-15ms kill switch abort, zero micro-action surveillance memory boundary; `docs/PHASE_9_PREFLIGHT_REPORT.md` created).
* **Phase 9.1 (AURA-901):** **COMPLETED & ACCEPTED** (Windows OS Control Foundation & Policy Boundary; `OSGuardService`, `OSActionRequest` / `OSActionResponse` contracts with 5.0s hard timeout clamping, `OSActionType` 11 types, deterministic 5-tier risk taxonomy `[READ_ONLY, LOW_RISK_WRITE, MEDIUM_RISK_INTERACTION, HIGH_RISK_SYSTEM_ACTION, CRITICAL_ACTION]`, `HostExecutionPartition` mapping, `OSPolicyEngine` with sliding-window token bucket rate limiters, 20 Windows LOLBins denylist, cryptographic HMAC-SHA256 HITL verification with parameter hash binding, single-use anti-replay, 120s TTL, `PathValidator` path traversal rejection, `ProcessIdentityValidator` PID + creation_time TOCTOU defense, `CoordinateSafetyValidator` monitor/window bounds and 5.0s stale observation TTL, `BaseOSExecutionAdapter` abstraction with `SafeMockOSExecutionAdapter`, single-worker concurrency lock `MAX_ACTIVE_ACTIONS = 1`, Emergency Kill Switch sub-15ms probing, tamper-evident audit ledger and OpenTelemetry redaction; 25/25 dedicated tests passing, 433/433 full backend regression passing, 33/33 frontend vitest passing, Next.js 15.5.27 production build passing; `docs/PHASE_9_1_AURA_901_ACCEPTANCE_REPORT.md` created).
* **Hard Phase Boundary:** **AURA-902 onward (Governed Application Launch & Process Control) and Phase 10 (Advanced Interactive Browser & Windows Boot Daemon) are NOT STARTED (Awaiting explicit user authorization before AURA-902).**












