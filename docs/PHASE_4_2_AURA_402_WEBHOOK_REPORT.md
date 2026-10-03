# AURA — PHASE 4.2 IMPLEMENTATION REPORT
## AURA-402: Inbound Webhook Reactive Gateway

**Document Version:** 1.0.0  
**Phase:** Phase 4.2 — Inbound Webhook Reactive Gateway  
**Task ID:** AURA-402  
**Author:** High-Accuracy AI Assistant (Architect of Knowledge)  
**Status:** COMPLETE — READY FOR AURA-403  

---

## 1. Objective

The primary objective of **AURA-402** is to introduce AURA's inbound reactive webhook gateway: an ingress authenticator that safely transforms external HTTP events into bounded, governed AURA tasks while strictly maintaining every runtime, security, multi-tenant isolation, autonomy, and zero-cost invariant.

The webhook gateway acts as an **ingress authenticator and trigger**, never an execution authority. Downstream execution strictly traverses the single authoritative governance chain:

$$\text{External Sender} \longrightarrow \text{HMAC/Timestamp Validation} \longrightarrow \text{Idempotency Check} \longrightarrow \text{Untrusted Wrapping} \longrightarrow \text{TaskService.create_task} \longrightarrow \text{Task DAG} \longrightarrow \text{Agent Runtime} \longrightarrow \text{AgentToolBridge} \longrightarrow \text{ToolRegistryService} \longrightarrow \text{Policy / HITL / Sandbox} \longrightarrow \text{Execution}$$

---

## 2. Architecture

```text
+---------------------------------------------------------------------------------------------------+
|                                 INBOUND WEBHOOK INGRESS GATEWAY                                   |
+---------------------------------------------------------------------------------------------------+
|                                                                                                   |
|  External Event (POST /api/v1/webhooks/ingress/{public_id})                                       |
|        |                                                                                          |
|        v                                                                                          |
|  [Step 1: Size & Rate Limit Check] --------------> Exceeds 1MB? ---------> HTTP 413 Rejected     |
|        |                                                                                          |
|        v                                                                                          |
|  [Step 2: Timestamp Verification] --------------> Drift > 300s? --------> HTTP 400 Stale Replay  |
|        |                                                                                          |
|        v                                                                                          |
|  [Step 3: HMAC-SHA256 Verification] -----------> Invalid Signature? ---> HTTP 401 Unauthorized   |
|        |                                                                                          |
|        v                                                                                          |
|  [Step 4: Idempotency Lookup] -----------------> Duplicate Key? --------> HTTP 200 Cached Result  |
|        |                                                                                          |
|        v                                                                                          |
|  [Step 5: Kill Switch Check] ------------------> Active? ---------------> HTTP 503 Blocked Record |
|        |                                                                                          |
|        v                                                                                          |
|  [Step 6: SSTI-Safe Template Hydration & Structured Untrusted Data Framing]                       |
|        |                                                                                          |
|        v                                                                                          |
|  [Step 7: Governed Task Dispatch via TaskService (Autonomy Level 4)]                              |
|        |                                                                                          |
|        v                                                                                          |
|  Task DAG Execution via AgentToolBridge -> ToolRegistryService -> HITL / Policy Sandbox           |
+---------------------------------------------------------------------------------------------------+
```

---

## 3. Database Schema

### Table: `webhook_endpoints`
| Column | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | UUID | Primary Key | Canonical UUID identifier |
| `workspace_id` | UUID | FK $\to$ `workspaces.id` (CASCADE), NOT NULL, INDEX | Multi-tenant workspace isolation |
| `created_by` | UUID | FK $\to$ `users.id` (SET NULL), NULLABLE | Creator user identifier |
| `public_id` | VARCHAR(64) | UNIQUE, NOT NULL, INDEX | Opaque unguessable public URL slug (`whk_...`) |
| `name` | VARCHAR(255) | NOT NULL | Human-readable webhook name |
| `description` | TEXT | NULLABLE | Webhook description |
| `secret_ciphertext` | TEXT | NOT NULL | AES-256-GCM encrypted HMAC secret |
| `prompt_template` | TEXT | NOT NULL | Task objective template with safe `{payload.x}` markers |
| `autonomy_level` | SMALLINT | NOT NULL, Default: `4` | Autonomy ceiling (bounded to 4) |
| `is_active` | BOOLEAN | NOT NULL, Default: `TRUE`, INDEX | Administrative enablement toggle |
| `max_payload_bytes` | INTEGER | NOT NULL, Default: `1048576` | Maximum payload size ceiling (1 MB) |
| `rate_limit_per_minute`| INTEGER | NOT NULL, Default: `60` | Request rate limit ceiling |
| `last_received_at` | TIMESTAMPTZ | NULLABLE | Timestamp of most recent delivery attempt |
| `total_received` | INTEGER | NOT NULL, Default: `0` | Cumulative received counter |
| `total_failed` | INTEGER | NOT NULL, Default: `0` | Cumulative failed authentication counter |
| `created_at` / `updated_at` | TIMESTAMPTZ | NOT NULL | Audit timestamps |

### Table: `webhook_deliveries`
| Column | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | UUID | Primary Key | Canonical delivery identifier |
| `webhook_endpoint_id` | UUID | FK $\to$ `webhook_endpoints.id` (CASCADE), NOT NULL, INDEX | Parent webhook endpoint |
| `workspace_id` | UUID | FK $\to$ `workspaces.id` (CASCADE), NOT NULL, INDEX | Workspace boundary |
| `idempotency_key` | VARCHAR(255) | NOT NULL, INDEX | Event delivery idempotency identifier |
| `received_at` | TIMESTAMPTZ | NOT NULL | Delivery reception timestamp |
| `status` | VARCHAR(50) | NOT NULL, Default: `'accepted'` | `accepted`, `dispatched`, `duplicate`, `blocked_kill_switch` |
| `task_id` | UUID | FK $\to$ `tasks.id` (SET NULL), NULLABLE, INDEX | Downstream AURA Task link |
| `payload_hash` | VARCHAR(64) | NOT NULL | SHA-256 digest of raw request body |
| `error_code` | VARCHAR(100) | NULLABLE | Error classification code |
| `error_summary` | TEXT | NULLABLE | Sanitized failure summary |
| `created_at` / `updated_at` | TIMESTAMPTZ | NOT NULL | Audit timestamps |

**Constraints:**
- `uq_webhook_delivery_idempotency`: Unique constraint on `(workspace_id, webhook_endpoint_id, idempotency_key)`.

---

## 4. Endpoint Contract

### Public Ingress Endpoint
- **Method:** `POST`
- **Path:** `/api/v1/webhooks/ingress/{public_id}`
- **Authentication:** Cryptographic HMAC signature + timestamp headers (no user bearer token required).
- **Required Headers:**
  - `Content-Type`: `application/json`
  - `X-AURA-Timestamp` or `X-Timestamp`: UTC Unix timestamp in seconds.
  - `X-AURA-Signature` or `X-Hub-Signature-256`: Hexadecimal HMAC-SHA256 signature (supports optional `sha256=` prefix).
  - `X-AURA-Idempotency-Key` or `X-Delivery-ID` (Optional; defaults to deterministic hash of timestamp + body).

---

## 5. HMAC Design

- **Algorithm:** HMAC-SHA256.
- **Signed Message:** `f"{timestamp}.".encode("utf-8") + raw_request_body`.
- **Comparison:** Constant-time `hmac.compare_digest(actual_sig, expected_sig)` to prevent timing side-channel attacks.
- **Raw Body Verification:** Verification occurs directly on the unparsed raw bytes before any JSON deserialization or normalization.

---

## 6. Replay Defense

- **Freshness Window:** 300 seconds (5 minutes).
- **Validation:**
  $$|\text{now}_{\text{UTC}} - \text{timestamp}_{\text{req}}| \le 300\text{s}$$
- **Rejection:** Stale timestamps or future timestamps beyond 300s are rejected immediately with `HTTP 400 Bad Request` (`"Timestamp out of bounds (replay protection)"`).

---

## 7. Idempotency Model

- **Scope:** Scoped to `(workspace_id, webhook_endpoint_id, idempotency_key)`.
- **Persistence:** Backed by database-level unique constraint on `webhook_deliveries`.
- **Duplicate Behavior:** Duplicate deliveries return `HTTP 200` with status `"duplicate"` and reference the existing `task_id` without creating redundant downstream tasks or re-executing agent workloads.

---

## 8. Payload Handling

- **Maximum Size:** 1,048,576 bytes (1 MB). Payloads exceeding 1MB are rejected with `HTTP 413 Payload Too Large`.
- **Untrusted Tagging:** All parsed payload content is explicitly marked as `is_untrusted_content = True` and framed in structured isolation blocks.

---

## 9. Template Security & SSTI Defense

- **Substitution Strategy:** Bounded placeholder extraction (`{payload.user.name}` or `{{payload.user.name}}`).
- **Path Validation:** Only simple alphanumeric dotted paths (`^[a-zA-Z0-9_]+(?:\.[a-zA-Z0-9_]+)*$`) are evaluated.
- **SSTI & Code Execution Prevention:**
  - No `eval()`, `exec()`, or template engine execution.
  - Dunder attributes (e.g. `__class__`, `__mro__`, `__globals__`) are blocked by `_safe_get_nested`.
  - Complex expressions or method invocations (e.g. `{payload.eval('...')}`) are stripped to empty strings.
- **Output Bound:** Maximum hydrated prompt length is capped at 10,000 characters.

---

## 10. Autonomy Level 4 Containment

Webhook-triggered tasks execute under Autonomy Level 4 with strict safety bounds:
- **Maximum Task Steps:** 10.
- **Maximum Tool Calls:** 5.
- **Maximum Execution Timeout:** 300 seconds (5 minutes).
- **Budget Ceiling:** 4,000 tokens.

---

## 11. Risk & HITL Behavior

- **Low / Read-Only Tools:** May proceed automatically according to workspace tool policy.
- **Medium / High / Critical Tools:** Must suspend for cryptographic Human-In-The-Loop approval, generating an HMAC-signed token.
- **Zero Elevation Invariant:** The webhook layer cannot alter risk classifications or auto-approve privileged tools.

---

## 12. Workspace Isolation

- The incoming public identifier `public_id` uniquely resolves the authoritative `workspace_id`.
- Client requests cannot specify or override the workspace boundary.
- Cross-workspace delivery lookups and management operations are strictly blocked by RBAC checks.

---

## 13. Rate Limits & Abuse Protection

- Configurable per-endpoint rate limits (default: 60 requests/minute).
- Payload size validation precedes JSON parsing.
- Invalid HMAC signatures fail immediately without invoking LLM inference or Task creation.

---

## 14. Kill-Switch Integration

- When `kill_switch.is_active(workspace_id)` is engaged:
  - Inbound webhook is logged as `status = "blocked_kill_switch"`.
  - HTTP 503 response is returned (`"Execution suspended by Emergency Kill Switch"`).
  - 0 downstream tasks are dispatched.

---

## 15. Audit Events

Recorded to the tamper-evident SHA-256 chained audit log:
- `webhook.created`, `webhook.updated`, `webhook.secret_rotated`, `webhook.enabled`, `webhook.disabled`, `webhook.deleted`, `webhook.task_dispatched`, `webhook.blocked_kill_switch`.

---

## 16. Realtime Events

Emits sanitized events over `EventBroadcasterHub`:
- `webhook.received`, `webhook.dispatched`, `webhook.blocked`.

---

## 17. Secret Handling

- Plaintext secrets are displayed **only once** upon initial creation or secret rotation.
- Secrets are persisted exclusively as AES-256-GCM encrypted ciphertext.
- Standard GET/list API responses mask secrets completely.
- Secrets are excluded from logs, audit details, and task context.

---

## 18. API Management Surface

| Method | Endpoint | Description | Auth Required |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/webhooks?workspace_id={id}` | Create webhook endpoint (returns secret once) | Yes (Workspace Member) |
| `GET` | `/api/v1/webhooks?workspace_id={id}` | List webhook endpoints (secrets masked) | Yes (Workspace Member) |
| `GET` | `/api/v1/webhooks/{id}?workspace_id={id}` | Get webhook endpoint metadata | Yes (Workspace Member) |
| `PATCH` | `/api/v1/webhooks/{id}?workspace_id={id}` | Update webhook endpoint configuration | Yes (Workspace Member) |
| `POST` | `/api/v1/webhooks/{id}/rotate-secret?workspace_id={id}` | Rotate HMAC secret (returns new secret once) | Yes (Workspace Member) |
| `POST` | `/api/v1/webhooks/{id}/toggle?workspace_id={id}` | Enable or disable webhook endpoint | Yes (Workspace Member) |
| `DELETE` | `/api/v1/webhooks/{id}?workspace_id={id}` | Soft-delete webhook endpoint | Yes (Workspace Member) |
| `GET` | `/api/v1/webhooks/{id}/deliveries?workspace_id={id}` | Inspect delivery receipts and history | Yes (Workspace Member) |
| `POST` | `/api/v1/webhooks/ingress/{public_id}` | Public ingress endpoint (HMAC authenticated) | No (HMAC/Timestamp Header) |

---

## 19. Test Matrix

| Test Module | Test Case | Scope / Coverage | Result | Classification |
| :--- | :--- | :--- | :--- | :--- |
| `test_webhook_db_models.py` | `test_webhook_endpoint_crud_and_defaults` | Endpoint defaults, UUIDs, limits | **PASS** | SQLITE / INTEGRATION |
| `test_webhook_db_models.py` | `test_webhook_delivery_uniqueness_constraint` | Unique `(ws, ep, idempotency_key)` | **PASS** | SQLITE / INTEGRATION |
| `test_webhook_db_models.py` | `test_webhook_cascade_deletion` | Foreign key CASCADE integrity | **PASS** | SQLITE / INTEGRATION |
| `test_webhook_gateway.py` | `test_template_hydration_and_ssti_prevention` | Placeholder replacement & SSTI block | **PASS** | STATIC / UNIT |
| `test_webhook_gateway.py` | `test_webhook_ingress_hmac_verification` | Valid, invalid, missing HMAC signatures | **PASS** | REAL FASTAPI / SQLITE |
| `test_webhook_gateway.py` | `test_webhook_timestamp_replay_defense` | 300s window & stale replay rejection | **PASS** | REAL FASTAPI / SQLITE |
| `test_webhook_gateway.py` | `test_webhook_payload_size_limit` | >1MB payload rejection with 413 | **PASS** | REAL FASTAPI / SQLITE |
| `test_webhook_gateway.py` | `test_webhook_idempotency_deduplication` | Duplicate delivery deduplication | **PASS** | REAL FASTAPI / SQLITE |
| `test_webhook_gateway.py` | `test_webhook_emergency_kill_switch_suspension`| Kill switch suspension & 0 tasks | **PASS** | REAL FASTAPI / SQLITE |
| `test_webhook_gateway.py` | `test_webhook_management_api_lifecycle` | Full CRUD, rotate, toggle, delete | **PASS** | REAL FASTAPI / SQLITE |
| `test_webhook_gateway.py` | `test_webhook_same_key_different_payload_conflict`| Same key / different payload 409 conflict | **PASS** | REAL FASTAPI / SQLITE |
| `test_webhook_gateway.py` | `test_webhook_different_scope_idempotency` | Multi-endpoint & multi-workspace scope isolation | **PASS** | REAL FASTAPI / SQLITE |
| `test_webhook_gateway.py` | `test_webhook_rate_limiting_sliding_window` | Per-endpoint sliding window HTTP 429 throttling | **PASS** | REAL FASTAPI / SQLITE |
| `test_webhook_gateway.py` | `test_webhook_secret_rotation_invalidation` | Old secret invalidation & new secret success | **PASS** | REAL FASTAPI / SQLITE |
| `test_webhook_gateway.py` | `test_webhook_adversarial_policy_tamper_isolation`| Attacker-controlled fields ignored / L4 bounded | **PASS** | REAL FASTAPI / SQLITE |

---

## 20. PostgreSQL Concurrency Classification

- Automated test environment: **SQLITE** (`aiosqlite` in-memory SQLite fixture for local zero-cost verification).
- Production environment: **REAL POSTGRESQL** (`postgresql+asyncpg://...`).
- Database uniqueness constraint: `UniqueConstraint("workspace_id", "webhook_endpoint_id", "idempotency_key", name="uq_webhook_delivery_idempotency")` enforces physical database-level race protection in PostgreSQL.

---

## 21. Integration Results

- **Ingress Dispatch:** Validated full pipeline from external HTTP request $\to$ HMAC validation $\to$ timestamp verification $\to$ idempotency check $\to$ prompt hydration $\to$ `TaskService.create_task` $\to$ database task entity.
- **Audit Logging:** Verified cryptographic SHA-256 chained audit records for all webhook events.

---

## 22. Regression Results

- **Backend Pytest Suite:**
  - **97 / 97 passing** (increased from 92 with acceptance gate tests).
  - 0 failures, 0 errors.
- **Frontend Vitest Suite:**
  - **12 / 12 passing**.
- **Next.js Production Build:**
  - **Successful** (4/4 static pages prerendered, 0 lint/type errors).

---

## 23. Zero-Cost Verification

- **Cost:** **$0.00 mandatory operating cost**.
- **Dependencies:** 0 third-party relays, 0 paid webhook SaaS (e.g. Hookdeck, ngrok), 0 external cloud queues.

---

## 24. Known Limitations

1. **Local Network Exposure:** The local FastAPI webhook endpoint is accessible on the local network (`localhost:8000`). Public Internet ingress requires user-configured reverse proxies or secure networking.
2. **Payload Size Ceiling:** Maximum supported webhook payload size is strictly capped at 1 MB.

---

## 25. Deferred Work

- **AURA-403:** Free Telegram Bot long-polling ingress adapter.
- **AURA-404:** Local Playwright web extractor tool.
- **Phase 4 UI:** Webhook management console & trigger history drawer.

---

## 26. Final Acceptance Gate Results

| Verification Item | Method | Environment | Classification | Result | Evidence |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **HMAC-SHA256 Cryptography** | Test Suite & Code Inspection | Python 3.12 / FastAPI | REAL FASTAPI / SQLITE | **PASS — Verified** | Verified constant-time verification over raw request bytes (`test_webhook_ingress_hmac_verification`). |
| **Timestamp Replay Protection** | Ingress Clock Drift Test | Python 3.12 / FastAPI | REAL FASTAPI / SQLITE | **PASS — Verified** | Stale (>300s) and malformed timestamps rejected with HTTP 400 (`test_webhook_timestamp_replay_defense`). |
| **Persistent Idempotency** | Ingress Duplicate Test | Python 3.12 / FastAPI | REAL FASTAPI / SQLITE | **PASS — Verified** | Duplicate key returns cached task without creating second task entity (`test_webhook_idempotency_deduplication`). |
| **PostgreSQL Concurrency** | Schema Inspection & DB Constraint | PostgreSQL Schema / SQLite | STATIC / CODE-PATH & SQLITE | **PASS — Verified** | Unique constraint `uq_webhook_delivery_idempotency` defined in SQLAlchemy and Alembic migration `005`. |
| **Same Key / Different Payload** | Ingress Divergence Test | Python 3.12 / FastAPI | REAL FASTAPI / SQLITE | **PASS — Verified** | Differing payload hash on duplicate key returns HTTP 409 Conflict (`test_webhook_same_key_different_payload_conflict`). |
| **Multi-Tenant Scope Isolation**| Cross-Tenant Ingress Test | Python 3.12 / FastAPI | REAL FASTAPI / SQLITE | **PASS — Verified** | Identical keys across separate endpoints and workspaces process independently (`test_webhook_different_scope_idempotency`). |
| **Secret Storage & Rotation** | Encrypted Storage & Rotation API | Python 3.12 / FastAPI | REAL FASTAPI / SQLITE | **PASS — Verified** | AES-256-GCM ciphertext persisted; old secret invalidated immediately upon rotation (`test_webhook_secret_rotation_invalidation`). |
| **Rate Limiting & Abuse** | Sliding Window Throttling Test | Python 3.12 / FastAPI | REAL FASTAPI / SQLITE | **PASS — Verified** | 429 Too Many Requests returned upon reaching rate limit ceiling (`test_webhook_rate_limiting_sliding_window`). |
| **L4 Autonomy Containment** | Malicious Payload Injection | Python 3.12 / FastAPI | REAL FASTAPI / SQLITE | **PASS — Verified** | Backend enforces strict bounds (L4, 10 steps, 5 tools, 300s, 4000 tokens) regardless of payload (`test_webhook_adversarial_policy_tamper_isolation`). |
| **HITL Policy Enforcement** | Tool Registry & HITL Engine | Python 3.12 / FastAPI | CODE-PATH / UNIT | **PASS — Verified** | Webhook ingress routes through standard `AgentToolBridge` -> `ToolRegistryService` -> HITL approval for high-risk actions. |
| **SSTI & Template Security** | Malicious AST & Dunder Test | Python 3.12 / FastAPI | STATIC / UNIT | **PASS — Verified** | Dunders (`__mro__`), reflection, and code execution stripped (`test_template_hydration_and_ssti_prevention`). |
| **Prompt Injection Isolation** | Adversarial Ingress Test | Python 3.12 / FastAPI | REAL FASTAPI / SQLITE | **PASS — Verified** | Payload wrapped in structured untrusted data boundary with `is_untrusted_content = True` (`test_webhook_adversarial_policy_tamper_isolation`). |
| **Workspace Boundary** | Multitenancy Isolation Tests | Python 3.12 / FastAPI | REAL FASTAPI / SQLITE | **PASS — Verified** | Workspace derived from endpoint identity; cross-tenant access blocked by RBAC dependencies. |
| **Emergency Kill Switch** | Workspace Suspension Test | Python 3.12 / FastAPI | REAL FASTAPI / SQLITE | **PASS — Verified** | Active kill switch returns HTTP 503, records `blocked_kill_switch` delivery, dispatches 0 tasks (`test_webhook_emergency_kill_switch_suspension`). |
| **Audit & Telemetry Safety** | Audit Chaining & SSE Sanitize | Python 3.12 / FastAPI | REAL FASTAPI / SQLITE | **PASS — Verified** | Chained audit records exclude raw secrets, HMAC digests, and sensitive headers. |
| **Zero Operating Cost** | Architecture Review | Localhost / Python 3.12 | STATIC / ARCHITECTURE | **PASS — Verified** | $0.00 mandatory cost; 0 external paid gateways or cloud brokers. |
| **Full Regression Suite** | Pytest, Vitest, Next.js Build | Python 3.12 / Node 24 | FULL SUITE | **PASS — Verified** | 97/97 Pytest PASS, 12/12 Vitest PASS, Next.js Build PASS. |

---

## 27. Final Status

```text
================================================================================
AURA-402 ACCEPTED — READY FOR AURA-403
================================================================================
```
