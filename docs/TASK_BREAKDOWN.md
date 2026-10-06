# Granular Engineering Task Breakdown (TASK_BREAKDOWN.md)
## Project Name: AURA (Autonomous Universal Reactive Agent)
**Document Version:** 9.6.0  
**Phase:** Phase 9 — Governed OS & Hardware Automation (COMPLETE & ACCEPTED) | Phase 1–9 Master Validated  
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

## 5. Phase 5: Enterprise Observability, Sandbox Hardening & Release QA (COMPLETED & ACCEPTED)

| Task ID | Task Title | Description & Acceptance Criteria | Dependencies | Complexity | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **AURA-505** | Local OpenTelemetry Tracing | Implement OTel TracerProvider, span middleware on FastAPI routes, Agent DAG loop, model calls, and local in-memory/OTLP exporters with zero paid cloud cost. | AURA-201, AURA-102 | 5 pts (2 days) | **COMPLETED** |
| **AURA-506** | Production Docker / WSL2 Hardening | Operational verification of container sandbox engine, fail-closed contract, active container tracking, orphan reaper, and resource controls. | AURA-501 (Hist.) | 5 pts (2 days) | **COMPLETED** |
| **AURA-507** | Kill Switch Multi-Process Abort QA | Operational validation of Windows process tree termination, post-abort recovery, and live concurrent worker benchmarking. | AURA-503 (Hist.) | 3 pts (1 day) | **COMPLETED** |
| **AURA-508** | Adversarial Prompt Injection QA | Multi-vector red-team test suite testing indirect prompt injection across web search, webhooks, Telegram, Playwright DOM, and memory poisoning. | AURA-404, AURA-505 | 5 pts (2 days) | **COMPLETED** |


---

## 6. Phase 6: Universal File Intelligence & Multi-Format Ingestion (COMPLETED & ACCEPTED)

| Task ID | Task Title | Description & Acceptance Criteria | Dependencies | Complexity | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **AURA-601** | Universal File Intake & Secure Registry | Storage engine, `FileRecord` DB model, `FileChunk` schema foundation reservation, SHA-256 deduplication, workspace tenancy isolation, idempotent deletion lifecycle (`UPLOADED/PARSING/INDEXED/FAILED/QUARANTINED` -> `DELETE_REQUESTED` -> `STORAGE_PURGED` -> `VECTORS_PURGED` -> `MEMORY_TOMBSTONED` -> `AUDITED` -> `DELETED`). | AURA-103, AURA-506 | 8 pts (3 days) | **COMPLETED & RECONCILED** |
| **AURA-602** | Multi-Format Extraction & Parser Isolation | PDF, DOCX, XLSX (inert formula preservation & cached results), PPTX, TXT/MD/CSV/JSON (stdlib), YAML (`PyYAML`), Codebase ZIP unpacker (rejection of traversal/drive/UNC/symlinks & zip-bomb defenses), source code AST, image/audio metadata, prompt sanitization; `INDEXED` represents registry cataloging without chunks/embeddings. | AURA-601, AURA-508 | 8 pts (3 days) | **COMPLETED & RECONCILED** |
| **AURA-603** | Structural Chunking, FastEmbed & Memory Link | Document splitters (64-tok header, 510-tok ceiling, 384-tok target, 48-tok overlap), `FileChunk` model, FastEmbed 768-dim normalized vector index in pgvector HNSW (`m=16, ef_construction=64`), symmetric hybrid retrieval ($0.70 \cdot S_{\text{dense}} + 0.30 \cdot S_{\text{lexical}}$ with dual quality gate), memory structured provenance linking and cascade tombstoning. | AURA-602, AURA-104 | 8 pts (3 days) | **COMPLETED & RECONCILED** |

| **AURA-604** | File Intelligence API, Next.js UI & Governed Agent Integration | 5 canonical governed tools (`file_search`, `file_get_chunks`, `file_summarize`, `spreadsheet_analyze`, `codebase_analyze`), REST/SSE APIs, 202 async lifecycle, 409 concurrency gate with `uq_active_file_job` partial unique index, Next.js File Intelligence Explorer view. | AURA-603, AURA-301 | 8 pts (3 days) | **COMPLETED & ACCEPTED** |


---

## 7. Phase 7: Real-Time Local Voice & Speech System (COMPLETED & ACCEPTED)

| Task ID | Task Title | Description & Acceptance Criteria | Dependencies | Complexity | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **AURA-701** | Local STT & Silero VAD | `SileroVADService` on ONNX Runtime (`onnxruntime`), `FasterWhisperSTTService` on CTranslate2 (`faster-whisper`, int8 CPU quantization), ephemeral audio ring buffer, `<untrusted_spoken_content>` prompt-injection envelope. | AURA-102, AURA-508 | 8 pts (3 days) | **COMPLETED & ACCEPTED** |
| **AURA-702** | Piper-TTS Speech Synthesis & Streaming | `PiperTTSService` on ONNX Runtime, streaming sentence-level audio synthesis, linear resampling to 16 kHz, Int16 PCM streaming, sub-250ms TTFA benchmark. | AURA-701 | 5 pts (2 days) | **COMPLETED & ACCEPTED** |
| **AURA-703** | Voice Session Protocol & Cooperative Barge-In | `VoiceSessionManager`, bi-directional speech turn-taking, real-time VAD interruption trigger, atomic cancellation of active TTS audio streaming and LLM token generation. | AURA-701, AURA-702 | 5 pts (2 days) | **COMPLETED & ACCEPTED** |
| **AURA-704** | Authenticated WebSocket Gateway & Tenancy | Short-lived single-use ticket handshake (`/api/v1/voice/ticket`), binary WebSocket framing (`/api/v1/voice/stream`), 256-bit session nonce, strict `workspace_id` tenant isolation, replay protection. | AURA-703, AURA-103 | 5 pts (2 days) | **COMPLETED & ACCEPTED** |
| **AURA-705** | Static Multimodal Vision & Image Inspection | `VisionService` with `Moondream2` default (and local Ollama `qwen2-vl:2b` alternative), image validation and downscaling (max $2048 \times 2048$, 10MB), `<untrusted_multimodal_content>` envelope, OCR fallback. | AURA-602, AURA-508 | 8 pts (3 days) | **COMPLETED & ACCEPTED** |
| **AURA-706** | Long-Horizon Checkpoint/Recovery & Voice HUD | `TaskRecoveryService`, deterministic `resume_task`, FastAPI lifespan `StartupRecoverySweep` for orphaned `RUNNING` tasks, budget governance enforcement, Next.js Voice HUD component with Web Audio API and `<canvas>` waveform. | AURA-704, AURA-301 | 8 pts (3 days) | **COMPLETED & ACCEPTED** |

---

## 8. Phase 8: Continuous Screen, Camera & Live Multimodal Vision (COMPLETED & ACCEPTED)

| Task ID | Task Title | Description & Acceptance Criteria | Dependencies | Complexity | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **AURA-801** | Multi-Monitor Screen & Active-Window Capture Engine | `ScreenCaptureService`, `mss` multi-monitor discovery, per-monitor DPI v2 scaling, active-window bounding boxes (`pygetwindow`), SSIM frame delta detection ($\ge 5\%$), depth-1 ephemeral memory buffer, kill-switch abort. | Phase 7 | 5 pts (2 days) | **COMPLETED & ACCEPTED** |
| **AURA-802** | Continuous Local OCR & Text Bounding Extraction | `ContinuousOCRService`, sub-100ms volatile cache access via `rapidocr-onnxruntime`, Jaccard deduplication cache, `<untrusted_multimodal_content>` envelope, degraded fallback, 1 Hz rate ceiling. | AURA-801 | 5 pts (2 days) | **COMPLETED & ACCEPTED** |
| **AURA-803** | Live Camera Ingestion & Duplex Vision Transport | `CameraVisionService`, `VisionTicketService` (60s TTL, 256-bit CSPRNG nonce), ticket-authenticated WebSocket `/api/v1/vision/stream`, canonical 26-byte Big-Endian framing, 5.0 FPS server ceiling, depth-1 ephemeral frame buffer, kill-switch abort, Next.js `VisionCamera` component. | AURA-801, AURA-704 | 5 pts (2 days) | **COMPLETED & ACCEPTED** |
| **AURA-804** | Real-Time Screen VLM, Governed Tools & Next.js HUD | 4 Governed Tools (`inspect_current_screen`, `inspect_active_window`, `inspect_camera_frame`, `query_visible_text`), Next.js Vision HUD component, local CPU VLM substrate (Moondream2 / Qwen2-VL), 0.2 FPS rate ceiling, prompt injection containment, Kill-Switch hooks. | AURA-802, AURA-803 | 8 pts (3 days) | **COMPLETED & ACCEPTED** |



---

## 9. Phase 9: Governed OS & Hardware Control Automation (COMPLETED & ACCEPTED)

| Task ID | Task Title | Description & Acceptance Criteria | Dependencies | Complexity | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **AURA-901** | Windows OS Control Foundation & Policy Boundary | Core `OSGuardService`, action taxonomy definitions (`READ_ONLY`, `LOW_RISK_WRITE`, `MEDIUM_RISK_INTERACTION`, `HIGH_RISK_SYSTEM_ACTION`, `CRITICAL_ACTION`), Pydantic schemas, sliding-window rate limiters, single-worker serialization lock. | Phase 8, AURA-204 | 5 pts (2 days) | **COMPLETED & ACCEPTED** |
| **AURA-902** | Governed Application Launch & Process Control | Executable allowlist engine, LOLBins denial filter (`powershell`, `cmd`, `wscript`, etc.), `psutil` process inspector, PID + `create_time` termination verification, cryptographic HMAC-SHA256 HITL integration. | AURA-901 | 5 pts (2 days) | **COMPLETED & ACCEPTED** |
| **AURA-903** | Governed Mouse & Keyboard Interaction | Coordinate safety validator, active window bounding box checks, stale observation guard ($\le 5\text{s}$ TTL), PyAutoGUI secure adapter, shortcut allowlist, failsafe corner $(0,0)$, typing privacy zero raw text leakage. | AURA-901, AURA-801 | 8 pts (3 days) | **COMPLETED & ACCEPTED** |
| **AURA-904** | System Telemetry & Hardware Control Boundary | Read-only local CPU/RAM/GPU/Storage/Battery telemetry, bounded system volume and display brightness adjustments ($\le \pm 10\%$), Core Audio / WMI adapters, governed clipboard boundary ($\le 4\text{KB}$, scrubbed). | AURA-901 | 5 pts (2 days) | **COMPLETED & ACCEPTED** |
| **AURA-905** | System Tray & Global Hotkey Control Plane | Dedicated Windows STA GUI process, `Shell_NotifyIcon` dynamic tray indicator, session Named Mutex, Win32 `RegisterHotKey` physical `Ctrl+Alt+Shift+K` kill switch with sub-15ms dual-path trigger, 300ms debounce, sensing privacy indicators, token-authenticated IPC client, zero hidden persistence. | AURA-901, AURA-507 | 5 pts (2 days) | **COMPLETED & ACCEPTED** |
| **AURA-906** | Phase 9 Integration, Kill-Switch Race Testing & Red Team | Cross-subsystem integration testing, 10 deterministic micro-races with async sync barriers, 20 red-team attack vectors, live Windows host validation, sub-15ms kill switch verification, full regression suite. | AURA-902, 903, 904, 905 | 8 pts (3 days) | **COMPLETED & ACCEPTED** |

---

## 10. Phase 10: Advanced Browser Automation & Windows Background Runtime (PREFLIGHT ARCHITECTED)

| Task ID | Task Title | Description & Acceptance Criteria | Dependencies | Complexity | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **AURA-1001** | Advanced Headless & Interactive Browser Engine | `PlaywrightBrowserManager` extension supporting interactive session lifecycle, multi-tab coordination ($\le 4$ tabs), AXTree accessibility snapshots with numeric element IDs, visual bounding box correlation, dual-representation page state capture, and `<untrusted_web_content>` prompt containment envelopes. | AURA-404, AURA-801 | 8 pts (3 days) | **PREFLIGHT SPECIFIED** |
| **AURA-1002** | Governed Browser Interaction Tools & Risk Policy | Suite of 8 canonical governed tools (`browser_navigate`, `browser_click`, `browser_type`, `browser_select`, `browser_scroll`, `browser_press_key`, `browser_get_page_state`, `browser_tab_manage`), strict 5-tier risk mapping (`READ`, `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`), mandatory HMAC-SHA256 HITL for consequential clicks/submissions, action loop budgets ($\le 30$ actions/task), and zero-delay kill switch abort hooks. | AURA-1001, AURA-204, AURA-901 | 8 pts (3 days) | **PREFLIGHT SPECIFIED** |
| **AURA-1003** | Encrypted Web Session & Credential Injection Vault | Encrypted cookie/session storage in PostgreSQL via AES-256-GCM bound to `workspace_id`, zero-prompt credential injection proxy (`page.fill` via server-side vault, no secrets in LLM context), domain scoping, and ephemeral incognito session clearing. | AURA-1002, AURA-105 | 5 pts (2 days) | **PREFLIGHT SPECIFIED** |
| **AURA-1004** | Governed Browser Download & Upload Pipeline | Sandboxed download directory `{workspace}/downloads/.incoming_{uuid}/`, path traversal defense, file type / MIME verification, size enforcement ($\le 50\text{MB}$), automatic routing into Phase 6 Universal File Registry (`FileStorageEngine`), and upload governance restricted to indexed workspace files. | AURA-1002, AURA-601 | 5 pts (2 days) | **PREFLIGHT SPECIFIED** |
| **AURA-1005** | Windows User-Session Background Daemon & Watchdog Supervisor | Lightweight Windows user-session background supervisor (`AuraDaemonSupervisor`), least-privilege non-SYSTEM execution, Uvicorn/FastAPI process lifecycle supervision, health check loop (5s interval), exponential backoff crash recovery, and `StartupRecoverySweep` task reconciliation. | AURA-905, AURA-706 | 8 pts (3 days) | **PREFLIGHT SPECIFIED** |
| **AURA-1006** | Session Awareness, Tray Integration & Controlled Autostart | Win32 `WM_WTSSESSION_CHANGE` session lock/unlock detection (suspending camera/mic/screen on lock), AURA-905 tray icon state extensions (`BROWSER_ACTIVE`, `DAEMON_ACTIVE`, `DAEMON_DEGRADED`), and explicit, user-controlled, reversible autostart via `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` (OFF by default). | AURA-1005, AURA-905 | 5 pts (2 days) | **PREFLIGHT SPECIFIED** |
| **AURA-1007** | Phase 10 Master Integration, Security Threat Red-Teaming & Live Validation | Comprehensive cross-subsystem integration, 10 kill-switch race micro-benchmarks ($<15\text{ms}$ abort), 25-vector security threat matrix validation, zero-skip Windows 11 host verification, resource budget compliance, and complete regression pass. | AURA-1001 to 1006 | 8 pts (3 days) | **PREFLIGHT SPECIFIED** |

