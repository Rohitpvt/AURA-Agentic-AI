# Engineering Roadmap (ROADMAP.md)
## Project Name: AURA (Autonomous Universal Reactive Agent)
**Document Version:** 5.0.0  
**Phase:** Phase 5 — Enterprise Observability, Sandbox Hardening & Release QA (PREFLIGHT CORRECTED)  
**Classification:** Phased Development Plan  

---

## 1. Master Engineering Roadmap Overview

```
+====================================================================================================+
|                                    AURA DEVELOPMENT PHASES                                         |
+====================================================================================================+
|  [PHASE 1: Core Control Plane, Local DB & Memory] ===> COMPLETE & VALIDATED                        |
|  [PHASE 2: Agent Runtime, Local MCP & Governance] ===> COMPLETE & VALIDATED                        |
|  [PHASE 3: Web Dashboard & Real-Time Client]      ===> COMPLETE & VALIDATED                        |
|  [PHASE 4: Automations, Ingress & Playwright]     ===> COMPLETE & RELEASE VALIDATED                |
|  ------------------------------------------------------------------------------------------------  |
|  [PHASE 5: Observability, Hardening & Release QA] ===> COMPLETE & ACCEPTED                         |
|  [PHASE 6: Universal File Intelligence & Memory]  ===> COMPLETE & ACCEPTED                         |
|  ------------------------------------------------------------------------------------------------  |
|  [PHASE 7: Real-Time Local Voice & Speech System] ===> PLANNED FUTURE (NOT STARTED)                |
|  [PHASE 8: Live Screen & Multimodal Vision]       ===> PLANNED FUTURE (Desktop OCR, Window Capture)|
|  [PHASE 9: Governed OS & Hardware Automation]     ===> PLANNED FUTURE (App Launch, System Control) |
|  [PHASE 10: Advanced Browser & Windows Daemon]    ===> PLANNED FUTURE (Interactive Web, Background)|
+====================================================================================================+
```

---

## 2. Granular Milestone Deliverables

### Phase 1: Core Control Plane, Local DB & Model Engine (COMPLETE)
* **Milestone 1.1 (AURA-101):** PostgreSQL 16 schema setup with `pgvector`, `uuid-ossp`, `pgcrypto`, and Alembic migrations.
* **Milestone 1.2 (AURA-102):** FastAPI Control Plane service with JWT/OAuth2 authentication and Pydantic v2 schemas.
* **Milestone 1.3 (AURA-103):** Auth & Workspace Tenancy middleware.
* **Milestone 1.4 (AURA-104):** Local FastEmbed + PostgreSQL cognitive memory connector with hybrid HNSW vector cosine + Full-Text Search.
* **Milestone 1.5 (AURA-105):** Local Model Provider Foundation (`OllamaProvider`, `GeminiProvider` BYOK adapter, AES-256-GCM encrypted vault).
* **Milestone 1.6 (AURA-106):** Local Tool Registry core supporting Pydantic JSON Schema validation and free DuckDuckGo search.
* **Milestone 1.7 (AURA-107):** Task DAG CRUD & Checkpointing API.

### Phase 2: Agent Runtime, Local MCP & Security Hardening (COMPLETE)
* **Milestone 2.1 (AURA-201):** AURA-Native Cognitive Execution Engine against local Ollama endpoint.
* **Milestone 2.2 (AURA-202):** Supervisor Planner & Structured Plan DAG decomposition.
* **Milestone 2.3 (AURA-203):** Local Model Context Protocol (MCP) host manager executing `stdio` subprocess servers.
* **Milestone 2.4 (AURA-204):** Deterministic 4-tier risk policy engine with cryptographically signed HMAC-SHA256 HITL approval tokens.
* **Milestone 2.5 (AURA-205):** Hierarchical local sub-agent delegation pool with recursion depth cap (max 2) and concurrency limits.
* **Milestone 2.6 (AURA-501 Hist.):** Ephemeral Container Sandboxing & Fail-Closed Host Policy (Phase 2C Advance).
* **Milestone 2.7 (AURA-503 Hist.):** Emergency Kill Switch Sub-15ms Cancellation Engine (Phase 2C Advance).

### Phase 3: Web Dashboard & Real-Time Frontend (COMPLETE)
* **Milestone 3.1 (AURA-301):** Next.js 15 App Router application with Tailwind CSS v4 design system.
* **Milestone 3.2 (AURA-302):** Local Server-Sent Events (SSE) streaming hook (`useSSEStream`).
* **Milestone 3.3 (AURA-303):** Interactive Task & Plan DAG tree viewer with live node states.
* **Milestone 3.4 (AURA-304):** HITL Approval Drawer with side-by-side parameter diffs and signed token submission.
* **Milestone 3.5 (AURA-305):** Memory Graph explorer with inline fact editing and local tombstoning controls.

### Phase 4: Automations & Ingress Gateways (RELEASE VALIDATED)
* **Milestone 4.1 (AURA-401):** PostgreSQL transactional Cron scheduler claiming due automations via `FOR UPDATE SKIP LOCKED`.
* **Milestone 4.2 (AURA-402):** Inbound Webhook Reactive Gateway with HMAC-SHA256 verification and replay protection.
* **Milestone 4.3 (AURA-403):** Telegram Bot Long-Polling Integration via official Telegram Bot API (15-min pairing, `/goal`, `/status`, `/cancel`, `/approve`).
* **Milestone 4.4 (AURA-404):** Local Playwright Headless Web Extraction Tool (`web_extract`) with SSRF filtering and clean Markdown parsing.

### Phase 5: Enterprise Observability, Sandbox Hardening & Release QA (COMPLETE)
* **Milestone 5.1 (AURA-505):** Local OpenTelemetry Distributed Tracing & Local In-Memory/OTLP Exporters.
* **Milestone 5.2 (AURA-506):** Production Docker / WSL2 Container Sandboxing Hardening & Fail-Closed Validation.
* **Milestone 5.3 (AURA-507):** Emergency Kill Switch Multi-Process Abort & Recovery Operational Hardening.
* **Milestone 5.4 (AURA-508):** Cross-Source Adversarial Prompt Injection Red-Teaming & Stress QA.

### Phase 6: Universal File Intelligence & Multi-Format Ingestion (COMPLETE & ACCEPTED)
* **Milestone 6.1 (AURA-601):** Universal File Intake & Secure File Registry (Storage Engine, Hashing, Tenancy, Foundational Schema, Idempotent Deletion Lifecycle) — **COMPLETED & ACCEPTED**.
* **Milestone 6.2 (AURA-602):** Multi-Format Extraction & Parser Isolation (PDF, DOCX, XLSX, PPTX, TXT/MD/CSV/JSON stdlib, PyYAML, Codebase ZIP path rejection & Zip-Bomb Guard, Source Code AST, Visual/Audio Metadata; Registry Cataloging `INDEXED` semantics) — **COMPLETED & ACCEPTED**.
* **Milestone 6.3 (AURA-603):** Structural Chunking, FastEmbed 768-dim Vector Indexing & Memory Provenance (Migration 008, HNSW Cosine Indexing, Format-Aware Chunker, Symmetric Hybrid Retrieval, Generation Reindexing, Multi-Tenant Benchmark 99.00% Recall@5) — **COMPLETED & ACCEPTED**.
* **Milestone 6.4 (AURA-604):** Universal File Intelligence API, Next.js UI Dashboard & Governed Agent Integration (Migration 009, `uq_active_file_job` partial unique index, 202 async lifecycle, 409 concurrency gate, inert preview, spreadsheet & AST analysis, 5 governed agent tools) — **COMPLETED & ACCEPTED**.



### Phase 7: Real-Time Local Voice & Speech System (COMPLETE & ACCEPTED)
* **Milestone 7.1 (AURA-701):** Silero VAD & CPU-Optimized Faster-Whisper Speech-to-Text Pipeline (16kHz Int8 ONNX/CTranslate2, ephemeral PCM ring buffer, `<untrusted_spoken_content>` envelope) — **COMPLETED & ACCEPTED**.
* **Milestone 7.2 (AURA-702):** Low-Latency Piper-TTS Speech Synthesis & Streaming (ONNX Kokoro/Piper runtime, sentence-level streaming, linear resampling to 16kHz, sub-250ms TTFA benchmark) — **COMPLETED & ACCEPTED**.
* **Milestone 7.3 (AURA-703):** Real-Time Barge-In & Cooperative Interruption Engine (`VoiceSessionManager`, bi-directional turn-taking, <50ms VAD interruption trigger, atomic TTS/LLM cancellation) — **COMPLETED & ACCEPTED**.
* **Milestone 7.4 (AURA-704):** Authenticated WebSocket Gateway & Session Ticket Transport (`/api/v1/voice/ticket`, `/api/v1/voice/stream`, single-use ticket handshake, workspace tenancy isolation, replay protection) — **COMPLETED & ACCEPTED**.
* **Milestone 7.5 (AURA-705):** Static Multimodal Vision & Image Inspection (`VisionService` with Moondream2 local VLM default, image downscaling, `<untrusted_multimodal_content>` envelope, OCR degraded fallback) — **COMPLETED & ACCEPTED**.
* **Milestone 7.6 (AURA-706):** Long-Horizon Checkpoint/Recovery & Next.js Voice HUD (`TaskRecoveryService`, deterministic `resume_task`, `StartupRecoverySweep` on lifecycle boot, budget preservation, Next.js Voice HUD component with Web Audio API & spectrum visualizer) — **COMPLETED & ACCEPTED**.

### Phase 8: Continuous Screen, Camera & Live Multimodal Vision (IN PROGRESS)
* **Milestone 8.1 (AURA-801):** Multi-Monitor Screen & Active-Window Capture Engine (`mss` / `pygetwindow` / Per-Monitor v2 DPI, depth-1 ephemeral memory buffer, kill-switch integration) — **COMPLETED & ACCEPTED**.
* **Milestone 8.2 (AURA-802):** Continuous Local OCR & Text Bounding Extraction (`rapidocr-onnxruntime` on ONNX Engine).
* **Milestone 8.3 (AURA-803):** Live Camera Ingestion & Duplex Vision Transport (WebSocket `/api/v1/vision/stream`, 26-byte binary framing).
* **Milestone 8.4 (AURA-804):** Real-Time Screen VLM, 4 Governed Tools & Next.js HUD (`inspect_current_screen`, `inspect_active_window`, `inspect_camera_frame`, `query_visible_text`).



### Phase 9: Governed Operating System & Hardware Automation (FUTURE)
* **Milestone 9.1 (AURA-901):** Application Launch & Process Management Allowlist Engine.
* **Milestone 9.2 (AURA-902):** System Settings & Hardware Telemetry (Volume, Brightness, Wi-Fi).
* **Milestone 9.3 (AURA-903):** Governed GUI Automation (Window-Scoped PyAutoGUI + HITL).
* **Milestone 9.4 (AURA-904):** Windows System Tray Controller & Physical Emergency Hotkey.

### Phase 10: Advanced Interactive Browser & Windows Boot Daemon (FUTURE)
* **Milestone 10.1 (AURA-1001):** Interactive Browser Action Suite (`browser_click`, `browser_fill_form`).
* **Milestone 10.2 (AURA-1002):** Authenticated Web Workflow Governance & Credential Injection.
* **Milestone 10.3 (AURA-1003):** Windows Background Service / Startup Daemon.
* **Milestone 10.4 (AURA-1004):** System Wake/Reboot Auto-Recovery & Daemon Health Telemetry.
