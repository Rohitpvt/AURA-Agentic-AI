# AURA — PHASE 4.3 IMPLEMENTATION REPORT
## AURA-403: Telegram Bot Long-Polling Integration

**Document Version:** 1.0.0  
**Phase:** Phase 4.3 — Telegram Bot Long-Polling Integration  
**Task ID:** AURA-403  
**Author:** High-Accuracy AI Assistant (Architect of Knowledge)  
**Date:** 2026-10-01  
**Status:** COMPLETE — READY FOR AURA-404  

---

## 1. Objective

The primary objective of **AURA-403** is to introduce Telegram as a secure, zero-cost external operator interface for AURA using the official Telegram Bot API in **long-polling mode** (`getUpdates`).

The Telegram adapter functions strictly as an **external communication and operator portal**, never an execution authority. Downstream task execution traverses the existing single execution and governance pipeline:

$$\text{Telegram Chat} \longrightarrow \text{TelegramLongPoller} \longrightarrow \text{Pairing / Workspace Authorization} \longrightarrow \text{Command Parser} \longrightarrow \text{TaskService.create_task} \longrightarrow \text{Task DAG} \longrightarrow \text{AgentRuntimeEngine} \longrightarrow \text{AgentToolBridge} \longrightarrow \text{ToolRegistryService} \longrightarrow \text{Policy / HITL / Sandbox} \longrightarrow \text{Execution}$$

---

## 2. Architecture

```text
+---------------------------------------------------------------------------------------------------+
|                                  AURA TELEGRAM ADAPTER ARCHITECTURE                               |
+---------------------------------------------------------------------------------------------------+
|                                                                                                   |
|  Telegram Cloud (api.telegram.org)                                                                |
|        |                                                                                          |
|        v (Long Polling via getUpdates: offset = last_update_id + 1)                               |
|  [Step 1: TelegramDaemon / Long-Poller Worker]                                                    |
|        |                                                                                          |
|        v                                                                                          |
|  [Step 2: Poller Lease Check] ------------> Acquired by another worker? --------> Skip iteration  |
|        |                                                                                          |
|        v                                                                                          |
|  [Step 3: Pairing Resolution & Chat Auth] -> Unpaired chat & non-/start? ---------> Reject         |
|        |                                                                                          |
|        v                                                                                          |
|  [Step 4: Command Parser (/start, /help, /status, /goal, /cancel, /approve)]                      |
|        |                                                                                          |
|        v                                                                                          |
|  [Step 5: Kill Switch Check] -------------> Active in Workspace? ---------------> Block execution |
|        |                                                                                          |
|        v                                                                                          |
|  [Step 6: Governed Service Dispatch via TaskService / ApprovalService (L4 Bounds)]                |
|        |                                                                                          |
|        v                                                                                          |
|  [Step 7: Persistent Offset Advancement (last_update_id in DB)]                                   |
|        |                                                                                          |
|        v                                                                                          |
|  [Step 8: Outbound Message Formatting & Length Bounding (Max 4000 chars) -> sendMessage]          |
+---------------------------------------------------------------------------------------------------+
```

---

## 3. Telegram API Contract

- **Mode:** Long-polling (`getUpdates`) exclusively (mutually exclusive with outgoing webhooks).
- **Endpoint Base:** `https://api.telegram.org/bot<token>`
- **Core Methods Used:**
  - `getMe`: Validates bot token authenticity and extracts safe identity metadata (`id`, `username`) without exposing the secret.
  - `getUpdates`: Fetches unacknowledged updates using `offset = last_update_id + 1`, `timeout = 20` seconds, and `limit = 10`.
  - `sendMessage`: Dispatches outbound status notifications, pairing confirmations, and execution receipts.

---

## 4. Credential Security

- **Storage:** Telegram bot API tokens (`bot_token`) are encrypted at rest using AES-256-GCM (`bot_token_ciphertext`).
- **Isolation Invariants:**
  - Tokens are never returned in standard REST API GET/list endpoints.
  - Tokens are never included in structured application logs.
  - Tokens are never emitted into SSE streams or WebSocket payloads.
  - Tokens are never placed in audit records or task prompt contexts.
  - Tokens are never exposed to LLM inference or frontend state.

---

## 5. Database Model

### Table: `telegram_integrations`
| Column | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | UUID | Primary Key | Canonical UUID identifier |
| `workspace_id` | UUID | FK $\to$ `workspaces.id` (CASCADE), NOT NULL, INDEX | Multi-tenant workspace isolation |
| `created_by` | UUID | FK $\to$ `users.id` (SET NULL), NULLABLE | Creator user identifier |
| `display_name` | VARCHAR(255) | NOT NULL, Default: `'Telegram Bot'` | Human-readable integration label |
| `bot_token_ciphertext` | TEXT | NOT NULL | AES-256-GCM encrypted bot API token |
| `bot_username` | VARCHAR(255) | NULLABLE | Verified Telegram bot username |
| `bot_id` | VARCHAR(64) | NULLABLE | Telegram bot numeric ID |
| `is_active` | BOOLEAN | NOT NULL, Default: `TRUE`, INDEX | Administrative enablement toggle |
| `polling_state` | VARCHAR(50) | NOT NULL, Default: `'stopped'` | Poller state (`stopped`, `polling`, `error`) |
| `last_update_id` | BIGINT | NOT NULL, Default: `0` | Persisted Telegram update confirmation offset |
| `poller_lease_id` | VARCHAR(255) | NULLABLE | Worker ID owning the active polling lease |
| `poller_lease_expires_at`| TIMESTAMPTZ | NULLABLE, INDEX | Lease expiration timestamp (60s TTL) |
| `last_successful_poll_at`| TIMESTAMPTZ | NULLABLE | Timestamp of most recent successful poll |
| `last_error_code` | VARCHAR(100) | NULLABLE | Failure error code |
| `last_error_summary` | TEXT | NULLABLE | Sanitized failure summary |
| `total_messages_received`| INTEGER | NOT NULL, Default: `0` | Cumulative messages counter |
| `total_commands_processed`| INTEGER| NOT NULL, Default: `0` | Cumulative commands counter |
| `created_at` / `updated_at` | TIMESTAMPTZ | NOT NULL | Audit timestamps |

### Table: `telegram_pairings`
| Column | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | UUID | Primary Key | Canonical pairing UUID |
| `workspace_id` | UUID | FK $\to$ `workspaces.id` (CASCADE), NOT NULL, INDEX | Multi-tenant workspace isolation |
| `integration_id` | UUID | FK $\to$ `telegram_integrations.id` (CASCADE), NOT NULL, INDEX | Parent integration reference |
| `created_by` | UUID | FK $\to$ `users.id` (SET NULL), NULLABLE | Creator user identifier |
| `telegram_chat_id` | VARCHAR(64) | NOT NULL, INDEX | External Telegram chat ID |
| `telegram_user_id` | VARCHAR(64) | NULLABLE | External Telegram user ID |
| `telegram_username` | VARCHAR(255) | NULLABLE | Telegram username |
| `is_active` | BOOLEAN | NOT NULL, Default: `FALSE`, INDEX | Pairing authorization state |
| `pairing_token_hash` | VARCHAR(64) | NULLABLE, INDEX | SHA-256 hash of one-time 15-min pairing token |
| `pairing_token_expires_at`| TIMESTAMPTZ | NULLABLE | Pairing token expiration timestamp |
| `paired_at` | TIMESTAMPTZ | NULLABLE | Timestamp when pairing completed |
| `revoked_at` | TIMESTAMPTZ | NULLABLE | Timestamp when pairing revoked |
| `last_seen_at` | TIMESTAMPTZ | NULLABLE | Timestamp of most recent command |
| `created_at` / `updated_at` | TIMESTAMPTZ | NOT NULL | Audit timestamps |

**Constraints:**
- `uq_telegram_pairing_chat`: Composite unique constraint on `(workspace_id, integration_id, telegram_chat_id)`.

---

## 6. Pairing Workflow

1. An authenticated AURA user generates a pairing token via `POST /api/v1/telegram/integrations/{id}/pairings`.
2. A cryptographically random token (`aurapair_<token_urlsafe(24)>`) is generated.
3. The SHA-256 hash of the token is persisted with a strict **15-minute TTL** (`pairing_token_expires_at = now + 900s`).
4. The user sends `/start <pairing_token>` in Telegram.
5. The gateway hashes the provided token and looks up the unexpired record.
6. Upon validation:
   - The chat is bound: `telegram_chat_id = str(chat_id)`.
   - The pairing is activated: `is_active = True`.
   - The one-time token is permanently revoked: `pairing_token_hash = None`.
7. Replaying or reusing the pairing token returns an immediate authorization failure.

---

## 7. Authorization

- Every incoming Telegram message is resolved against `TelegramPairing` by `(integration_id, telegram_chat_id, is_active=True)`.
- The paired record determines the authoritative `workspace_id`.
- Unpaired chats are rejected with safe, non-leaking guidance to generate a token in the dashboard.
- Commands cannot supply or switch `workspace_id`.

---

## 8. Polling Worker

- Managed by `TelegramDaemon` in `apps/api/app/workers/telegram_daemon.py`.
- Integrates with FastAPI application lifespan (`startup` $\to$ `start()`, `shutdown` $\to$ `stop()`).
- Iterates over active integrations and invokes `telegram_service.poll_integration_updates`.

---

## 9. Offset Persistence

- Telegram confirmed updates are tracked via `TelegramIntegration.last_update_id`.
- After processing each update, `last_update_id` is committed to PostgreSQL/SQLite.
- On process crash and restart, polling resumes strictly from `offset = last_update_id + 1`, eliminating duplicate update reprocessing.

---

## 10. Idempotency

- Updates are deduplicated through Telegram's `update_id`.
- Task dispatch creates an idempotency key: `tg_{integration_id}_{update_id}` passed to `TaskService.create_task`.
- Redelivered updates return existing task records without generating redundant execution DAGs.

---

## 11. Command Parser

Supported canonical command set:
- `/start [pairing_token]`
- `/help`
- `/status`
- `/goal <description>`
- `/cancel <task_id>`
- `/approve <approval_id>`

---

## 12. Command Semantics

- `/start`: Completes pairing if token provided; otherwise displays status for paired users or instructions for unpaired users.
- `/help`: Lists command syntax and descriptions.
- `/status`: Summarizes active tasks, pending HITL approvals, and kill switch status in the paired workspace.
- `/goal <description>`: Creates a governed AURA Task with Autonomy Level 4, timeout 300s, token budget 4000, and structured untrusted framing.
- `/cancel <task_id>`: Cancels a task belonging strictly to the paired workspace.
- `/approve <approval_id>`: Resolves a pending HITL approval request through `ApprovalService`.

---

## 13. HITL / Approval

- Telegram commands cannot manufacture, forge, or bypass HITL approval tokens.
- `/approve <id>` verifies that the approval belongs to the paired workspace and invokes `ApprovalService.resolve_approval` which validates tool policy and executes the approved action through the single tool registry boundary.

---

## 14. Cancellation

- `/cancel <task_id>` validates workspace ownership before invoking `task_service.cancel_task`.
- Cross-workspace task cancellation attempts are rejected with `HTTP 404 / EntityNotFoundError`.

---

## 15. Outbound Messaging

- Messages are formatted cleanly with Markdown / plain-text fallbacks.
- Length is capped at **4,000 characters** to strictly conform to Telegram's 4,096 character ceiling.
- Raw stack traces, database strings, and secret credentials are scrubbed.

---

## 16. Rate Limiting

- Long polling interval: 2.0s loop cycle with 20s long-polling timeout.
- Bounded batch size: `limit = 10` updates per poll.
- Outbound sends bounded and throttled against burst limits.

---

## 17. Retry / Backoff

- Network timeouts during `getUpdates` are handled cleanly without error escalation.
- API HTTP error codes (e.g. 401 Unauthorized, 429 Too Many Requests) transition `polling_state` to `'error'` or `'backoff'` with exponential sleep intervals.

---

## 18. Kill Switch

- When `kill_switch.is_active(workspace_id)` is engaged:
  - `/goal` is suspended: returns `"⛔ Emergency Kill Switch is active..."` and creates 0 tasks.
  - `/approve` is suspended: returns `"⛔ Cannot approve: Emergency Kill Switch is active."`
  - `/status` reports `"• Emergency Kill Switch: ⛔ ACTIVE (Suspended)"`.

---

## 19. Workspace Isolation

- A Telegram pairing is bound to a single workspace.
- A user in Chat A cannot access, query, cancel, or approve tasks in Workspace B.

---

## 20. Audit Events

Recorded in the SHA-256 chained audit ledger:
- `telegram.integration_created`
- `telegram.integration_updated`
- `telegram.token_rotated`
- `telegram.integration_deleted`
- `telegram.pairing_token_generated`
- `telegram.pairing_revoked`
- `telegram.chat_paired`
- `telegram.goal_dispatched`

---

## 21. SSE Integration

- Sanitized status changes and task dispatches emit events across `EventBroadcasterHub` for the paired workspace.

---

## 22. Multi-Process Poller Ownership

- `poller_lease_id` and `poller_lease_expires_at` enforce single-worker polling per integration with a 60-second heartbeat lease.
- Competing worker processes skip polling integrations owned by an active peer lease.

---

## 23. API Management Surface

| Method | Endpoint | Description | Auth Required |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/telegram/integrations?workspace_id={id}` | Configure bot token (returns metadata) | Yes (Workspace Member) |
| `GET` | `/api/v1/telegram/integrations?workspace_id={id}` | List integrations (tokens masked) | Yes (Workspace Member) |
| `GET` | `/api/v1/telegram/integrations/{id}?workspace_id={id}` | Get integration metadata | Yes (Workspace Member) |
| `PATCH`| `/api/v1/telegram/integrations/{id}?workspace_id={id}` | Update integration | Yes (Workspace Member) |
| `POST` | `/api/v1/telegram/integrations/{id}/rotate-token?workspace_id={id}` | Rotate bot token | Yes (Workspace Member) |
| `DELETE`| `/api/v1/telegram/integrations/{id}?workspace_id={id}` | Soft-delete integration | Yes (Workspace Member) |
| `POST` | `/api/v1/telegram/integrations/{id}/pairings?workspace_id={id}` | Generate 15-minute pairing token | Yes (Workspace Member) |
| `GET` | `/api/v1/telegram/integrations/{id}/pairings?workspace_id={id}` | List active pairings | Yes (Workspace Member) |
| `DELETE`| `/api/v1/telegram/integrations/{id}/pairings/{pid}?workspace_id={id}` | Revoke pairing | Yes (Workspace Member) |

---

## 24. Test Matrix

| Test Module | Test Case | Scope / Coverage | Result | Classification |
| :--- | :--- | :--- | :--- | :--- |
| `test_telegram_db_models.py` | `test_telegram_integration_crud_and_defaults` | Integration entity, UUIDs, ciphertext | **PASS** | SQLITE / INTEGRATION |
| `test_telegram_db_models.py` | `test_telegram_pairing_uniqueness_and_indexes` | Unique `(ws, int, chat_id)` constraint | **PASS** | SQLITE / INTEGRATION |
| `test_telegram_db_models.py` | `test_telegram_cascade_deletion` | Foreign key cascade integrity | **PASS** | SQLITE / INTEGRATION |
| `test_telegram_integration.py` | `test_telegram_bot_token_validation` | `getMe` token validation & error handling | **PASS** | MOCKED HTTP / UNIT |
| `test_telegram_integration.py` | `test_telegram_pairing_flow_and_token_invalidation` | 15-min TTL, /start token binding, single-use | **PASS** | REAL FASTAPI / SQLITE |
| `test_telegram_integration.py` | `test_telegram_unauthorized_chat_rejection` | Unpaired chat rejection & safe messages | **PASS** | REAL FASTAPI / SQLITE |
| `test_telegram_integration.py` | `test_telegram_goal_command_and_governance` | `/goal` L4 bounds, untrusted framing, Task | **PASS** | REAL FASTAPI / SQLITE |
| `test_telegram_integration.py` | `test_telegram_status_command` | `/status` summary of tasks and approvals | **PASS** | REAL FASTAPI / SQLITE |
| `test_telegram_integration.py` | `test_telegram_cancel_command_workspace_isolation`| `/cancel` own task vs cross-workspace reject | **PASS** | REAL FASTAPI / SQLITE |
| `test_telegram_integration.py` | `test_telegram_approve_command_hitl_resumption` | `/approve` HITL resumption via ApprovalService | **PASS** | REAL FASTAPI / SQLITE |
| `test_telegram_integration.py` | `test_telegram_emergency_kill_switch_suspension` | Kill switch suspends `/goal` and `/approve` | **PASS** | REAL FASTAPI / SQLITE |
| `test_telegram_integration.py` | `test_telegram_long_polling_offset_advancement` | `getUpdates`, persistent offset advancement | **PASS** | MOCKED HTTP / SQLITE |
| `test_telegram_integration.py` | `test_telegram_management_api_lifecycle` | Authenticated REST API CRUD & pairing tokens | **PASS** | REAL FASTAPI / SQLITE |

---

## 25. Real Telegram Verification

- Automated test environment: **MOCKED HTTP / REAL FASTAPI / SQLITE**.
- Live Telegram API validation classification: **BLOCKED — REAL TELEGRAM API CREDENTIAL UNAVAILABLE** (No live production bot token configured in local development environment; all API contracts verified against official Telegram Bot API specs).

---

## 26. Regression Results

- **Backend Pytest Suite:**
  - **110 / 110 passing** (increased from 97 in AURA-402).
  - 0 failures, 0 errors.
- **Frontend Vitest Suite:**
  - **12 / 12 passing**.
- **Next.js Production Build:**
  - **Successful** (4/4 static pages prerendered, 0 lint/type errors).

---

## 27. Zero-Cost Verification

- **Mandatory Operating Cost:** **$0.00**.
- **Dependencies:** 0 third-party paid relays (e.g. Twilio, ngrok, Hookdeck), direct communication with Telegram Bot API.

---

## 28. Privacy Considerations

- Telegram is an external network channel; messages traverse Telegram infrastructure.
- AURA transmits only high-level task summaries, status updates, and approval prompts.
- Raw database credentials, private memories, and tool stack traces are never transmitted.

---

## 29. Known Limitations

1. **Telegram Outbound Size:** Messages longer than 4,000 characters are safely truncated.
2. **Long-Polling Poller Lease:** In multi-process deployments, poller lease ownership relies on 60-second database heartbeats.

---

## 30. Deferred Work

- **AURA-404:** Local Playwright web extractor tool.
- **Phase 4 UI:** Telegram integration configuration tab and pairing manager in the web dashboard.

---

## 31. Final Status

```text
================================================================================
AURA-403 COMPLETE — READY FOR AURA-404
================================================================================
```
