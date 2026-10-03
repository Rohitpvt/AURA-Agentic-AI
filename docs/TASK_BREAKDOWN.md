# Granular Engineering Task Breakdown (TASK_BREAKDOWN.md)
## Project Name: AURA (Autonomous Universal Reactive Agent)
**Document Version:** 5.0.0  
**Phase:** Phase 5 — Enterprise Observability, Sandbox Hardening & Release QA (PREFLIGHT CORRECTED)  
**Classification:** Work Breakdown Structure (WBS)  

---

## 1. Phase 1: Core Control Plane, Local DB & Model Engine

| Task ID | Task Title | Description & Acceptance Criteria | Dependencies | Complexity | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **AURA-101** | PostgreSQL 16 & pgvector Setup | Initialize schema with `uuid-ossp`, `pgcrypto`, `vector`, create tables (`users`, `workspaces`, `sessions`, `messages`, `tasks`, `task_steps`, `agent_runs`, `tools`, `skills`, `approval_requests`, `audit_logs`, `memory_records`). Implement Alembic migrations. | None | 5 pts (2 days) | **COMPLETED** |
| **AURA-102** | FastAPI Application Skeleton & Ollama Connector | Build FastAPI async app, error handling middleware, DB session dependency injection, CORS, correlation logging, health probes, and local Ollama client. | AURA-101 | 3 pts (1 day) | **COMPLETED** |
| **AURA-103** | Auth & Workspace Tenancy | Implement JWT authentication, password hashing (argon2/bcrypt), API key verification, and Row-Level Security (RLS) context middleware. | AURA-102 | 5 pts (2 days) | **COMPLETED** |
| **AURA-104** | FastEmbed + pgvector Memory | Build local embedding service using FastEmbed (`BAAI/bge-base-en-v1.5`, 768-dim) and hybrid HNSW vector + PostgreSQL Full-Text Search recall. | AURA-101, AURA-102 | 8 pts (3 days) | **COMPLETED** |
| **AURA-105** | Local Model Provider Foundation + Secure BYOK | Multi-tier model provider abstraction, OllamaProvider, GeminiProvider BYOK adapter, AES-256-GCM encrypted credential vault, and model router. | AURA-102 | 5 pts (2 days) | **COMPLETED** |
| **AURA-106** | Local Tool Registry & DDG Search | Implement Tool Registry with Pydantic JSON Schema validation, risk classifier, and zero-cost DuckDuckGo search tool. | AURA-101, AURA-102 | 8 pts (3 days) | **COMPLETED** |
| **AURA-107** | Task CRUD & Checkpoint API | Build REST endpoints for creating goals, reading task DAG steps, updating step checkpoints, and cancelling active tasks. | AURA-101, AURA-102 | 5 pts (2 days) | **COMPLETED** |

---

## 2. Phase 2: Agent Runtime, Local MCP & Security Hardening

| Task ID | Task Title | Description & Acceptance Criteria | Dependencies | Complexity | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **AURA-201** | Native Agent Cognitive Runtime | Encapsulate modular agent substrate running against local Ollama endpoint. Bridge events to local pubsub/SSE. | AURA-105, AURA-106 | 8 pts (3 days) | **COMPLETED** |
| **AURA-202** | Supervisor Planner & Plan DAG | Build Master Supervisor Agent prompt loop decomposing user goals into structured DAGs with verification assertions. | AURA-201 | 8 pts (3 days) | **COMPLETED** |
| **AURA-203** | Local MCP Host Client Manager | Implement MCP client supporting local `stdio` subprocess servers. Add dynamic tool schema discovery and workspace policy filtering. | AURA-106 | 8 pts (3 days) | **COMPLETED** |
| **AURA-204** | Deterministic HITL Engine | Implement approval request generation, HMAC-SHA256 token signing, TTL validation, and execution suspension/resumption. | AURA-106, AURA-201 | 8 pts (3 days) | **COMPLETED** |
| **AURA-205** | Local Sub-Agent Worker Pool | Implement hierarchical sub-agent delegation (Research, Coding, Synthesis) with depth limits (max 2) and local worker thread bounds. | AURA-202 | 8 pts (3 days) | **COMPLETED** |
| **AURA-501 (Hist.)** | Ephemeral Container Sandbox | Isolate shell and code execution inside Docker containers with dropped capabilities, read-only root, and fail-closed host execution policy. | AURA-106, AURA-203 | 8 pts (3 days) | **COMPLETED (Ph 2C)** |
| **AURA-503 (Hist.)** | Emergency Kill Switch | Sub-15ms atomic execution circuit breaker aborting runtimes, sub-agents, MCP servers, and sandboxes. | AURA-201, AURA-205 | 5 pts (2 days) | **COMPLETED (Ph 2C)** |

---

## 3. Phase 3: Web Dashboard & Real-Time Client

| Task ID | Task Title | Description & Acceptance Criteria | Dependencies | Complexity | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **AURA-301** | Next.js 15 App Router Scaffold | Setup Next.js 15, TypeScript, Tailwind CSS v4, dark mode layout, sidebar navigation, and TanStack Query provider. | None | 5 pts (2 days) | **COMPLETED** |
| **AURA-302** | Local SSE Streaming Hook | Build `useSSEStream` React hook connecting to `localhost:8000` with auto-reconnect, token buffering, and thought-accordion rendering. | AURA-301, AURA-107 | 5 pts (2 days) | **COMPLETED** |
| **AURA-303** | Task & DAG Visualizer | Implement interactive DAG tree view displaying task steps, status indicators, output previews, and manual retry buttons. | AURA-301, AURA-107 | 8 pts (3 days) | **COMPLETED** |
| **AURA-304** | Approval Modal & HITL Drawer | Build real-time approval drawer showing tool parameters, risk level, countdown timer, and signed token approval submission. | AURA-301, AURA-204 | 5 pts (2 days) | **COMPLETED** |
| **AURA-305** | Memory Graph & Skills Editor | Build Memory management view (with inline edit & tombstone) and Markdown editor for `SKILL.md` version management. | AURA-301, AURA-104 | 8 pts (3 days) | **COMPLETED** |

---

## 4. Phase 4: Automations & Ingress Gateways (RELEASE VALIDATED)

| Task ID | Task Title | Description & Acceptance Criteria | Dependencies | Complexity | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **AURA-401** | PostgreSQL Cron Scheduler | Implement background scheduler claiming due automations via PostgreSQL `FOR UPDATE SKIP LOCKED`, 15-min lease recovery, retry/circuit breaker, and governed Task dispatch. | AURA-107 | 5 pts (2 days) | **COMPLETED** |
| **AURA-402** | Webhook Ingress Gateway | Build `/api/v1/webhooks/ingress/{public_id}` with HMAC-SHA256 signature verification, replay protection, persistent idempotency deduplication, and SSTI-safe prompt template hydration. | AURA-401 | 5 pts (2 days) | **COMPLETED** |
| **AURA-403** | Free Telegram Ingress Adapter | Implement official Telegram Bot API long-polling adapter linking Telegram chat IDs to AURA workspaces via 15-minute one-time pairing, lease locking, governed `/goal`, `/status`, `/cancel`, and cryptographic `/approve`. | AURA-103, AURA-201 | 8 pts (3 days) | **COMPLETED** |
| **AURA-404** | Playwright Web Extractor | Build local headless browser extraction tool (`web_extract`) converting target web page DOM to clean Markdown with multi-layer SSRF protection, 5MB response budget, and untrusted output framing. | AURA-106 | 8 pts (3 days) | **COMPLETED** |

---

## 5. Phase 5: Enterprise Observability, Sandbox Hardening & Release QA (CURRENT TARGET)

| Task ID | Task Title | Description & Acceptance Criteria | Dependencies | Complexity | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **AURA-505** | Local OpenTelemetry Tracing | Implement OTel TracerProvider, span middleware on FastAPI routes, Agent DAG loop, model calls, and local in-memory/OTLP exporters with zero paid cloud cost. | AURA-201, AURA-102 | 5 pts (2 days) | **COMPLETED** |
| **AURA-506** | Production Docker / WSL2 Hardening | Operational verification of container sandbox engine, fail-closed contract, active container tracking, orphan reaper, and resource controls. | AURA-501 (Hist.) | 5 pts (2 days) | **COMPLETED** |
| **AURA-507** | Kill Switch Multi-Process Abort QA | Operational validation of Windows process tree termination, post-abort recovery, and live concurrent worker benchmarking. | AURA-503 (Hist.) | 3 pts (1 day) | **COMPLETED** |
| **AURA-508** | Adversarial Prompt Injection QA | Multi-vector red-team test suite testing indirect prompt injection across web search, webhooks, Telegram, Playwright DOM, and memory poisoning. | AURA-404, AURA-505 | 5 pts (2 days) | **COMPLETED** |


---

## 6. Phase 6: Universal File Intelligence & Multi-Format Ingestion (PREFLIGHT READY)

| Task ID | Task Title | Description & Acceptance Criteria | Dependencies | Complexity | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **AURA-601** | Universal File Intake & Secure Registry | Storage engine, `FileRecord` DB model, `FileChunk` schema foundation reservation, SHA-256 deduplication, workspace tenancy isolation, idempotent deletion lifecycle (`UPLOADED/PARSING/INDEXED/FAILED/QUARANTINED` -> `DELETE_REQUESTED` -> `STORAGE_PURGED` -> `VECTORS_PURGED` -> `MEMORY_TOMBSTONED` -> `AUDITED` -> `DELETED`). | AURA-103, AURA-506 | 8 pts (3 days) | **COMPLETED & RECONCILED** |
| **AURA-602** | Multi-Format Extraction & Parser Isolation | PDF, DOCX, XLSX (inert formula preservation & cached results), PPTX, TXT/MD/CSV/JSON (stdlib), YAML (`PyYAML`), Codebase ZIP unpacker (rejection of traversal/drive/UNC/symlinks & zip-bomb defenses), source code AST, image/audio metadata, prompt sanitization; `INDEXED` represents registry cataloging without chunks/embeddings. | AURA-601, AURA-508 | 8 pts (3 days) | **COMPLETED & RECONCILED** |
| **AURA-603** | Structural Chunking, FastEmbed & Memory Link | Document splitters (64-tok header, 510-tok ceiling, 384-tok target, 48-tok overlap), `FileChunk` model, FastEmbed 768-dim normalized vector index in pgvector HNSW (`m=16, ef_construction=64`), symmetric hybrid retrieval ($0.70 \cdot S_{\text{dense}} + 0.30 \cdot S_{\text{lexical}}$ with dual quality gate), memory structured provenance linking and cascade tombstoning. | AURA-602, AURA-104 | 8 pts (3 days) | **COMPLETED & RECONCILED** |

| **AURA-604** | File Intelligence API, Next.js UI & Governed Agent Integration | 5 canonical governed tools (`file_search`, `file_get_chunks`, `file_summarize`, `spreadsheet_analyze`, `codebase_analyze`), REST/SSE APIs, 202 async lifecycle, 409 concurrency gate with `uq_active_file_job` partial unique index, Next.js File Intelligence Explorer view. | AURA-603, AURA-301 | 8 pts (3 days) | **COMPLETED & ACCEPTED** |


---

## 7. Phase 7: Real-Time Local Voice & Speech System (FUTURE)

| Task ID | Task Title | Description & Acceptance Criteria | Dependencies | Complexity | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **AURA-701** | CPU Faster-Whisper & Silero VAD | Real-time speech capture, VAD voice segmentation, and CPU int8 Whisper transcription. | AURA-102 | 8 pts (3 days) | PLANNED |
| **AURA-702** | Low-Latency Piper-TTS Synthesis | CPU ONNX Piper speech synthesis with WebSocket streaming and sentence buffering. | AURA-701 | 5 pts (2 days) | PLANNED |
| **AURA-703** | Real-Time Barge-In Engine | Cooperative interruption token cancelling speech output and active LLM tokens upon user speech. | AURA-701, AURA-702 | 5 pts (2 days) | PLANNED |
| **AURA-704** | Voice HUD & Audio Waveform UI | Real-time audio visualizer, microphone toggle, and hands-free indicator in Next.js UI. | AURA-301, AURA-703 | 5 pts (2 days) | PLANNED |

---

## 8. Phase 8: Live Desktop Screen Intelligence & Multimodal Vision (FUTURE)

| Task ID | Task Title | Description & Acceptance Criteria | Dependencies | Complexity | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **AURA-801** | Desktop Window & Screen Capture | Native OS screen/window snapshot service with region clipping and image downscaling. | AURA-106 | 5 pts (2 days) | PLANNED |
| **AURA-802** | Local Tesseract OCR Engine | Layout extraction, text bounding boxes, and tabular visual extraction from images. | AURA-801 | 5 pts (2 days) | PLANNED |
| **AURA-803** | Local Multimodal Vision Integration | On-demand local VLM (Moondream2 / Qwen2-VL 2B) visual reasoning and description. | AURA-105, AURA-801 | 8 pts (3 days) | PLANNED |
| **AURA-804** | Explicit Consent Gate & Privacy Purge | User permission prompt for visual capture and immediate memory deletion of raw frames. | AURA-801, AURA-304 | 5 pts (2 days) | PLANNED |

---

## 9. Phase 9: Governed OS & Hardware Control Automation (FUTURE)

| Task ID | Task Title | Description & Acceptance Criteria | Dependencies | Complexity | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **AURA-901** | Application Launch Allowlist Engine | Governed process execution allowlist with path verification and process tree monitoring. | AURA-106, AURA-204 | 5 pts (2 days) | PLANNED |
| **AURA-902** | System Hardware & Setting Control | Read/set system volume, display brightness, and network status via native Windows APIs. | AURA-901 | 5 pts (2 days) | PLANNED |
| **AURA-903** | Governed GUI Automation | Window-bounded PyAutoGUI mouse clicks, keystrokes, and mandatory HITL for destructive actions. | AURA-901, AURA-204 | 8 pts (3 days) | PLANNED |
| **AURA-904** | Windows System Tray & Hotkey Guard | Background system tray icon, live status indicator, and physical global emergency hotkey. | AURA-901, AURA-507 | 5 pts (2 days) | PLANNED |

---

## 10. Phase 10: Advanced Interactive Browser & Windows Boot Daemon (FUTURE)

| Task ID | Task Title | Description & Acceptance Criteria | Dependencies | Complexity | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **AURA-1001**| Interactive Browser Action Suite | Multi-step clicking, typing, form filling, and dropdown selection via Playwright. | AURA-404, AURA-204 | 8 pts (3 days) | PLANNED |
| **AURA-1002**| Authenticated Web Session Governance | Isolated browser contexts with encrypted credential injection and session preservation. | AURA-1001, AURA-105 | 8 pts (3 days) | PLANNED |
| **AURA-1003**| Windows Background Service Daemon | Windows Service / Startup Task management with automatic startup and crash recovery. | AURA-904 | 8 pts (3 days) | PLANNED |
| **AURA-1004**| System Wake/Reboot Auto-Recovery | Automatic state reconciliation, database connection recovery, and scheduler resumption. | AURA-1003, AURA-401 | 5 pts (2 days) | PLANNED |
