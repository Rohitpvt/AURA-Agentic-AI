# Architecture Decision Records (ARCHITECTURE_DECISIONS.md)
## Project Name: AURA (Autonomous Universal Reactive Agent)
**Document Version:** 2.0.0  
**Phase:** Phase 0.5 — Zero-Cost Architecture Reconciliation & Invariant Audit  
**Classification:** Formal Architecture Decision Records (ADRs)  

---

## ADR-001: Hermes Agent Framework as Execution Substrate (Wrapped & Governed)

* **Status:** Accepted
* **Context:** We need a cognitive execution engine capable of long-running agent loops, procedural skill acquisition, and multi-model tool calling without writing basic agent loops from scratch.
* **Decision:** Adopt the Hermes Agent framework (Nous Research) as the lower-level execution substrate, strictly wrapped inside AURA's Control Plane, running entirely against local model endpoints (Ollama / llama.cpp / vLLM), and governed by our deterministic policy engine.
* **Zero-Cost Validation:** Hermes is fully open-source (MIT/Apache 2.0) and supports custom OpenAI-compatible local endpoints (Ollama at `http://localhost:11434/v1`). No paid subscription or Nous Portal cloud account is required.
* **Alternatives Considered:**
  1. *Build Raw Prompt Graphs from Scratch:* High development effort; reinvents wheel on skill acquisition and tool parsing.
  2. *LangGraph / CrewAI:* Opinionated, rigid conversational paradigms; lack native persistent procedural skill generation.
* **Advantages:** Built-in procedural skill learning, model-agnostic local architecture, zero mandatory cloud dependencies.
* **Disadvantages:** Requires custom wrapping for deterministic security and local sandboxing.
* **Risks:** Tight coupling to Hermes internal state formats.
* **Migration / Mitigation:** Encapsulate Hermes behind an internal interface (`AgentRuntimeEngine`) so the execution engine can be swapped or customized locally.

---

## ADR-002: Zero-Cost Hybrid Memory Architecture (PostgreSQL 16 + pgvector + Local Embeddings)

* **Status:** Revised (Supersedes previous external Honcho dependency)
* **Context:** AI agents require deterministic relational storage for application state (users, tasks, logs) AND dialectical cognitive memory for user modeling and cross-session semantic recall without incurring SaaS subscription costs or memory container bloat.
* **Decision:** Deploy local **PostgreSQL 16 with the `pgvector` extension** as the single unified persistence and cognitive memory engine. Semantic embeddings are computed locally using **FastEmbed (`BAAI/bge-base-en-v1.5`, 768-dim)** on CPU (ONNX Runtime, with no intentional GPU allocation) with zero external API calls. Honcho is retained purely as an optional external adapter.
* **Zero-Cost Validation:** PostgreSQL, `pgvector`, and FastEmbed are 100% free, open-source, and run on local hardware with zero network egress, zero API billing, and complete data privacy.
* **Alternatives Considered:**
  1. *Dedicated Honcho SaaS Platform:* Incurs paid monthly subscriptions and external data transmission.
  2. *Honcho Self-Hosted Multi-Container Stack:* Requires running multiple extra containers (Honcho API, separate Redis, separate Postgres), consuming ~3 GB extra RAM on resource-constrained local machines.
  3. *Pure Vector Database (Pinecone/Chroma):* Adds unnecessary distributed infrastructure.
* **Advantages:** Unified database instance; zero added infrastructure; fast hybrid search (pgvector cosine distance + Postgres Full-Text Search for BM25); 100% zero cost.
* **Disadvantages:** Dialectical user modeling logic is implemented directly in AURA Control Plane Python services rather than an external cognitive microservice.
* **Risks:** Vector index performance at scale.
* **Migration / Mitigation:** Utilize `HNSW` vector indexing in `pgvector` for sub-10ms similarity searches across millions of local memory embeddings.

---

## ADR-003: Model Context Protocol (MCP) as Primary Extensibility Boundary

* **Status:** Accepted
* **Context:** We need a scalable, standard way to connect AURA to local tools, databases, and developer environments without writing custom monolithic adapters.
* **Decision:** Adopt Anthropic's open **Model Context Protocol (MCP)** using `stdio` (local subprocess pipes) and local `SSE` servers as the primary integration boundary.
* **Zero-Cost Validation:** MCP is an open standard specification. Local MCP servers (GitHub, Filesystem, SQLite, Postgres, Playwright) run as free local processes on the host.
* **Alternatives Considered:**
  1. *Custom Proprietary Tool Plugins:* High maintenance burden; non-standard; closed ecosystem.
  2. *LangChain Toolkits:* Bloated dependencies; tight coupling to Python ecosystem.
* **Advantages:** Standardized tool discovery; isolated subprocess execution; compatibility with a massive ecosystem of free open-source MCP servers.
* **Disadvantages:** Subprocess management overhead for `stdio` transports.
* **Risks:** Untrusted third-party MCP servers attempting malicious host actions.
* **Migration / Mitigation:** Enforce sandboxing on all MCP subprocesses and filter available tools dynamically via workspace policy.

---

## ADR-004: Local-First Multi-Tier Model Architecture via Ollama & Local Gateway

* **Status:** Revised (Supersedes mandatory cloud router requirement)
* **Context:** AURA must run 100% offline and cost-free on consumer hardware (e.g. AMD Ryzen 7 / 24GB RAM / 4GB VRAM GPU) while supporting dynamic model switching.
* **Decision:** Standardize on **Ollama (or local llama.cpp / vLLM)** as the primary local LLM inference engine. A lightweight Python Model Gateway routes requests across local model tiers:
  * **General & Tool-Calling Tier:** `qwen2.5:7b-instruct-q4_K_M` or `hermes3:8b-llama3.1-q4_K_M` (hybrid GPU + CPU offload)
  * **Fast / Routine Extraction Tier:** `llama3.2:3b-instruct-q4_K_M` or `qwen2.5:3b-instruct-q4_K_M` (Fits entirely in 4GB VRAM)
  * **Reasoning Tier:** `deepseek-r1:7b` / `deepseek-r1:8b` (Distilled open-weights)
  * **Embedding Tier:** FastEmbed `BAAI/bge-base-en-v1.5` (768-dim, CPU ONNX Runtime)
* **Zero-Cost Validation:** All recommended models possess permissive open licenses (Apache 2.0 / MIT / Llama 3.1 & 3.2 Community Licenses) and run 100% locally with zero API keys and zero billing.
* **Alternatives Considered:**
  1. *Mandatory OpenRouter / LiteLLM Cloud Proxy:* Requires credit card, paid tokens, and internet connectivity.
  2. *Single Monolithic 70B Model:* Exceeds consumer VRAM/RAM capacity, resulting in unusable token latency (<1 tok/sec).
* **Advantages:** 100% offline capability; $0.00 operating cost; low latency for routine tasks; hardware-adaptive.
* **Disadvantages:** Local models have lower raw reasoning capacity than trillion-parameter frontier cloud models.
* **Risks:** Quantization loss affecting complex tool call schema adherence.
* **Migration / Mitigation:** Use structured JSON grammar enforcement (`format: "json"` / Pydantic schema constraints) in Ollama to guarantee 100% valid tool call syntax. Cloud model adapters (Claude, OpenAI) remain optional Tier-3 plugins.

---

## ADR-005: Deterministic Policy Engine & Cryptographic HITL Tokens

* **Status:** Accepted
* **Context:** LLMs must never be trusted to evaluate their own security boundaries or authorize dangerous side effects.
* **Decision:** Build an independent, deterministic Policy Engine in Python that intercepts all tool calls. High/Critical risk actions generate cryptographically signed (HMAC-SHA256) Approval Tokens with a 15-minute TTL that require explicit user resolution in the Web Dashboard.
* **Zero-Cost Validation:** Implemented using standard Python `hashlib` and `hmac` libraries. Zero external costs.
* **Alternatives Considered:**
  1. *Prompt-based Guardrails (LLM self-policing):* Vulnerable to prompt injection and jailbreaks.
  2. *Manual Approval for Every Tool Call:* Destroys agentic autonomy and causes extreme user friction.
* **Advantages:** Mathematically verifiable security; zero possibility of LLM hallucinating approval; full audit trail.
* **Disadvantages:** User must occasionally interact to approve sensitive operations.
* **Risks:** Approval token expiration causing task timeout if user is away.
* **Migration / Mitigation:** Implement push notifications to local dashboard and optional Telegram bot.

---

## ADR-006: Local PostgreSQL-Backed Job Queue for Task Scheduling

* **Status:** Accepted & Confirmed Zero-Cost
* **Context:** AURA requires reliable background job processing and Cron scheduling without requiring external paid queue SaaS or heavy multi-container clusters.
* **Decision:** Utilize PostgreSQL-backed transactional queuing (`FOR UPDATE SKIP LOCKED` async worker / `pg_boss`) for all background task orchestration.
* **Zero-Cost Validation:** Runs directly inside the local PostgreSQL 16 database. Zero extra infrastructure, zero paid queue subscriptions.
* **Alternatives Considered:**
  1. *Hosted Celery / AWS SQS / Temporal Cloud:* Incurs cloud infrastructure costs and external maintenance.
  2. *Separate RabbitMQ / Kafka Cluster:* Adds 1+ GB RAM overhead and operational complexity.
* **Advantages:** Zero additional infrastructure; atomic transaction guarantees (task creation and queue insertion commit together); simple observability via SQL.
* **Disadvantages:** Throughput bounded by local disk IOPS (more than sufficient for personal OS workloads).
* **Risks:** Database polling overhead.
* **Migration / Mitigation:** Use PostgreSQL `LISTEN/NOTIFY` for instant event wakeups and indexed polling.

---

## ADR-007: Granular Autonomy Levels (L0 to L5) with Hard Ceilings

* **Status:** Accepted
* **Context:** Users require fine-grained control over how independently AURA can act across different contexts and tasks.
* **Decision:** Establish a 6-tier Autonomy taxonomy (L0: Chat Only, L1: Assistive, L2: Supervised Multi-Step, L3: Scheduled Batch, L4: Proactive Event-Driven, L5: Controlled Meta-Evolution) bounded by strict local execution timeouts and recursion ceilings.
* **Zero-Cost Validation:** Policy is implemented entirely in local application logic.

---

## ADR-008: Ephemeral Local Sandboxing for Code & Shell Execution

* **Status:** Accepted
* **Context:** Arbitrary code execution and shell commands generated by LLMs represent a severe host compromise vulnerability even on a local personal computer.
* **Decision:** Isolate all shell, script, and filesystem tool executions inside ephemeral Docker or Firejail containers with read-only root filesystems and dropped Linux capabilities.
* **Zero-Cost Validation:** Docker Community Edition (CE) and Firejail are 100% free and open-source.

---

## ADR-009: Next.js 15 App Router + TanStack Query for Local Command Center

* **Status:** Accepted
* **Context:** The frontend dashboard must provide rich, low-latency, real-time observability into the agent's internal state, tasks, and memory on the local machine.
* **Decision:** Build the Web Dashboard using Next.js 15 (App Router), TypeScript, Tailwind CSS v4, and TanStack Query v5 with local Server-Sent Events (SSE) streaming connecting to `localhost:8000`.
* **Zero-Cost Validation:** Next.js and React are open-source (MIT). Runs locally on `http://localhost:3000` with zero hosting fees.

---

## ADR-010: Tamper-Evident Immutable Audit Log via Cryptographic Hash Chaining

* **Status:** Accepted
* **Context:** Enterprise security and compliance require proof that sensitive agent actions and approvals have not been altered or deleted.
* **Decision:** Implement a blockchain-inspired SHA-256 cryptographic hash chain on the `audit_logs` table in local PostgreSQL.
* **Zero-Cost Validation:** Uses standard SHA-256 hashing. Zero external dependencies.

---

## ADR-011: Zero-Cost Multi-Platform Ingress Strategy

* **Status:** Revised
* **Context:** Users need to interact with AURA from messaging apps and local CLI without paying for webhook proxies or paid gateway services.
* **Decision:** Use the official free Telegram Bot API (long-polling mode, zero public IP / webhook hosting needed) and Discord Bot API as optional ingress adapters that forward events directly to the local FastAPI Control Plane.
* **Zero-Cost Validation:** Telegram Bot API and Discord Gateway are completely free for personal bot operations.

---

## ADR-012: Versioned Markdown Skill Specification (`SKILL.md`) with Controlled Promotion Gate

* **Status:** Accepted
* **Context:** Procedural workflows and recipes must be version-controlled, inspectable by humans, and self-optimizable locally.
* **Decision:** Standardize skills as versioned Markdown files (`SKILL.md`) containing YAML frontmatter and step-by-step assertions, with proposed self-improvements subject to administrative promotion.
* **Zero-Cost Validation:** File-based Markdown and SQL storage. Zero cost.

---

## ADR-013: Boundary Separation between TECH_STACK.md and TRD.md

* **Status:** Accepted
* **Decision:** `TECH_STACK.md` is the single canonical source of truth for technology choices, versions, and dependencies. `TRD.md` is the authoritative specification for technical requirements, performance SLAs, and protocol constraints.

---

## ADR-014: Zero-Cost / Local-First Core Architecture (THE ZERO-COST INVARIANT)

* **Status:** Accepted & Mandatory (NON-NEGOTIABLE ARCHITECTURAL INVARIANT)
* **Context:** AURA must never depend on mandatory paid APIs, paid SaaS subscriptions, paid cloud platforms, or per-use billing services. The entire core system must be buildable, runnable, and fully functional on a user's local personal computer.
* **Decision:** 
  1. **Core Invariant:** "AURA Core must remain 100% operational using locally hosted, open-source components without requiring any paid external service."
  2. **Mandatory Stack:** Ollama (Local LLM), PostgreSQL 16 + pgvector (Local DB & Memory), FastEmbed (Local Embeddings), DuckDuckGo / SearXNG / Playwright (Free Local Web Retrieval), FastAPI (Local Control Plane), Next.js 15 (Local Web UI), Docker / Firejail (Local Sandboxing).
  3. **Cloud & Paid Decoupling:** Any cloud LLM provider (Anthropic, OpenAI), paid search API (Tavily), paid voice API (ElevenLabs), or hosted platform is strictly categorized as an **Optional Tier-3 Plugin**. The core system must boot, execute tasks, recall memory, browse the web, and schedule automations with zero external API keys configured.
* **Consequences:**
  * **Zero Financial Barrier:** Anyone with a standard computer can run AURA indefinitely with $0.00 ongoing service costs.
  * **Total Privacy & Data Sovereignty:** Prompts, documents, memories, and code never leave the local machine.
  * **Resilience:** Completely immune to third-party API outages, price hikes, rate limit blocks, or terms-of-service deprecations.
* **Hardware Implications:** System runs on standard 8-core CPU with 16–24 GB RAM and 4 GB VRAM (e.g. AMD Ryzen 7 + RTX 3050) using optimized 3B–8B quantized models (Q4_K_M / Q5_K_M).

---

## ADR-015: Provider-Neutral Model Interface with Secure Bring-Your-Own-Key (BYOK)

* **Status:** Accepted (Augments ADR-004 & ADR-014)
* **Context:** While AURA is strictly Zero-Cost Local-First by default (ADR-014), users frequently possess their own API credentials for frontier cloud models (starting with Google Gemini) and wish to leverage them selectively for complex reasoning tasks, while keeping data private and costs completely transparent. Hardcoding any cloud provider directly into the Agent Core violates architectural decoupling and creates vendor lock-in.
* **Decision:**
  1. **Provider-Neutral Abstraction:** Decouple the Agent Core from all model runtimes via an abstract `ModelProvider` interface (`generate`, `stream`, `embed`, `validate_credentials`, `health_check`).
  2. **Core Providers:**
     - `OllamaProvider`: Default, zero-cost, local-only, no API keys, zero network egress.
     - `GeminiProvider`: Optional BYOK cloud adapter utilizing the official `google-genai` SDK and/or Google's native OpenAI-compatible API endpoint (`https://generativelanguage.googleapis.com/v1beta/openai/`).
     - Future adapters (`OpenAIProvider`, `AnthropicProvider`) plug into the same abstraction without changing Agent Core logic.
  3. **Deterministic Routing Modes:**
     - `LOCAL_ONLY` (Default): Hard enforcement. No cloud provider requests are permitted.
     - `BYOK_ONLY`: Uses the user-configured BYOK provider for all tasks.
     - `AUTO`: Prefers local model; escalates to configured BYOK provider only if task complexity requires it and workspace policy permits; falls back gracefully to local Ollama.
  4. **Strict Zero Secret Leakage:**
     - Master encryption key (`AURA_MASTER_ENCRYPTION_KEY`) is stored outside the database (in environment / OS keyring).
     - Credentials are encrypted at rest using AES-256-GCM / Authenticated Cryptography before persisting to PostgreSQL.
     - Credentials are never exposed to the frontend JavaScript runtime, never logged in telemetry, never included in agent prompts, and never committed to version control.
  5. **Explicit Cost & Billing Transparency:**
     - The system explicitly distinguishes `LOCAL_ZERO_COST`, `BYOK_FREE_TIER`, and `BYOK_POTENTIALLY_BILLABLE`.
     - Silent/hidden paid fallbacks are strictly prohibited. The system fails clearly or falls back to local execution.
* **Zero-Cost Validation:** BYOK is strictly optional. If a user deletes all cloud credentials, AURA continues operating 100% locally via Ollama with zero degradation of core functionality.
* **Alternatives Considered:**
  1. *Direct Integration of Gemini in Agent Core:* Tight coupling; creates cloud dependencies and breaks zero-cost invariant.
  2. *Frontend Direct Key Ingestion:* Critical security vulnerability; leaks credentials in browser memory and devtools.
  3. *Unencrypted Key Storage in DB:* High risk of credential exfiltration upon database dump or backup inspection.
* **Advantages:** Clean architectural separation; allows users to leverage frontier models if desired; prevents provider lock-in; military-grade credential protection.
* **Disadvantages:** Adds credential encryption/decryption overhead on the Control Plane backend.
* **Risks:** User accounts incurring unexpected cloud charges if billing policies are misconfigured.
* **Migration / Mitigation:** Enforce per-task and daily token budgets, display prominent billing transparency banners in UI, and require explicit user opt-in before executing cloud-routed tasks.

---

## ADR-016: Verified Agent Runtime Architecture & Single Authoritative Tool Governance

* **Status:** Accepted (Supersedes preliminary Hermes encapsulation assumptions in ADR-001)
* **Context:** Phase 0 specifications originally envisioned adopting the external Hermes Agent framework (Nous Research) as the lower-level execution substrate. Following the Phase 2A Runtime Authenticity Audit, we verified that:
  1. Hermes Agent as an external CLI/framework maintains its own independent tool discovery and filesystem/web dispatchers, which would create a dangerous split-brain tool execution model bypassing AURA's `ToolRegistryService` and HMAC-signed HITL governance.
  2. Hermes reference deployments mandate a minimum 64K token context window. On consumer host hardware (AMD Ryzen 7 4800H, 24GB RAM, NVIDIA RTX 3050 4GB VRAM), allocating a 64K KV cache causes severe memory swapping, out-of-memory thrashing, or extreme latency (<1 tok/sec).
  3. Embedding an external black-box library creates tight coupling to external upstream schemas and bypasses AURA's multi-tier `ModelProvider` routing and AES-256-GCM encrypted BYOK credential vault.
* **Decision:**
  1. **Adopt AURA-Native Cognitive Runtime (Path B):** Implement a clean, native, and modular agent execution engine composed of:
     - `AgentRuntimeEngine`: Primary control-plane facade managing execution lifecycle, health probes, and cooperative cancellation.
     - `SupervisorPlanner`: Decomposes user goals into structured, non-cyclic Task DAGs validated via Kahn's algorithm before execution.
     - `AuraAgentSubstrate`: Executes single-turn cognitive steps, structured JSON function calling, and observation synthesis via the `ModelProvider` contract.
     - `AgentExecutionLoop`: Orchestrates the *Observe $\rightarrow$ Decide $\rightarrow$ Act $\rightarrow$ Verify* loop with step checkpointing, FastEmbed semantic memory retrieval, governed writeback, and deterministic loop circuit breakers.
  2. **Single Authoritative Tool Governance Boundary:** All model-requested tool calls must strictly pass through `AgentToolBridge` $\rightarrow$ `ToolRegistryService`. No direct, unmonitored tool execution is permitted. Web search results are quarantined and sanitized as untrusted external content.
  3. **Hardware-Tuned Bounded Context (8,192 Tokens):** Local context length is deterministically bounded to 8,192 tokens with prompt compression and selective top-$k$ memory recall, guaranteeing responsive local execution on 4GB VRAM consumer laptops.
* **Zero-Cost Validation:** The runtime executes 100% locally against Ollama (`qwen2.5:7b-instruct-q4_K_M` or `llama3.2:3b-instruct-q4_K_M`) and FastEmbed (`BAAI/bge-base-en-v1.5`) with zero paid API dependencies.
* **Alternatives Considered:**
  1. *Subprocess Hermes CLI Execution (Path A):* Rejected due to split-brain tool governance, uncontrolled subprocess overhead, and 64K context hardware incompatibilities.
  2. *Hybrid Hermes Runtime (Path C):* Rejected because maintaining dual orchestration layers adds architectural complexity without security or performance benefits.
* **Advantages:** Absolute tool authorization governance; zero secret leakage; fully responsive on consumer hardware; 100% testable via deterministic unit and integration suites.
* **Disadvantages:** Advanced procedural skill learning must be implemented via AURA's own `SkillRegistryService` in Phase 2B.
* **Risks:** Local open-weight models generating non-JSON output.
* **Migration / Mitigation:** The runtime features deterministic JSON extraction and heuristic fallback plan generation to ensure execution continuity under any model output format.

---

## ADR-017: Local MCP Host Subprocess Governance and Dynamic Tool Normalization

* **Status:** Accepted (Phase 2B)
* **Context:** AURA requires an extensible tool ecosystem supporting external tool servers via the open Model Context Protocol (MCP). However, connecting external or third-party MCP servers introduces severe security, isolation, and process-management risks if executed unmonitored.
* **Decision:**
  1. **Local Subprocess Architecture:** Implement `StdioMCPClient` and `MCPHostManager` managing local `stdio` subprocesses. No cloud-hosted MCP services or proprietary relays are permitted.
  2. **Single Authoritative Tool Boundary:** MCP-discovered tools must be validated, normalized into canonical AURA schemas (`mcp_{server_name}_{tool_name}`), and registered directly into `ToolRegistryService`. The model/sub-agent never communicates with raw MCP transports.
  3. **Untrusted Content Quarantining:** All MCP tool outputs are flagged with `is_untrusted_content: True` and sanitized before reaching LLM context windows to prevent prompt injection and instruction hijack.
  4. **Deterministic Lifecycle & Zombie Prevention:** Process supervisor enforces startup timeouts, per-call execution timeouts, graceful SIGTERM/SIGKILL termination, and explicit cleanup on task cancellation.
* **Zero-Cost Validation:** 100% zero-cost local stdio subprocesses.
* **Alternatives Considered:**
  1. *Direct Model-to-MCP transport:* Rejected due to severe prompt injection and privilege escalation risks.
  2. *Hosted cloud MCP gateways:* Rejected to uphold the Zero-Cost Invariant.

---

## ADR-018: Deterministic Cryptographic HITL State Suspension & Resumption Engine

* **Status:** Accepted (Phase 2B)
* **Context:** High-risk and critical tools (e.g. filesystem destruction, deployment, credential alteration) require mandatory human authorization before side-effect execution. Previous mocks simply validated tokens in memory.
* **Decision:**
  1. **Cryptographic Binding:** Generate HMAC-SHA256 tokens bound to `(approval_id, workspace_id, task_id, step_number, tool_name, exact_param_hash, expires_at)`.
  2. **State Machine Suspension:** When high-risk tools are requested, the runtime halts task/step progress into `waiting_approval` and checkpoints the exact DAG execution state.
  3. **Atomic Resolution with Row Locks:** The `/api/v1/approvals/{id}/resolve` endpoint uses database row-level locking (`SELECT ... FOR UPDATE`) to prevent race conditions and enforce single-use replay protection.
  4. **Pre-Execution Policy Re-check:** Immediately prior to side-effect resumption, permissions, workspace scopes, and parameter hashes are re-evaluated against the active database state.
* **Zero-Cost Validation:** Native FastAPI + PostgreSQL + HMAC-SHA256 with zero third-party approval SaaS dependencies.

---

## ADR-019: Bounded Local Sub-Agent Worker Pool and Scoped Delegation Model

* **Status:** Accepted (Phase 2B)
* **Context:** Complex multi-step reasoning often benefits from hierarchical delegation. However, unconstrained sub-agent spawning can cause infinite recursion, memory thrashing, and compute exhaustion on consumer hardware.
* **Decision:**
  1. **Strict Recursion Depth Cap ($\le 2$):** Hierarchy is strictly bounded: `Supervisor (Depth 0)` $\rightarrow$ `Sub-Agent (Depth 1)` $\rightarrow$ `Leaf (Depth 2)`. Deeper recursive delegation is rejected deterministically.
  2. **Bounded Concurrency Semaphore ($\le 4$):** Active sub-agent workers are capped at a maximum of 4 concurrent tasks per supervisor instance to respect consumer host resources (AMD Ryzen 7 4800H / 24GB RAM).
  3. **Role-Based Tool Scoping:** Fixed role specifications (`research_agent`, `analysis_agent`, `coding_agent`, `synthesis_agent`) with explicit tool allowlists. Sub-agents cannot invoke unauthorized or unassigned tools.
  4. **Structured Result Contract:** Sub-agents must return validated `SubAgentResult` payloads (subtask, status, findings, artifacts, verification, consumed tokens) without leaking internal chain-of-thought traces.
  5. **Cooperative Task Cancellation:** Cancellation from the parent task propagates immediately through the worker pool to terminate all active sub-agent tasks without leaving zombie processes.
* **Zero-Cost Validation:** Uses local `OllamaProvider` and local CPU thread pools with zero external agent cloud APIs.

---

## ADR-020: Ephemeral Docker Container Sandboxing and Fail-Closed Host Execution Policy

* **Status:** Accepted (Phase 2C — Advanced from Phase 5)
* **Context:** Enabling code generation, script execution, and technical development tools presents critical security hazards if executed directly on the host machine. On Windows and Linux, unconstrained shell execution could lead to host compromise or data exfiltration.
* **Decision:**
  1. **Strict Fail-Closed Host Policy:** Unsandboxed host execution is strictly prohibited for arbitrary code, shell commands, and untrusted binaries. If Docker/container sandbox is unavailable or disabled, execution fails closed with `AuthorizationError`.
  2. **Profile-Based Isolation:** Implement deterministic container profiles (`READ_ONLY`, `DEVELOPMENT`, `NETWORK_RESEARCH`, `HIGH_RISK`) with dropped capabilities (`--cap-drop ALL`), `--security-opt no-new-privileges`, read-only rootfilesystems, memory limits (max 512MB default), and bounded CPU quotas.
  3. **Strict Volume Scoping:** Containers mount exclusively the designated canonical workspace root (`/workspace`), preventing access to host drives, OS system binaries, or external user directories.
* **Zero-Cost Validation:** 100% zero-cost local Docker / WSL2 container engine.

---

## ADR-021: Multi-Layer Network Isolation and SSRF Defense Shield

* **Status:** Accepted (Phase 2C)
* **Context:** Web search extraction and future browser tools require outbound HTTP connectivity. Without rigorous validation, malicious prompts or injected web URLs could trigger SSRF attacks targeting loopback services (`127.0.0.1:8000`), local databases (`5432`), internal networks (RFC 1918), or cloud metadata endpoints (`169.254.169.254`).
* **Decision:**
  1. **Pre-Flight IP and Scheme Validation:** `SSRFProtectionGuard` inspects URL schemes (allowing only `http` and `https`), resolves hostnames synchronously, and blocks loopback, private RFC 1918 (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), link-local (`169.254.0.0/16`), cloud metadata (`169.254.169.254`), and multicast addresses.
  2. **Redirect Validation:** Outbound clients validate each HTTP redirect target prior to following links.
* **Zero-Cost Validation:** Pure Python socket and IPAddress validation with zero external dependencies.

---

## ADR-022: Emergency Execution Kill-Switch and Tamper-Evident Ledger Verifier

* **Status:** Accepted (Phase 2C — Advanced from Phase 5)
* **Context:** Operators require an immediate, sub-500ms circuit breaker to abort runaway agent loops, sub-agent workers, sandboxes, and MCP subprocesses, along with cryptographic proof of audit ledger integrity.
* **Decision:**
  1. **Emergency Kill-Switch Service (`kill_switch`):** Broadcasts simultaneous cancellation across `AgentRuntimeEngine`, `SubAgentWorkerPool`, `SandboxManager`, and `MCPHostManager`, updates database task/run states to `cancelled`, appends a tamper-evident audit record, and measures total cancellation latency ($<500$ms target, $<15$ms verified).
---

## ADR-023: Single Unified Capability Architecture vs Autonomous Sub-Runtimes

* **Status:** Accepted (Phase 5 Preflight)
* **Context:** As AURA expands to encompass rich multimodal, voice, vision, file analysis, OS control, and browser automation capabilities, a critical design question arises: Should each new capability (Voice, Vision, OS, Files, Browser) introduce its own independent "Capability Sub-Runtime" with separate loop logic and policy enforcement, or should all capabilities be modeled as governed tools within AURA's unified execution and governance framework?
* **Decision:**
  1. **Single Authoritative Execution Chain:** All future capabilities are strictly integrated into AURA's unified execution and governance framework without creating split-brain sub-runtimes.
  2. **Four-Layer Architecture Taxonomy:**
     - **Interfaces (Sensors & Ingress):** Web Dashboard (`localhost:3000`), Microphone Audio Stream, Screen Capture, Camera Video, Telegram Bot API, Inbound Webhooks.
     - **Capability Services (Domain Engines):** Speech STT (Faster-Whisper), TTS (Piper), OCR (Tesseract), Local VLM (Moondream2 / Qwen2-VL), Document Parser, Browser Manager.
     - **Governed Tools (Execution-Capable Units):** `web_extract`, `web_search`, `read_file`, `write_file`, `system_volume_set`, `browser_click_element`. Each dispatched tool must pass through `AgentToolBridge` $\rightarrow$ `ToolRegistryService` $\rightarrow$ `PolicyEngine` (HITL Gate) $\rightarrow$ Sandbox/Isolation $\rightarrow$ Audit Ledger.
     - **Runtime Infrastructure (Daemons & Transports):** PostgreSQL Cron Scheduler Daemon, Telegram Long-Poller Daemon, EventBroadcasterHub SSE stream, OpenTelemetry Tracing Exporter, Windows Startup Daemon Service.
  3. **No Split-Brain Execution Authority:** No capability subsystem may establish a secondary execution loop, bypass `TaskService`, bypass the deterministic `PolicyEngine`, or evade HMAC-SHA256 HITL approval requirements.
  4. **Universal Ingress Normalization:** Voice streams, Telegram messages, Webhooks, and Web Dashboard requests are treated as standardized ingress triggers that produce canonical `Task` and `TaskStep` entities.
* **Zero-Cost Validation:** Preserves local-first modularity without redundant background runtime overhead.
* **Consequences:** Eliminates architectural drift, guarantees uniform security auditing, prevents privilege escalation, and preserves full system observability.

---

## ADR-024: Local OpenTelemetry Distributed Tracing, In-Memory Exporters & Telemetry Security Boundary

* **Status:** Accepted (Phase 5 — AURA-505)
* **Context:** AURA requires end-to-end distributed observability across asynchronous cognitive execution paths (`Ingress → AgentRuntime → AgentToolBridge → ToolRegistryService → Policy/Risk/HITL → Sandbox → Execution → Audit → Exporters`). However, introducing observability must not compromise data privacy, introduce cloud telemetry SaaS costs, or leak sensitive tokens/prompts.
* **Decision:**
  1. **Local-First & $0 Telemetry:** Standard OpenTelemetry SDK (`TracerProvider`) configured with local in-memory (`InMemorySpanExporter`) and optional local console/OTLP endpoints. No third-party SaaS or cloud observability dependency is required.
  2. **W3C Traceparent Context Propagation:** Universal context propagation across HTTP middleware (`X-Trace-ID`, `traceparent`), async task DAG loops, and tool execution boundaries.
  3. **Strict Telemetry Redaction & Bounding:** All span attributes are filtered through `SafeTelemetrySanitizer` and `SecretRedactor`. Access tokens, JWTs, API keys, Telegram bot tokens, webhook secrets, and signed HITL tokens are strictly prohibited from telemetry spans. String attributes are bounded to `OTEL_MAX_ATTR_LENGTH` (256 chars), and structured dictionaries are summarized to prevent indirect data exfiltration.
  4. **Fail-Safe Telemetry Boundary:** Any telemetry initialization, span recording, or export failure fails silently without interrupting agent execution or altering security policy decisions.
  5. **Audit Independence:** Traces provide performance and diagnostic visibility; they do NOT replace the immutable SHA-256 cryptographic audit ledger (`audit_logs`), which remains the single authoritative source of security truth.
* **Zero-Cost Validation:** 100% in-memory and local endpoint execution ($0.00).
* **Consequences:** Provides granular performance tracing, span hierarchy visualization, and bidirectional audit correlation without security or cost trade-offs.

---

## ADR-025: Production Container Sandbox Operational Hardening, Fail-Closed Boundaries & Bounded Lifecycle

* **Status:** Accepted (Phase 5 — AURA-506)
* **Context:** Arbitrary code execution and untrusted tool workloads require robust operating-system isolation. The container sandbox must guarantee strict fail-closed behavior, workspace filesystem isolation, dropped Linux capabilities, read-only root filesystems, resource limits (CPU, memory, PIDs), bounded output buffers, and emergency kill-switch termination.
* **Decision:**
  1. **Strict Fail-Closed Contract:** If Docker/WSL2 is unavailable, stopped, or misconfigured, arbitrary execution fails closed with `AuthorizationError`. Silently falling back to unsandboxed host execution is strictly prohibited.
  2. **Container Security Hardening:** Containers run with `--security-opt no-new-privileges`, `--cap-drop ALL`, `--read-only` rootfs with ephemeral `/tmp:size=64m` tmpfs, `--network none` (or controlled `bridge`), and explicit resource bounds (`--memory`, `--cpus`, `--pids-limit`).
  3. **Multi-Tenant Workspace Mount Boundary:** Volume mounts are restricted to canonical workspace roots (`filesystem_guard.get_workspace_root`). Cross-workspace access, path traversal, UNC paths, and symlink/junction breakout attempts are blocked.
  4. **Output Buffer Bounding:** Container output is capped at `MAX_OUTPUT_BYTES = 512 KB` with truncation indicators to prevent host memory exhaustion.
  5. **Orphan Reaper & Kill-Switch Integration:** Active containers are tracked in an in-memory registry and forcefully cleaned upon execution completion, timeout, emergency kill-switch activation, or orphan reaper invocation (`reap_orphan_sandboxes`).
  6. **Telemetry & Cryptographic Audit:** Sandbox executions emit OpenTelemetry spans with sanitized metadata (`aura.sandbox_profile`, `aura.container_id`, `aura.exit_code`, `aura.duration_ms`) and append immutable SHA-256 audit ledger records.
* **Zero-Cost Validation:** Relies entirely on local Docker/WSL2 engine and local process isolation without cloud infrastructure fees ($0.00).
* **Consequences:** Ensures defense-in-depth isolation for agent-driven code execution, protects host integrity, and provides auditable operational guarantees.

---

## ADR-026: Universal File Intelligence, Multi-Format Ingestion & Untrusted Content Isolation

* **Status:** Accepted (Phase 6 Preflight & AURA-602 Reconciled)
* **Context:** AURA requires native file intelligence to allow users to upload, inspect, and query diverse document formats (PDF, DOCX, XLSX, PPTX, TXT/MD, CSV, JSON/YAML, Images, Audio, Codebases/ZIP). Ingesting untrusted files introduces major risks: path traversal, zip bombs, macro/script execution, prompt injection, memory poisoning, and unconstrained resource consumption.
* **Decision:**
  1. **Strict Untrusted Pipeline:** All uploaded files are treated as untrusted data. Uploaded code files are data and never executed directly on the host.
  2. **Multi-Format Extraction Boundaries:** Use lightweight, pure-Python stdlib modules (`codecs`, `json`, `csv`, `ast`, `wave`, `zipfile`) and precompiled local wheels (`pypdf`, `pdfplumber`, `python-docx`, `openpyxl`, `python-pptx`, `Pillow`, and `PyYAML` for safe YAML parsing) operating in in-process bounded modes with no active content execution (e.g., `openpyxl` with `data_only=False` preserving formulas as inert data without evaluation; optional cached results via `data_only=True` labeled as `cached_formula_result`; legacy BIFF `.xls` deferred; macros/scripts ignored; non-scanned PDFs only with OCR deferred to Phase 8; static audio metadata-only with STT/TTS deferred to Phase 7).
  3. **Zip-Bomb & Explicit Path Rejection Defense:** ZIP archive unpacking is strictly bounded (max 100 MB uncompressed, max 500 members, ratio < 10:1; TAR/GZ deferred). Archive members containing path traversal sequences (`..`), absolute paths, Windows drive letters (`C:`), UNC paths (`\\`), or symlinks/junctions are explicitly rejected with `ValidationError` rather than silently mutated, preventing destination path collisions, ambiguity, or overwrites.
  4. **Structural Chunking & FastEmbed Vectorization (AURA-603 Capability with AURA-601 Schema Foundation):** Database schema reservation (`file_chunks`) is established in AURA-601; document structural chunking (target 512 tokens with 64-token overlap), FastEmbed `BAAI/bge-base-en-v1.5` 768-dim vectorization, and pgvector HNSW indexing are implemented in AURA-603.
  5. **Workspace Tenancy & Idempotent Deletion Lifecycle:** Files are stored in `{WORKSPACE_ROOT}/{workspace_id}/files/{file_id}/` guarded by `WorkspaceFilesystemGuard`. Successful extraction transitions `FileRecord.status` to `INDEXED` (meaning structural extraction and metadata cataloging are recorded in the file registry). Deletion follows an idempotent state machine (`[UPLOADED/PARSING/INDEXED/FAILED/QUARANTINED]` → `DELETE_REQUESTED` → `STORAGE_PURGED` → `VECTORS_PURGED` → `MEMORY_TOMBSTONED` → `AUDITED` → `DELETED`) with complete orphan reconciliation.
  6. **Prompt-Injection Containment & Multi-Layer Safety:** Extracted text is wrapped in `<untrusted_external_content>` envelopes with escaped delimiters; file directives cannot bypass `PolicyEngine`, `ToolRegistryService`, or `HITLApprovalService`. Real storage paths are never leaked to frontend, LLM context, or telemetry.
* **Zero-Cost & Connectivity Validation:** Local-first extraction, local FastEmbed embeddings, and local PostgreSQL `pgvector` indexing with no mandatory cloud dependency ($0.00 mandatory cloud/SaaS cost).
* **Consequences:** Empowers governed agent subagents to perform high-accuracy document Q&A, spreadsheet inspection, and codebase comprehension without security, privacy, or licensing compromises.

---

## ADR-027: Format-Aware Structural Chunking, FastEmbed Local Vectors & Multi-Tenant Hybrid Retrieval


* **Status:** Accepted (Phase 6 — AURA-603)
* **Context:** High-accuracy semantic recall across multi-format documents requires structural chunking preserving contextual headers, deterministic sequence bounds compliant with local embedding models, sub-second vectorization on consumer CPUs, robust concurrency control during index updates, and zero-leakage multi-tenant hybrid retrieval.
* **Decision:**
  1. **Canonical Model Contract:** Use `BAAI/bge-base-en-v1.5` generating 768-dimensional L2-normalized vectors via CPU-first ONNX Runtime (`FastEmbed` in-process Python). Text passages are vectorized directly without instruction prefixes; search queries prepend the canonical instruction: `"Represent this sentence for searching relevant passages: <user_query>"`. Maximum sequence length is 512 tokens.
  2. **Chunking Limits & Invariant:** Target 384 tokens, maximum stored chunk 510 tokens, structural context header $\le 64$ tokens, body payload $\le 446$ tokens, 48 body tokens overlap. Strict invariant: `stored FileChunk.chunk_text == exact passage embedding input text` with zero silent truncation.
  3. **Operational Database Architecture (Migration 008):** `file_chunks` table operationalized with composite foreign key `(workspace_id, file_id)` referencing `file_records(workspace_id, id)`, unique constraint `(workspace_id, file_id, chunk_index)`, HNSW cosine index `USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)`, and GIN full-text search index `USING gin (to_tsvector('english', chunk_text))`.
  4. **Two-Stage Reindexing & Generation Safety:** Stage 1 performs extraction, structural chunking, token counting, and vector generation outside database locks with optimistic generation UUIDs. Stage 2 executes a short atomic database transaction to verify active state, swap chunk sets, publish `FileRecord.metadata["vector_index"]`, and record a SHA-256 audit entry. Reindexing races against deletion fail closed.
  5. **Symmetric Candidate Union & Hybrid Linear Fusion:** Candidate generation unions Top-50 Dense ($1.0 - \text{cosine}$) and Top-50 Lexical (`websearch_to_tsquery('english', :query)` via `ts_rank_cd`). Linear fusion uses $S_{\text{hybrid}} = 0.70 \cdot S_{\text{dense}} + 0.30 \cdot S_{\text{lexical}}$ with Dual Quality Survival Gate ($S_{\text{hybrid}} \ge 0.30 \lor S_{\text{lexical}} \ge 0.50$) and deterministic final sort `ORDER BY hybrid_score DESC, chunk_id ASC`.
  6. **Structured Memory Provenance & Cascading Tombstoning:** Memory facts promoted from document chunks retain deterministic provenance (`workspace_id`, `file_id`, `chunk_id`, `chunk_index`, parser/model versions). Deletion cascades tombstoning scoped to `source_type = 'file_intelligence'` and `provenance.file_id = target_file`.
  7. **Multi-Tenant Benchmark Verification:** Empirical testing over 4,550 chunks across 5 isolated workspaces and 100 labeled queries achieved 100% Recall@5 against exact filtered KNN ground truth with 0.00% cross-tenant leakage.
* **Zero-Cost & Offline Validation:** 100% local CPU ONNX inference and PostgreSQL HNSW indexing without cloud embedding APIs or SaaS vector databases ($0.00 mandatory cost).
* **Consequences:** Provides millisecond semantic search and retrieval over diverse enterprise documents while guaranteeing multi-tenant security and zero cloud cost.







