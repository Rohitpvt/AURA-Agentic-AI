# Event & Automation Architecture Specification (EVENT_AND_AUTOMATION.md)
## Project Name: AURA (Autonomous Universal Reactive Agent)
**Document Version:** 9.6.0  
**Phase:** Phase 9 — Governed OS & Hardware Automation (COMPLETE & ACCEPTED) | Phase 1–9 Master Validated  
**Classification:** Event-Driven Orchestration & Background Scheduling  

---

## 1. Automation System Architecture

AURA unifies scheduled, delayed, and reactive event-driven tasks into a centralized **Automation Engine** managed by the Control Plane:

```
+====================================================================================================+
|                                    EVENT & TRIGGER INGRESS                                         |
+====================================================================================================+
|  [Cron Scheduler (pg_boss / APScheduler)] | [Inbound Webhooks] | [Internal System Event Bus (Redis)]|
+-------------------------------------------+--------------------+-----------------------------------+
                                              │
                                              ▼ (Standardized Event Normalization)
+====================================================================================================+
|                                  AURA AUTOMATION DISPATCHER                                        |
+====================================================================================================+
|  ├── 1. Trigger Verification & Signature Check (HMAC-SHA256)                                       |
|  ├── 2. Rate Limit & Deduplication Check (Idempotency Key in Redis)                                |
|  ├── 3. Rule Evaluation & Automation Record Lookup in PostgreSQL                                   |
|  ├── 4. Hydrates Assigned Skill / Prompt Template with Ingress Event Data                          |
|  └── 5. Spawns Scoped Task in PostgreSQL (`autonomy_level: 3 or 4`)                                |
+----------------------------------------------------------------------------------------------------+
                                              │
                                              ▼
+====================================================================================================+
|                                    AGENT RUNTIME WORKER POOL                                       |
|  - Executes goal within pre-approved sandboxed tool permissions                                    |
|  - Emits real-time execution telemetry to PostgreSQL & Redis PubSub                                |
+====================================================================================================+
                                              │
                                              ▼
+====================================================================================================+
|                                MULTI-CHANNEL DELIVERY TARGETS                                      |
+====================================================================================================+
|  [Web Dashboard Feed] | [Telegram Bot Notification] | [Discord Channel] | [Outbound Webhook]       |
+----------------------------------------------------------------------------------------------------+
```

---

## 2. Trigger Types & Execution Models

### 2.1 Scheduled Tasks (Cron / Recurring)
* **Configuration:** Standard 5-field Cron format (e.g., `0 7 * * *` for Daily 07:00 AM).
* **Storage:** Stored in PostgreSQL `automations` table with `trigger_type: 'cron'`, `last_run_at`, and calculated `next_run_at`.
* **Execution:** Scheduler daemon scans `automations` every 60 seconds, claims due rows using PostgreSQL `FOR UPDATE SKIP LOCKED` to prevent duplicate worker pickups, and dispatches a background agent task.

### 2.2 Inbound Webhook Reactive Tasks
* **Configuration:** Generates a dedicated webhook endpoint `/api/v1/webhooks/ingress/{webhook_id}` with a unique shared HMAC secret.
* **Payload Ingestion:** The inbound JSON payload (e.g., GitHub issue opened, Stripe payment succeeded) is parsed and mapped into the automation prompt template via mustache placeholders (e.g., `{{payload.issue.title}}`).
* **Sandbox Policy:** Automatically assigned **Autonomy Level 4 (L4)** with hard-gated permissions (no external side effects without drafting an approval request).

### 2.3 One-Time Delayed Tasks
* **Configuration:** Enqueues a task for single execution at an absolute timestamp in the future (e.g., *"Remind me and summarize project status in 3 hours"*).

---

## 3. Failure Handling, Retries & Exponential Backoff

* **Retry Strategy:** Failed automation runs execute up to **3 retries** with exponential jitter backoff ($30\text{s} \rightarrow 120\text{s} \rightarrow 480\text{s}$).
* **Circuit Breaker:** If an automation fails 3 consecutive scheduled runs, the system automatically transitions `automations.is_active = FALSE`, flags `status = 'error'`, and emits an urgent notification to the Web Dashboard.
* **Timeout Ceilings:** Background automations enforce a strict 15-minute execution timeout to prevent zombie processes.

---

## 4. Multi-Channel Notification Dispatcher

When an automation completes, the generated summary or artifact is delivered to designated delivery channels:

1. **Web Dashboard:** Appears in the **Activity Feed** and **Notifications Drawer**.
2. **Telegram Bot:** Pushes formatted markdown summary via the official Telegram Bot API adapter.
3. **Discord Webhook:** Pushes rich embed card to a configured Discord channel.
4. **Outbound Webhook:** Emits an HTTP POST payload with an HMAC signature to downstream third-party systems.
