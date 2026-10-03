# AURA-507 — Emergency Kill Switch Multi-Process Abort & Recovery Operational Hardening Report

**Milestone ID:** `AURA-507`  
**Phase:** `Phase 5 — Enterprise Observability, Sandbox Hardening & Release QA`  
**Status:** `AURA-507 ACCEPTED — READY FOR AURA-508`  
**Cost Model:** `$0.00 (100% Zero-Cost Local-First)`  

---

## 1. Executive Summary & Objective

`AURA-507 — Emergency Kill Switch Multi-Process Abort & Recovery Operational Hardening` hardens the global AURA emergency kill-switch mechanism for real multi-process, multi-worker, and target-OS execution governance.

Historical milestone `AURA-503 — Emergency Kill Switch` established the foundational single-process kill switch contract. AURA-507 establishes:
1. **Cross-Process Shared Authority:** Atomic, persistent kill-state synchronization across independent OS processes and worker daemons with atomic JSON swaps and file modification tracking.
2. **Deep Target-OS Process-Tree Termination:** Windows 11 recursive process-tree termination for Python child/grandchild processes, Node.js process trees, and real Playwright/Chromium browser process trees with multi-pass sweep guarantees.
3. **Strict PID-Reuse Defense & Ownership:** Storing and comparing process creation timestamps (`create_time`) prior to termination, ensuring host processes with recycled PIDs or matching process names are never killed.
4. **Comprehensive Race Condition Immunity:** Dedicated deterministic race defenses across tool dispatch, subagent dispatch, task retries, scheduler claims, Telegram/Webhook ingress, HITL approval resolution, and rapid child creation.
5. **Multi-Cycle Recovery Stability:** Bounded `Run -> Kill -> Recover` lifecycle ensuring clean reconciliation across process registries, sandbox registries, database task states, and cryptographic audit ledgers.
6. **Strict RBAC & Endpoint Authorization:** Multi-tenant workspace isolation and role-based permissions governing `/system/kill-switch`, `/system/kill-switch/reset`, and `/system/kill-switch/status`.

### Observed Host Environment
* **Operating System:** Microsoft Windows 11 Home Single Language (Build `26300.9457` x86_64)
* **WSL Subsystem:** WSL 2 (`Kernel 6.18.40.1-microsoft-standard-WSL2`, `WSL version 3.0.1.0`)
* **Process Management:** `psutil` 7.2.2 + Windows native `taskkill /F /T` kernel fallback
* **Node Runtime:** Node.js v24.13.0
* **Headless Browser:** Playwright Chromium (`chrome-headless-shell.exe`)
* **Docker Engine:** Docker Desktop 4.93.0 (`runc` container runtime, `cgroups v2`)

---

## 2. Gap Analysis: Historical AURA-503 vs Hardened AURA-507

| Area | Existing AURA-503 Behavior | Remaining AURA-507 Gap | Required Hardening Implemented |
|---|---|---|---|
| **Cross-Process Authority** | In-memory `_is_active` flag inside a single Python process | Separate worker/daemon OS processes could not observe kill state | Implemented atomic, persistent state file synchronization (`~/.aura/kill_state.json`) with sub-millisecond mtime cache |
| **Process Tree Scope** | Basic asyncio task cancellation + single container kill | Nested child/grandchild OS processes and browser processes left dangling | Implemented `ManagedProcessRegistry` with recursive `terminate_process_tree` and multi-pass sweeps |
| **PID Reuse Safety** | Process termination relied on raw PID integers | Stale PIDs or OS PID reuse could inadvertently kill unrelated user processes | Verified process creation timestamps (`create_time`) against registered metadata before issuing terminate |
| **Browser / Chromium** | Web extraction relied on per-request timeouts | Headless Chromium processes remained active if kill occurred mid-extraction | Registered Playwright driver and integrated Chromium process-tree reaping directly into canonical kill sequence |
| **Node.js Processes** | Not explicitly managed in process registry | MCP Node subprocesses could survive termination | Registered MCP client subprocesses and verified deep Node.js tree termination |
| **Race Conditions** | Kill state checked loosely in runtime loops | Tasks, tool calls, retries, HITL approvals, or scheduler runs starting concurrently with kill could execute | Added atomic pre-execution checks in `ToolRegistryService`, `SubAgentWorkerPool`, `SchedulerService`, `ApprovalService`, `TelegramService`, `WebhookService` |
| **Recovery State Machine** | Kill state was reset by manual variable reset | No formalized recovery API, audit record, or registry reconciliation | Implemented `reset_emergency_state()` with audit ledger logging (`EMERGENCY_KILL_SWITCH_RECOVERED`) and OTel tracing |
| **Telemetry Failure** | No OTel span or failure isolation | Telemetry exceptions could disrupt emergency shutdown | Fail-safe try/except blocks ensuring kill switch succeeds even if exporter fails |
| **Endpoint RBAC** | Unrestricted system endpoints | Any authenticated user could trigger global reset | Enforced workspace tenancy checks and role restrictions (`owner`/`admin` required for reset) |

---

## 3. Cross-Process & Subsystem Coordination Architecture

```
[Operator / API / CLI / Webhook / Telegram Trigger]
                       │
                       ▼
    [EmergencyKillSwitchService.trigger_emergency_kill()]
                       │
       ┌───────────────┴───────────────┐
       ▼                               ▼
[Atomic Shared Disk State]    [Canonical Subsystem Abort Sequence]
(~/.aura/kill_state.json)              │
       │                               ├── 1. SubAgent Worker Cancellation (cancel_task_workers)
       │ (Cross-Process Sync)          ├── 2. Docker Sandbox Termination (terminate_all_sandboxes)
       ▼                               ├── 3. Managed Process Tree Reaping (terminate_all_processes)
[Independent OS Processes]             ├── 4. Playwright Chromium Cleanup (browser_manager.close)
├── FastAPI Web Worker                 ├── 5. MCP Server Subprocesses Stop (mcp_manager.stop_all)
├── Scheduler Background Daemon        ├── 6. DB Task State Cancellation (status='cancelled')
├── Subagent Worker Pool               ├── 7. Cryptographic SHA-256 Audit Log Entry
└── Local Tool Invocation              └── 8. OpenTelemetry Span (Fail-Safe)
```

### Shared Authority Matrix Across Independent OS Processes

| Component | Process A (Worker / Subprocess) | Process B (API / CLI / Ingress) | Shared Authority Mechanism |
|---|---|---|---|
| **Kill State** | Polls `kill_switch.is_active(ws_id)` | Calls `kill_switch.trigger_emergency_kill` | Atomic persistent file `kill_state.json` via `.tmp` rename + mtime sync |
| **Process Registry** | Registers child PIDs with `create_time` | Discovers & terminates managed process trees | `ManagedProcessRegistry` with OS PID validation + `taskkill /F /T` |
| **Sandbox State** | Spawns sandboxed container executions | Calls `terminate_all_sandboxes()` | Docker Engine daemon API + container labels (`aura_sandbox=true`) |
| **Task State** | Queries task status before execution/retry | Transitions active tasks to `cancelled` | PostgreSQL / SQLite `tasks`, `task_steps`, `agent_runs` tables |

---

## 4. Exact Test Inventory

### A. Deterministic Local/Offline Suite (`apps/api/tests/test_kill_switch_hardening.py`) — 12 Tests

| Test Name | Classification | Purpose | Mocked / Real | Result |
|---|---|---|---|---|
| `test_kill_switch_state_transitions` | Deterministic local | Verify global vs tenant-scoped kill state transitions | In-memory + State file | **PASS** |
| `test_kill_switch_concurrent_idempotency` | Deterministic local | Verify 5 concurrent kill triggers execute idempotently | Real async DB session | **PASS** |
| `test_kill_switch_db_state_cancellation` | Deterministic local | Verify active tasks, steps, and agent runs transition to `cancelled` | Real async DB session | **PASS** |
| `test_kill_race_against_tool_dispatch` | Deterministic local | Verify tool execution is blocked at registry boundary when kill is active | Real tool registry | **PASS** |
| `test_kill_race_against_subagent_dispatch` | Deterministic local | Verify subagent pool rejects worker dispatch when kill is active | Real worker pool | **PASS** |
| `test_kill_race_against_task_retry` | Deterministic local | Verify task retry loop suppresses execution during active emergency | Real async DB session | **PASS** |
| `test_kill_race_against_scheduler_claim` | Deterministic local | Verify scheduler claim cycle suppresses claiming when kill is active | Real scheduler service | **PASS** |
| `test_kill_race_against_external_ingress` | Deterministic local | Verify Telegram `/goal` and Webhook ingress reject new tasks during kill | Real service handlers | **PASS** |
| `test_kill_race_against_hitl_approval` | Deterministic local | Verify pending HITL approval resolution cannot execute tool during kill | Real approval service | **PASS** |
| `test_repeated_kill_recovery_cycles` | Deterministic local | Bounded 3-cycle Run $\rightarrow$ Kill $\rightarrow$ Recover stability test | Real registries & DB | **PASS** |
| `test_kill_switch_telemetry_isolation` | Deterministic local | Verify kill switch succeeds when OpenTelemetry exporter raises error | Mocked OTel failure | **PASS** |
| `test_kill_switch_api_endpoint_authorization_matrix` | Deterministic local | Verify unauthenticated (401), unauthorized member (403), authorized owner (200), and reset RBAC | Real FastAPI AsyncClient | **PASS** |

### B. Target-OS Process Integration Suite (`apps/api/tests/test_kill_switch_process_integration.py`) — 10 Tests

| Test Name | Classification | Purpose | Mocked / Real | Result |
|---|---|---|---|---|
| `test_cross_process_kill_state_coordination` | Real target-OS multi-process | Real independent Python OS worker detects kill switch from parent | **Real separate OS subprocesses** | **PASS** |
| `test_real_target_os_process_tree_termination` | Real target-OS process integration | Spawn real Python Parent $\rightarrow$ Child $\rightarrow$ Grandchild tree and kill | **Real Windows process tree** | **PASS** |
| `test_real_target_os_chromium_process_tree_termination` | Real target-OS process integration | Launch real Playwright Chromium browser and verify process-tree termination | **Real Playwright Chromium** | **PASS** |
| `test_real_target_os_node_process_tree_termination` | Real target-OS process integration | Spawn real Node.js Parent $\rightarrow$ Child tree and verify recursive termination | **Real Node.js processes** | **PASS** |
| `test_pid_reuse_protection` | Real target-OS process integration | Refuse to kill process if creation timestamp (`create_time`) differs | **Real Windows OS process** | **PASS** |
| `test_process_already_exited_graceful_handling` | Real target-OS process integration | Verify terminating already-exited PID handles NoSuchProcess gracefully | **Real Windows OS process** | **PASS** |
| `test_kill_race_against_child_creation` | Real target-OS process integration | Process rapidly spawning children in a loop terminated by multi-pass sweep | **Real Windows process tree** | **PASS** |
| `test_real_api_kill_switch_lifecycle_with_managed_process` | Real AURA runtime integration | End-to-end HTTP invocation of `POST /system/kill-switch` with real managed process | **Real HTTP API + OS process** | **PASS** |
| `test_multi_process_and_sandbox_coordinated_kill` | Real target-OS process integration | Coordinated termination of host OS subprocess and Docker sandbox container | **Real OS process + Sandbox** | **PASS** |
| `test_kill_switch_operational_latency_benchmark` | Real target-OS process integration | Measure real operational kill latency across multiple samples (n=5) | **Real OS process + DB** | **PASS** |

---

## 5. Measured Operational Kill Latency

* **Benchmark Methodology:** 5 consecutive emergency kill switch executions against real active OS subprocesses, DB task updates, SHA-256 cryptographic audit ledger writes, and OpenTelemetry spans.
* **Evaluation Note:** AURA-503 historical baseline established the original single-process contract. AURA-507 benchmarks multi-process, multi-subsystem abort latency. No arbitrary hard pass/fail threshold is invented; metrics are recorded as observed.

| Sample Iteration | Total Latency (ms) | Notes |
|---|---|---|
| Sample 1 (Warmup) | `112.67 ms` | Initial DB connection pool & module initialization |
| Sample 2 (Steady State) | `39.66 ms` | Multi-subsystem abort + DB flush + SHA-256 audit write |
| Sample 3 (Steady State) | `41.22 ms` | Multi-subsystem abort + DB flush + SHA-256 audit write |
| Sample 4 (Steady State) | `38.67 ms` | Multi-subsystem abort + DB flush + SHA-256 audit write |
| Sample 5 (Steady State) | `40.94 ms` | Multi-subsystem abort + DB flush + SHA-256 audit write |

### Summary Statistics (Sample Size $n = 5$):
* **Minimum Latency:** `38.67 ms`
* **Median Latency:** `40.94 ms`
* **Maximum Latency:** `112.67 ms`
* **95th Percentile (p95):** `112.67 ms`

---

## 6. Process Ownership & Unrelated Host Process Protection

The implementation guarantees that unrelated host processes on Windows 11 are never terminated:
1. **Explicit Registration Only:** `ManagedProcessRegistry` only operates on processes explicitly registered by AURA via `register_process()`. It **never** uses generic process-name matching (such as "kill all `python.exe`" or "kill all `node.exe`").
2. **PID Reuse Protection:** Before sending any termination signal, `ManagedProcessRegistry` inspects `psutil.Process(pid).create_time()`. If the actual creation timestamp differs from the registered timestamp by $\ge 0.5\text{s}$, termination is immediately aborted with status `pid_reuse_aborted`.
3. **Multi-Pass Sweeps:** 2-pass recursive child enumeration ensures children spawned during the termination window are caught without unbounded loops.

---

## 7. Master Test Accounting & Regression Results

* **AURA-507 Dedicated Hardening Tests (`test_kill_switch_hardening.py`):** `12/12 PASSED`
* **AURA-507 Target-OS Process Integration Tests (`test_kill_switch_process_integration.py`):** `10/10 PASSED`
* **Complete Backend Pytest Suite:** `181/181 PASSED` (0 failed, 0 skipped, 0 blocked)
* **Frontend Vitest Suite:** `12/12 PASSED` (12/12 passed)
* **Next.js Production Build:** `Compiled successfully` (4/4 static pages generated, 0 type/lint errors)

---

## 8. Final Acceptance Matrix

| Control | Required Evidence | Status |
|---|---|---|
| **Global kill activation** | Deterministic state machine + live API invocation (`test_real_api_kill_switch_lifecycle_with_managed_process`) | **PASS** |
| **Async task cancellation** | Task, TaskStep, and AgentRun database cancellation test (`test_kill_switch_db_state_cancellation`) | **PASS** |
| **Windows process-tree termination** | Real Target-OS Python Parent $\rightarrow$ Child $\rightarrow$ Grandchild kill test (`test_real_target_os_process_tree_termination`) | **PASS** |
| **Python child/grandchild cleanup** | Recursive `psutil` process tree traversal with `taskkill` fallback (`test_real_target_os_process_tree_termination`) | **PASS** |
| **Node/Chromium cleanup** | Real Playwright Chromium and Node.js process-tree termination tests (`test_real_target_os_chromium_process_tree_termination`, `test_real_target_os_node_process_tree_termination`) | **PASS** |
| **Docker coordination** | Coordinated Docker sandbox + host process termination (`test_multi_process_and_sandbox_coordinated_kill`) | **PASS** |
| **Race safety** | Explicit race tests for tool dispatch, subagents, retries, scheduler, external ingress, HITL approvals, and child creation | **PASS** |
| **Idempotency** | Concurrent 5-way kill trigger test (`test_kill_switch_concurrent_idempotency`) | **PASS** |
| **Cross-process idempotency/authority** | Real separate Python OS worker synchronization test (`test_cross_process_kill_state_coordination`) | **PASS** |
| **Process identity/ownership** | PID + `create_time` registration and mismatch defense (`test_pid_reuse_protection`) | **PASS** |
| **Unrelated-process protection** | Verified PID reuse protection test (`test_pid_reuse_protection`) | **PASS** |
| **Scheduler gating** | Claiming and background daemon polling suspension (`test_kill_race_against_scheduler_claim`) | **PASS** |
| **Telegram gating** | `/goal` and `/approve` rejection with user feedback (`test_kill_race_against_external_ingress`) | **PASS** |
| **Webhook gating** | Inbound payload rejection with 503 status code (`test_kill_race_against_external_ingress`) | **PASS** |
| **Subagent cancellation** | Worker dispatch rejection and active task worker cancellation (`test_kill_race_against_subagent_dispatch`) | **PASS** |
| **Audit integrity** | Tamper-evident SHA-256 audit ledger records for trigger and recovery (`test_kill_switch_db_state_cancellation`, `test_repeated_kill_recovery_cycles`) | **PASS** |
| **Telemetry independence** | Fail-safe try/except handling during OTel exporter outage (`test_kill_switch_telemetry_isolation`) | **PASS** |
| **Recovery** | Explicit `reset_emergency_state` API and audit verification (`test_repeated_kill_recovery_cycles`) | **PASS** |
| **Repeated kill/recovery stability** | Bounded 3-cycle Run $\rightarrow$ Kill $\rightarrow$ Recover stability test (`test_repeated_kill_recovery_cycles`) | **PASS** |
| **Kill latency** | Measured 5-sample benchmark (Median: `40.94 ms`, Min: `38.67 ms`) | **MEASURED — n=5** |
| **Kill/reset endpoint authorization** | RBAC matrix test verifying 401 unauth, 403 non-admin reset, 200 owner reset (`test_kill_switch_api_endpoint_authorization_matrix`) | **PASS** |
| **Full regression** | 181/181 backend + 12/12 frontend + Next.js production build | **PASS** |

---

## 9. Final Milestone State

**`AURA-507 ACCEPTED — READY FOR AURA-508`**
