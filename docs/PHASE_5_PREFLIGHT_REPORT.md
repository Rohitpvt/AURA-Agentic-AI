# AURA — Phase 5 Master Preflight & Capability Roadmap Reconciliation Report

**Document ID:** `docs/PHASE_5_PREFLIGHT_REPORT.md`  
**Version:** 3.0.0 (Final Consistency Gate & Architecture Lock)  
**Phase:** Phase 5 Preflight — Enterprise Observability, Sandbox Hardening & Release QA  
**Status:** **PHASE 5 FINAL PREFLIGHT — READY FOR IMPLEMENTATION**  
**Verification Date:** October 2, 2026  
**Target Hardware Baseline:** AMD Ryzen 7 4800H (8C/16T), 24 GB RAM, NVIDIA RTX 3050 Laptop GPU (4 GB VRAM), Windows 11  
**Mandatory Operating Cost:** $0.00 (100% Local-First Invariant Preserved)

---

## 1. Executive Summary

Phase 4 of AURA has been completed and release-validated across all four milestones (PostgreSQL Transactional Cron Scheduler AURA-401, Inbound Webhook Reactive Gateway AURA-402, Telegram Long-Polling Operator Gateway AURA-403, and Local Playwright Web Extraction AURA-404).

This document serves as the **Final Pre-Implementation Consistency Gate for Phase 5**. It establishes:
1. Complete alignment on the single canonical embedding specification (`FastEmbed` + `BAAI/bge-base-en-v1.5`, 768 dimensions, normalized embeddings, stored in local PostgreSQL `pgvector`).
2. Exact hardware budget terminology distinguishing GPU VRAM allocation, CPU RAM, CPU offloading, and transient process memory.
3. Strict residual scope boundaries for Phase 5 (`AURA-505` through `AURA-508`) confirming that already-implemented Phase 2C security controls are inherited rather than recreated.
4. Telemetry security and redaction rules for OpenTelemetry instrumentation.
5. Preservation of the Four-Layer Capability Architecture ([ADR-023](file:///c:/Users/rghos/OneDrive%20-%20Vivekananda%20Institute%20of%20Professional%20Studies/PROJECTS/Agentic%20AI/docs/ARCHITECTURE_DECISIONS.md)) and the long-term Jarvis capability roadmap across Phases 6 through 10.

---

## 2. Canonical Embedding Model Consistency Audit

The project enforces one single, authoritative embedding definition everywhere:

* **Embedding Provider:** FastEmbed (`fastembed.TextEmbedding`)
* **Canonical Model:** `BAAI/bge-base-en-v1.5`
* **Output Dimension:** 768
* **Normalization:** L2-normalized unit vectors ($\|v\|_2 = 1.0$)
* **Persistence:** PostgreSQL 16 + `pgvector` with HNSW cosine similarity index (`vector_cosine_ops`)
* **Execution Target:** CPU-optimized local inference via ONNX Runtime with zero intentional GPU allocation.

All contradictory historical references to secondary embedding models have been reconciled across all project documentation.

---

## 3. Historical Milestone Audit & Global Inventory

To prevent milestone-ID collisions and preserve historical integrity, the complete milestone inventory is locked:

| Phase | Milestone ID | Capability / Scope | Status | Acceptance / Report Location |
| :--- | :--- | :--- | :--- | :--- |
| **Phase 1** | `AURA-101` | PostgreSQL 16 + pgvector Schema & DDL | COMPLETED | `docs/DATABASE_SCHEMA.md` |
| **Phase 1** | `AURA-102` | FastAPI Skeleton & Local Ollama Connector | COMPLETED | `docs/TECH_STACK.md` |
| **Phase 1** | `AURA-103` | JWT Authentication & Workspace Tenancy | COMPLETED | `docs/SECURITY_MODEL.md` |
| **Phase 1** | `AURA-104` | FastEmbed (`BAAI/bge-base-en-v1.5`) Memory | COMPLETED | `docs/MEMORY_ARCHITECTURE.md` |
| **Phase 1** | `AURA-105` | Model Router Foundation & AES-256 BYOK Vault | COMPLETED | `docs/SECURITY_MODEL.md` |
| **Phase 1** | `AURA-106` | Local Tool Registry & DuckDuckGo Search | COMPLETED | `docs/TOOL_ARCHITECTURE.md` |
| **Phase 1** | `AURA-107` | Task DAG CRUD & Checkpointing Engine | COMPLETED | `docs/SDD.md` |
| **Phase 2A** | `AURA-201` | Native Agent Cognitive Execution Engine | COMPLETED | `docs/AGENT_ARCHITECTURE.md` |
| **Phase 2A** | `AURA-202` | Supervisor Planner & Plan DAG Decomposition | COMPLETED | `docs/AGENT_ARCHITECTURE.md` |
| **Phase 2B** | `AURA-203` | Local MCP Host Subprocess Manager | COMPLETED | `docs/INTEGRATION_PLAN.md` |
| **Phase 2B** | `AURA-204` | Deterministic Cryptographic HITL Engine | COMPLETED | `docs/SECURITY_MODEL.md` |
| **Phase 2B** | `AURA-205` | Bounded Local Sub-Agent Worker Pool | COMPLETED | `docs/AGENT_ARCHITECTURE.md` |
| **Phase 2C** | `AURA-501 (Hist.)` | Ephemeral Container Sandbox & Fail-Closed Host | COMPLETED | `docs/PHASE_2C_SECURITY_HARDENING_REPORT.md` |
| **Phase 2C** | `AURA-503 (Hist.)` | Emergency Kill Switch (<15ms Abort Engine) | COMPLETED | `docs/PHASE_2C_SECURITY_HARDENING_REPORT.md` |
| **Phase 2C** | `AURA-SEC` | Traversal Guard, SSRF Shield, Secret Redaction | COMPLETED | `docs/PHASE_2C_SECURITY_HARDENING_REPORT.md` |
| **Phase 3** | `AURA-301` – `305` | Next.js 15 Web Dashboard, Realtime SSE, DAG | COMPLETED | `docs/PHASE_3_VALIDATION_REPORT.md` |
| **Phase 4** | `AURA-401` – `404` | Cron Scheduler, Webhooks, Telegram, Playwright | COMPLETED | `docs/PHASE_4_RELEASE_VALIDATION_REPORT.md` |
| **Phase 5** | **`AURA-505`** | Local OpenTelemetry Distributed Tracing | **LOCKED TARGET** | Active Phase 5 Implementation |
| **Phase 5** | **`AURA-506`** | Production Docker / WSL2 Sandbox Hardening | **LOCKED TARGET** | Active Phase 5 Implementation |
| **Phase 5** | **`AURA-507`** | Kill Switch Multi-Process Abort & Recovery QA | **LOCKED TARGET** | Active Phase 5 Implementation |
| **Phase 5** | **`AURA-508`** | Adversarial Prompt Injection Red-Teaming & QA | **LOCKED TARGET** | Active Phase 5 Implementation |
| **Phase 6** | `AURA-601` – `604` | Universal File Intelligence & Multi-Format Ingestion | **FUTURE** | `docs/ROADMAP.md` |
| **Phase 7** | `AURA-701` – `704` | Real-Time Local Voice & Speech System | **FUTURE** | `docs/ROADMAP.md` |
| **Phase 8** | `AURA-801` – `804` | Live Desktop Screen Intelligence & Multimodal Vision | **FUTURE** | `docs/ROADMAP.md` |
| **Phase 9** | `AURA-901` – `904` | Governed OS & Hardware Control Automation | **FUTURE** | `docs/ROADMAP.md` |
| **Phase 10** | `AURA-1001` – `1004`| Advanced Interactive Browser & Windows Boot Daemon | **FUTURE** | `docs/ROADMAP.md` |

---

## 4. Phase 5 Scope: Residual Hardening & Observability Only

Phase 5 does **NOT** recreate previously completed Phase 2C security foundations. Its exact residual scope is defined as follows:

### AURA-505 — Local OpenTelemetry Distributed Tracing & Local Exporters
* **Scope:**
  - Setup OpenTelemetry `TracerProvider` with W3C `traceparent` context propagation across FastAPI request middleware, Supervisor DAG planning, ModelProvider inference, tool execution boundaries, and async sub-agent runs.
  - Ingress-to-runtime correlation (linking Webhook, Cron, Telegram, and Dashboard requests to generated Task DAG spans).
  - Local-only exporters: `InMemorySpanExporter` (for automated test assertions and Web UI trace views) and `ConsoleSpanExporter` / local OTLP endpoint (`localhost:4317` / `localhost:4318`) for optional local Jaeger.
  - **Security Invariant:** Exporter failure must fail safely without breaking agent execution.
  - **Audit Invariant:** OpenTelemetry traces provide telemetry/performance correlation but **DO NOT** replace the SHA-256 cryptographic audit ledger (`audit_logs`), which remains the single authoritative security audit record.

### AURA-506 — Production Docker / WSL2 Container Sandbox Hardening & Validation
* **Scope:**
  - Verify inherited Phase 2C container profiles (`READ_ONLY`, `DEVELOPMENT`, `NETWORK_RESEARCH`, `HIGH_RISK`) directly against the live Docker Desktop / WSL2 configured production runtime on Windows 11.
  - Operational testing of fail-closed behavior (confirming that when Docker/WSL2 is stopped, misconfigured, or unavailable, arbitrary code execution tools strictly reject fallback to unprotected host execution).
  - Explicit runtime enforcement validation: CPU limits, memory limits, cgroups resource quota enforcement on the actual container daemon, read-only rootfs, filesystem volume mount restrictions, denied capability escalation (`--cap-drop ALL`), and network isolation lockdown.
  - Container lifecycle cleanup and orphan recovery (ensuring zero orphaned container instances or zombie processes persist across timeouts, crashes, or cancellations).

### AURA-507 — Emergency Kill Switch Multi-Process Abort & Recovery Operational Hardening
* **Scope:**
  - Windows 11 target-OS process-tree termination testing (exercising `TerminateProcess` and native Windows process-tree termination strategies to guarantee parent, child, and grandchild process cancellation without orphaned Chromium, Node, or Python workers).
  - Independent validation of POSIX / WSL2 process-group (`SIGKILL`) termination where applicable, without conflating Windows and Linux behavior.
  - Concurrency race handling, repeated kill-switch invocation idempotency, and async task DAG cancellation interaction.
  - Interaction with background schedulers and Telegram pollers (ensuring notifications emit and task locks release).
  - Immediate tamper-evident audit ledger event recording (`kill_switch_triggered`) with post-abort state recovery and operational resumption without requiring server restarts.

### AURA-508 — Cross-Source Adversarial Prompt Injection Red-Teaming & Stress QA
* **Scope:**
  - Multi-vector adversarial test suite simulating indirect prompt injection via web search markdown, webhook payloads, Telegram commands, Playwright DOM content, and MCP outputs.
  - Memory poisoning resistance tests (ensuring injected malicious instructions do not compromise semantic memory or hijack future sessions).
  - Privilege escalation and schema tampering regression tests across deterministic offline test harnesses and controlled local integration suites.

---

## 5. Telemetry Security & Redaction Policy

To prevent sensitive credentials and PII from entering local telemetry buffers:

1. **Strict Plaintext Prohibitions:** The OpenTelemetry instrumentation **MUST NOT** record plaintext:
   - Access tokens, refresh tokens, JWTs, password hashes.
   - External provider API keys (Gemini BYOK credentials, OpenAI keys).
   - Telegram bot tokens, webhook secrets, pairing tokens.
   - `Authorization` headers, `Cookie` headers, signed HITL approval tokens.
   - Raw environment variables or filesystem secrets.
2. **Attribute Bounding:**
   - Raw prompts, tool arguments, tool outputs, webhook payloads, and Telegram message bodies must be truncated and sanitized through `SecretRedactor` before being attached to span attributes.
3. **Telemetry Boundary:** Telemetry is strictly diagnostic; no telemetry failure may bypass or alter `ToolRegistryService`, `PolicyEngine`, HITL gates, or `audit_service` ledger recording.

---

## 6. Four-Layer Capability Architecture ([ADR-023](file:///c:/Users/rghos/OneDrive%20-%20Vivekananda%20Institute%20of%20Professional%20Studies/PROJECTS/Agentic%20AI/docs/ARCHITECTURE_DECISIONS.md))

```text
1. INTERFACES (Sensors, Clients & Ingress Surfaces)
   - Next.js Web Command Center (localhost:3000)
   - Microphone Audio Input Stream
   - Screen & Window Video Capture Source
   - Camera Video Frames
   - Telegram Bot Client & Inbound Webhooks

2. CAPABILITY SERVICES (Internal Domain Engines)
   - Speech Recognition Service (Faster-Whisper on CPU)
   - Text-to-Speech Engine (Piper on CPU)
   - OCR Engine (Tesseract on CPU)
   - Local Multimodal Vision (Moondream2 / Qwen2-VL)
   - Document Ingestion & AST Parsing Service
   - Browser Context & Session Pool Manager

3. GOVERNED TOOLS (Execution-Capable Units with Side-Effects)
   - web_extract, web_search, read_file, write_file, system_volume_set, browser_click_element
   [Crosses AgentToolBridge -> ToolRegistryService -> Policy/HITL -> Sandbox -> Audit]

4. RUNTIME INFRASTRUCTURE (Daemons, Schedulers & Transports)
   - PostgreSQL Cron Scheduler Daemon (AURA-401)
   - Telegram Long-Poller Daemon (AURA-403)
   - EventBroadcasterHub SSE Stream
   - OpenTelemetry Trace Exporter (AURA-505)
   - Windows Startup Daemon Service (Phase 10)
```

No capability subsystem may create a second execution loop or bypass canonical governance.

---

## 7. Target Hardware Budget & Resource Allocation

> [!NOTE]
> Resource allocations represent an **estimated resource envelope** for the target machine (AMD Ryzen 7 4800H, 24 GB RAM, NVIDIA RTX 3050 4 GB VRAM). Actual resource usage varies with workload and model selection and must be measured during testing.

### Estimated Resource Breakdown

| Subsystem | Target Hardware | VRAM Allocation | CPU RAM Footprint | Resource Model |
| :--- | :--- | :--- | :--- | :--- |
| **`llama3.2:3b-instruct` (Fast)** | GPU VRAM | ~2.0 GB VRAM | ~500 MB RAM | Primary fast extraction & routine agent loop |
| **`qwen2.5:7b-instruct` (General)**| GPU + Partial CPU | ~3.2 GB VRAM | ~2.5 GB RAM (CPU offload) | Complex reasoning & multi-step planning |
| **FastEmbed (`bge-base-en-v1.5`)** | CPU (ONNX) | No intentional GPU allocation | ~300 MB RAM | 768-dim semantic memory embedding |
| **Faster-Whisper (STT - Ph 7)** | CPU (int8) | No intentional GPU allocation | ~200 MB RAM | Voice transcription on speech activity |
| **Piper-TTS (TTS - Ph 7)** | CPU (ONNX) | No intentional GPU allocation | ~60 MB RAM | Speech synthesis |
| **Tesseract OCR (Vision - Ph 8)** | CPU | No intentional GPU allocation | ~200 MB RAM | Text extraction from images/screen |
| **Playwright Chromium (Web - Ph 4)**| CPU / Host RAM| ~50 MB VRAM (compositing) | ~250 MB RAM per context | Ephemeral headless web extraction |
| **FastAPI + PostgreSQL + Next.js**| Host Services | No intentional GPU allocation | ~800 MB RAM combined | Core Control Plane & Web Command Center |

* **Total Baseline RAM Utilization:** Approximately 5.5 GB RAM under typical single-agent execution (leaving >18 GB available for OS, multitasking, and burst caching). This is an illustrative baseline, not a fixed maximum ceiling.
* **VRAM Arbitration:** Primary text LLM and on-demand local VLM are scheduled sequentially or partitioned to avoid GPU out-of-memory thrashing on 4 GB VRAM.

---

## 8. Reality Test Classification Standards

Every Phase 5 test result must be explicitly classified using one of the following exact reality tiers:

* `deterministic local/offline test` — Pure unit and mock tests running offline without external services.
* `SQLite compatibility test` — Fast schema and model logic tests on local SQLite.
* `real PostgreSQL integration test` — Database concurrency and transaction lock verification on live PostgreSQL.
* `real Docker/WSL2 sandbox test` — Container isolation and capability drop testing against a live container daemon.
* `real Playwright/browser test` — Chromium DOM rendering and extraction against real HTTP/HTTPS targets.
* `real Telegram/API integration test` — End-to-end communication verified with the live Telegram Bot API.
* `measured target-hardware test` — Latency and memory benchmarks measured directly on host hardware.

No test may claim "100% offline validation" if it depends on live external infrastructure.

---

## 9. Long-Term Master Roadmap (Phases 5 through 10)

* **Phase 5 (Active Gate):** Enterprise Observability, Sandbox Hardening & Release QA (`AURA-505` to `AURA-508`).
* **Phase 6 (Future):** Universal File Intelligence & Multi-Format Ingestion (`AURA-601` to `AURA-604` — PDF, XLSX, CSV, Audio, Codebases).
* **Phase 7 (Future):** Real-Time Local Voice & Speech System (`AURA-701` to `AURA-704` — Whisper STT, Piper TTS, VAD, Barge-In).
* **Phase 8 (Future):** Live Desktop Screen Intelligence & Multimodal Vision (`AURA-801` to `AURA-804` — Desktop OCR, Window Capture, Local VLM).
* **Phase 9 (Future):** Governed OS & Hardware Control Automation (`AURA-901` to `AURA-904` — App Launching, System Control, PyAutoGUI, Tray).
* **Phase 10 (Future):** Advanced Interactive Browser & 24/7 Windows Boot Daemon Service (`AURA-1001` to `AURA-1004` — Interactive Web, Background Daemon).

---

## 10. Canonical Phase 5 Implementation Acceptance Matrix

| Milestone | Target Feature | Required Acceptance | Test Classification Target |
| :--- | :--- | :--- | :--- |
| **`AURA-505`** | OpenTelemetry Distributed Tracing | Context propagation across the real local AURA runtime path; secret redaction; bounded attributes; exporter failure isolation; no governance bypass; audit correlation | `deterministic local/offline test` + `real AURA runtime integration test` |
| **`AURA-506`** | Production Docker/WSL2 Sandbox Hardening | Actual runtime resource enforcement; filesystem/network isolation; fail-closed execution; cleanup and orphan recovery | `real Docker/WSL2 sandbox test` |
| **`AURA-507`** | Emergency Kill Switch Multi-Process Abort | Actual process-tree termination; async cancellation; cleanup; recovery; idempotency; scheduler/Telegram interaction; audit evidence | `deterministic local/offline test` + `SQLite compatibility test` + `real target-OS process integration test` |
| **`AURA-508`** | Adversarial Prompt-Injection Red-Team QA | Cross-source corpus; delimiter/boundary evasion; indirect injection; regression coverage and deterministic reproduction | `deterministic local/offline test` |

---

# **PHASE 5 FINAL PREFLIGHT — READY FOR IMPLEMENTATION**
