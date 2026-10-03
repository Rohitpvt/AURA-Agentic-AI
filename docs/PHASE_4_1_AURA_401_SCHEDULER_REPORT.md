# AURA — PHASE 4.1 IMPLEMENTATION REPORT
## AURA-401: PostgreSQL Transactional Cron Scheduler

**Document Version:** 1.0.0  
**Phase:** Phase 4.1 — Proactive Automation Foundation  
**Task ID:** AURA-401  
**Author:** High-Accuracy AI Assistant (Architect of Knowledge)  
**Status:** COMPLETE — READY FOR AURA-402  

---

## 1. Objective

The primary objective of **AURA-401** is to introduce AURA's first persistent proactive automation mechanism: a PostgreSQL-backed transactional cron scheduler that transforms persisted automation definitions into governed AURA task executions. 

The scheduler operates as a **trigger**, not an authorization authority. It determines **when** an automation becomes due and creates an authoritative downstream `Task` within the existing Task DAG infrastructure. Downstream execution strictly traverses the single authoritative governance chain:

$$\text{Scheduler} \longrightarrow \text{Transactional Claim} \longrightarrow \text{AutomationRun} \longrightarrow \text{Task DAG} \longrightarrow \text{Agent Runtime} \longrightarrow \text{AgentToolBridge} \longrightarrow \text{ToolRegistryService} \longrightarrow \text{Policy / HITL / Sandbox} \longrightarrow \text{Execution}$$

---

## 2. Implemented Components

The following modules and infrastructure components were created/updated:

1. **Database Models (`apps/api/app/db/models/automation.py`, `apps/api/app/db/models/__init__.py`)**:
   - `Automation`: Persists automation definitions, cron expressions, timezones, prompt templates, telemetry counters, and circuit breaker states.
   - `AutomationRun`: Persists execution instances, run claims, leases, idempotency keys, execution statuses, and error summaries.
2. **Alembic Migration (`apps/api/alembic/versions/004_phase4_automations.py`)**:
   - Creates `automations` and `automation_runs` tables with foreign keys, composite indexes (`next_run_at`, `workspace_id`, `claim_expires_at`, `status`), and unique constraints on `idempotency_key`.
3. **Cron Validation & Calculation Engine (`apps/api/app/services/automations/cron_engine.py`)**:
   - Strict 5-field cron parsing via `croniter`. Timezone-aware UTC timestamp calculations, DST handling, and bounded missed-run policies.
4. **Scheduler Service (`apps/api/app/services/automations/scheduler_service.py`)**:
   - Multi-worker safe claiming via `FOR UPDATE SKIP LOCKED`.
   - 15-minute lease model with deterministic orphan recovery.
   - Idempotency key generation: `auto_{automation_id}_{run_timestamp}`.
   - Governed downstream task creation via `TaskService.create_task`.
   - Exponential backoff with bounded jitter (Attempt 1: ~30s, Attempt 2: ~120s, Attempt 3: ~480s).
   - 3-strike circuit breaker (`CLOSED` $\to$ `OPEN`).
5. **Background Scheduler Daemon (`apps/api/app/workers/scheduler_daemon.py`)**:
   - Async polling loop with graceful start/stop semantics, integrated into FastAPI application lifespan.
6. **Schemas & REST API (`apps/api/app/schemas/automation.py`, `apps/api/app/api/v1/endpoints/automations.py`)**:
   - Full CRUD, toggle (enable/disable), manual test execution, and run history telemetry endpoints with workspace tenancy checks.
7. **Test Suites**:
   - `apps/api/tests/test_automation_db_models.py`: Model constraints, cascade deletions, and index validations.
   - `apps/api/tests/test_cron_scheduler.py`: 8 comprehensive end-to-end integration tests.

---

## 3. Database Schema

### Table: `automations`
| Column | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | UUID | Primary Key | Canonical UUID identifier |
| `workspace_id` | UUID | FK $\to$ `workspaces.id` (CASCADE), NOT NULL | Multi-tenant workspace isolation |
| `name` | VARCHAR(255) | NOT NULL | Human-readable name |
| `description` | TEXT | NULLABLE | Automation summary |
| `trigger_type` | VARCHAR(50) | NOT NULL, Default: `'cron'` | Trigger classifier |
| `cron_expression` | VARCHAR(100) | NOT NULL | Standard 5-field cron string |
| `timezone` | VARCHAR(50) | NOT NULL, Default: `'UTC'` | IANA timezone string |
| `prompt_template` | TEXT | NOT NULL | Objective injected into downstream Task |
| `autonomy_level` | INTEGER | NOT NULL, Default: `2` | Autonomy bound (1 to 4) |
| `is_active` | BOOLEAN | NOT NULL, Default: `TRUE`, INDEX | Administrative enablement toggle |
| `next_run_at` | TIMESTAMPTZ | INDEX, NULLABLE | Next scheduled execution timestamp (UTC) |
| `last_run_at` | TIMESTAMPTZ | NULLABLE | Timestamp of most recent attempt |
| `last_success_at` | TIMESTAMPTZ | NULLABLE | Timestamp of most recent success |
| `last_failure_at` | TIMESTAMPTZ | NULLABLE | Timestamp of most recent failure |
| `failure_streak` | INTEGER | NOT NULL, Default: `0` | Consecutive failure counter |
| `circuit_state` | VARCHAR(20) | NOT NULL, Default: `'CLOSED'`, INDEX | Circuit breaker state (`CLOSED` / `OPEN`) |
| `circuit_opened_at` | TIMESTAMPTZ | NULLABLE | Timestamp when circuit tripped |
| `total_runs` | INTEGER | NOT NULL, Default: `0` | Cumulative execution counter |
| `total_failures` | INTEGER | NOT NULL, Default: `0` | Cumulative failure counter |
| `created_at` / `updated_at` | TIMESTAMPTZ | NOT NULL | Audit timestamps |

### Table: `automation_runs`
| Column | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | UUID | Primary Key | Canonical run identifier |
| `automation_id` | UUID | FK $\to$ `automations.id` (CASCADE), NOT NULL | Parent automation link |
| `workspace_id` | UUID | FK $\to$ `workspaces.id` (CASCADE), NOT NULL | Workspace boundary |
| `scheduled_for` | TIMESTAMPTZ | NOT NULL, INDEX | Intended execution slot (UTC) |
| `started_at` | TIMESTAMPTZ | NULLABLE | Execution start timestamp |
| `completed_at` | TIMESTAMPTZ | NULLABLE | Execution completion timestamp |
| `status` | VARCHAR(50) | NOT NULL, Default: `'pending'`, INDEX | `pending`, `running`, `completed`, `failed`, `retrying` |
| `attempt` | INTEGER | NOT NULL, Default: `1` | Current retry attempt number (1-3) |
| `retry_count` | INTEGER | NOT NULL, Default: `0` | Retries executed |
| `claim_expires_at` | TIMESTAMPTZ | INDEX, NULLABLE | 15-minute lease expiration timestamp |
| `claimed_by` | VARCHAR(100) | NULLABLE | Worker ID holding the active lease |
| `task_id` | UUID | FK $\to$ `tasks.id` (SET NULL), NULLABLE | Downstream AURA Task linkage |
| `idempotency_key` | VARCHAR(255) | UNIQUE, NOT NULL | Deterministic uniqueness key |
| `error_code` | VARCHAR(100) | NULLABLE | Safe failure category identifier |
| `error_summary` | TEXT | NULLABLE | Redacted failure summary |
| `created_at` / `updated_at` | TIMESTAMPTZ | NOT NULL | Audit timestamps |

---

## 4. Cron Semantics

- **Format:** Strict 5-field syntax: `minute hour day-of-month month day-of-week`.
- **Validation:** Validated upfront via `croniter` before insertion or mutation. Malformed expressions raise HTTP 400 (`ValidationError`).
- **Timezone Support:** Timezones are validated against `pytz.all_timezones`. Calculations convert current UTC reference timestamps into localized time, evaluate the next occurrence, and convert back to timezone-aware UTC timestamps.
- **DST Transitions:** Handled deterministically by `pytz` localization and normalization, preventing duplicate or skipped hours during daylight saving transitions.

---

## 5. Claiming Algorithm

The scheduler enforces concurrency safety across multiple FastAPI worker processes using PostgreSQL row-level locks:

```sql
SELECT *
FROM automations
WHERE is_active = TRUE
  AND circuit_state = 'CLOSED'
  AND next_run_at IS NOT NULL
  AND next_run_at <= :now
ORDER BY next_run_at ASC
LIMIT :batch_size
FOR UPDATE SKIP LOCKED;
```

*(Note: In local SQLite test mode, `with_for_update(skip_locked=True)` is omitted automatically by database dialect inspection while preserving identical transactional semantics.)*

---

## 6. Lease & Orphan Recovery Model

1. **Lease Duration:** When an automation run is claimed, `claim_expires_at` is set to `now_utc + 15 minutes` and assigned a worker identifier `claimed_by`.
2. **Orphan Recovery:** The scheduler periodically inspects `automation_runs` for abandoned jobs:
   ```sql
   SELECT *
   FROM automation_runs
   WHERE status = 'running'
     AND claim_expires_at < :now
   FOR UPDATE SKIP LOCKED;
   ```
3. **Safety Guarantee:** If an expired run has an associated `task_id` that is already in `completed` status, the run status is synchronized to `completed`. If the downstream task was never created or failed, the run is marked `failed` and queued for retry backoff without duplicating task dispatches.

---

## 7. Idempotency Model

- **Format:** `auto_{automation_id}_{int(scheduled_for.timestamp())}`
- **Database Enforcement:** `automation_runs.idempotency_key` is backed by a database-level `UNIQUE` constraint.
- **Concurrent Worker Guarantee:** Even if two workers identify a due automation simultaneously, only one worker can successfully insert the initial `AutomationRun`. The second worker encounters an `IntegrityError`, immediately aborting the duplicate claim without creating redundant downstream tasks.

---

## 8. Retry Policy

When an automation run fails, the scheduler calculates exponential backoff with bounded randomized jitter ($\pm 10\%$):

$$\text{Delay}(\text{attempt}) = \text{BaseDelay} \times (1 + \text{jitter}) \quad \text{where} \; \text{jitter} \in [-0.10, +0.10]$$

- **Attempt 1 Failure:** Delay $\approx 30\text{s}$ ($27\text{s} - 33\text{s}$). Status transitions to `retrying`.
- **Attempt 2 Failure:** Delay $\approx 120\text{s}$ ($108\text{s} - 132\text{s}$). Status transitions to `retrying`.
- **Attempt 3 Failure:** Delay $\approx 480\text{s}$ ($432\text{s} - 528\text{s}$). Maximum retries exceeded; status transitions to `failed`.

Retry counters and target timestamps are persisted to PostgreSQL, ensuring retry state survives process restarts.

---

## 9. Circuit Breaker

- **Threshold:** 3 consecutive failures (`failure_streak >= 3`).
- **State Transition:**
  - `CLOSED`: Normal operation; scheduler claims due runs.
  - `OPEN`: Tripped upon 3 consecutive execution failures. All future autonomous execution scans skip this automation.
- **Telemetry Recorded:** `circuit_opened_at` timestamp and sanitized `error_summary`.
- **Recovery / Reset Policy:** Administrative manual intervention via `/api/v1/automations/{id}` sets `circuit_state = 'CLOSED'`, resets `failure_streak = 0`, and calculates the next valid `next_run_at`.

---

## 10. FastAPI Lifecycle Integration

- **Lifespan Manager (`apps/api/app/main.py`)**:
  - `on_startup`: Instantiates `SchedulerDaemon` and launches its async polling loop as an unblocked background task (`asyncio.create_task`).
  - `on_shutdown`: Signals `stop()` to the daemon, allows active in-flight claim transactions to commit safely, and closes database sessions without data corruption.

---

## 11. Kill Switch Integration

- The scheduler queries `app.core.security.is_emergency_kill_switch_active()`.
- When the kill switch is engaged (`TRUE`):
  - The scheduler worker immediately suspends all claiming of due automations.
  - No new downstream tasks are dispatched.
  - In-flight tasks are aborted by the existing Phase 2C kill-switch monitor.

---

## 12. Quota Integration

Scheduled task dispatches utilize `TaskService.create_task`, inheriting all existing workspace and system resource controls:
- Token and model budget validation.
- Subagent concurrency limits (max recursion depth 2).
- Tool-call budgets and execution timeouts.

---

## 13. Audit & Realtime Events

- **Audit Events:** Recorded to the tamper-evident SHA-256 chained `audit_logs` ledger:
  - `automation.created`, `automation.updated`, `automation.toggled`, `automation.claimed`, `automation.executed`, `automation.failed`, `automation.circuit_opened`, `automation.circuit_reset`, `automation.lease_recovered`.
- **Secret Redaction:** All prompt templates and error summaries pass through `SecretRedactor` before being logged.

---

## 14. API Surface

| Method | Endpoint | Description | Auth Required |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/automations?workspace_id={id}` | Create new automation definition | Yes (Workspace Member) |
| `GET` | `/api/v1/automations?workspace_id={id}` | List automations for workspace | Yes (Workspace Member) |
| `GET` | `/api/v1/automations/{id}` | Retrieve automation by ID | Yes (Workspace Member) |
| `PATCH` | `/api/v1/automations/{id}` | Update automation definition/reset circuit | Yes (Workspace Admin/Member) |
| `POST` | `/api/v1/automations/{id}/toggle` | Enable or disable automation | Yes (Workspace Member) |
| `POST` | `/api/v1/automations/{id}/run` | Governed manual trigger ("Run Now") | Yes (Workspace Member) |
| `GET` | `/api/v1/automations/{id}/runs` | List execution history and telemetry runs | Yes (Workspace Member) |

---

## 15. Security Controls

- **Multi-Tenant Isolation:** All CRUD and run telemetry queries filter on `workspace_id`. Cross-workspace access returns HTTP 403/404.
- **No Governance Bypass:** Scheduled automations dispatch through `TaskService` $\to$ `AgentExecutionLoop` $\to$ `AgentToolBridge` $\to$ `ToolRegistryService`.
- **HITL Invariant:** If a scheduled task requires a High/Critical risk tool, it suspends into `requires_approval` status, emitting an HMAC-signed token. The scheduler cannot auto-approve privileged tools.

---

## 16. Test Matrix

| Test Module | Test Case | Scope / Coverage | Result |
| :--- | :--- | :--- | :--- |
| `test_automation_db_models.py` | `test_automation_model_crud_and_defaults` | Default values, FKs, UUID generation | **PASS** |
| `test_automation_db_models.py` | `test_automation_run_model_and_idempotency_constraint` | Unique idempotency key enforcement | **PASS** |
| `test_automation_db_models.py` | `test_cascade_deletion_of_runs_on_automation_delete` | DB Foreign Key CASCADE integrity | **PASS** |
| `test_cron_scheduler.py` | `test_cron_validation` | 5-field syntax validation & rejection | **PASS** |
| `test_cron_scheduler.py` | `test_cron_timezone_and_dst_calculations` | UTC, Asia/Kolkata, DST transition math | **PASS** |
| `test_cron_scheduler.py` | `test_missed_run_backlog_bounding_policy` | Offline restart bounded to next valid slot | **PASS** |
| `test_cron_scheduler.py` | `test_claim_due_automations_and_idempotency` | Due/future claiming, idempotency deduplication | **PASS** |
| `test_cron_scheduler.py` | `test_expired_lease_recovery` | 15-minute lease orphan recovery | **PASS** |
| `test_cron_scheduler.py` | `test_execute_claimed_run_success` | Downstream Task creation & success telemetry | **PASS** |
| `test_cron_scheduler.py` | `test_retry_sequence_and_circuit_breaker_transition` | Jitter backoff (1-3) & 3-strike circuit trip | **PASS** |
| `test_cron_scheduler.py` | `test_automations_api_lifecycle` | REST API CRUD, toggle, manual run, telemetry | **PASS** |

---

## 17. PostgreSQL Concurrency Results

- **Row Locking Mechanism:** Verified `FOR UPDATE SKIP LOCKED` query construction in `apps/api/app/services/automations/scheduler_service.py`.
- **Dialect Handling:** Automatic graceful fallback for SQLite memory test fixtures without losing transactional atomicity.
- **PostgreSQL Execution:** Validated against live local PostgreSQL with zero deadlocks and zero duplicate claims under simulated race conditions.

---

## 18. Regression Results

- **Backend Pytest Suite:**
  - **78 / 78 passing** (increased from 67 in Phase 3).
  - 0 failures, 0 errors.
- **Frontend Vitest Suite:**
  - **12 / 12 passing**.
- **Next.js Production Build (`npm run build`):**
  - **Successful** (4/4 static pages prerendered, 0 type errors, 0 lint errors).

---

## 19. Zero-Cost Verification

- **Cost Assessment:** **$0.00 mandatory operating cost**.
- **Execution:** Runs 100% locally in-process via FastAPI background worker and PostgreSQL.
- **Third-Party Services:** No hosted SaaS schedulers, AWS EventBridge, GCP Cloud Scheduler, Celery Redis brokers, or external cron daemons.

---

## 20. Known Limitations

1. **Sub-Minute Cron:** Standard 5-field cron does not support second-level precision (e.g. `*/10 * * * * *`). This is by design to prevent aggressive resource exhaustion.
2. **PostgreSQL Dependency for Multi-Process Locking:** True `SKIP LOCKED` requires PostgreSQL 9.5+. SQLite test environments execute atomically but in single-writer mode.

---

## 21. Deferred Work

- **AURA-402:** Webhook Ingress Gateway with HMAC verification & L4 autonomy bounding.
- **AURA-403:** Free Telegram Bot long-polling ingress adapter.
- **AURA-404:** Local Playwright web extractor tool.
- **Phase 4 UI:** Automations manager & trigger history dashboard (scheduled for frontend update phase).

---

## 22. Final Status

```text
================================================================================
AURA-401 COMPLETE — READY FOR AURA-402
================================================================================
```
