# Technology Stack & Ecosystem Specification (TECH_STACK.md)
## Project Name: AURA (Autonomous Universal Reactive Agent)
**Document Version:** 2.0.0  
**Phase:** Phase 0.5 — Zero-Cost Architecture Reconciliation & Invariant Audit  
**Classification:** Canonical Technology Decision & Ecosystem Matrix  

---

## 1. Zero-Cost / Local-First Technology Stack

Every technology in the AURA Core stack is **100% free, open-source, and locally runnable** on consumer hardware without any mandatory paid subscription, cloud billing, or external SaaS dependency.

| Subsystem | Technology Selected | Version | License | Cost / Deployment | Primary Rationale |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Local LLM Engine** | **Ollama** (or llama.cpp) | Latest (0.5+) | MIT / Open Source | **$0.00 / Local** | High-performance local GGUF model execution, GPU offloading (CUDA/ROCm/Metal), native OpenAI-compatible `/v1` endpoint, structured JSON mode. |
| **Local LLM Models** | `qwen2.5:7b-instruct-q4_K_M` & `llama3.2:3b-instruct-q4_K_M` | Latest | Apache 2.0 / Llama Community | **$0.00 / Local** | Qwen 2.5 7B provides state-of-the-art local function calling and tool execution. Llama 3.2 3B fits entirely in 4GB VRAM for <50ms instant extraction. |
| **Agent Runtime Substrate** | **Hermes Agent** (Nous Research) | Latest Stable | MIT / Apache 2.0 | **$0.00 / Local** | Procedural skill generation, persistent process execution, model-agnostic local routing via Ollama endpoint. |
| **Database & Vector Store** | **PostgreSQL 16 + pgvector** | 16.x + pgvector 0.7+ | PostgreSQL License / Apache 2.0 | **$0.00 / Local** | Single unified engine for relational state, task checkpoints, and HNSW vector similarity search. Zero extra DB infrastructure. |
| **Local Embeddings** | **FastEmbed** (`BAAI/bge-base-en-v1.5`, 768-dim) | Latest (Python) | Apache 2.0 | **$0.00 / Local** | Sub-10ms local embedding generation on CPU (ONNX Runtime, no intentional GPU allocation). No paid embedding API keys required. |
| **Control Plane API** | **FastAPI / Python** | Python 3.12+, FastAPI 0.115+ | MIT | **$0.00 / Local** | Async concurrency, native Pydantic v2 validation, OpenAPI schema generation. |
| **Web Research & Search** | **DuckDuckGo Search + SearXNG + Playwright** | Latest | MIT / AGPLv3 / Apache 2.0 | **$0.00 / Local** | Free, zero-API-key web search, metasearch aggregation, and local headless browser DOM extraction. |
| **Job Queue & Scheduler** | **PostgreSQL Async Worker** (`FOR UPDATE SKIP LOCKED`) | Built-in | PostgreSQL License | **$0.00 / Local** | Transactional job dispatch directly in PostgreSQL. Zero external queue broker needed for personal OS. |
| **Integration Boundary** | **Model Context Protocol (MCP)** | 2024-11-05 Spec | Open Standard | **$0.00 / Local** | Local `stdio` subprocess tool execution (GitHub, Filesystem, SQLite, Playwright). |
| **Execution Sandboxing** | **Docker CE / Firejail** | 26+ / 0.9.72+ | Apache 2.0 / GPLv2 | **$0.00 / Local** | Unprivileged process isolation, read-only root filesystems, dropped capabilities. |
| **Web Dashboard** | **Next.js 15 / TypeScript / Tailwind v4** | Next.js 15+, TS 5.5+ | MIT | **$0.00 / Local** | React Server Components, responsive dark-mode command center, local SSE token streaming on `localhost:3000`. |
| **Observability & Audit** | **OpenTelemetry SDK + Local SQLite / Postgres Logs** | 1.25+ | Apache 2.0 | **$0.00 / Local** | Structured local spans, token counters, and cryptographic SHA-256 hash-chained audit ledger. |

---

## 2. Hardware-Aware Model Strategy (Validated for AMD Ryzen 7 + 24GB RAM + 4GB VRAM)

*Estimated resource envelope; actual usage must be measured on the target machine under representative workloads.*

```
+====================================================================================================+
|                                    HARDWARE-ADAPTIVE MODEL TIERS                                   |
+====================================================================================================+
|                                                                                                    |
|  1. GENERAL & TOOL-CALLING TIER: `qwen2.5:7b-instruct-q4_K_M` (Size: ~4.7 GB)                     |
|     - Offload: ~24 layers to 4GB RTX 3050 GPU; remaining layers to 24GB System RAM (CPU offload). |
|     - Performance: ~18-25 tokens/sec. 32k context window. 99% accuracy on JSON tool schemas.      |
|                                                                                                    |
|  2. FAST & ROUTINE EXTRACTION TIER: `llama3.2:3b-instruct-q4_K_M` (Size: ~2.0 GB)                  |
|     - Offload: 100% in 4GB GPU VRAM. Zero CPU offload bottleneck.                                  |
|     - Performance: ~45-60 tokens/sec. Instantaneous fact extraction & intent classification.        |
|                                                                                                    |
|  3. REASONING TIER: `deepseek-r1:7b` / `deepseek-r1:8b-llama3.1-q4_K_M` (Size: ~4.9 GB)            |
|     - Offload: Hybrid GPU/CPU. Complex planning & DAG decomposition with chain-of-thought.          |
|                                                                                                    |
|  4. LOCAL EMBEDDING TIER: FastEmbed `BAAI/bge-base-en-v1.5` (768-dim, ~300 MB RAM)                 |
|     - Execution: In-memory CPU (ONNX Runtime, no intentional GPU allocation). Sub-10ms latency.    |
|                                                                                                    |
+====================================================================================================+
```

---

## 3. The 3-Tier Cost Classification Architecture

AURA explicitly organizes all dependencies into three strict tiers:

* **TIER 1 (Required & Zero-Cost):** 
  * Ollama, local models (Qwen2.5-7B, Llama-3.2-3B), PostgreSQL 16 + pgvector, FastEmbed, DuckDuckGo Search, Playwright, FastAPI, Next.js 15, Docker/Firejail.
  * *Constraint:* AURA **MUST** boot, execute goals, search the web, recall memories, and run automations using **only** Tier 1 components.
* **TIER 2 (Optional Zero-Cost):**
  * Self-hosted SearXNG instance, self-hosted Langfuse Docker, local Whisper STT / Piper TTS, local Telegram Bot API (long-polling).
  * *Constraint:* Free enhancements requiring optional local setup; never mandatory.
* **TIER 3 (Optional Bring-Your-Own-Key Cloud Adapters):**
  * **Google Gemini BYOK (Official SDK `google-genai` / OpenAI-compatible endpoint):** User-supplied API key; supports `gemini-2.5-flash`, `gemini-2.5-pro`.
  * **Future Adapters:** Anthropic Claude API, OpenAI API, Tavily Search, ElevenLabs Voice.
  * *Constraint:* Purely optional BYOK adapters. The system must remain 100% functional via Tier 1 local components if every Tier 3 key is omitted or revoked.

---

## 4. BYOK Security & Cloud Model Specification

### 4.1 Cryptographic Storage & Key Vault
* **Library:** `cryptography` (Python `Fernet` / `AESGCM` primitives).
* **Master Key:** `AURA_MASTER_ENCRYPTION_KEY` loaded via environment variable or OS Keyring (never stored in PostgreSQL).
* **Storage Column:** `credentials.encrypted_secret` (AES-256-GCM ciphertext with random IV and authentication tag).
* **UI Display:** Key fingerprint SHA-256 prefix/suffix (e.g. `AIza...4f8a`) to prevent plaintext key exposure.

### 4.2 Google Gemini BYOK Adapter Architecture
* **Official SDK:** `google-genai` (Modern unified Google GenAI SDK) with support for direct REST calls via `httpx`.
* **API Endpoints:**
  * Native Google AI Studio: `https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent`
  * OpenAI-Compatible Surface: `https://generativelanguage.googleapis.com/v1beta/openai/chat/completions`
* **Supported Models (Current Active Catalog):**
  * `gemini-2.5-flash`: Fast multimodal reasoning, 1M+ token context window, lowest latency (Primary Fast Cloud Tier).
  * `gemini-2.5-pro`: Advanced complex reasoning, code synthesis, multi-step planning (Frontier Reasoning Cloud Tier).
  * *(Decommissioned/Retired Models: `gemini-2.0-flash`, `gemini-1.5-flash`, `gemini-1.5-pro`, `gemini-1.0-pro`)*.
* **Authentication Flow:** API key passed exclusively via backend HTTP header `x-goog-api-key` or `Authorization: Bearer <API_KEY>`. No frontend client calls.
* **Cost Classification:**
  * Free-tier AI Studio keys are subject to Google rate limits (RPM/RPD/TPM).
  * Pay-as-you-go keys incur standard Google Cloud per-token charges.
  * AURA surfaces transparent billing badges in UI and enforces task-level token budgets.

