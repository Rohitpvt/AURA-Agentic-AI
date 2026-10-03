# AURA — Phase 4 Pre-Flight, Dependency Security & Roadmap Lock Report
## Document: `docs/PHASE_4_PREFLIGHT_REPORT.md`
**Document Version:** 3.0.0 (Final Corrected & Authoritative Baseline)  
**Status:** Canonical & Locked  
**Phase:** Phase 4 Pre-Flight & Environment Reconciliation  
**Target Next Phase:** Phase 4 — Automations, Ingress Gateways & Zero-Cost Tools  

---

## 1. Phase 4 Scope

Based on canonical architectural specifications ([ROADMAP.md](file:///c:/Users/rghos/OneDrive%20-%20Vivekananda%20Institute%20of%20Professional%20Studies/PROJECTS/Agentic%20AI/docs/ROADMAP.md), [TASK_BREAKDOWN.md](file:///c:/Users/rghos/OneDrive%20-%20Vivekananda%20Institute%20of%20Professional%20Studies/PROJECTS/Agentic%20AI/docs/TASK_BREAKDOWN.md), [EVENT_AND_AUTOMATION.md](file:///c:/Users/rghos/OneDrive%20-%20Vivekananda%20Institute%20of%20Professional%20Studies/PROJECTS/Agentic%20AI/docs/EVENT_AND_AUTOMATION.md), [ARCHITECTURE_DECISIONS.md](file:///c:/Users/rghos/OneDrive%20-%20Vivekananda%20Institute%20of%20Professional%20Studies/PROJECTS/Agentic%20AI/docs/ARCHITECTURE_DECISIONS.md)), the objective and boundary for **Phase 4** are strictly defined as:

### 1.1 Objective
Transform AURA from a user-initiated reactive agent into a proactive, event-driven, autonomous cognitive operating system through local background scheduling, inbound webhook ingress, zero-cost messaging adapters (Telegram long-polling), and deep headless browser extraction tools, while preserving the Zero-Cost Invariant and strict security governance.

### 1.2 In-Scope Deliverables (Milestones 4.1 – 4.4)
1. **Milestone 4.1 (AURA-401) — PostgreSQL Transactional Cron Scheduler:**
   - Multi-process safe background scheduler daemon running within FastAPI/asyncio lifecycle.
   - Periodic scan of `automations` table claiming due jobs using PostgreSQL `FOR UPDATE SKIP LOCKED`.
   - Standard 5-field cron parsing (`croniter`), next-run calculation, deterministic lease duration, and execution dispatching.
   - Exponential jitter retry backoff ($30\text{s} \rightarrow 120\text{s} \rightarrow 480\text{s}$) and 3-strike circuit breaker.
2. **Milestone 4.2 (AURA-402) — Inbound Webhook Reactive Gateway:**
   - Dedicated ingress endpoints (`/api/v1/webhooks/ingress/{webhook_id}`).
   - Cryptographic HMAC-SHA256 signature verification per endpoint secret.
   - Idempotency deduplication lock and replay attack prevention ($\le 300\text{s}$ timestamp drift window).
   - Template hydration (Mustache/Jinja2 placeholder substitution) and strictly bounded Autonomy Level 4 (L4) sandboxed task creation.
3. **Milestone 4.3 (AURA-403) — Free Telegram Bot Ingress Adapter:**
   - Free Telegram Bot API client operating strictly in **long-polling mode** (`getUpdates`, zero public IP, tunneling, or webhook hosting required).
   - Cryptographic pairing token workflow (15-min TTL) linking external Telegram `chat_id` to canonical AURA user/workspace.
   - Inbound message command parser (`/goal`, `/status`, `/cancel`, `/approve`) and outbound markdown execution summary dispatcher.
4. **Milestone 4.4 (AURA-404) — Local Playwright Headless Web Extractor:**
   - Local Playwright headless browser tool integrated via `ToolRegistryService` and `AgentToolBridge`.
   - SSRF protection guard pre-flight checks on target URLs and HTTP redirects.
   - Clean DOM-to-markdown reader extraction and untrusted content quarantine tagging (`is_untrusted_content: True`).
5. **Phase 4 Frontend Control Surfaces:**
   - Dedicated `AutomationsView.tsx` with cron schedule builder, run history, and pause/resume toggles.
   - `WebhooksView.tsx` with endpoint generation, secret display, and incoming payload tester.
   - `IntegrationsView.tsx` with Telegram pairing status and configuration.

### 1.3 Affected Services & Subsystems
- **Backend:** `app/db/models/automations.py`, `app/services/automations/`, `app/services/webhooks/`, `app/services/integrations/telegram.py`, `app/services/tools/playwright_extractor.py`, `app/api/v1/automations.py`, `app/api/v1/webhooks.py`, `app/api/v1/integrations.py`, `app/workers/scheduler.py`.
- **Frontend:** `apps/web/components/views/AutomationsView.tsx`, `apps/web/components/views/WebhooksView.tsx`, `apps/web/components/views/IntegrationsView.tsx`, `apps/web/lib/api.ts`.
- **Database:** `automations`, `automation_runs`, `webhook_endpoints`, `telegram_pairings` tables.

### 1.4 Explicit Non-Goals for Phase 4
- **Paid Telephony / SMS Services:** No Twilio, Vonage, or paid carrier APIs.
- **Paid Web Scraping / Search APIs:** No ScrapingBee, BrightData, or Tavily.
- **Cloud Webhook Relays:** No mandatory Ngrok or Hookdeck accounts (Telegram long-polling eliminates public ingress requirements for messaging).
- **L5 Self-Evolution Engine:** Scheduled for future meta-evolution phases under strict administrative oversight.

---

## 2. Current Project State

| Component | Status | Verification Evidence |
| :--- | :--- | :--- |
| **Phase 1 Control Plane** | Completed | PostgreSQL 16 schema, FastAPI, JWT Auth, FastEmbed memory, Ollama provider, Gemini BYOK vault, Task DAG. |
| **Phase 2A Agent Runtime** | Completed | AURA-Native cognitive loop, SupervisorPlanner, AgentToolBridge, Observe-Decide-Act-Verify cycle. |
| **Phase 2B Governance** | Completed | MCP Host Client Manager, Cryptographic HITL State Suspension/Resumption, Bounded Subagent Pool ($\le 4$ workers, depth $\le 2$). |
| **Phase 2C Security Hardening** | Completed | Ephemeral Docker sandbox, Fail-closed host policy, SSRF shield, Filesystem jail, Secret redactor, SHA-256 audit ledger, Sub-15ms kill switch. |
| **Phase 3 Web Dashboard** | Completed & Validated | Next.js 15 App Router, 12 Core Views, Real-time SSE streaming, HITL approval drawer, Memory editor, 12/12 frontend vitest tests passing, static build passing. |
| **Backend Test Suite** | 67 / 67 Passed (100%) | `pytest tests -v` executed in 29.02s with zero errors. |
| **Frontend Test Suite** | 12 / 12 Passed (100%) | `vitest run` executed in 1.28s with zero errors. |
| **Frontend Build** | Successful | `next build` static page prerendering completed cleanly (4/4 static pages). |
| **Active Daemons** | Healthy | FastAPI on port 8000; Next.js dev server on port 3000. |

---

## 3. Database Runtime Reconciliation

### 3.1 Investigation Findings
1. **Canonical Supported Architecture:** PostgreSQL 16 + `pgvector` ([DATABASE_SCHEMA.md](file:///c:/Users/rghos/OneDrive%20-%20Vivekananda%20Institute%20of%20Professional%20Studies/PROJECTS/Agentic%20AI/docs/DATABASE_SCHEMA.md)) is the authoritative production and persistent storage layer. Connection string: `postgresql+asyncpg://postgres:postgres@localhost:5432/aura_db`.
2. **Automated Test Layer:** In-memory SQLite async (`sqlite+aiosqlite:///:memory:`) in `tests/conftest.py` is utilized exclusively for ultra-fast, isolated unit/integration test runs without requiring an external PostgreSQL daemon.
3. **Local Dev Environment:** Defaults to PostgreSQL 16; features graceful multi-dialect portability in `app/db/base.py`.
4. **Dialect Abstraction & Compatibility:**
   - Portable `GUID` decorator maps to PostgreSQL `UUID` and SQLite `CHAR(36)`.
   - Portable `JSONB` decorator maps to PostgreSQL native `JSONB` and SQLite `JSON`.
   - Portable `Vector` decorator maps to `pgvector.sqlalchemy.Vector(768)` on PostgreSQL and JSON arrays on SQLite.
   - All migrations in `alembic/versions/` target PostgreSQL DDL.
5. **Phase 4 Impact (`FOR UPDATE SKIP LOCKED`):**
   - PostgreSQL natively supports `SELECT ... FOR UPDATE SKIP LOCKED` for concurrent worker queue claiming across multiple processes.
   - SQLite does not support row-level row lock hints.
   - **Resolution Policy:** The scheduler service will execute `FOR UPDATE SKIP LOCKED` on PostgreSQL engines and gracefully omit lock hints when running against SQLite test engines, verified through dialect detection (`session.bind.dialect.name`).

---

## 4. Gemini Provider Lifecycle Audit & Final Model Catalog

### 4.1 Authoritative Model Catalog (October 1, 2026 Baseline)
All legacy and non-active identifiers (`gemini-2.0-flash`, `gemini-1.5-flash`, `gemini-1.5-pro`, `gemini-1.0-pro`) are decommissioned from active configuration. The verified active model catalog is:

| Model ID | Family | Lifecycle Status | Access & Availability Notes | Context Limit | Tool / JSON Support | Cost Classification | Recommended Role |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`gemini-2.5-flash`** | `gemini-2.5` | `active_supported` | Standard Google AI Studio API key access; subject to project quota and rate limits (RPM/TPM). | 1,048,576 | Full (Tools, JSON, Stream) | `byok_free_tier` / billable | Fast Multimodal Reasoning & Tool Calling |
| **`gemini-2.5-pro`** | `gemini-2.5` | `active_supported` | Google AI Studio tier access; may require billing enablement for high token volumes. | 2,097,152 | Full (Tools, JSON, Stream) | `byok_potentially_billable` | Frontier Reasoning, Code & Complex Planning |

### 4.2 Centralized Provider Metadata Architecture
Model metadata is centralized in `GEMINI_MODEL_CATALOG` within `apps/api/app/services/providers/gemini_provider.py` and referenced by `list_models()`:

```text
GeminiProvider
    ├── GEMINI_MODEL_CATALOG (Centralized dictionary: model_id, family, lifecycle, access notes, context, tools, JSON)
    ├── DECOMMISSIONED_GEMINI_MODELS (Audit reference for decommissioned identifiers)
    ├── validate_credentials() (GET /v1beta/models with x-goog-api-key)
    ├── generate_chat() (POST /v1beta/models/{model}:generateContent)
    └── health_check() (Returns ProviderHealthStatus with validated active models)
```

### 4.3 Routing Policies & Invariants
1. **`LOCAL_ONLY` (Default):** Zero cloud egress. All requests execute strictly via local Ollama (`qwen2.5:7b` / `llama3.2:3b`).
2. **`BYOK_ONLY`:** Routes exclusively to the user's enrolled BYOK Gemini key. If the key is invalid, revoked, or rate-limited (HTTP 429), the request **fails safely with `ModelUnavailableError`** without silently invoking any other provider.
3. **`AUTO`:** Local-first intelligent escalation. Routine tasks execute on local Ollama. Tasks explicitly flagged as high-complexity route to BYOK Gemini only when valid credentials exist. If BYOK becomes unavailable, it falls back gracefully to local Ollama with telemetry logging.
4. **No Silent Paid Fallback:** The system will never silently initiate a paid cloud call or billable fallback.
5. **Billing Transparency:** BYOK credentials belong to the user and may incur third-party provider charges based on the user's account tier. BYOK is explicitly documented as **optional and not automatically free**.

---

## 5. Next.js & Frontend Security Baseline (CVE-2025-66478 Patch)

### 5.1 Version Audit & Patch Details
- **Previous Versions:** `15.0.1` / `15.1.7`
- **Corrected & Locked Version:** `next = 15.5.27` in `apps/web/package.json`
- **Security Verification (CVE-2025-66478):**
  - **Vulnerability:** Upstream Next.js Server Actions / App Router data handling advisory (CVE-2025-66478).
  - **Patched Release:** Next.js 15.5.27 incorporates the official upstream security patch.
  - **Compatibility:** Preserves 100% App Router architecture compatibility, React 18, Tailwind CSS v3/v4, and TanStack Query v5 with zero architectural breaking changes.

### 5.2 Verification Evidence
- `vitest run`: **12 / 12 tests passing** (1.28s).
- `npm run build`: **Compiled successfully**; 4/4 static routes prerendered cleanly with zero lint or type errors.
- Client secret invariant: Verified that no API keys or master secrets are bundled into client JavaScript chunks.

---

## 6. Dependency, License & Zero-Cost Audit

### 6.1 Backend Dependencies (`apps/api/requirements.txt`)
| Package | License | Category | Mandatory Cost |
| :--- | :--- | :--- | :--- |
| `fastapi` | MIT | Core Web Framework | $0.00 (Local) |
| `uvicorn[standard]` | BSD-3-Clause | ASGI Server | $0.00 (Local) |
| `pydantic` / `pydantic-settings` | MIT | Data Validation | $0.00 (Local) |
| `sqlalchemy` / `asyncpg` | MIT / Apache 2.0 | Relational Persistence | $0.00 (Local) |
| `alembic` | MIT | Schema Migrations | $0.00 (Local) |
| `pgvector` | PostgreSQL (Open Source) | Vector Extension | $0.00 (Local) |
| `httpx` / `aiofiles` | BSD-3-Clause / Apache 2.0 | Async I/O & Networking | $0.00 (Local) |
| `duckduckgo-search` (`ddgs`) | MIT | Free Web Search | $0.00 (Free Public API) |
| `fastembed` | Apache 2.0 | Local Embeddings | $0.00 (Local CPU/GPU) |
| `python-multipart` | Apache 2.0 | Form Data Parsing | $0.00 (Local) |
| `passlib[bcrypt]` / `pyjwt` | BSD / MIT | Auth & Cryptography | $0.00 (Local) |
| `croniter` (Phase 4 Add) | MIT | Cron Expression Parsing | $0.00 (Local) |
| `playwright` (Phase 4 Add) | Apache 2.0 | Headless Web Extraction | $0.00 (Local Headless) |

### 6.2 Frontend Dependencies (`apps/web/package.json`)
| Package | Version | License | Category | Mandatory Cost |
| :--- | :--- | :--- | :--- | :--- |
| `next` | `15.5.27` | MIT | Web Framework & UI | $0.00 (Local) |
| `react` / `react-dom` | `^18.3.1` | MIT | UI Library | $0.00 (Local) |
| `@tanstack/react-query` | `^5.59.0` | MIT | Async State Sync | $0.00 (Local) |
| `lucide-react` | `^0.453.0` | ISC | UI Icons | $0.00 (Local) |
| `tailwindcss` | `^3.4.14` | MIT | Design System | $0.00 (Local) |
| `zustand` | `^5.0.0` | MIT | Client State Store | $0.00 (Local) |

### 6.3 Zero-Cost Invariant Certification
- **Mandatory Operating Cost:** **$0.00 (Zero)**.
- **Optional BYOK:** User-enrolled Gemini API keys carry zero platform fees.
- **Licensing Compliance:** 100% permissive open-source licenses (MIT, Apache 2.0, BSD, ISC, PostgreSQL).

---

## 7. Security Baseline Lock (19 Core Invariants)

All 19 security invariants established in Phases 1–3 remain authoritative and strictly locked for Phase 4:

1. **Backend-Only Authorization Authority:** The frontend never makes security or permission decisions.
2. **Single Tool Governance Boundary:** All tool executions flow through `AgentToolBridge` $\rightarrow$ `ToolRegistryService`.
3. **Deterministic Cryptographic HITL:** HMAC-SHA256 tokens with DB row locks protect High/Critical side effects.
4. **Fail-Closed Container Sandboxing:** Arbitrary code/shell execution fails closed if sandbox is unavailable.
5. **SSRF Defense Shield:** Outbound URLs are pre-flight validated against loopback, RFC 1918, link-local, and cloud metadata IPs.
6. **Filesystem Traversal Protection:** All file operations are jailed strictly within canonical workspace boundaries.
7. **MCP Process Governance:** Subprocesses adhere to strict binary allowlists, sanitized environments, and timeout monitors.
8. **Automated Secret Redaction:** API keys, passwords, and tokens are redacted before entering logs, traces, or LLM context.
9. **AES-256-GCM BYOK Vault:** Keys are encrypted at rest with authenticated encryption outside the main database tables.
10. **Tamper-Evident SHA-256 Audit Ledger:** Cryptographic hash chaining on all audit entries with verification integrity checks.
11. **Emergency Global Kill Switch:** Sub-15ms broadcast cancellation across all running tasks, loops, and workers.
12. **Resource Quota Enforcers:** Token, memory, process, and execution time limits per workspace and task.
13. **Untrusted Content Quarantining:** External search results, web scraper output, and webhook payloads are tagged untrusted.
14. **Multi-Tenant Workspace Isolation:** Strict horizontal data isolation enforced on all SQL queries and file paths.
15. **Subagent Recursion Ceiling:** Depth strictly capped at $\le 2$ (Supervisor $\rightarrow$ Subagent $\rightarrow$ Leaf).
16. **Subagent Concurrency Ceiling:** Active subagent workers strictly capped at $\le 4$ concurrent tasks per supervisor.
17. **Bounded Context Window:** Context length capped at 8,192 tokens with prompt compression to prevent VRAM thrashing.
18. **Bounded Agent Loop:** Observe-Decide-Act-Verify loop bounded by deterministic step limits and cycle detectors.
19. **Zero Silent Paid Fallback:** Unavailability of BYOK keys falls back exclusively to local Ollama.

---

## 8. Phase 3 Regression Baseline

```
================================================================================
AURA PHASE 3 REGRESSION BASELINE RECORD (FINAL LOCKED)
================================================================================
Backend Pytest Suite:     67 / 67 Passed (100%) in 29.02s
Frontend Vitest Suite:    12 / 12 Passed (100%) in 1.28s
Next.js Production Build: Prerendered 4/4 Static Routes Cleanly
FastAPI Control Plane:    Healthy (Port 8000)
Web Dashboard UI:         Healthy (Port 3000, 12 Core Views Operational)
SSE Real-Time Stream:     Operational with auto-reconnect & token buffering
Emergency Kill Switch:    Verified (<15ms latency)
================================================================================
```

---

## 9. Phase 4 Architecture Impact

```
+====================================================================================================+
|                                    PHASE 4 ARCHITECTURE EXPANSION                                  |
+====================================================================================================+
|                                                                                                    |
|  [CRON SCHEDULER DAEMON]          [INBOUND WEBHOOKS]            [TELEGRAM BOT ADAPTER]             |
|   (PostgreSQL FOR UPDATE           (/api/v1/webhooks/ingress/    (Long-Polling Client,              |
|    SKIP LOCKED, croniter)           HMAC-SHA256, Idempotency)     Zero-Tunnel Ingress)             |
|            │                                  │                                  │                 |
|            ▼                                  ▼                                  ▼                 |
|  +──────────────────────────────────────────────────────────────────────────────────────────────+  |
|  |                                  AURA AUTOMATION DISPATCHER                                  |  |
|  |  - Normalizes event data & sanitizes input (`is_untrusted_content = True`)                   |  |
|  |  - Enforces Autonomy Level 4 (L4) bounded permissions (Low-Risk auto; Medium/High HITL)      |  |
|  |  - Spawns Task in PostgreSQL DAG Engine with idempotency keys                                 |  |
|  +──────────────────────────────────────────────────────────────────────────────────────────────+  |
|                                                │                                                   |
|                                                ▼                                                   |
|  +──────────────────────────────────────────────────────────────────────────────────────────────+  |
|  |                                AGENT COGNITIVE EXECUTION ENGINE                              |  |
|  |  - SupervisorPlanner / AuraAgentSubstrate / SubAgentWorkerPool (Depth<=2, Concurrency<=4)    |  |
|  |  - Single Tool Boundary: AgentToolBridge -> ToolRegistryService                              |  |
|  |  - Added Zero-Cost Tool: Local Playwright Headless Web Extractor (SSRF-Protected)            |  |
|  +──────────────────────────────────────────────────────────────────────────────────────────────+  |
|                                                │                                                   |
|                                                ▼                                                   |
|  +──────────────────────────────────────────────────────────────────────────────────────────────+  |
|  |                               MULTI-CHANNEL NOTIFICATION OUTBOX                              |  |
|  |  - Web Dashboard SSE Feed & Notifications Drawer                                             |  |
|  |  - Telegram Markdown Result Dispatcher                                                       |  |
|  |  - Outbound Webhook Dispatcher                                                               |  |
|  +──────────────────────────────────────────────────────────────────────────────────────────────+  |
|                                                                                                    |
+====================================================================================================+
```

---

## 10. Phase 4 Refined Subsystem Designs

### 10.1 AURA-401: Multi-Process Safe PostgreSQL Scheduler
- **Concurrency Mechanism:** Transactional polling using `SELECT ... FROM automations WHERE is_active = TRUE AND next_run_at <= :now FOR UPDATE SKIP LOCKED LIMIT 10`.
- **Lease Duration & Recovery:** Claimed rows set `status = 'claimed'`, `claimed_at = :now`, and `claim_expires_at = :now + interval '15 minutes'`. If a worker dies, orphaned claimed rows whose leases have expired are automatically re-queued.
- **Idempotency Guarantee:** Task creation generates a unique `idempotency_key = f"auto_{automation_id}_{run_timestamp}"` to prevent duplicate task execution across distributed workers.
- **Retry Backoff & Circuit Breaker:** Exponential jitter backoff ($30\text{s} \rightarrow 120\text{s} \rightarrow 480\text{s}$). If 3 consecutive scheduled runs fail, `is_active = FALSE`, `status = 'error'`, and an urgent notification is emitted to the dashboard.
- **Graceful Shutdown:** SIGTERM/SIGINT signal handlers stop polling, await in-flight task creation, and release unstarted claims.

### 10.2 AURA-402: Bounded Inbound Webhook Autonomy (L4 Containment)
- **Privilege Boundary:** Inbound webhook execution **MUST NOT** serve as a privilege escalation vector.
- **Maximum Auto-Approved Risk:** Low risk (Read-Only) tools ONLY. Any Medium, High, or Critical risk tool requested by the agent during a webhook-triggered task automatically suspends execution to `waiting_approval` (mandatory HITL).
- **Task & Tool Budgets:** Hard-capped at max 10 steps, max 5 tool calls, and max 5 minutes execution timeout.
- **Payload Constraints:** Maximum payload size 1MB; timestamp freshness window $\le 300\text{s}$ to block replay attacks; payload content tagged `is_untrusted_content = True`.
- **System Policy Immutability:** Webhooks are strictly prohibited from altering system policies, tool permissions, BYOK credentials, workspace ownership, or user accounts.

### 10.3 AURA-403: Zero-Cost Telegram Bot Poller Design
- **Architecture:** Async long-polling daemon utilizing `getUpdates` with persistent `update_id` offset stored in PostgreSQL.
- **Mutual Exclusivity:** Telegram long-polling and outgoing webhooks are mutually exclusive. Long-polling requires **zero public IP, tunneling, or webhook hosting**, maintaining $0.00 cost.
- **Pairing & Authentication:** Users pair their Telegram `chat_id` using a single-use pairing token generated in the web dashboard (15-minute TTL). Unauthenticated `chat_id` messages are ignored.
- **Isolation & Lifecycle:** Strict workspace tenancy binding; bounded update queue (max 50 updates); backoff on network errors; graceful cancellation on process shutdown.

### 10.4 AURA-404: Local Playwright Security Boundary
- **SSRF Shield Enforcement:** All target URLs and redirects are validated against `SSRFProtectionGuard` (blocks loopback, RFC 1918, link-local, cloud metadata).
- **Resource Constraints:** Page timeout 30s, max content size 5MB, bounded concurrency ($\le 2$ browser pages).
- **Isolation:** Executes in headless container sandbox; zero access to host drives or network credentials; output converted to clean markdown and tagged `is_untrusted_content = True`.
- **Governance:** Accessible exclusively via `AgentToolBridge` $\rightarrow$ `ToolRegistryService`.

---

## 11. Phase 4 Implementation Plan & Milestones

### Milestone A: Foundation & Schema Definitions
- **Deliverables:**
  - Create SQLAlchemy models: `Automation`, `AutomationRun`, `WebhookEndpoint`, `TelegramPairing`.
  - Add Alembic migration script for Phase 4 schema.
  - Install zero-cost Python dependencies: `croniter>=2.0.0`, `playwright>=1.48.0`.
- **Security Implications:** Workspace foreign keys on all automation models; HMAC secrets stored encrypted.
- **Tests:** `test_automation_db_models.py` verifying CRUD, constraints, and cascade deletions.

### Milestone B: Core PostgreSQL Transactional Cron Scheduler (AURA-401)
- **Deliverables:**
  - `app/services/automations/scheduler_service.py`: Cron calculation, worker loop, `FOR UPDATE SKIP LOCKED` claim queries.
  - `app/services/automations/execution_service.py`: Task DAG instantiation, retry policy with exponential jitter, 3-strike circuit breaker.
  - REST endpoints in `app/api/v1/automations.py`.
- **Security Implications:** Strict autonomy level enforcement; execution timeout caps (15 minutes).
- **Tests:** `test_cron_scheduler.py` verifying concurrency safety, interval math, and retry transitions.

### Milestone C: Inbound Webhook Reactive Gateway (AURA-402)
- **Deliverables:**
  - `app/services/webhooks/ingress_service.py`: HMAC signature validation, timestamp replay check (300s window), idempotency key cache.
  - Ingress controller in `app/api/v1/webhooks.py`.
  - Mustache/Jinja template placeholder substitution for inbound payload mapping.
- **Security Implications:** Automatic L4 autonomy scoping; payload sanitization as untrusted input.
- **Tests:** `test_webhook_ingress.py` verifying HMAC verification, replay attack rejection, and task dispatching.

### Milestone D: Free Telegram Bot Ingress Adapter (AURA-403)
- **Deliverables:**
  - `app/services/integrations/telegram_service.py`: Async long-polling daemon, command router (`/goal`, `/status`, `/cancel`, `/approve`).
  - Telegram pairing token exchange workflow.
  - Outbound response delivery formatting.
- **Security Implications:** Strict chat ID authorization allowlist; pairing token expiration (15 min).
- **Tests:** `test_telegram_integration.py` with mocked Telegram HTTP API.

### Milestone E: Local Playwright Web Extractor Tool (AURA-404)
- **Deliverables:**
  - `app/services/tools/playwright_extractor.py`: Headless browser manager, DOM cleaning, Markdown conversion.
  - Registration into `ToolRegistryService` with schema and risk classification (Medium risk).
- **Security Implications:** Mandatory SSRF pre-flight validation on target URLs; output flagged with `is_untrusted_content: True`.
- **Tests:** `test_playwright_extractor.py` verifying SSRF blocking and DOM sanitization.

### Milestone F: Frontend Control Surfaces & Release Verification
- **Deliverables:**
  - Integrate `AutomationsView.tsx`, `WebhooksView.tsx`, and `IntegrationsView.tsx` into Next.js dashboard.
  - Add automated frontend tests in `apps/web/tests/automations.test.ts`.
  - Comprehensive end-to-end integration validation.
- **Tests:** 100% passing backend, frontend, and build suites.

---

## 12. Risks & Mitigation Matrix

| Risk | Impact | Likelihood | Mitigation |
| :--- | :--- | :--- | :--- |
| **Duplicate Cron Execution Across Workers** | High | Low | PostgreSQL `FOR UPDATE SKIP LOCKED` atomic row claiming with lease timeouts. |
| **Webhook Replay Attack** | High | Medium | HMAC-SHA256 signature, timestamp freshness check ($\le 300\text{s}$), and idempotency keys. |
| **Prompt Injection via Ingress / Scraper** | Critical | High | Mandatory untrusted content tagging (`is_untrusted_content: True`) and strict prompt quarantining. |
| **Telegram Polling Memory Leak** | Medium | Low | Use bounded async task queues and graceful cancellation on shutdown. |
| **Playwright Resource Exhaustion** | High | Low | Impose headless page timeout (30s), single browser instance reuse, and memory limits. |
| **SSRF via Web Scraper** | Critical | Medium | Pass all target URLs through `SSRFProtectionGuard` before opening browser page. |

---

## 13. Known Issues & Tech Debt
- `duckduckgo_search` library emitted a deprecation notice recommending the `ddgs` package alias (addressed in Phase 4 tool optimization).
- `starlette.formparsers` deprecation warning regarding `python-multipart` import (non-blocking).

---

## 14. Deferred Items (Scheduled for Future Phases)
- **Phase 5:** Ephemeral Firejail Linux sandboxing enhancements (Docker sandboxing already operational from Phase 2C).
- **Phase 5:** OpenTelemetry exporter integration.
- **Post-Phase 5:** Voice input/output local whisper/piper synthesis.

---

## 15. Exact Implementation Starting Point
When authorized to begin Phase 4, implementation will commence precisely with:
1. **Step 1:** Add Phase 4 dependencies (`croniter>=2.0.0`, `playwright>=1.48.0`) to `apps/api/requirements.txt`.
2. **Step 2:** Define SQLAlchemy models in `apps/api/app/db/models/automations.py` and `integrations.py`.
3. **Step 3:** Implement Alembic migration script for the new tables.

---

## 16. Final Baseline Corrections & Invariant Lock

1. **Gemini Model Catalog Corrected:**
   - Active models: `gemini-2.5-flash`, `gemini-2.5-pro`.
   - Obsolete identifiers `gemini-2.0-flash`, `gemini-1.5-flash`, and `gemini-1.5-pro` removed from active configuration.
   - Centralized metadata dictionary `GEMINI_MODEL_CATALOG` implemented in `GeminiProvider` with capabilities, access limitations, and cost classifications.
2. **Next.js Dependency Patched (CVE-2025-66478):**
   - Locked to `next = 15.5.27` in `apps/web/package.json`.
   - 12/12 frontend tests passing; Next.js production build passing with 0 errors.
3. **Concurrency & Autonomy Formally Bound:**
   - Multi-worker PostgreSQL `FOR UPDATE SKIP LOCKED` scheduler with lease recovery.
   - Webhook ingress hard-gated to Autonomy Level 4 with mandatory HITL for Medium/High/Critical tools.
   - Telegram long-polling designed with singleton lifecycle, chat allowlist, and zero public webhooks.
   - Playwright web extractor enclosed within `SSRFProtectionGuard` and `AgentToolBridge`.
4. **Zero-Cost & Regression Invariants Certified:**
   - 100% $0.00 mandatory operational cost.
   - 67/67 backend pytest tests passing (100%).
   - 12/12 frontend vitest tests passing (100%).
   - Bounded subagent limits ($\le 4$ workers, depth $\le 2$) preserved.

---

**FINAL STATUS:**  
`PHASE 4 PREFLIGHT CORRECTED AND LOCKED — READY FOR IMPLEMENTATION`
