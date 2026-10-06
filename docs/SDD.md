# Software Design Document (SDD)
## Project Name: AURA (Autonomous Universal Reactive Agent)
**Document Version:** 9.6.0  
**Phase:** Phase 9 — Governed OS & Hardware Automation (COMPLETE & ACCEPTED) | Phase 1–9 Master Validated  
**Classification:** System Design Specification  

---

## 1. System Architecture Overview

AURA is architected around a strict decoupled paradigm: the **Control Plane** (authoritative, deterministic, stateful, secure) and the **Agent Runtime** (cognitive, non-deterministic, distributed, sandboxed).

```
+----------------------------------------------------------------------------------------------------+
|                                      INGRESS CLIENT LAYER                                          |
|   +-----------------------+   +------------------------+   +-------------------+   +-----------+   |
|   | Web Dashboard (Next.js)|   | Messaging (TG/Discord) |   | Inbound Webhooks  |   | Voice API |   |
+---+-----------+-----------+---+------------+-----------+---+---------+---------+---+-----+-----+---+
                |                            |                         |                   |
                +----------------------------+------------+------------+-------------------+
                                                          |
                                                          v
+----------------------------------------------------------------------------------------------------+
|                                    AURA CONTROL PLANE (FastAPI)                                    |
|  +----------------------------------------------------------------------------------------------+  |
|  | Authentication & RBAC Engine (JWT / API Key / OAuth2 / Workspace Partitioning)               |  |
|  +----------------------------------------------------------------------------------------------+  |
|  | Deterministic Policy & Security Guardrails (Risk Evaluator, HITL Approval State Machine)     |  |
|  +----------------------------------------------------------------------------------------------+  |
|  | Task & Automation Orchestrator (Cron Scheduler, Webhook Ingress, Job Queues via pg_boss)     |  |
|  +----------------------------------------------------------------------------------------------+  |
|  | Context Assembly & Memory Router (PostgreSQL Application State <---> FastEmbed Local Memory) |  |
|  +----------------------------------------------------------------------------------------------+  |
|  | Tool & Skill Registry (Schema Validation, Permission Scopes, Secret Injection Proxy)         |  |
|  +----------------------------------------------------------------------------------------------+  |
|  | Telemetry & Audit Publisher (OpenTelemetry, Tamper-Evident Hash Chain Logging)              |  |
+-------------------------------------------------+--------------------------------------------------+
                                                  | Structured Agent Payload (JSON Contract)
                                                  v
+----------------------------------------------------------------------------------------------------+
|                                   AURA AGENT RUNTIME (Cognitive Engine)                            |
|  +----------------------------------------------------------------------------------------------+  |
|  | Supervisor / Planner Agent (Goal Decomposition, Dynamic DAG Generation, Step Validation)      |  |
|  +----------------------------------------------------------------------------------------------+  |
|  | Sub-Agent Worker Pool (Research Agent, Coding Agent, Analysis Agent, Synthesis Agent)        |  |
|  +----------------------------------------------------------------------------------------------+  |
|  | Model Gateway / Router (LiteLLM / OpenRouter / Ollama Failover Matrix)                        |  |
|  +----------------------------------------------------------------------------------------------+  |
|  | Execution Interceptor & Sandbox Controller (Docker / Firejail / Isolated Worker Boundary)    |  |
|  +----------------------------------------------------------------------------------------------+  |
|  | MCP Host Client (Model Context Protocol stdio / SSE Client Multiplexer)                     |  |
+-------------------------------------------------+--------------------------------------------------+
                                                  |
                         +------------------------+------------------------+
                         |                                                 |
                         v                                                 v
+------------------------------------------------+  +------------------------------------------------+
|             PERSISTENCE & MEMORY               |  |           EXTERNAL DIGITAL SYSTEMS             |
|  +------------------------------------------+  |  |  +------------------------------------------+  |
|  | PostgreSQL 16 (State, Logs, RLS, Tasks)   |  |  |  | Model Context Protocol (MCP) Servers    |  |
|  +------------------------------------------+  |  |  +------------------------------------------+  |
|  | Cognitive Memory (FastEmbed + pgvector)  |  |  |  | Native Integrations (GitHub, Search, FS)|  |
|  +------------------------------------------+  |  |  +------------------------------------------+  |
|  | Redis (Ephemeral Caching, SSE PubSub)    |  |  |  | Sandbox Runners (Containerized Code Exec)|  |
|  +------------------------------------------+  |  |  +------------------------------------------+  |
+------------------------------------------------+  +------------------------------------------------+
```

---

## 2. Core Architectural Principles

### 2.1 The Invariant Separation of Responsibilities
1. **Control Plane Responsibilities (Authoritative):**
   * Manages user identity, workspace tenancy, authentication tokens, and session lifecycles.
   * Maintains canonical database records in PostgreSQL (Tasks, Runs, Tool Registry, Approvals).
   * Enforces security policies, rate limits, budget ceilings, and Human-in-the-Loop approvals before any execution occurs.
   * Securely stores credentials and API keys in an isolated secret store, injecting them only into sandboxed tool processes.
   * Operates as the central event broker and scheduler for all cron jobs, webhooks, and asynchronous notifications.
2. **Agent Runtime Responsibilities (Cognitive):**
   * Consumes structured execution plans and instructions from the Control Plane.
   * Manages LLM context windows, prompt formatting, tool schema binding, and response streaming.
   * Executes multi-step cognitive reasoning loops (Observe $\rightarrow$ Reason $\rightarrow$ Act $\rightarrow$ Verify).
   * Spawns, monitors, and terminates isolated sub-agent workers.
   * Interfaces with MCP servers to discover and invoke external tools within the permission boundaries dictated by the Control Plane.

### 2.2 Deterministic Safety Guardrail Loop
```
[User / Event Input]
         │
         ▼
[Ingress Authentication & Rate Limiter]
         │
         ▼
[Context Assembly & Memory Retrieval]
         │
         ▼
[LLM Planner / Reasoning Engine]
         │ (Generates Proposed Tool Call / Action)
         ▼
[AURA Deterministic Policy Engine] <─────── Independent Code Layer (Zero LLM Influence)
    ├── Risk Tier Check (Low, Med, High, Critical)
    ├── Permission & Scope Check
    └── Rate Limit & Budget Check
         │
    ┌────┴────────────────────────┐
    ▼                             ▼
[ALLOW (Low/Med)]        [REQUIRE APPROVAL (High/Crit)]
    │                             │
    │                             ▼
    │                    [Create Approval Request in DB]
    │                    [Emit Push Notification to UI]
    │                    [Suspend Agent Run Checkpoint]
    │                             │
    │                    (User Approves with Signed Token)
    │                             │
    ├─────────────────────────────┘
    ▼
[Secret Injection Proxy & Tool Sandbox Execution]
    │
    ▼
[Output Sanitizer & Verification Assertions]
    │
    ▼
[Observation Streamed Back to Runtime & State Persisted in PostgreSQL]
```

---

## 3. Subsystem Decomposition

### 3.1 Ingress & Gateway Layer
* **HTTP/REST API:** Built with FastAPI (Python 3.12+). Provides OpenAPI-compliant endpoints for user authentication, session management, task dispatch, skill administration, and approval resolution.
* **Real-time Event Streaming:** Server-Sent Events (SSE) and WebSockets backed by Redis Pub/Sub for real-time token streaming, thought-process telemetry, and execution step notifications.
* **Multi-Platform Webhooks:** Ingress adapter normalizing events from external systems (GitHub, Telegram, Discord, custom webhooks) into unified AURA Event Payloads.

### 3.2 Memory & Social Cognition Subsystem
* **Working Context Window Buffer:** Ephemeral sliding window of the last $N$ turns managed in Redis/FastAPI memory with strict token budgeting.
* **Relational State Store (PostgreSQL):** Stores normalized conversation history, task checkpoints, agent run metadata, audit logs, and skill definitions.
* **User Modeling & Dialectical Memory (Honcho):** Captures semantic representations, user traits, behavioral preferences, project facts, and episodic memory across sessions. Queries Honcho via hybrid BM25 + Vector search during Context Assembly.

### 3.3 Model Gateway & Routing Subsystem
* **Unified Interface:** Employs an internal abstraction layer (leveraging LiteLLM / OpenRouter proxy architecture) to normalize API requests across OpenAI, Anthropic, Google Gemini, DeepSeek, and local Ollama/vLLM endpoints.
* **Tiered Routing Matrix:**
  * `TIER_REASONING`: For DAG generation, complex task decomposition, and code architecture review (e.g., Claude 3.7 Sonnet / DeepSeek-R1 / OpenAI o3-mini).
  * `TIER_FAST`: For intent parsing, memory extraction, chat formatting, and intermediate summaries (e.g., GPT-4o-mini / Claude 3.5 Haiku).
  * `TIER_CODING`: For shell command generation, code refactoring, and AST manipulation.
  * `TIER_LOCAL`: For offline, private, or air-gapped tasks (e.g., Hermes-3 8B / Llama 3.3 70B via vLLM/Ollama).
* **Resilience Features:** Automatic fallback cascades (Primary $\rightarrow$ Secondary $\rightarrow$ Local), exponential backoff jitter, circuit-breaking on upstream rate limits, and token usage accounting.

### 3.4 Tool Execution Engine & Sandbox Controller
* **Tool Registry:** In-memory and PostgreSQL-backed catalogue defining every tool's JSON Schema, risk level, required capabilities, and execution timeout.
* **MCP Host Manager:** Manages long-running subprocesses (`stdio`) and network connections (`SSE`) to external MCP servers. Enforces strict process isolation, stdout/stderr parsing, and error encapsulation.
* **Sandboxed Execution Workers:** High-risk actions (arbitrary shell commands, Python script execution, filesystem operations outside workspace root) are routed to isolated Docker containers or Firejail sandboxes with restricted network access and ephemeral storage.

---

## 4. State Machines & Lifecycle Specifications

### 4.1 Task Lifecycle State Machine
```
[PENDING] ────► [SCHEDULED] ────► [PLANNING] ────► [EXECUTING] ────► [VERIFYING] ────► [COMPLETED]
    │                 │               │                 │                 │
    │                 │               │                 ├────► [AWAITING_APPROVAL]
    │                 │               │                 │          │ (User Rejects / Timeout)
    │                 │               │                 ├──────────┴────────► [REJECTED]
    │                 │               │                 │
    ▼                 ▼               ▼                 ▼
[CANCELLED]      [CANCELLED]       [FAILED]          [FAILED]
```

* **States:**
  * `PENDING`: Task registered in database; waiting for scheduler or worker pickup.
  * `SCHEDULED`: Queued in task broker (pg_boss / Redis) for execution at a specific timestamp.
  * `PLANNING`: Supervisor agent decomposing goal into execution plan DAG.
  * `EXECUTING`: Worker runtime actively executing plan steps and invoking tools.
  * `AWAITING_APPROVAL`: Execution suspended pending human resolution of a High/Critical risk tool call.
  * `VERIFYING`: Completed execution steps evaluated against post-condition assertions.
  * `COMPLETED`: All steps verified; artifacts generated; memory writeback committed.
  * `FAILED`: Unrecoverable error occurred; retry limit exceeded; failure logged.
  * `CANCELLED`: Explicitly aborted by user or emergency kill switch.
  * `REJECTED`: User explicitly rejected an approval request or approval TTL expired.

### 4.2 Approval Request State Machine
```
[CREATED] ──(Notification Sent)──► [PENDING] ───┬──► [APPROVED] ──► [CONSUMED]
                                                 ├──► [REJECTED]
                                                 └──► [EXPIRED (TTL)]
```
* **Security Invariant:** An approval token is single-use, cryptographically signed with HMAC-SHA256, tied to an exact `task_id`, `tool_call_id`, and parameter hash, with a strictly enforced TTL (default: 900 seconds).

---

## 5. Resilience & Fault Tolerance Patterns

1. **Idempotency Envelope:** Every state-altering API request and tool invocation requires an `idempotency_key` header (UUIDv4). The Control Plane validates and locks this key in Redis/PostgreSQL to prevent duplicate executions during network retries.
2. **Circuit Breakers:** Upstream model providers and MCP servers are wrapped in circuit breakers. If error rates exceed 50% over a 60-second window, the circuit trips to `OPEN`, immediately diverting requests to secondary fallback providers.
3. **Graceful Checkpointing:** At the completion of each plan step, the agent runtime persists the step state and execution context to PostgreSQL. If a worker process is killed unexpectedly, a new worker resumes execution from the latest checkpoint rather than re-running the entire workflow from scratch.
4. **Context Window Token Budgeting:** Dynamic context allocation prevents context overflow:
   * System Prompt & Core Directives: 15%
   * Retrieved Memories & User Profile: 20%
   * Active Skill & Plan Definition: 15%
   * Conversation Turn History: 25%
   * Tool Schemas & Output Buffer: 25%

---

## 6. Phase 10 Subsystem Architecture (Preflight Specification)

### 6.1 Advanced Interactive Browser Engine Architecture
```
[Agent Core / Planner]
          │
          ▼ (Governed Tool Invocation: e.g., browser_click)
[AgentToolBridge -> ToolRegistryService]
          │
          ▼ (Risk Evaluation: READ / LOW / MEDIUM / HIGH / CRITICAL)
[OSPolicyEngine / Risk Gate] ──(If HIGH/CRITICAL)──► [HMAC-SHA256 HITL Approval Drawer]
          │ (Approved / Low-Risk)
          ▼
[PlaywrightBrowserManager]
    ├── Isolated BrowserContext (per-workspace session, ephemeral storage)
    ├── Multi-Tab Controller (max 4 concurrent tabs per workspace)
    ├── AXTree & Semantic State Extractor (aria-labels, roles, numeric element IDs)
    ├── Multi-Layer SSRF Guard (pre-nav, redirect, and subresource routing filters)
    ├── Prompt Sanitizer (<untrusted_web_content> XML envelope wrapping)
    └── Bounded Action Execution Engine (page.click, page.fill, page.goto with 15s/25s timeouts)
```

### 6.2 Windows Background Runtime Architecture
```
[Windows User Session (Interactive Session 1+)]
    │
    ├── [AuraDaemonSupervisor] (Watchdog, health heartbeat, least-privilege non-SYSTEM)
    │         │
    │         ├── Spawns & Monitors ──► [FastAPI Control Plane / Uvicorn Server]
    │         └── Spawns & Monitors ──► [AURA-905 System Tray & Hotkey Process]
    │
    ├── [Win32 Session Change Listener] (`WM_WTSSESSION_CHANGE`)
    │         ├── On WTS_SESSION_LOCK: Suspend camera, mic, screen, and OS interactions
    │         └── On WTS_SESSION_UNLOCK: Resume listening upon user authentication
    │
    └── [Controlled Autostart Manager] (Registry HKCU Run Key, OFF by default, reversible)
```

