# Autonomy Model Specification (AUTONOMY_MODEL.md)
## Project Name: AURA (Autonomous Universal Reactive Agent)
**Document Version:** 1.0.0  
**Phase:** Phase 0 — Architecture & Foundation  
**Classification:** Autonomy & Safety Governance  

---

## 1. Six-Tier Autonomy Classification (L0 – L5)

AURA implements a granular, policy-driven autonomy model. Every task, session, and automation is bound to an explicit Autonomy Level:

```
+====================================================================================================+
|                                    AURA AUTONOMY TAXONOMY                                          |
+====================================================================================================+
| LEVEL | DESIGNATION              | EXECUTION CAPABILITY               | HUMAN INTERVENTION LEVEL    |
+-------+--------------------------+------------------------------------+-----------------------------+
| L0    | Interactive Chat Only    | Pure text generation; NO tools.    | Direct turn-by-turn chat.   |
+-------+--------------------------+------------------------------------+-----------------------------+
| L1    | Single-Turn Assistive    | Single tool call per turn.         | User confirms tool params.  |
+-------+--------------------------+------------------------------------+-----------------------------+
| L2    | Supervised Multi-Step    | Multi-step DAG; auto Low/Med tools.| Pauses only for High/Crit.  |
+-------+--------------------------+------------------------------------+-----------------------------+
| L3    | Scheduled Batch Auto     | Background Cron execution.         | Unattended within budget.   |
+-------+--------------------------+------------------------------------+-----------------------------+
| L4    | Proactive Event-Driven   | Inbound Webhook / Reactive triggers| Unattended in sandbox.      |
+-------+--------------------------+------------------------------------+-----------------------------+
| L5    | Controlled Meta-Evolution| Evaluates & proposes skill updates | Admin approves promotions.  |
+====================================================================================================+
```

---

## 2. Granular Specification by Autonomy Level

### 2.1 Level 0 (L0): Interactive Chat Only
* **Scope:** Conversational Q&A, brainstorming, code explanation, text rewriting.
* **Tool Permissions:** ZERO tool execution allowed.
* **Trigger:** Default web chat with tools toggled off.
* **Safety Boundary:** Standard LLM prompt safety filters.

### 2.2 Level 1 (L1): Single-Turn Assistive
* **Scope:** Focused single-action requests (e.g., *"Search the web for latest AI news"* or *"Read file X"*).
* **Tool Permissions:** Single tool call allowed per turn.
* **Policy:** Low-risk tools execute immediately. Medium/High-risk tools prompt the user for confirmation before firing.
* **Context Bounds:** Turn history only.

### 2.3 Level 2 (L2): Supervised Multi-Step Execution (Interactive Default)
* **Scope:** Goal-driven multi-step task execution (e.g., *"Audit this repository, fix formatting errors, and generate a markdown summary"*).
* **Planning:** Supervisor agent generates a full multi-step DAG plan.
* **Tool Permissions:**
  * Low-risk tools (read-only): Auto-executed.
  * Medium-risk tools (workspace writes): Auto-executed with real-time UI notification.
  * High-risk tools (external side effects / deletions): Execution is suspended; generates a signed Approval Request in PostgreSQL; resumes only after user approves.
* **Budget Limits:** Default max 100,000 tokens / $2.00 cost / 30-minute timeout.

### 2.4 Level 3 (L3): Scheduled Batch Automation
* **Scope:** Recurring or delayed workflows (e.g., Daily 07:00 AM briefing, weekly code dependency scan).
* **Execution Boundary:** Fully unattended background execution via `pg_boss` / background scheduler.
* **Tool Permissions:** Pre-scoped to specific whitelisted tools defined in the Automation configuration.
* **Safety Invariant:** High-risk actions (e.g., sending emails to external recipients) *cannot* auto-execute. They draft a pending item and notify the user's dashboard for later review.
* **Failure Handling:** Exponential backoff with max 3 retries. If the third retry fails, the automation pauses and emits a high-priority alert.

### 2.5 Level 4 (L4): Proactive Event-Driven Execution
* **Scope:** Reactive workflows triggered by external webhooks (e.g., GitHub PR opened, Prometheus server alert, Sentry exception).
* **Execution Boundary:** Sandboxed container environment with strict rate limits (max 10 triggered runs per hour per webhook source).
* **Policy:** Read-only ingestion and diagnostic analysis. Remediation actions (e.g., creating hotfix PR or restarting a service) draft a proposal requiring human confirmation.

### 2.6 Level 5 (L5): Controlled Meta-Evolution
* **Scope:** Autonomous analysis of system execution logs, failure traces, and prompt efficiencies to generate improved skill versions (`SKILL.md`).
* **Governance Gate:** Proposed changes are written to draft status (`is_published: FALSE`). They *never* go live automatically. A human system administrator must review the diff in the Web Dashboard and explicitly click "Promote to Production".

---

## 3. Global Guardrails, Circuit Breakers & Kill Switch

1. **Deterministic Budget Hard Ceiling:** Every task carries a hard token and cost ceiling. If accumulated usage reaches 100% of the ceiling, execution aborts immediately with status `FAILED_BUDGET_EXCEEDED`.
2. **Loop & Recursion Circuit Breaker:** If the agent runtime attempts to call the exact same tool with the identical parameters 3 times consecutively without state change, the runtime triggers a loop breaker, halts the step, and requests replanning.
3. **Emergency Global Kill Switch:** An administrative API endpoint (`POST /api/v1/system/kill-switch`) and physical UI button capable of:
   * Terminating all active worker processes within <500ms.
   * Cancelling all `PENDING` and `EXECUTING` tasks in PostgreSQL.
   * Revoking all active ephemeral tool approval tokens.
   * Pausing all scheduled automations until manual administrative reset.
