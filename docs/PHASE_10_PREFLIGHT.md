# AURA PHASE 10 — PREFLIGHT ARCHITECTURAL REPORT
## Advanced Browser Automation & Windows Background Runtime

**Document ID:** `AURA-REP-PHASE10-PREFLIGHT-001`  
**Date:** October 6, 2026  
**Auditor / Architect:** High-Accuracy AI Assistant (Architect of Knowledge / Scientific Validation Engine)  
**Target System:** AURA Local-First Autonomous AI Operating Assistant  
**Baseline Commit:** `09af1cf` (Phase 1–9 Fully Verified & Frozen)  
**Phase 10 Implementation Status:** `PREFLIGHT ARCHITECTED — IMPLEMENTATION GATED`

---

## 1. Current Phase 1–9 Validated Baseline

Phase 1 through Phase 9 have completed exhaustive, independent, zero-skip verification across all system vectors:

* **Backend Test Suite (Pytest):** **632 passed, 0 skipped, 0 failed** (100% zero-skip execution).
* **Master Audit Suite:** **63 passed, 0 skipped, 0 failed** (`tests/master_audit/`).
* **Live Windows 11 Host Validation:** **16 / 16 Pillars passed** (`tests/master_audit/live_validation_phase01_to_phase09.py`).
* **Live Docker / WSL2 Container Acceptance:** **11 / 11 passed live** on Docker Desktop v29.8.1 (`tests/test_docker_sandbox_live_acceptance.py`).
* **Frontend Test Suite (Vitest):** **33 passed, 0 skipped, 0 failed** (`apps/web`).
* **Frontend Production Build (Next.js):** `Next.js 15.5.27` static & app bundle optimization succeeded.
* **Security Findings:** **0 Critical, 0 High, 0 Medium, 0 Low.**
* **Architectural Invariant:** Phase 10 builds strictly on top of this frozen baseline without altering existing Phase 1–9 behavior or security guarantees.

---

## 2. Current-State Inventory & Gap Analysis

```
+─────────────────────────────────────────────────────────────────────────────────────────────+
|                                    CURRENT REPOSITORY STATE                                 |
+─────────────────────────────────────────────────────────────────────────────────────────────+
| [Already Implemented]                                                                       |
|   - Playwright headless Chromium lifecycle (browser_manager.py)                             |
|   - Multi-layer SSRF filter & redirect validation (ssrf_guard.py)                           |
|   - Read-only DOM / Markdown extraction (web_extract.py)                                    |
|   - Prompt injection sanitization & XML envelope framing (prompt_sanitizer.py)              |
|   - Sub-15ms Emergency Kill Switch (kill_switch.py)                                         |
|   - Managed process registry (process.py)                                                   |
|   - Windows System Tray & Physical Win32 Hotkey (tray_icon.py, AURA-905)                    |
|   - Task Checkpointing & Startup Recovery Sweep (task_recovery.py, AURA-706)                |
|   - Universal File Registry & Ingestion Pipeline (Phase 6, AURA-601 to 604)                 |
|   - Continuous Screen Capture & RapidOCR Engine (Phase 8, AURA-801/802)                      |
|                                                                                             |
| [Partially Implemented]                                                                     |
|   - Web extraction (limited to static read-only text/markdown parsing)                      |
|   - BrowserManager (ephemeral context only, no persistent tabs or cookie stores)            |
|   - Tray controller (has sensing/idle states, lacks browser/daemon sub-states)              |
|                                                                                             |
| [Missing - To Be Implemented in Phase 10]                                                   |
|   - Interactive browser tools (click, type, select, scroll, press_key, state, tab_manage)   |
|   - Accessibility Tree (AXTree) snapshot engine with numeric element IDs                    |
|   - Dual-representation state (AXTree + visual bounding box correlation)                   |
|   - Encrypted browser cookie/session vault in PostgreSQL (AES-256-GCM)                      |
|   - Governed browser download manager integrated with Phase 6 file intake                   |
|   - Windows user-session background daemon supervisor (AuraDaemonSupervisor)                |
|   - Workstation session lock/unlock detection (WM_WTSSESSION_CHANGE)                        |
|   - Explicit, user-controlled, reversible autostart manager (OFF by default)                |
+─────────────────────────────────────────────────────────────────────────────────────────────+
```

### 2.1 Unsafe If Reused Directly (Avoided)
1. **Raw `page.evaluate()` / Javascript Execution:** Allowing the LLM to pass arbitrary Javascript strings into browser contexts would create an instant remote code execution (RCE) / XSS bridge.
2. **Direct Browser Downloads to Host:** Unrestricted browser downloads could write malicious binaries directly to disk without Phase 6 path traversal and malware screening.
3. **Windows `SYSTEM` Service:** Running the background daemon as Windows `NT AUTHORITY\SYSTEM` (Session 0) breaks desktop interaction, camera/mic capture, display capture, tray icons, and user-scoped cryptographic keys.
4. **Cloud Browser Services:** Commercial hosted browser APIs (Browserbase, Browserless) violate the $0.00 zero-cost floor and introduce external data leakage.

---

## 3. Pillar A — Advanced Browser Automation Architecture

### 3.1 Dual-Representation Page State Engine
To achieve reliable web interaction without relying exclusively on brittle CSS selectors or heavy VLM screenshots:
1. **Semantic Accessibility Tree (AXTree):** Playwright extracts the Chromium accessibility snapshot, assigning sequential numeric IDs (`[1]`, `[2]`, `[3]`) to actionable nodes (`button`, `link`, `textbox`, `combobox`, `checkbox`).
2. **Spatial Bounding Box Mapping:** Each node is mapped to its viewport bounding box `(x, y, width, height)`.
3. **Multimodal State Output:** The model receives a compact, structured representation:
```xml
<untrusted_web_content source="https://example.com/login" title="Login Portal" timestamp="2026-10-06T15:00:00Z">
[1] link "Home" (x: 50, y: 20)
[2] textbox "Username or Email" (x: 120, y: 150, value: "")
[3] textbox "Password" [TYPE=PASSWORD] (x: 120, y: 200, value: "")
[4] button "Sign In" (x: 120, y: 260)
[5] checkbox "Remember Me" (x: 120, y: 310, checked: false)
</untrusted_web_content>
```

### 3.2 Canonical Browser Governed Tools (8 Tools)
All browser operations route through `AgentToolBridge` and `ToolRegistryService`:

| Tool Name | Risk Tier | Approval | Description & Invariants |
| :--- | :---: | :---: | :--- |
| `browser_navigate` | `READ` | Auto | Navigates to a validated URL. Subject to 3-layer SSRF filter, 25s timeout, max 10 redirects. |
| `browser_get_page_state`| `READ` | Auto | Extracts AXTree snapshot, active tab metadata, scroll offsets, and viewport dimensions. |
| `browser_screenshot` | `READ` | Auto | Captures viewport image, downsamples to max 1280x800, returns temporary visual context. |
| `browser_scroll` | `LOW` | Auto | Scrolls viewport or specific container by pixel delta or page ratio. Rate-limited. |
| `browser_tab_manage` | `LOW` | Auto | Creates (`new`), switches (`switch`), or closes (`close`) tabs. Enforces max 4 tabs. |
| `browser_click` | `MEDIUM` / `HIGH` | HITL (if submit) | Clicks element by numeric ID. Auto-approved for navigational links; **HITL required** for submit/checkout/delete buttons. |
| `browser_type` | `MEDIUM` / `HIGH` | HITL (if secret) | Types text into input field. Auto-approved for search boxes; **HITL required** for credential submission. |
| `browser_select` | `LOW` | Auto | Selects options from dropdown (`<select>`) elements by value or index. |

---

## 4. Pillar B — Windows Background Runtime Architecture

```
+─────────────────────────────────────────────────────────────────────────────────────────────+
|                         WINDOWS USER SESSION (Interactive Session 1+)                       |
|                                                                                             |
|   +─────────────────────────────────────────────────────────────────────────────────────+   |
|   |                   AuraDaemonSupervisor (Python / Win32 Subprocess)                  |   |
|   |   - Operating Context: Standard User (Least Privilege, Non-SYSTEM)                  |   |
|   |   - Watchdog Loop: 5s Health Heartbeat over Local Named Pipe / Loopback             |   |
|   |   - Crash Recovery: Exponential Backoff (1s, 2s, 4s ... max 30s)                   |   |
|   |   - State Reconciliation: Invokes StartupRecoverySweep on Restart                   |   |
|   +──────────────────────────┬───────────────────────────────────────┬──────────────────+   |
|                              │ Spawns & Supervises                   │ Spawns & Supervises  |
|                              v                                       v                      |
|   +──────────────────────────────────────────────────+   +──────────────────────────────+   |
|   |         FastAPI Control Plane (Uvicorn)          |   |  AURA-905 System Tray & GUI  |   |
|   |   - Task DAG Scheduler & Cron Queues             |   |   - Win32 Hotkey (Ctrl+Alt+  |   |
|   |   - Tool Governance & OSPolicyEngine             |   |     Shift+K)                 |   |
|   |   - PostgreSQL State & FastEmbed Vector Memory   |   |   - Shell_NotifyIcon Dynamic |   |
|   |   - Playwright Browser Session Pool              |   |     Tray Indicator           |   |
|   +──────────────────────────────────────────────────+   +──────────────────────────────+   |
|                              │                                       │                      |
|                              +───────────────────┬───────────────────+                      |
|                                                  │                                          |
|                                                  v                                          |
|   +─────────────────────────────────────────────────────────────────────────────────────+   |
|   |                       Win32 Session Change Listener (WTSRegisterSessionNotification)|   |
|   |   - WTS_SESSION_LOCK   ──► Immediately suspends camera/mic sensing & desktop control|   |
|   |   - WTS_SESSION_UNLOCK ──► Resumes listening upon authenticated user return         |   |
|   +─────────────────────────────────────────────────────────────────────────────────────+   |
+─────────────────────────────────────────────────────────────────────────────────────────────+
```

### 4.1 Process Topology & Least-Privilege Invariant
* **User-Session Scope:** The daemon runs strictly within the logged-in user's desktop session (`Session 1+`), inheriting standard user permissions.
* **Non-SYSTEM Guarantee:** It never runs under `NT AUTHORITY\SYSTEM` or requires administrative elevation during normal operation.
* **IPC Transport:** Utilizes the existing authenticated Windows Named Pipe transport (`\\.\pipe\aura_control_pipe_<SESSION_ID>`) with 256-bit token verification (`~/.aura/.auth_token`).

---

## 5. Risk Taxonomy & Human-in-the-Loop (HITL) Governance

```
+─────────────────────────────────────────────────────────────────────────────────────────────+
|                                    AURA RISK TAXONOMY                                       |
+─────────────────────────────────────────────────────────────────────────────────────────────+
| TIER 1: READ_ONLY (Auto-Approved)                                                           |
|   - browser_navigate (GET requests to public domains)                                       |
|   - browser_get_page_state, browser_screenshot                                              |
|                                                                                             |
| TIER 2: LOW_RISK_INTERACTION (Auto-Approved with Audit Log)                                 |
|   - browser_scroll, browser_select, browser_tab_manage (new/switch/close)                   |
|                                                                                             |
| TIER 3: MEDIUM_RISK_INTERACTION (Logged & Rate-Limited)                                     |
|   - browser_click (non-submitting elements, search filters, pagination)                     |
|   - browser_type (public search boxes, query filters)                                       |
|                                                                                             |
| TIER 4: HIGH_RISK_SYSTEM_ACTION (Mandatory HMAC-SHA256 Signed HITL Approval Token)         |
|   - browser_click on form submit buttons (<button type="submit">, "Place Order", "Delete")  |
|   - browser_type on sensitive input fields (passwords, payment fields, personal data)       |
|   - browser_upload_file, browser_download_file                                              |
|                                                                                             |
| TIER 5: CRITICAL_ACTION (Double-Confirmation HITL + Re-Authentication)                      |
|   - Financial checkout confirmation, fund transfers, banking operations                     |
|   - Account password reset, 2FA credential reconfiguration, security settings alterations   |
+─────────────────────────────────────────────────────────────────────────────────────────────+
```

* **Deterministic Assignment:** The LLM cannot set or modify the risk tier. The `OSPolicyEngine` inspects element attributes (`type="submit"`, `aria-label`, `role`, text content) deterministically.

---

## 6. Security Threat Model & Mitigations (25 Vectors)

| # | Threat Vector | Target Component | Likelihood | Impact | Severity | Mitigation & Architectural Defense |
| :-: | :--- | :--- | :---: | :---: | :---: | :--- |
| 1 | **Indirect Prompt Injection in Web Page** | AXTree / DOM Extractor | High | High | **CRITICAL** | All web text wrapped in `<untrusted_web_content>` envelopes; delimiter breakout neutralization; regex signature screening. |
| 2 | **Hidden Text / Steganographic Injections** | DOM Parser | High | Med | **HIGH** | AXTree ignores `display:none`, `visibility:hidden`, `opacity:0`, and zero-font text; NFKC normalization strips zero-width chars. |
| 3 | **SSRF / Localhost Targeting** | `browser_navigate` | High | High | **CRITICAL** | Pre-navigation DNS resolution, private IP denylist (`127.0.0.0/8`, `10.0.0.0/8`, `192.168.0.0/16`, `169.254.169.254`), redirect validation. |
| 4 | **Malicious URL Schemes (`javascript:`, `file:`)** | Navigation Engine | High | High | **CRITICAL** | Strict scheme whitelist (`http://`, `https://` only); immediate rejection of `file:`, `javascript:`, `data:`, `vbscript:`. |
| 5 | **Sub-Resource SSRF via `fetch()`/`<img>`** | Network Route Handler | Med | Med | **HIGH** | Playwright `context.route('**/*', ...)` intercepts all subresources, applying SSRF validation to every sub-request. |
| 6 | **Malicious File Download** | Download Pipeline | High | High | **CRITICAL** | Isolated temp folder; path traversal checks; size cap (50MB); mandatory Phase 6 Universal File Registry intake. |
| 7 | **Unauthorized File Upload** | Upload Tool | Med | High | **HIGH** | Uploads strictly restricted to verified files already cataloged in workspace File Registry; host path access blocked. |
| 8 | **Credential Theft via Phishing Page** | Form Filling Tool | Med | High | **CRITICAL** | Domain binding for stored credentials; credentials injected directly via server-side Playwright `page.fill()`; zero model prompt exposure. |
| 9 | **Session Hijacking / Cookie Leakage** | Cookie Store | Med | High | **CRITICAL** | Cookies stored in PostgreSQL encrypted with AES-256-GCM bound to `workspace_id`; incognito contexts wiped on task completion. |
| 10 | **Automation Runaway / Infinite Loop** | Browser Manager | High | Med | **HIGH** | Max 30 actions per task; max 5 consecutive actions without state change; per-action timeouts (15s click, 25s nav). |
| 11 | **Tab Explosion / Resource Exhaustion** | Multi-Tab Controller | High | Med | **HIGH** | Hard ceiling of max 4 concurrent tabs per workspace; oldest tab auto-pruned or new tab rejected. |
| 12 | **Browser Memory Leakage** | Chromium Process | Med | Med | **MEDIUM** | Ephemeral contexts closed upon task completion; process memory monitored; recycled if RSS exceeds 1024 MB. |
| 13 | **Deceptive UI / Clickjacking** | Element Locator | Med | High | **HIGH** | Element visibility, pointer-events, and bounding box validation before dispatching click; coordinate cross-check. |
| 14 | **Fake HITL Prompt Injection** | Web Content Parser | High | High | **CRITICAL** | HITL approvals require cryptographic HMAC-SHA256 signature generated exclusively by Control Plane; web text cannot forge tokens. |
| 15 | **Workstation Surveillance While Locked** | Vision / Voice Sensors | Med | High | **CRITICAL** | `WM_WTSSESSION_CHANGE` listener immediately halts camera stream, microphone recording, and desktop capture on lock. |
| 16 | **Hidden Windows Autostart Persistence** | Autostart Manager | Low | Med | **HIGH** | Autostart is OFF by default; uses standard visible Registry HKCU Run key; dashboard toggle with full reversibility. |
| 17 | **Daemon Privilege Escalation** | Supervisor Daemon | Low | High | **CRITICAL** | Runs strictly in user-session context with standard user token; zero `SYSTEM` or elevated admin tokens requested. |
| 18 | **Unauthenticated Local IPC Abuse** | Named Pipe Server | Med | High | **CRITICAL** | Windows Named Pipe protected with session-scoped DACL and 256-bit token authentication (`~/.aura/.auth_token`). |
| 19 | **Kill Switch Bypass During Browser Task** | Kill Switch Engine | High | High | **CRITICAL** | Kill switch triggers `context.close()` and deep process tree kill within $<15\text{ms}$; pending operations aborted. |
| 20 | **Stale Approval Replay** | Approval Engine | Med | High | **CRITICAL** | Single-use nonce, 120s TTL, and SHA-256 parameter hash binding prevent token replay. |
| 21 | **Cross-Tenant Session Confusion** | Context Pool | Med | High | **CRITICAL** | Every `BrowserContext` is isolated per `workspace_id`; zero shared cookies, cache, or local storage between workspaces. |
| 22 | **Browser Escape via DevTools / CDP** | Chromium Engine | Low | High | **CRITICAL** | Remote debugging ports disabled; `--disable-blink-features=AutomationControlled` applied. |
| 23 | **Download-to-Memory Vector Poisoning** | Memory Pipeline | High | Med | **HIGH** | Downloaded files do not automatically promote to cognitive memory; require explicit user authorization. |
| 24 | **Malicious Redirect Chains** | Navigation Handler | Med | Med | **MEDIUM** | Max 10 redirects enforced; each redirect URL validated through SSRF guard before following. |
| 25 | **Clipboard Data Poisoning / Secret Exfiltration** | Clipboard Tool | Med | High | **HIGH** | 4096-char ceiling; automated secret scrubbing; zero vector memory persistence. |

---

## 7. Credential & Privacy Architecture

### 7.1 Zero-Prompt Credential Proxy
1. **At-Rest Security:** User credentials for authorized websites are stored in PostgreSQL encrypted with AES-256-GCM using authenticated associated data (AAD) bound to `workspace_id`.
2. **Model Isolation:** The LLM never sees raw usernames or passwords in context. It emits a governed command: `browser_fill_credentials(domain="github.com", account_alias="work")`.
3. **Runtime Injection:** The Control Plane fetches the ciphertext, decrypts it in memory, and passes it directly to Playwright's `page.fill()` via private IPC.
4. **Context Cleanup:** Decrypted memory buffers are scrubbed immediately after injection; browser input fields are masked.

---

## 8. Controlled Autostart & Windows Session Architecture

### 8.1 Autostart Policy & Governance
* **Default State:** **OFF (Disabled by default).**
* **Mechanism:** Single user-scoped Windows Registry Key:
  `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\AURA` $\rightarrow$ `"{AURA_DIR}\bin\aura-daemon.exe" --background`
* **Zero Stealth Guarantee:** Visible in Windows Task Manager Startup tab; toggleable in Next.js Settings and Tray context menu; audit log recorded upon enable/disable.

### 8.2 Workstation Lock/Unlock Lifecycle
* When Windows emits `WM_WTSSESSION_CHANGE` with `WTS_SESSION_LOCK`:
  1. Camera frame ingestion is **IMMEDIATELY PAUSED**.
  2. Microphone STT listening is **PAUSED**.
  3. Continuous OCR & Screen capture are **PAUSED**.
  4. Active interactive browser workflows are **SUSPENDED**.
  5. Tray indicator switches to `PRIVACY_MUTED` state.
* Upon `WTS_SESSION_UNLOCK`, sensing is restored only if previously active.

---

## 9. Failure Modes & Graceful Degradation

| Failure Condition | Immediate Safe Behavior | Recovery Mechanism |
| :--- | :--- | :--- |
| **Chromium Process Crash** | Active task halted; error returned to AgentRuntime; context recycled. | `PlaywrightBrowserManager` restarts browser instance on next request. |
| **Page Navigation Timeout (>25s)** | Aborts navigation; captures partial DOM/AXTree; reports timeout error. | Planner decides whether to retry or adjust URL. |
| **Element Selector Not Found** | Action fails-closed; refreshes AXTree state; returns updated element list. | Planner adapts plan using fresh element IDs. |
| **FastAPI Backend Crash** | `AuraDaemonSupervisor` detects dropped heartbeat (<5s). | Restarts Uvicorn; executes `StartupRecoverySweep` to reconcile tasks. |
| **Database Unavailable** | Background tasks pause; reject new write operations; log warning. | Reconnects with exponential backoff (1s, 2s, 4s). |
| **Emergency Kill Switch Activated** | All browser contexts terminated immediately (`<15ms`); processes killed. | Requires explicit operator reset before accepting new tasks. |

---

## 10. Resource Constraints & Bounded Budgets

| Resource Vector | Hard Limit Ceiling | Enforcement Mechanism |
| :--- | :--- | :--- |
| **Browser Context Concurrency** | Max 2 concurrent contexts | `asyncio.Semaphore(2)` in `PlaywrightBrowserManager`. |
| **Tab Concurrency** | Max 4 tabs per context | Context tab counter; rejects `new_tab` if limit reached. |
| **Chromium Memory Footprint** | Max 512 MB per context (1024 MB total) | Process RSS monitor; context recycle if threshold exceeded. |
| **Daemon Supervisor Memory** | $\le 250\text{ MB}$ RAM | Lightweight Python/Win32 process with minimal dependency load. |
| **Idle Background CPU Usage** | $\le 1.0\%$ CPU | Event-driven architecture; sleep-based polling intervals (5s heartbeat). |
| **Action Budget per Task** | Max 30 browser actions | Counter in `TaskExecutionRuntime`; terminates with `BudgetExceededError`. |

---

## 11. $0.00 Zero-Cost Architecture Guarantee

* **100% Local Execution:**
  - Browser engine: Local Playwright Chromium distribution.
  - VLM / Screen Understanding: Local CPU/GPU models (Moondream2 / Qwen2-VL 2B).
  - Background Supervisor: Local Win32 / Python runtime.
  - Memory & State: Local PostgreSQL 16 + pgvector.
* **No Mandatory Paid Dependencies:**
  - Zero Browserbase / Browserless cloud browser subscriptions.
  - Zero paid scraping APIs or proxy rotation fees.
  - Zero commercial CAPTCHA solving services.
  - Zero external cloud AI requirements.

---

## 12. Complete Phase 10 Validation & Test Strategy

```
+─────────────────────────────────────────────────────────────────────────────────────────────+
|                                    PHASE 10 TEST STRATEGY                                   |
+─────────────────────────────────────────────────────────────────────────────────────────────+
| 1. Unit Test Suite (pytest)                                                                 |
|    - AXTree parsing, numeric ID assignment, and XML envelope formatting                     |
|    - SSRF pre-navigation, redirect, and subresource filter logic                            |
|    - 5-tier risk taxonomy mapping and rate limiter token buckets                            |
|    - Registry autostart enable/disable idempotent operations                                |
|                                                                                             |
| 2. Integration Test Suite (pytest-asyncio)                                                  |
|    - AgentToolBridge -> browser_navigate -> Playwright page load                            |
|    - Multi-tab lifecycle (create, switch, close, max-tab ceiling)                          |
|    - Encrypted credential injection into mock login forms                                   |
|    - Sandboxed download intake -> Phase 6 Universal File Registry                           |
|                                                                                             |
| 3. Security Red-Team Matrix (25 Vectors)                                                    |
|    - Prompt injection payloads in DOM text and hidden elements                              |
|    - SSRF localhost / cloud metadata bypass attempts                                        |
|    - Path traversal attacks in downloads and uploads                                        |
|    - HMAC-SHA256 HITL token forgery and replay tests                                        |
|                                                                                             |
| 4. Deterministic Kill-Switch Micro-Races (10 Races, <15ms SLA)                              |
|    - Kill switch vs in-flight navigation, click, typing, file download                      |
|    - Multi-process termination of Playwright driver and Chromium instances                  |
|                                                                                             |
| 5. Live Windows 11 Host Acceptance                                                          |
|    - Real user-session background supervisor startup and health heartbeat                   |
|    - System tray status indicators (BROWSER_ACTIVE, DAEMON_ACTIVE)                          |
|    - WM_WTSSESSION_CHANGE simulated lock/unlock event verification                          |
+─────────────────────────────────────────────────────────────────────────────────────────────+
```

---

## 13. Phase 10 Granular Task Breakdown

| Task ID | Task Title | Detailed Scope & Acceptance Criteria | Dependencies | Complexity | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **AURA-1001** | Advanced Headless & Interactive Browser Engine | `PlaywrightBrowserManager` extension supporting interactive session lifecycle, multi-tab coordination ($\le 4$ tabs), AXTree accessibility snapshots with numeric element IDs, visual bounding box correlation, dual-representation page state capture, and `<untrusted_web_content>` prompt containment envelopes. | AURA-404, AURA-801 | 8 pts (3 days) | **PREFLIGHT SPECIFIED** |
| **AURA-1002** | Governed Browser Interaction Tools & Risk Policy | Suite of 8 canonical governed tools (`browser_navigate`, `browser_click`, `browser_type`, `browser_select`, `browser_scroll`, `browser_press_key`, `browser_get_page_state`, `browser_tab_manage`), strict 5-tier risk mapping (`READ`, `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`), mandatory HMAC-SHA256 HITL for consequential clicks/submissions, action loop budgets ($\le 30$ actions/task), and zero-delay kill switch abort hooks. | AURA-1001, AURA-204, AURA-901 | 8 pts (3 days) | **PREFLIGHT SPECIFIED** |
| **AURA-1003** | Encrypted Web Session & Credential Injection Vault | Encrypted cookie/session storage in PostgreSQL via AES-256-GCM bound to `workspace_id`, zero-prompt credential injection proxy (`page.fill` via server-side vault, no secrets in LLM context), domain scoping, and ephemeral incognito session clearing. | AURA-1002, AURA-105 | 5 pts (2 days) | **PREFLIGHT SPECIFIED** |
| **AURA-1004** | Governed Browser Download & Upload Pipeline | Sandboxed download directory `{workspace}/downloads/.incoming_{uuid}/`, path traversal defense, file type / MIME verification, size enforcement ($\le 50\text{MB}$), automatic routing into Phase 6 Universal File Registry (`FileStorageEngine`), and upload governance restricted to indexed workspace files. | AURA-1002, AURA-601 | 5 pts (2 days) | **PREFLIGHT SPECIFIED** |
| **AURA-1005** | Windows User-Session Background Daemon & Watchdog Supervisor | Lightweight Windows user-session background supervisor (`AuraDaemonSupervisor`), least-privilege non-SYSTEM execution, Uvicorn/FastAPI process lifecycle supervision, health check loop (5s interval), exponential backoff crash recovery, and `StartupRecoverySweep` task reconciliation. | AURA-905, AURA-706 | 8 pts (3 days) | **PREFLIGHT SPECIFIED** |
| **AURA-1006** | Session Awareness, Tray Integration & Controlled Autostart | Win32 `WM_WTSSESSION_CHANGE` session lock/unlock detection (suspending camera/mic/screen on lock), AURA-905 tray icon state extensions (`BROWSER_ACTIVE`, `DAEMON_ACTIVE`, `DAEMON_DEGRADED`), and explicit, user-controlled, reversible autostart via `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` (OFF by default). | AURA-1005, AURA-905 | 5 pts (2 days) | **PREFLIGHT SPECIFIED** |
| **AURA-1007** | Phase 10 Master Integration, Security Threat Red-Teaming & Live Validation | Comprehensive cross-subsystem integration, 10 kill-switch race micro-benchmarks ($<15\text{ms}$ abort), 25-vector security threat matrix validation, zero-skip Windows 11 host verification, resource budget compliance, and complete regression pass. | AURA-1001 to 1006 | 8 pts (3 days) | **PREFLIGHT SPECIFIED** |

---

## 14. Manual Dependency Inventory

### 14.1 Required Manual Actions Before Implementation
* **None.** All foundational dependencies (Python 3.12, PostgreSQL 16, Playwright, Node.js, Win32 APIs) are already installed and validated on the host.

### 14.2 Required Manual Actions During Implementation
* **None.** Mock adapters and local fixtures will allow isolated unit and integration testing without manual operator intervention.

### 14.3 Required Manual Actions During Live Acceptance / Validation
1. **Interactive Browser Verification (Headed Mode Inspection):** User may observe a test browser window perform automated navigation and form filling.
2. **Workstation Lock Event Simulation:** User may optionally lock Windows (`Win+L`) to verify sensor pausing, or automated test will dispatch synthetic `WM_WTSSESSION_CHANGE` events.
3. **Autostart Enablement Confirmation:** User may toggle the autostart checkbox in Settings to verify Windows Registry key creation and removal.

### 14.4 Optional User Choices
* **Browser Mode:** Headless (default, zero UI disturbance) vs. Headed (for visual debugging).
* **Autostart on Boot:** Enable or disable automatic launch upon Windows user login (default: disabled).

---

## 15. Implementation Authorization Gate Decision

```
================================================================================
PHASE 10 PREFLIGHT EVALUATION DECISION:
PHASE 10 READY FOR IMPLEMENTATION
================================================================================
```

* **Gate Condition:** Preflight specifications, threat models, risk taxonomies, and task breakdowns are fully completed and reconciled across all foundational documentation.
* **Invariant Enforced:** **Implementation has NOT started.** Phase 10 remains strictly gated and paused awaiting explicit user authorization.

---

**Signed:**  
*High-Accuracy AI Assistant (Architect of Knowledge / Scientific Validation Engine)*  
*AURA Architecture & Governance Board*
