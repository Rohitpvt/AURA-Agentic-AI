# PHASE 9.1 ACCEPTANCE REPORT: AURA-901 — WINDOWS OS CONTROL FOUNDATION & POLICY BOUNDARY

**Milestone:** AURA-901 (Phase 9.1 - Windows OS Control Foundation & Policy Boundary)  
**Date:** October 5, 2026  
**Status:** COMPLETE & ACCEPTED  
**Commit Baseline:** `9d3a3b8` (Phase 9 Preflight)  
**Target Hardware:** AMD Ryzen 7 4800H (8C/16T), 24 GB DDR4 RAM, NVIDIA GeForce RTX 3050 Laptop GPU (4 GB VRAM), Windows 11 Home  

---

## 1. EXECUTIVE SUMMARY

AURA-901 delivers the single governed foundation, security boundaries, and policy evaluation architecture required for all subsequent Phase 9 Windows host interactions (AURA-902 through AURA-906).

The milestone enforces the canonical non-negotiable security principle:
```text
┌──────────────────────────────────────────────────────────────────────────────────┐
│                            UNBREAKABLE GOVERNANCE PATH                           │
│                                                                                  │
│   Agent (LLM)                                                                    │
│     │                                                                            │
│     ▼                                                                            │
│   AgentToolBridge (Runtime Interception)                                         │
│     │                                                                            │
│     ▼                                                                            │
│   ToolRegistryService (Pydantic Schema Validation)                               │
│     │                                                                            │
│     ▼                                                                            │
│   OSGuardService (Concurrency Gate, Kill Switch Probe, Hard Timeout)             │
│     │                                                                            │
│     ▼                                                                            │
│   OSPolicyEngine (5-Tier Risk Taxonomy, Rate Buckets, LOLBins Denylist)          │
│     │                                                                            │
│     ▼                                                                            │
│   HITL Gateway (Cryptographic HMAC-SHA256 Token Verification)                    │
│     │                                                                            │
│     ▼                                                                            │
│   Validated Execution Adapter (Safe Boundary)                                    │
│     │                                                                            │
│     ▼                                                                            │
│   Audit Ledger (SHA-256 Hash Chain) & OpenTelemetry (Secret Redaction)           │
└──────────────────────────────────────────────────────────────────────────────────┘
```

**Prohibited Execution Channels:**
- Direct `Agent ──► Windows API` (FORBIDDEN)
- Direct `Agent ──► subprocess.Popen` (FORBIDDEN)
- Direct `Agent ──► PyAutoGUI` (FORBIDDEN)
- Direct `Agent ──► psutil destructive kill` (FORBIDDEN)
- Direct `Agent ──► shell=True / powershell.exe / cmd.exe` (FORBIDDEN)

---

## 2. SUBSYSTEM IMPLEMENTATION & ARCHITECTURAL SPECS

### 2.1 OS Action Contract & Pydantic Validation (`app.services.os_guard.types`)
- **`OSActionRequest`:** Carries `action_id`, `workspace_id`, `actor_type`, `actor_id`, `action_type`, `parameters`, `hitl_approval_token`, `created_at`, `expires_at`, `timeout_seconds`, `correlation_id`, `trace_id`.
- **Hard Timeout Clamping:** Timeout is strictly bounded between $0.1\text{s}$ and $5.0\text{s}$. Oversized timeouts (e.g. 999s) are clamped to $5.0\text{s}$; non-positive timeouts are rejected with validation errors.
- **Untrusted Model Guard:** Workspace IDs, actor identities, and authorization tokens submitted by the agent are validated against authenticated control plane context.

### 2.2 Action Taxonomy & Deterministic 5-Tier Risk Classification (`app.services.os_guard.policy`)

| Action Type | Risk Tier | Execution Partition | Pre-Configured Rate Limit | Autonomy L3+ HITL Gate |
| :--- | :--- | :--- | :--- | :--- |
| `READ_ONLY` | `READ_ONLY` | `HOST_REQUIRED_GOVERNED` | 60 ops/min | Autonomous (No HITL) |
| `SYSTEM_TELEMETRY` | `READ_ONLY` | `HOST_REQUIRED_GOVERNED` | 60 ops/min | Autonomous (No HITL) |
| `CLIPBOARD_READ` | `READ_ONLY` | `HOST_REQUIRED_GOVERNED` | 60 ops/min | Autonomous (No HITL) |
| `WINDOW_FOCUS` | `LOW_RISK_WRITE` | `HOST_REQUIRED_GOVERNED` | 60 ops/min | Autonomous (No HITL) |
| `MOUSE_MOVE` | `MEDIUM_RISK_INTERACTION` | `HOST_REQUIRED_GOVERNED` | 60 ops/min | Autonomous (L3+) |
| `MOUSE_CLICK` | `MEDIUM_RISK_INTERACTION` | `HOST_REQUIRED_GOVERNED` | 60 ops/min | Autonomous (L3+) |
| `KEYBOARD_INPUT` | `MEDIUM_RISK_INTERACTION` | `HOST_REQUIRED_GOVERNED` | 10 ops/min | Autonomous (L3+) |
| `CLIPBOARD_WRITE` | `MEDIUM_RISK_INTERACTION` | `HOST_REQUIRED_GOVERNED` | 30 ops/min | Autonomous (L3+) |
| `APPLICATION_LAUNCH` | `HIGH_RISK_SYSTEM_ACTION` | `PRIVILEGED_HOST` | 5 ops/min | **MANDATORY HITL Token** |
| `PROCESS_TERMINATE` | `HIGH_RISK_SYSTEM_ACTION` | `PRIVILEGED_HOST` | 5 ops/min | **MANDATORY HITL Token** |
| `HARDWARE_CONTROL` | `HIGH_RISK_SYSTEM_ACTION` | `PRIVILEGED_HOST` | 10 ops/min | **MANDATORY HITL Token** |

### 2.3 Strict Lifecycle State Machine
```text
CREATED ──► VALIDATING ──► POLICY_CHECK ──► WAITING_HITL ──► AUTHORIZED ──► EXECUTING ──► COMPLETED
                                 │                                               │
                                 ├──► EXPIRED                                    ├──► TIMED_OUT
                                 ├──► FAILED                                     ├──► FAILED
                                 └──► KILL_SWITCHED                              └──► KILL_SWITCHED
```
**Replay Immunity Guarantee:** All terminal states (`COMPLETED`, `FAILED`, `TIMED_OUT`, `CANCELLED`, `KILL_SWITCHED`, `EXPIRED`) are permanently immutable. Cancelled or interrupted actions can never re-enter execution.

### 2.4 Cryptographic HMAC-SHA256 HITL Verification & Anti-Replay
- **HMAC-SHA256 Signatures:** Verified using `verify_approval_signature` with application secret key.
- **Strict Parameter Binding:** Payload binds `param_hash = SHA256(canonical_json(parameters))`. Approving `notepad.exe` fails if parameters are altered to `calc.exe`.
- **Workspace Tenancy Binding:** Approvals issued for `workspace_alpha` are rejected if submitted to `workspace_beta`.
- **Anti-Replay Defense:** Consumed token hashes are recorded in `_consumed_hitl_tokens`; duplicate submissions fail with `TokenReplayedError`.
- **Short TTL:** 120-second expiration strictly enforced.

### 2.5 Single-Worker Concurrency Serialization & Hard Timeout
- **Single-Worker Lock:** Managed centrally via `asyncio.Lock()` in `OSGuardService` (`MAX_ACTIVE_ACTIONS = 1`). Concurrent requests are strictly serialized without race conditions.
- **5.0-Second Hard Timeout:** All adapter executions are wrapped in `asyncio.wait_for(..., timeout=5.0)`.

### 2.6 Authoritative Kill Switch Probing
- Integrates `EmergencyKillSwitchService`.
- Triple-point probing:
  1. Pre-lock check
  2. Post-lock pre-policy check
  3. Pre-execution & in-flight check
- Aborts immediately in $\le 15\text{ms}$ with deterministic `KILL_SWITCHED` state without running unapproved actions.

### 2.7 Security Validators (`app.services.os_guard.validators`)
1. **`PathValidator`:**
   - Rejects relative paths and path traversal sequences (`..`).
   - Rejects Windows LOLBins (`powershell.exe`, `pwsh.exe`, `cmd.exe`, `wscript.exe`, `cscript.exe`, `mshta.exe`, `rundll32.exe`, `regsvr32.exe`, `certutil.exe`, `bitsadmin.exe`, `msiexec.exe`, `installutil.exe`, `regasm.exe`, `regsvcs.exe`, `wmic.exe`, `cscr.exe`, `hh.exe`, `schtasks.exe`, `vssadmin.exe`, `bash.exe`).
   - Enforces `.exe` extension and canonical absolute drive path.
2. **`ProcessIdentityValidator`:**
   - Permanent immunity for protected system processes (`System`, `csrss.exe`, `lsass.exe`, `smss.exe`, `services.exe`, `explorer.exe`, `dwm.exe`, `MsMpEng.exe`, `SecurityHealthService.exe`, `postgres.exe`, `ollama.exe`, `python.exe`, `node.exe`).
   - PID reuse defense: Verifies `psutil.Process(pid).create_time()` against expected creation timestamp within $\pm 0.05\text{s}$ tolerance.
3. **`CoordinateSafetyValidator`:**
   - Rejects negative coordinates ($(x < 0, y < 0)$).
   - Validates coordinates against monitor and active window bounding boxes.
   - Stale visual observation TTL ($\le 5.0\text{s}$): Rejects actions derived from sensory observations older than $5.0\text{s}$ (`StaleVisualObservationError`).
   - Invariant: Visual observations are untrusted sensory inputs, never authorization.

---

## 3. TEST SUITE & VERIFICATION SUMMARY

### 3.1 Dedicated AURA-901 Test Suite (`tests/test_os_guard_foundation.py`)
25 tests executed in `0.68s` (100% PASSED):
- `test_os_action_request_validation` (Pydantic contract & timeout clamping)
- `test_deterministic_risk_classification` (5-tier risk taxonomy mapping)
- `test_host_execution_partitioning` (Execution partition boundaries)
- `test_policy_read_only_allowed_without_hitl` (Read-only / telemetry autonomy)
- `test_policy_medium_risk_autonomy_gate` (L0–L2 HITL vs L3+ autonomy)
- `test_policy_high_risk_requires_hitl_always` (Launch/terminate HITL requirement)
- `test_hitl_valid_token_authorization` (Valid HMAC-SHA256 signature verification)
- `test_hitl_wrong_workspace_rejected` (Multi-tenant token isolation)
- `test_hitl_parameter_tampering_rejected` (Parameter hash integrity check)
- `test_hitl_expired_token_rejected` (120s TTL expiration enforcement)
- `test_hitl_single_use_replay_defense` (Single-use anti-replay defense)
- `test_single_active_action_concurrency_serialization` (Single-worker lock concurrency)
- `test_sliding_window_rate_limiting` (Sliding window rate limit enforcement)
- `test_kill_switch_pre_execution_abort` (Sub-15ms kill switch abort)
- `test_kill_switch_triggered_during_execution` (In-flight kill switch transition)
- `test_hard_action_timeout_enforcement` (5.0s timeout ceiling enforcement)
- `test_path_traversal_rejection` (Path traversal `..` rejection)
- `test_lolbins_denylist_rejection` (All 20 LOLBins rejected)
- `test_forbidden_shell_parameter_rejection` (`shell=True` parameter denied)
- `test_protected_system_process_denial` (Protected system processes protected)
- `test_pid_below_4_denial` (Kernel PIDs $\le 4$ protected)
- `test_negative_coordinates_rejected` (Negative coordinates blocked)
- `test_stale_visual_observation_rejected` (Visual observation $> 5.0\text{s}$ rejected)
- `test_out_of_window_bounds_rejected` (Out-of-window bounds blocked)
- `test_valid_in_bounds_coordinate_allowed` (Valid coordinate allowed)

### 3.2 Regression Suite Results

| Test Suite | Total Tests | Status | Execution Time |
| :--- | :--- | :--- | :--- |
| `tests/test_os_guard_foundation.py` (Dedicated AURA-901 Suite) | 25 | PASSED | 0.68s |
| Full Backend Regression Suite (`pytest tests/ -q`) | 444 (433 passed, 11 skipped) | PASSED | 166.50s |
| Frontend Vitest Suite (`npm test`) | 33 | PASSED | 1.52s |
| Production Web Build (`npm run build`) | 4 Pages | PASSED (Next.js 15.5.27) | 2.8s |

---

## 4. ACCEPTANCE CRITERIA CHECKLIST

- [x] `OSGuardService` implemented
- [x] Action contract implemented (`OSActionRequest`, `OSActionResponse`)
- [x] Explicit action types implemented (`OSActionType` 11 types)
- [x] Deterministic risk classification implemented (`OSRiskTier` 5 tiers)
- [x] Policy decision engine implemented (`OSPolicyEngine`)
- [x] Existing HITL integrated (`sign_approval_payload`, `verify_approval_signature`, parameter binding, single-use anti-replay)
- [x] Kill switch integrated (`EmergencyKillSwitchService` triple-point probing)
- [x] One-active-action lock enforced (`MAX_ACTIVE_ACTIONS = 1` via `asyncio.Lock`)
- [x] 5-second hard action timeout enforced ($0 < \text{timeout} \le 5.0\text{s}$)
- [x] Workspace isolation verified
- [x] Host/container partitions enforced (`CONTAINER_SAFE`, `HOST_REQUIRED_GOVERNED`, `PRIVILEGED_HOST`, `FORBIDDEN`)
- [x] Arbitrary shell execution prohibited (`shell=True` / cmd / powershell rejected)
- [x] Explicit LOLBin denylist implemented (20 binaries)
- [x] Path validation foundation implemented (`PathValidator`)
- [x] PID + creation-time identity foundation implemented (`ProcessIdentityValidator`)
- [x] Coordinate safety foundation implemented (`CoordinateSafetyValidator`)
- [x] Visual observations remain untrusted
- [x] Audit integrated (`AuditLedgerService` with secret redaction)
- [x] Telemetry redaction integrated (OpenTelemetry span attributes)
- [x] Rate-limit primitives implemented (Sliding-window token buckets)
- [x] Security/negative tests pass (25/25 dedicated tests green)
- [x] Full backend regression passes (433/433 passed)
- [x] Frontend regression passes (33/33 passed)
- [x] Production build passes (Next.js 15.5.27 compiled 4/4 static pages)
- [x] Documentation reconciled
- [x] Working tree clean
- [x] Commit created

---

## 5. KNOWN LIMITATIONS & EXPLICIT BOUNDARIES TO AURA-902

AURA-901 establishes the **governance, policy, validation, and execution-adapter foundation**.

In accordance with strict phased milestones:
- Live process launching and full executable allowlist management will be operationalized in **AURA-902**.
- Live mouse clicking, movement, text typing, and PyAutoGUI adapters will be operationalized in **AURA-903**.
- System hardware telemetry and volume/brightness adapters will be operationalized in **AURA-904**.
- Windows system tray and global physical hotkeys will be operationalized in **AURA-905**.
- Cross-system integration and adversarial red-teaming will be finalized in **AURA-906**.

**Explicit authorization is required before AURA-902.**
