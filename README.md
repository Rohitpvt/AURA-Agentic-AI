# AURA: Autonomous Universal Reactive Agent
> **The 100% Zero-Cost, Local-First Personal Agentic AI Operating System**

[![Architecture: Zero-Cost Verified](https://img.shields.io/badge/Architecture-Zero--Cost%20Verified-06B6D4.svg)](docs/ARCHITECTURE.md)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.12+](https://img.shields.io/badge/Python-3.12+-3776AB.svg)](docs/TECH_STACK.md)
[![LLM: Ollama Local](https://img.shields.io/badge/LLM-Ollama%20Local-black.svg)](docs/TECH_STACK.md)
[![Database: PostgreSQL 16 + pgvector](https://img.shields.io/badge/Database-PostgreSQL%2016%20%2B%20pgvector-336791.svg)](docs/DATABASE_SCHEMA.md)
[![Backend Tests: 880 Passed](https://img.shields.io/badge/Backend%20Tests-880%20Passed%20(100%25)-brightgreen.svg)](apps/api/tests/)
[![Frontend Tests: 33 Passed](https://img.shields.io/badge/Frontend%20Tests-33%20Passed%20(100%25)-brightgreen.svg)](apps/web/tests/)

---

## 1. Project Overview & Vision

**AURA (Autonomous Universal Reactive Agent)** is an enterprise-grade, local-first **Personal Agentic AI Operating System** designed to run **100% locally on consumer hardware** with **$0.00 ongoing API or SaaS costs**. It functions as a persistent, proactive, and autonomous cognitive orchestrator capable of:

* **Decomposing Natural Language Goals:** Translates raw user objectives into verifiable execution Directed Acyclic Graphs (DAGs) with explicit step assertions;
* **Cognitive Memory & Vector Recall:** Maintains continuous, cross-session episodic memory and user preferences via PostgreSQL 16 + `pgvector` and FastEmbed (`BAAI/bge-base-en-v1.5`, 768-dim);
* **Zero-Cost Open-Weight Inference:** Runs state-of-the-art open-weight models (`Qwen 2.5 7B`, `Llama 3.2 3B`) locally via **Ollama**;
* **Governed Tool & Sub-Agent Orchestration:** Dispatches native tools, hierarchical sub-agent worker pools (depth $\le 2$), and Model Context Protocol (MCP) servers with strict budget caps;
* **Automations & Ingress Gateways:** Runs scheduled Cron automations (`FOR UPDATE SKIP LOCKED`), inbound HMAC-SHA256 webhooks, and long-polling Telegram Bot interactions (`@Aura_Agentic_Bot`);
* **Universal File Intelligence:** Multi-format ingestion and extraction for PDF, DOCX, XLSX, PPTX, Codebase ZIPs, AST symbol parsing, format-aware structural chunking, symmetric hybrid retrieval ($0.70 \cdot S_{\text{dense}} + 0.30 \cdot S_{\text{lexical}}$), document synthesis, and inert preview rendering;
* **Enterprise Security & Governance:** Enforces a deterministic 4-tier risk policy engine, cryptographic HMAC-SHA256 Human-in-the-Loop (HITL) approval tokens, ephemeral Docker container sandboxes, prompt-injection boundary envelopes (`<untrusted_external_content>`), and a sub-15ms multi-process Emergency Kill Switch;
* **Real-Time Command Dashboard:** Next.js 15 App Router web interface with live Server-Sent Events (SSE) thought streaming, interactive DAG visualizer, memory explorer, file intelligence drawer, and HITL approval modal.

---

## 2. The Zero-Cost Core Invariant (Non-Negotiable)

> [!IMPORTANT]
> The entire AURA core system is buildable, testable, and runnable without requiring ANY paid API, paid SaaS subscription, cloud hosting, or per-use billing service. Cloud models (Google Gemini BYOK) are strictly optional Tier-3 adapters.

```
+====================================================================================================+
|                                    100% LOCAL-FIRST TOPOLOGY                                       |
+====================================================================================================+
|  INGRESS:       Next.js 15 Web Dashboard (`localhost:3000`) | Telegram Long-Polling | Webhooks    |
|  CONTROL PLANE: FastAPI (Python 3.12) | Deterministic Policy Engine | Secret Injection Proxy       |
|  AGENT RUNTIME: AURA-Native Engine | Supervisor Planner | Subagent Pool | Governed Tool Bridge    |
|  LOCAL MEMORY:  PostgreSQL 16 + pgvector (HNSW Cosine) + FastEmbed (`BAAI/bge-base-en-v1.5`)       |
|  LOCAL TOOLS:   DuckDuckGo Search + Playwright DOM Extractor + Local MCP stdio Subprocesses       |
|  LOCAL SAFETY:  Ephemeral Docker Sandboxes | SHA-256 Hash Chained Audit Ledger | Kill Switch (<15ms)|
+====================================================================================================+
```

---

## 3. Technology Stack Summary

| Subsystem | Technology | License | Cost / Deployment | Primary Rationale |
| :--- | :--- | :--- | :--- | :--- |
| **Local LLM Engine** | **Ollama** (`qwen2.5:7b`, `llama3.2:3b`) | MIT / Apache 2.0 | **$0.00 / Local** | High-performance local GGUF model execution, GPU offloading, structured JSON mode. |
| **Database & Vectors** | **PostgreSQL 16 + pgvector 0.8.7** | PostgreSQL / Apache 2.0 | **$0.00 / Local** | Single unified database for relational state, task DAGs, and HNSW vector similarity search. |
| **Vector Embeddings** | **FastEmbed** (`bge-base-en-v1.5`, 768d) | Apache 2.0 | **$0.00 / Local** | Sub-10ms CPU embedding generation via ONNX Runtime without consuming GPU VRAM. |
| **Control Plane API** | **FastAPI / Python 3.12+** | MIT | **$0.00 / Local** | Asynchronous execution, Pydantic v2 validation, OpenAPI schema generation. |
| **Web Research** | **DuckDuckGo + Playwright** | MIT / Apache 2.0 | **$0.00 / Local** | Free, zero-API-key search and headless browser DOM-to-Markdown extraction. |
| **Automations & Ingress** | **PostgreSQL Cron + Webhooks + Telegram** | Built-in / MIT | **$0.00 / Local** | Transactional `SKIP LOCKED` scheduler, HMAC webhook gateway, official Telegram Bot API long-polling. |
| **File Intelligence** | **PyPDF, python-docx, openpyxl, python-pptx, AST** | MIT / BSD / Apache 2.0 | **$0.00 / Local** | Multi-format parser isolation, formula injection defense, zip-bomb protection, hybrid search. |
| **Web Dashboard** | **Next.js 15 (App Router) + Tailwind CSS** | MIT | **$0.00 / Local** | React Server Components, real-time SSE token streaming, interactive DAGs, and File Intelligence UI. |
| **Observability & Audit** | **OpenTelemetry SDK + SHA-256 Audit Ledger** | Apache 2.0 | **$0.00 / Local** | Distributed tracing, secret redaction, and cryptographic hash-chained audit logging. |

---

## 4. Master Documentation Index

All architectural specifications, protocols, schemas, and implementation reports are located in the [`docs/`](docs/) directory:

| Document | Purpose & Scope |
| :--- | :--- |
| [**PRD.md**](docs/PRD.md) | Product Requirements Document (Vision, Zero-Cost Invariant, Functional & NFR Requirements). |
| [**SDD.md**](docs/SDD.md) | Software Design Document (Control Plane vs Runtime Separation, State Machines, Resilience). |
| [**ARCHITECTURE.md**](docs/ARCHITECTURE.md) | Core System Architecture (Topology, Sequence Diagrams, Multi-Agent Flow, Security Enclaves). |
| [**TECH_STACK.md**](docs/TECH_STACK.md) | Authoritative Technology Stack, Versions, Dependencies & Comparative Evaluations. |
| [**DATABASE_SCHEMA.md**](docs/DATABASE_SCHEMA.md) | Complete PostgreSQL 16 + pgvector Schema, DDL, Indexes & Entity Lifecycles. |
| [**AGENT_ARCHITECTURE.md**](docs/AGENT_ARCHITECTURE.md) | Local Agent Cognitive Loop, Supervisor Planning, Local Model Tiering. |
| [**MEMORY_ARCHITECTURE.md**](docs/MEMORY_ARCHITECTURE.md) | Zero-Cost Memory Architecture (PostgreSQL + pgvector + FastEmbed + Tombstoning). |
| [**TOOL_ARCHITECTURE.md**](docs/TOOL_ARCHITECTURE.md) | Tool Registry, JSON Schemas, 4-Tier Risk Classification, Secret Proxy, Sandboxing. |
| [**SECURITY_MODEL.md**](docs/SECURITY_MODEL.md) | Threat Model, Cryptographic HITL Tokens, Sandboxing, Tamper-Evident Audit Ledger. |
| [**API_SPECIFICATION.md**](docs/API_SPECIFICATION.md) | REST, SSE & Webhook Contracts, Payload Schemas, Webhook Ingress Protocol. |
| [**EVENT_AND_AUTOMATION.md**](docs/EVENT_AND_AUTOMATION.md) | Local Cron Schedulers, Webhook Ingress Gateway, Retry Jitter, Multi-Channel Dispatcher. |
| [**OBSERVABILITY.md**](docs/OBSERVABILITY.md) | OpenTelemetry Traces, Span Hierarchy, Metrics, PII & Secret Redaction Pipeline. |
| [**FRONTEND_ARCHITECTURE.md**](docs/FRONTEND_ARCHITECTURE.md) | Information Architecture (12 Core Views), Next.js 15, TanStack Query, Real-Time SSE. |
| [**ROADMAP.md**](docs/ROADMAP.md) | Phased Engineering Roadmap from Phase 1 to Production Launch. |
| [**TASK_BREAKDOWN.md**](docs/TASK_BREAKDOWN.md) | Granular Ticket-Level Work Breakdown Structure (AURA-101 through AURA-604). |
| [**PROJECT_MEMORY.md**](docs/PROJECT_MEMORY.md) | Living Architectural Index, Invariants, Glossary, Planned Directory Structure. |

---

## 5. Quickstart (100% Zero-Cost Local Setup)

### Prerequisites
* **Python 3.12+**
* **Node.js 18+** & npm
* **PostgreSQL 16** with `pgvector` extension (e.g. via local installation or Docker `pgvector/pgvector:pg16`)
* **Ollama** running locally on port 11434

### Step 1: Pull Local Models in Ollama
```bash
ollama pull qwen2.5:7b-instruct-q4_K_M
ollama pull llama3.2:3b-instruct-q4_K_M
```

### Step 2: Configure & Run FastAPI Control Plane
```bash
cd apps/api

# Install dependencies
pip install -r requirements.txt

# Run database migrations
alembic upgrade head

# Start FastAPI server
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Step 3: Configure & Run Next.js 15 Web Dashboard
```bash
cd apps/web

# Install dependencies
npm install

# Start Next.js development server
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) in your browser to access the AURA Command Center.

---

## 6. Verification & Test Suite

The entire AURA codebase is rigorously tested across all unit, integration, multi-tenant security, and end-to-end flows:

### Run Backend Pytest Suite (823 Tests)
```bash
cd apps/api
pytest
```
*Result: **823 passed / 0 skipped / 0 failed (100%)**.*

### Run Frontend Vitest Suite (33 Tests)
```bash
cd apps/web
npm test -- --run
```
*Result: **33 passed (100%)**.*

### Validate Next.js Production Build
```bash
cd apps/web
npm run build
```
*Result: **Static prerender generated successfully (Exit 0)**.*

---

## 7. License

AURA is released under the [MIT License](LICENSE).

