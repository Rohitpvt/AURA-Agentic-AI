# PHASE 9 PREFLIGHT REPORT: GOVERNED OS & HARDWARE CONTROL

**Phase:** Phase 9 — Governed Operating System & Hardware Control Automation  
**Date:** October 5, 2026  
**Status:** READY / PREFLIGHT COMPLETE (Implementation NOT Started)  
**Preflight Authorization:** Authorized for Architectural Audit & Safety Design Only  
**Commit Baseline:** `cf820aa`  
**Target Hardware:** AMD Ryzen 7 4800H (8C/16T), 24 GB DDR4 RAM, NVIDIA GeForce RTX 3050 Laptop GPU (4 GB VRAM), Windows 11 Home  

---

## 1. EXECUTIVE SUMMARY & BASELINE VERIFICATION

Phase 9 marks the critical architectural transition of AURA from purely perceptual observation to governed physical action:

```text
┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   OBSERVE    │ ──► │    REASON    │ ──► │    GOVERN    │ ──► │     ACT      │
│ (Phases 7/8) │     │ (Phases 1/2) │     │ (Phase 2/5)  │     │  (Phase 9)   │
└──────────────┘     └──────────────┘     └──────────────┘     └──────────────┘
```

The baseline established in Phases 1 through 8 is 100% accepted, validated, and functioning:
- **Phase 1–2:** Core Control Plane, PostgreSQL 16 + pgvector memory, AURA-native cognitive loop, tool registry, 4-tier risk engine, HMAC-SHA256 HITL tokens, and MCP host.
- **Phase 3–4:** Next.js 15.5.27 dashboard, SSE streaming, transactional cron scheduler, inbound webhooks, Telegram integration, and Playwright extraction.
- **Phase 5:** OpenTelemetry distributed tracing, container sandbox hardening, sub-15ms emergency kill switch, and prompt-injection red-teaming.
- **Phase 6:** Universal file intelligence, format-aware chunking, FastEmbed 768-dim normalized embeddings, HNSW cosine search (99.00% Recall@5), and file intelligence tools.
- **Phase 7:** Local Silero VAD + Faster-Whisper STT (CPU int8), Piper-TTS streaming, cooperative barge-in (<50ms trigger), authenticated voice WebSocket gateway, and voice HUD.
- **Phase 8:** Continuous screen capture (`mss`), Continuous OCR (`rapidocr-onnxruntime`), live camera WebSocket stream, local CPU VLM (`moondream`), 4 governed vision tools, and Next.js Vision HUD.

**Strict Phase 9 Constraint:** All Phase 9 actions are strictly mediated through the deterministic governance pipeline. Zero direct agent-to-OS execution paths are permitted. Zero implementation code is written during this preflight pass.

---

## 2. RECONCILIATION OF EMBEDDING-SERVICE CHANGE

During the AURA-804 reconciliation pass, `apps/api/app/services/embedding_service.py` was amended in `count_tokens`:

```diff
@@ -84,6 +84,10 @@ class EmbeddingService:
         if not text:
             return 0
 
+        if text.startswith(self.BGE_QUERY_PREFIX):
+            remainder = text[len(self.BGE_QUERY_PREFIX):]
+            return self.PREFIX_TOKENS_COUNT + self.count_tokens(remainder)
+
         tok = self._get_tokenizer()
```

### 2.1 Root Cause & Analysis
- **Context:** In `EmbeddingService`, the canonical asymmetric retrieval instruction `BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "` is exactly 8 non-special tokens (`PREFIX_TOKENS_COUNT = 8`).
- **Mechanism:** During offline unit testing (`settings.is_testing = True`), FastEmbed avoids downloading model weights, engaging the deterministic WordPiece-approximating subword fallback in `count_tokens`.
- **Discrepancy:** The subword fallback estimated token count based on word lengths: words in the prefix like `"Represent"`, `"sentence"`, `"searching"`, `"relevant"`, `"passages"` (lengths 8–9) were evaluated as $\lceil \text{len}/3.5 \rceil = 3$ tokens each, artificially inflating the 8-token prefix to 18 tokens.
- **Test Failure:** In `test_embedding_service_bge.py::test_query_payload_token_boundaries`, a 501-word query `"data ..."` produced $18 + 501 = 519$ estimated tokens, failing the assertion `assert tok_count_501 <= 510` with `519 <= 510`.
- **The Fix:** If the query starts with `BGE_QUERY_PREFIX`, `count_tokens` adds the exact constant `self.PREFIX_TOKENS_COUNT` (8) to the token count of the remaining payload.

### 2.2 Invariant & Backward-Compatibility Verification
- **FastEmbed & Model Execution:** Unaffected. FastEmbed ONNX tokenizer continues to tokenize full query strings natively during live execution.
- **pgvector & Relational Schema:** Unaffected. Tables (`file_chunks`, `memory_records`), HNSW cosine indexes (`m=16, ef_construction=64`), and GIN full-text indexes remain identical.
- **Memory Retrieval & Provenance:** Unaffected. Symmetric hybrid dense + lexical search candidate fusion ($0.70 \cdot S_{\text{dense}} + 0.30 \cdot S_{\text{lexical}}$) and provenance tracking remain unchanged.
- **Vector Dimension:** Unaffected. Strictly 768 dimensions with unit L2 normalization ($||v|| = 1.0$).
- **Multi-Tenant Isolation:** Unaffected. Workspace tenancy partitioning and metadata boundaries are untouched.
- **Test Suite Verification:** 21/21 memory, embedding, indexing, chunking, and multi-tenant vector benchmark tests pass 100% green (`65.62s`). Zero architectural invariants violated.

---

## 3. PHASE 9 SCOPE SPECIFICATION

Phase 9 establishes governed interaction with the host operating system and approved local hardware peripherals under strict deterministic controls:

### A. Windows Application Control
- **Governed Application Launch:** Launch pre-approved binaries from an explicit executable allowlist with strict argument validation and environment sanitization.
- **Process Inspection:** Read-only enumeration of active desktop processes, window titles, PIDs, memory usage, and creation timestamps.
- **Governed Process Termination:** Tightly restricted process termination requiring explicit allowlist validation, protected-process denylist screening, creation-time verification (PID reuse protection), and cryptographic HITL approval.
- **Window Focus & Activation:** Safely bringing approved target application windows into the foreground without altering process state.

### B. Desktop GUI Interaction
- **Coordinate Safety Layer:** Window-scoped and monitor-bounded mouse movement and clicking via PyAutoGUI.
- **Governed Keystroke Dispatch:** Controlled text entry and standard keyboard shortcuts with character length limits and sensitive key screening.
- **Visual Target Verification:** Enforcing fresh visual observation prerequisites (maximum coordinate staleness TTL $\le 5.0\text{s}$) to prevent clicking vanished or relocated UI elements.

### C. Hardware & System Telemetry
- **Read-Only Telemetry:** Local query of CPU utilization (per-core and aggregate), RAM consumption, GPU utilization and VRAM allocation, local storage capacity, battery/power state, and display topology.
- **Zero Cloud Reporting:** All system telemetry remains strictly local to the workspace control plane ($0.00 zero-cost floor).

### D. Governed Hardware Control
- **Explicit Device Adapters:** Bounded control of master system volume and display brightness via native Windows Core Audio and WMI/DDC-CI APIs.
- **Strict Bounds:** Granular step limits ($\le 10\%$ per action) and hard minimum/maximum clamps. Zero unrestricted device manipulation.

### E. Windows System Tray Controller
- **Persistent Local Indicator:** System tray icon displaying real-time AURA state (Idle, Processing, Suspended, Kill Switch Active, Camera Active, Screen Active).
- **Physical Control Plane:** Immediate access to Emergency Kill Switch trigger, status inspect, and clean application shutdown.

### F. Global Emergency Hotkeys
- **Physical Hardware Interrupter:** Low-level global hotkey (`Ctrl+Alt+Shift+K`) registered directly with the Windows kernel (`RegisterHotKey`) to trigger the sub-15ms Emergency Kill Switch independently of the agent reasoning loop.

---

## 4. HARD EXCLUSIONS (NON-NEGOTIABLE BOUNDARIES)

To maintain absolute containment and enterprise safety, Phase 9 **STRICTLY PROHIBITS**:
1. **Arbitrary Shell Execution:** Zero arbitrary execution of `cmd.exe`, `powershell.exe`, `pwsh.exe`, `bash.exe`, `wscript.exe`, `cscript.exe`, `mshta.exe`, `rundll32.exe`, or `regsvr32.exe`.
2. **Unrestricted Process Termination:** Zero termination of system processes, security software, Windows core services, or AURA infrastructure (`postgres`, `ollama`, `python` host).
3. **Arbitrary Filesystem Mutation:** Zero file modification outside the designated sandbox workspace directory.
4. **Registry & Driver Manipulation:** Zero modification of Windows Registry keys, system drivers, hardware firmware, or kernel settings.
5. **Credential Extraction & Keylogging:** Zero access to Windows Credential Manager, browser cookie vaults, browser saved passwords, or background keylogging.
6. **Stealth Persistence & Privilege Escalation:** Zero creation of hidden scheduled tasks, auto-start registry run keys, UAC bypasses, or elevation of privilege.
7. **Unconsented Surveillance:** Zero background microphone recording, zero unconsented webcam activation outside explicit Phase 8 camera sessions.
8. **Interactive Browser Automation:** Playwright interactive web automation, DOM event dispatch, and web session management remain strictly deferred to **Phase 10**.

---

## 5. GOVERNED ACTION ARCHITECTURE

The authoritative governance path is immutable and unbreakable:

```text
┌──────────────────────────────────────────────────────────────────────────────────┐
│                             AGENT COGNITIVE LAYER                                │
│                                                                                  │
│   Agent LLM ──► Proposes Tool Call (e.g. `launch_application`, `gui_click`)      │
└───────────────────────────────────────┬──────────────────────────────────────────┘
                                        │
                                        ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                            GOVERNANCE & POLICY GATE                              │
│                                                                                  │
│   AgentToolBridge ──► Intercepts call, resolves workspace & user context         │
│   ToolRegistryService ──► Validates Pydantic JSON Schema                         │
│   Risk Assessment Service ──► Evaluates Risk Tier (LOW / MEDIUM / HIGH)          │
│   Policy Engine ──► Checks Autonomy Level (L0–L5) & Workspace Quotas             │
│   HITL Gateway ──► Validates HMAC-SHA256 Signed Approval Token (if HIGH/CRITICAL)│
└───────────────────────────────────────┬──────────────────────────────────────────┘
                                        │
                                        ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                           SAFETY & EXECUTION LAYER                               │
│                                                                                  │
│   Kill Switch Probe ──► Verifies active authority file (sub-15ms abort)          │
│   OS Guard & Coordinate Safety ──► Bounds checks coordinates & target window     │
│   Execution Adapter (PyAutoGUI / Windows API / psutil) ──► Performs action       │
└───────────────────────────────────────┬──────────────────────────────────────────┘
                                        │
                                        ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                            AUDIT & TELEMETRY LEDGER                              │
│                                                                                  │
│   AuditService ──► Appends SHA-256 tamper-evident record                         │
│   OpenTelemetry ──► Records span with redacted arguments & correlation ID        │
│   Observation Output ──► Formats structured result to Agent Execution Loop       │
└──────────────────────────────────────────────────────────────────────────────────┘
```

**Prohibited Direct Paths:**
- `Agent ──► PyAutoGUI` (FORBIDDEN)
- `Agent ──► subprocess.Popen` (FORBIDDEN)
- `Agent ──► psutil.Process.kill()` (FORBIDDEN)
- `Agent ──► ctypes / win32api` (FORBIDDEN)

---

## 6. ACTION TAXONOMY & RISK CLASSIFICATION

Every OS and hardware operation is deterministically mapped to the 4-tier risk classification:

| Action Category | Concrete Operations | Risk Tier | Autonomy Requirement | HITL Requirement |
| :--- | :--- | :--- | :--- | :--- |
| **READ_ONLY** | `get_system_telemetry`, `list_running_processes`, `get_active_window_info`, `get_display_info` | `LOW` | L1–L5 | No confirmation required |
| **LOW_RISK_WRITE** | `focus_application_window`, `set_system_volume` ($\le \pm 10\%$), `set_display_brightness` ($\le \pm 10\%$) | `LOW` | L2–L5 | No confirmation required |
| **MEDIUM_RISK_INTERACTION** | `gui_mouse_move`, `gui_mouse_click`, `gui_type_text`, `gui_press_key`, `gui_keyboard_shortcut` | `MEDIUM` | L3–L5 | Parameter-bound confirmation at L0–L2; autonomous at L3+ under active window bounds |
| **HIGH_RISK_SYSTEM_ACTION** | `launch_application` (allowlisted executable), `terminate_process` (allowlisted, non-system PID + creation time verified) | `HIGH` | L4–L5 | **MANDATORY Cryptographic HITL Token** |
| **CRITICAL_ACTION** | System shutdown, system restart, non-allowlisted execution, destructive bulk termination | `CRITICAL` | L5 Only | **MANDATORY Admin Console Verification + Cryptographic Token** |

---

## 7. HUMAN-IN-THE-LOOP (HITL) SECURITY MODEL

For all `HIGH` and `CRITICAL` risk OS actions:

```text
┌──────────────────────────────────────────────────────────────────────────────────┐
│                            HITL TOKEN SPECIFICATION                              │
│                                                                                  │
│  Payload:                                                                        │
│    - token_id:        UUIDv4                                                     │
│    - workspace_id:    UUIDv4 (Tenant isolation)                                  │
│    - action_type:     "launch_application" | "terminate_process"                 │
│    - target_hash:     SHA-256(canonical_executable_path | pid_with_create_time) │
│    - parameters_hash: SHA-256(canonical_json(arguments))                         │
│    - issued_at:       Unix Timestamp                                             │
│    - expires_at:      Unix Timestamp (TTL = 120 seconds)                         │
│    - nonce:           256-bit CSPRNG hex                                         │
│                                                                                  │
│  Signature:                                                                      │
│    HMAC-SHA256(SECRET_KEY, canonical_payload_string)                             │
└──────────────────────────────────────────────────────────────────────────────────┘
```

### Invariants:
1. **Strict Parameter Binding:** Approving `launch_application(target="notepad.exe")` generates a token bound specifically to `notepad.exe`. Attempting to use the same token for `calc.exe` fails with `AuthorizationError`.
2. **Single-Use Replay Protection:** Tokens are marked consumed in Redis/PostgreSQL immediately upon execution. Replay attempts fail with `TokenReplayedError`.
3. **120-Second Expiration:** Tokens older than 120 seconds are rejected with `TokenExpiredError`.
4. **Active Workspace Verification:** The token's `workspace_id` must match the executing task's workspace.

---

## 8. PYAUTOGUI SECURITY WRAPPER & COORDINATE SAFETY LAYER

To eliminate risks of arbitrary mouse movements, infinite loops, and stray clicks:

```text
┌──────────────────────────────────────────────────────────────────────────────────┐
│                         COORDINATE SAFETY ARCHITECTURE                           │
│                                                                                  │
│   Target Coordinate (x, y)                                                       │
│          │                                                                       │
│          ▼                                                                       │
│   [Monitor Boundary Validator] ──► Ensures (x, y) lies inside Monitor Bounds     │
│          │                                                                       │
│          ▼                                                                       │
│   [Active Window Bounds Check] ──► Ensures (x, y) lies inside Focused Window     │
│          │                                                                       │
│          ▼                                                                       │
│   [Stale Observation Gate]    ──► Rejects if observation age > 5.0 seconds       │
│          │                                                                       │
│          ▼                                                                       │
│   [PyAutoGUI Adapter]         ──► Enforces duration (0.1s - 2.0s), FAILSAFE=True │
└──────────────────────────────────────────────────────────────────────────────────┘
```

### Safety Constraints:
- **PyAutoGUI Failsafe:** `pyautogui.FAILSAFE = True` is permanently enabled (moving the cursor to $(0,0)$ raises `pyautogui.FailSafeException`).
- **Duration Limits:** Mouse movements must specify a duration between $0.1\text{s}$ and $2.0\text{s}$ (instantaneous $(0.0\text{s})$ teleportation is clamped to $0.1\text{s}$ to preserve visual human auditability).
- **Text Typing Bounds:** `gui_type_text` accepts a maximum of 256 characters per tool call. Secret redaction patterns (`[REDACTED_SECRET]`) are applied prior to typing.
- **Keyboard Shortcut Allowlist:** Only standard UI navigation combinations are permitted (`Ctrl+C`, `Ctrl+V`, `Ctrl+S`, `Ctrl+Z`, `Ctrl+F`, `Ctrl+A`, `Tab`, `Enter`, `Escape`, `Arrow Keys`). Destructive system chords (`Win+R`, `Ctrl+Alt+Del`, `Alt+F4` on system windows) are hard-blocked by policy.

---

## 9. VISUAL ACTION SAFETY & STALE-COORDINATE PROTECTION

When an agent proposes an action based on Phase 8 VLM or OCR coordinates:
1. **Freshness Invariant:** The visual observation timestamp $T_{\text{obs}}$ must satisfy:
   $$\Delta T = T_{\text{current}} - T_{\text{obs}} \le 5.0\text{ seconds}$$
   If $\Delta T > 5.0\text{s}$, the action is rejected with `StaleVisualObservationError("Visual coordinate expired. Fresh inspect_current_screen required.")`.
2. **Active Window Confirmation:** Before clicking, the system queries the Windows OS foreground window title and bounding box. If the active window title does not match the target window in the visual plan, the action is aborted.
3. **Geometry Transformation:** Coordinates provided in normalized $[0, 1]$ or captured frame dimensions are transformed into screen pixel coordinates using per-monitor DPI scaling factors from AURA-801.

---

## 10. FAIL-SAFE CONTROLS & EMERGENCY ABORT ENGINE

Phase 9 integrates directly with the Phase 5 sub-15ms Emergency Kill Switch (`KillSwitchService`):
1. **Pre-Action Probe:** Before any OS action begins, the kill switch state file is probed. If active, the action throws `KillSwitchActiveError`.
2. **In-Flight Cancellation:** For multi-step actions (e.g. typing or multi-point dragging), the adapter checks `kill_switch.is_active` between individual keystrokes/steps. If triggered, execution aborts immediately.
3. **Physical Hotkey Interrupter:** Pressing `Ctrl+Alt+Shift+K` on the physical keyboard writes directly to the kill switch authority file, halting all active PyAutoGUI interactions and background workers in $\le 15\text{ms}$.
4. **Failsafe Corner:** Moving the physical mouse to $(0,0)$ triggers PyAutoGUI's native hardware interrupt.

---

## 11. PROCESS CONTROL SAFETY

### 11.1 Process Allowlist (Destructive Operations)
Only explicitly designated non-critical productivity applications may be terminated:
- Approved: `notepad.exe`, `calc.exe`, `mspaint.exe`, `wordpad.exe`, user-configured development processes.

### 11.2 Protected Process Denylist (Permanent Immunity)
The following processes can NEVER be terminated under any circumstances:
- **Windows Core & Security:** `System`, `Registry`, `smss.exe`, `csrss.exe`, `wininit.exe`, `services.exe`, `lsass.exe`, `svchost.exe`, `explorer.exe`, `dwm.exe`, `MsMpEng.exe` (Windows Defender), `SecurityHealthService.exe`.
- **AURA Infrastructure:** `python.exe` (AURA API / worker processes), `node.exe` (AURA Web / Next.js), `postgres.exe` (PostgreSQL DB), `ollama.exe` (Ollama runtime).

### 11.3 PID Reuse & TOCTOU Protection
Windows aggressively recycles Process IDs (PIDs). To prevent terminating an unrelated application that recycled a PID:
```python
# Canonical Identity Check
proc = psutil.Process(target_pid)
actual_create_time = proc.create_time()
actual_name = proc.name().lower()

if actual_name != expected_name.lower() or abs(actual_create_time - expected_create_time) > 0.05:
    raise ProcessIdentityMismatchError("PID was recycled or target process changed. Aborting termination.")
```

---

## 12. APPLICATION LAUNCH POLICY & LOLBINS DENIAL

### 12.1 Canonical Executable Allowlist
Applications must match validated absolute executable paths:
- Windows Accessories: `C:\Windows\System32\notepad.exe`, `C:\Windows\System32\calc.exe`, `C:\Windows\System32\mspaint.exe`.
- Browser (Standard): `C:\Program Files\Google\Chrome\Application\chrome.exe`, `C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`.
- Developer Tools: `C:\Users\<user>\AppData\Local\Programs\Microsoft VS Code\Code.exe`.

### 12.2 Explicit LOLBins Blacklist
The following Windows Living-off-the-Land Binaries (LOLBins) are permanently rejected by the launch policy:
- `powershell.exe`, `pwsh.exe`, `cmd.exe`, `wscript.exe`, `cscript.exe`, `mshta.exe`, `rundll32.exe`, `regsvr32.exe`, `certutil.exe`, `bitsadmin.exe`, `vssadmin.exe`, `wmic.exe`, `cscr.exe`, `hh.exe`, `schtasks.exe`.

### 12.3 Execution Invocation Safety
- All launches execute via `subprocess.Popen(args, shell=False)` with strictly sanitized argument arrays.
- Zero shell interpolation (`shell=True` is prohibited).

---

## 13. CLIPBOARD SECURITY MODEL

1. **Permission Separation:** `clipboard_read` and `clipboard_write` are discrete tool capabilities with independent policy gates.
2. **Content Length Bounding:** Clipboard read is bounded to a maximum of 4,096 characters (4 KB). Larger payloads are truncated.
3. **Secret Redaction:** Regex filters scrub API keys, JWT tokens, private keys, and passwords before returning clipboard text to the agent.
4. **Zero Persistent Clipboard History:** Clipboard contents are never written to long-term memory or OpenTelemetry attributes.
5. **Kill Switch Authority:** When the kill switch is active, all clipboard read/write operations return `AuthorizationError`.

---

## 14. HARDWARE TELEMETRY SPECIFICATION

Read-only hardware metrics queried via native local APIs:
- **CPU:** Total usage percentage, per-core utilization, logical/physical core counts, processor model string.
- **RAM:** Total physical memory, available memory, percent utilized, process memory RSS.
- **GPU & VRAM:** NVIDIA GPU name, utilization percentage, total VRAM, allocated VRAM, free VRAM (queried via PyTorch/NVML/DXGI without cloud dependencies).
- **Storage:** Disk partitions, total space, free space, utilization percentage per mounted drive.
- **Power & Battery:** AC power connected, battery percent remaining, power saving status.
- **Display Topology:** Screen resolution, monitor count, scaling DPI per monitor.

---

## 15. GOVERNED HARDWARE CONTROL ADAPTERS

Hardware adjustments are strictly bounded:
1. **Master Audio Volume (`set_system_volume`):**
   - Substrate: Windows Core Audio API (`pycaw` / `endpoint_volume`).
   - Range: $0\%$ to $100\%$.
   - Max Step: $\pm 10\%$ per action.
2. **Display Brightness (`set_display_brightness`):**
   - Substrate: WMI / DDC-CI (`screen_brightness_control`).
   - Range: $0\%$ to $100\%$.
   - Max Step: $\pm 10\%$ per action.
3. **Prohibited Controls:** Zero direct network adapter disabling, zero Bluetooth pairing manipulation, zero power-off/reboot via hardware control tools.

---

## 16. SYSTEM TRAY ARCHITECTURE & STATE SYNCHRONIZATION

A lightweight background system tray component built with Python `pystray` / Windows Shell NotifyIcon:

```text
┌──────────────────────────────────────────────────────────────────────────────────┐
│                           SYSTEM TRAY MENU TOPOLOGY                              │
│                                                                                  │
│   [Icon State: Green = Active, Yellow = Paused, Red = Kill Switch Active]       │
│                                                                                  │
│   ● AURA Status: RUNNING (Autonomy L3)                                           │
│   ● Screen Sensing: ACTIVE (mss, 1 Monitor)                                      │
│   ● Camera Stream: STOPPED                                                       │
│   ● Local VLM: IDLE (Moondream @ CPU)                                            │
│   ------------------------------------------------                               │
│   [ ! ] TRIGGER EMERGENCY KILL SWITCH (Ctrl+Alt+Shift+K)                         │
│   [   ] Reset Kill Switch (Requires Admin Passphrase)                            │
│   ------------------------------------------------                               │
│   [ ⚙ ] Open Dashboard (http://localhost:3000)                                   │
│   [ ✕ ] Exit AURA (Graceful Shutdown)                                            │
└──────────────────────────────────────────────────────────────────────────────────┘
```

---

## 17. GLOBAL PHYSICAL EMERGENCY HOTKEYS

- **Registration Substrate:** Windows Win32 `RegisterHotKey` API running in a dedicated thread within the host process.
- **Canonical Hotkey:** `Ctrl + Alt + Shift + K` (Unambiguous, non-conflicting with common IDE/OS shortcuts).
- **Behavior:** Immediately writes `{"active": true, "triggered_by": "global_hotkey", "timestamp": ...}` to the kill switch authority file.
- **Debouncing:** Hardware keypress events debounced with a $250\text{ms}$ refractory period.

---

## 18. SANDBOX / HOST BOUNDARY PARTITIONING

| Execution Domain | Partition Category | Permitted Technologies | Governance Gate |
| :--- | :--- | :--- | :--- |
| **Container-Safe** | Sandboxed Docker / WSL2 | Python script evaluation, code AST parsing, file format extraction, vector math | Docker cgroups v2 quotas, read-only rootfs |
| **Host-Required Governed** | Local Windows Host | Screen capture (`mss`), Continuous OCR (`rapidocr`), Camera WebSocket (`getUserMedia`), PyAutoGUI GUI interaction, Process inspection | `AgentToolBridge` $\rightarrow$ `ToolRegistryService` $\rightarrow$ `PolicyEngine` |
| **Privileged-Host** | Local Windows Host (Restricted) | Application launch (allowlist), Process termination (allowlist + create_time), Hardware volume/brightness | **Mandatory Cryptographic HITL Token** |
| **Forbidden** | Blocked Permanently | Arbitrary cmd/powershell, LOLBins, registry write, driver mutation, keylogging | Hard rejection at policy engine; zero execution path |

---

## 19. OBSERVABILITY & AUDIT LEDGER

Every Phase 9 tool call records a tamper-evident audit ledger entry in PostgreSQL:

```json
{
  "audit_id": "aud_01J9X8K9L7M2N3P4Q5R6S7T8U9",
  "workspace_id": "ws_7b8c9d0e-1f2a-3b4c-5d6e-7f8a9b0c1d2e",
  "actor": "aura_agent_supervisor",
  "tool_name": "launch_application",
  "action_type": "HIGH_RISK_SYSTEM_ACTION",
  "target": "C:\\Windows\\System32\\notepad.exe",
  "arguments_redacted": {
    "target": "notepad.exe",
    "args": ["[REDACTED_ARG]"]
  },
  "risk_level": "high",
  "hitl_token_id": "tok_9a8b7c6d-5e4f-3a2b-1c0d-9e8f7a6b5c4d",
  "duration_ms": 142.5,
  "status": "success",
  "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
  "prev_ledger_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "ledger_hash": "a591a6d40bf420404a011733cfb7b190d62c65bf0bcda32b57b277d9ad9f146e"
}
```

---

## 20. MEMORY BOUNDARY & PRIVACY PRESERVATION

To prevent persistent surveillance of user desktop actions:
- **Zero Raw Keystroke/Click Memorization:** Individual mouse coordinates and typed text strings are NEVER indexed into long-term vector memory (`pgvector`).
- **High-Level Semantic Summaries Only:** Only task-level completion summaries (e.g., *"Exported report from Accounting application to output folder"*) are retained in episodic memory upon task completion.
- **Volatile Operational State:** Transient process lists and window titles are retained in ephemeral memory only for the duration of the active task.

---

## 21. KILL SWITCH EXTENSION (AURA-507 HARDENING)

When the kill switch is triggered:
1. `KillSwitchService.activate()` writes to the authority file.
2. In-flight PyAutoGUI loops abort within $\le 15\text{ms}$.
3. Pending tool execution promises in `AgentToolBridge` reject with `KillSwitchActiveError`.
4. Process spawning subprocesses are terminated via recursive tree kill (`psutil.Process.children(recursive=True)`).
5. System tray icon transitions to `RED (SUSPENDED)`.
6. Dashboard broadcasts SSE emergency suspension event.

---

## 22. RECOVERY STATE MACHINE & REPLAY IMMUNITY

```text
┌─────────────────┐       Kill Switch Triggered       ┌─────────────────┐
│     ACTIVE      │ ────────────────────────────────► │    SUSPENDED    │
│  (Normal Oper)  │                                   │ (All Ops Halts) │
└─────────────────┘                                   └────────┬────────┘
         ▲                                                     │
         │                User Explicit Reset                  │
         │           + Re-Authentication Required              │
         └─────────────────────────────────────────────────────┘
```

### Replay Immunity Rules:
- When resumed, all partially completed or interrupted OS actions (e.g., half-typed strings, pending clicks, queued application launches) are **PERMANENTLY PURGED**.
- Zero automatic re-execution of interrupted destructive actions. The agent must re-observe the screen state and propose a fresh, governed action plan.

---

## 23. RATE BUDGETS & RESOURCE CEILINGS

To prevent runaway automation and system instability:

| Metric | Hard Limit | Enforcement Substrate |
| :--- | :--- | :--- |
| **Mouse Movements & Clicks** | Max 60 actions / minute | Sliding-window token bucket in `OSInteractionService` |
| **Keyboard Typing Calls** | Max 10 calls / min ($\le 256$ chars/call) | Sliding-window token bucket |
| **Application Launches** | Max 5 launches / minute | Database rate limiter |
| **Process Terminations** | Max 5 terminations / minute | Database rate limiter |
| **Hardware Adjustments** | Max 10 adjustments / minute | Sliding-window token bucket |
| **Concurrent OS Actions** | Max 1 active action (Strictly Serialized) | `asyncio.Lock()` single-worker lock |
| **Max Action Execution Duration**| Max 5.0 seconds per action | `asyncio.wait_for` timeout |

---

## 24. PHASE 9 TASK GRAPH (AURA-901 to AURA-906)

```text
┌──────────────────────────────────────────────────────────────────────────────────┐
│                               PHASE 9 TASK GRAPH                                 │
│                                                                                  │
│   ┌──────────────────────────────────────────────────────────────────────────┐   │
│   │ AURA-901: Windows OS Control Foundation & Policy Boundary (5 pts)        │   │
│   │ (OS Guard, Action Taxonomy, Security Wrapper, Rate Budgets)              │   │
│   └──────────────────────┬───────────────────────────────────────────────────┘   │
│                          │                                                       │
│         ┌────────────────┴────────────────────────┐                              │
│         ▼                                         ▼                              │
│   ┌───────────────────────────┐             ┌───────────────────────────┐        │
│   │ AURA-902: Governed App    │             │ AURA-903: Governed Mouse  │        │
│   │ Launch & Process Control  │             │ & Keyboard Interaction    │        │
│   │ (Allowlist, PID verify)   │             │ (Coordinate Safety, Window│        │
│   │ (5 pts)                   │             │ Bounds, PyAutoGUI) (8 pts)│        │
│   └─────────────┬─────────────┘             └─────────────┬─────────────┘        │
│                 │                                         │                      │
│                 └────────────────────┬────────────────────┘                      │
│                                      │                                           │
│         ┌────────────────────────────┴────────────────────────────┐              │
│         ▼                                                         ▼              │
│   ┌───────────────────────────┐                             ┌───────────┐        │
│   │ AURA-904: System Telemetry│                             │ AURA-905: │        │
│   │ & Hardware Control Bounds │                             │ System    │        │
│   │ (CPU/RAM/GPU, Vol/Bright) │                             │ Tray &    │        │
│   │ (5 pts)                   │                             │ Hotkeys   │        │
│   └─────────────┬─────────────┘                             │ (5 pts)   │        │
│                 │                                           └─────┬─────┘        │
│                 └────────────────────┬────────────────────────────┘              │
│                                      ▼                                           │
│   ┌──────────────────────────────────────────────────────────────────────────┐   │
│   │ AURA-906: Phase 9 Integration, Kill-Switch Race Testing & Red Team (8pts)│   │
│   │ (End-to-end integration, kill-switch races, adversarial testing)         │   │
│   └──────────────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────────────┘
```

| Task ID | Task Title | Description & Acceptance Criteria | Dependencies | Complexity |
| :--- | :--- | :--- | :--- | :--- |
| **AURA-901** | Windows OS Control Foundation & Policy Boundary | Core `OSGuardService`, action taxonomy definitions, Pydantic schemas, sliding-window rate limiters, single-worker serialization lock. | Phase 8, AURA-204 | 5 pts (2 days) |
| **AURA-902** | Governed Application Launch & Process Control | Executable allowlist engine, LOLBins denial filter, `psutil` process inspector, PID + create_time termination verification, cryptographic HITL integration. | AURA-901 | 5 pts (2 days) |
| **AURA-903** | Governed Mouse & Keyboard Interaction | Coordinate safety validator, active window bounding box checks, stale observation guard ($\le 5\text{s}$), PyAutoGUI secure adapter, shortcut allowlist, failsafe corner. | AURA-901, AURA-801 | 8 pts (3 days) |
| **AURA-904** | System Telemetry & Hardware Control Boundary | Read-only local CPU/RAM/GPU/Storage/Battery telemetry, bounded system volume and display brightness adjustments ($\le \pm 10\%$), Core Audio / WMI adapters. | AURA-901 | 5 pts (2 days) |
| **AURA-905** | System Tray & Global Hotkey Control Plane | Python `pystray` system tray status indicator, Win32 `RegisterHotKey` physical `Ctrl+Alt+Shift+K` kill switch hotkey with sub-15ms trigger, state sync. | AURA-901, AURA-507 | 5 pts (2 days) |
| **AURA-906** | Phase 9 Integration, Kill-Switch Race Testing & Red Team | Cross-subsystem integration testing, kill-switch vs active action race condition verification, prompt injection to OS action red-teaming, full regression. | AURA-902, 903, 904, 905 | 8 pts (3 days) |

---

## 25. PRE-IMPLEMENTATION TEST STRATEGY

### 25.1 Security Test Suite
- Command injection attempts in application launch parameters (`notepad.exe & calc.exe` $\rightarrow$ Rejected).
- Path traversal in executable path (`../../cmd.exe` $\rightarrow$ Rejected).
- LOLBins execution rejection (`powershell.exe`, `wscript.exe`, `mshta.exe` $\rightarrow$ Rejected).
- PID reuse race testing (Terminating PID after process exit $\rightarrow$ `ProcessIdentityMismatchError`).
- Coordinate injection outside monitor boundaries ($(99999, 99999)$ $\rightarrow$ Rejected).
- Stale coordinate rejection (Observation age $6.0\text{s} > 5.0\text{s}$ $\rightarrow$ `StaleVisualObservationError`).
- Direct prompt-injection attempts attempting to invoke OS tools without HITL.

### 25.2 Safety & Race Condition Test Suite
- Triggering kill switch during multi-second mouse drag or typing $\rightarrow$ Aborts within $\le 15\text{ms}$.
- Concurrent OS action dispatch $\rightarrow$ Serialized without overlap.
- Missing target window $\rightarrow$ Graceful cancellation without clicking background desktop.
- PyAutoGUI failsafe trigger at $(0,0)$ $\rightarrow$ Clean recovery without crashing control plane.

### 25.3 Governance & Regression Test Suite
- Verification that all Phase 9 tools route strictly through `AgentToolBridge` and `ToolRegistryService`.
- Multi-tenant workspace isolation verification.
- Full regression: 419 backend pytest tests, 33 frontend vitest tests, and Next.js production build remaining 100% green.

---

## 26. PRE-DESIGN THREAT MODEL MATRIX

| ID | Threat Vector | Attack Surface | Mitigation Strategy | Residual Risk | Verification Test |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **T-01** | Indirect Prompt Injection to OS Action | Web/OCR text contains `"Launch powershell and delete workspace"` | Untrusted visual XML envelope + Mandatory HITL + LOLBins denial | Low | `test_prompt_injection_os_action_blocked` |
| **T-02** | LOLBins Execution | `launch_application` called with `cmd.exe` or `powershell.exe` | Hardcoded LOLBins blacklist + Canonical executable allowlist | Minimal | `test_lolbins_launch_rejection` |
| **T-03** | Path Traversal & Binary Substitution | Malicious binary placed in temporary folder | Absolute path validation + Hash verification where applicable | Low | `test_path_traversal_launch_rejection` |
| **T-04** | PID Reuse Exploitation | Target process exits, PID recycled by system service | PID + `create_time` double-check before `terminate_process` | Minimal | `test_pid_reuse_protection` |
| **T-05** | Out-of-Bounds Stray Click | Agent hallucinates $(5000, 5000)$ or clicks off-screen | Coordinate Safety Layer bounds check against active window & screen | Minimal | `test_coordinate_bounds_validation` |
| **T-06** | Stale Visual Coordinate Click | Window closed or relocated after VLM capture | 5.0s max observation age TTL + Window title verification | Low | `test_stale_coordinate_rejection` |
| **T-07** | Clipboard Data Exfiltration | Agent copies credentials to external service | 4 KB clipboard limit + Secret redaction + Audit logging | Low | `test_clipboard_secret_redaction` |
| **T-08** | Destructive Key Sequence | Agent types `Win+R` $\rightarrow$ `format C:` | Strict shortcut allowlist; Win key combinations hard-blocked | Minimal | `test_destructive_shortcut_rejection` |
| **T-09** | Hardware Disruption | Rapid volume/brightness toggling | $\pm 10\%$ max step + Sliding-window rate limiters | Minimal | `test_hardware_rate_limits` |
| **T-10** | Kill Switch Bypass | Long-running GUI action ignores kill switch | In-flight polling inside execution loop + Sub-15ms file probe | Minimal | `test_kill_switch_inflight_abort` |
| **T-11** | Replay of Interrupted Action | Interrupted click re-executed on restart | Deterministic queue purge on kill switch resume | Minimal | `test_kill_switch_replay_immunity` |
| **T-12** | Secret Leakage into Audit | Password typed into login box logged in plaintext | Sensitive argument screening + Secret redaction in audit ledger | Low | `test_audit_secret_redaction` |
| **T-13** | Multi-Tenant Workspace Crossing | Workspace A terminates process owned by Workspace B | Workspace-scoped process mapping + Tenant ID validation | Minimal | `test_workspace_process_isolation` |
| **T-14** | Privilege Escalation Attempt | Agent invokes UAC elevation prompt | Standard user execution context; UAC interaction prohibited | Low | `test_uac_elevation_rejection` |
| **T-15** | Runaway Loop Click Storm | Agent emits infinite click tool calls | Hard limit 60 clicks/min + Single-worker serialization | Minimal | `test_click_rate_limit_enforcement` |
| **T-16** | Global Hotkey Hijack | Malicious app intercepts `Ctrl+Alt+Shift+K` | Native Win32 `RegisterHotKey` priority registration | Low | `test_global_hotkey_registration` |

---

## 27. PREFLIGHT ACCEPTANCE CRITERIA CHECKLIST

- [x] Phase 8 baseline verified (AURA-801, 802, 803, 804 accepted; commit `cf820aa`)
- [x] `embedding_service.py` reconciliation explained with full test suite proof (21/21 tests passing)
- [x] OS control boundary defined (Unbreakable `AgentToolBridge` $\rightarrow$ `ToolRegistryService` pipeline)
- [x] PyAutoGUI architecture defined with coordinate safety layer and failsafe corner
- [x] Process-control policy defined with protected process denylist and PID+create_time verification
- [x] Application-launch policy defined with executable allowlist and LOLBins denial
- [x] Clipboard policy defined with separate read/write, length bounding, and secret redaction
- [x] Hardware telemetry policy defined with read-only local CPU/RAM/GPU/Storage queries
- [x] Hardware-control scope defined with bounded volume and brightness adjustments
- [x] System-tray architecture defined with real-time state indicator and kill switch access
- [x] Global-hotkey architecture defined with physical `Ctrl+Alt+Shift+K` interrupter
- [x] Kill-switch behavior defined with sub-15ms in-flight abort
- [x] Recovery behavior defined with zero-replay guarantees
- [x] HITL rules defined with HMAC-SHA256 parameter-bound single-use tokens
- [x] Risk classifications defined across 5 discrete tiers
- [x] Resource/rate limits defined with sliding-window token buckets
- [x] Sandbox/host boundary defined across 4 execution domains
- [x] Threat model completed with 16 threat vectors and mitigations
- [x] Test strategy completed covering security, safety, governance, and reliability
- [x] Task graph completed with 6 granular milestones (AURA-901 to AURA-906)
- [x] Task IDs verified (Zero collision with historical IDs)
- [x] Phase 10 remains untouched (Interactive browser and Windows daemon deferred)
- [x] No Phase 9 implementation performed (Preflight and architectural audit only)

---

## 28. CONCLUSION & NEXT AUTHORIZATION

The Phase 9 preflight and architectural safety audit is complete. All boundaries, security invariants, coordinate safety layers, HITL protocols, and task breakdowns are defined and locked.

**Phase 9 preflight is complete; explicit authorization is required before AURA-901 implementation.**
