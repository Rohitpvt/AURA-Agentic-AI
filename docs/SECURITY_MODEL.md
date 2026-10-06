# Security & Threat Model Specification (SECURITY_MODEL.md)
## Project Name: AURA (Autonomous Universal Reactive Agent)
**Document Version:** 9.6.0  
**Phase:** Phase 9 — Governed OS & Hardware Automation (COMPLETE & ACCEPTED) | Phase 1–9 Master Validated  
**Classification:** Enterprise Security & Threat Mitigation Specification  

---

## 1. Threat Modeling & Attack Vectors

| Attack Vector | Threat Description | AURA Mitigation Architecture |
| :--- | :--- | :--- |
| **Direct Prompt Injection** | Malicious user attempts to override system prompts and bypass security filters. | Deterministic Policy Engine sits *outside* the LLM context. Permissions and risk levels are checked in Python code before execution. |
| **Indirect Prompt Injection** | Malicious third-party data (e.g., hidden payload on a scraped web page or issue description) attempts to hijack tool calls. | Tool outputs and external text are wrapped in strict data boundaries (`<untrusted_content>...</untrusted_content>`). High-risk actions triggered after untrusted reads mandate HITL confirmation. |
| **Credential Exfiltration** | Prompt or tool payload attempts to read API keys, database credentials, or environment variables. | Zero secrets are passed to LLMs. Secrets are injected at the network proxy layer. Output sanitizer redacts any detected secret patterns. |
| **Rogue / Runaway Tool Loop** | Agent gets caught in an infinite loop executing repetitive paid API calls or modifying data. | Deterministic call counters, token budget hard ceilings, and loop circuit breakers (max 3 identical consecutive calls). |
| **Host System Compromise** | Malicious shell command or Python script attempts to access host OS, escape container, or read SSH keys. | All arbitrary code/shell tools run in isolated ephemeral Docker/Firejail sandboxes with read-only root and dropped capabilities. |

---

## 2. Deterministic Human-in-the-Loop (HITL) Protocol

```
+----------------------------------------------------------------------------------------------------+
|                                    HITL CRYPTOGRAPHIC FLOW                                         |
+----------------------------------------------------------------------------------------------------+
[Agent Runtime proposes High-Risk Tool Call: e.g. git_push()]
         │
         ▼
[1. Policy Engine generates Approval Token Payload]
    {
      "request_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
      "task_id": "4a12...",
      "tool_name": "git_push",
      "params_hash": SHA256(JSON_STRINGIFY(params)),
      "expires_at": 1759240000 (UTC Timestamp + 900s)
    }
         │
         ▼
[2. Sign Payload via HMAC-SHA256(SecretKey, Payload)]
         │
         ▼
[3. Save to PostgreSQL `approval_requests` (Status: PENDING)]
         │
         ▼
[4. Dispatch Real-time Notification to Web Dashboard (SSE/Push)]
         │
         ▼
[5. User reviews params in UI and clicks 'Approve']
         │
         ▼
[6. Dashboard submits POST /api/v1/approvals/{id}/resolve with Signed Token]
         │
         ▼
[7. Policy Engine verifies Signature, Expiration, and Parameter Hash match]
         │
         ▼
[8. Transition Status to APPROVED & Execute Tool with injected credentials]
```

---

## 3. Secret Management & Credential Isolation

* **Storage at Rest:** All third-party credentials (API keys, OAuth tokens, BYOK keys) are encrypted using **AES-256-GCM** (or cryptography Fernet with HMAC-SHA256 authentication) before storage in the PostgreSQL `credentials` and `integrations` tables.
* **Master Key Management:** The master encryption key is loaded strictly via environment variable (`AURA_MASTER_ENCRYPTION_KEY`) or local OS Keyring / Secret Service and is never stored in the database or committed to Git.
* **Ephemeral Ingestion:** Secrets are decrypted exclusively in-memory inside the `SecretInjectionProxy` at the exact moment of outbound request dispatch, stripped immediately after socket transmission, and sanitized from any telemetry, logs, or response payloads.
* **Key Fingerprinting:** To allow users to identify registered keys in the UI without exposing the underlying secret, AURA stores a SHA-256 key fingerprint (e.g., `AIza...4f8a`) representing only the prefix and cryptographic digest of the key.

---

## 4. Sandboxing & Process Isolation Architecture

```
+----------------------------------------------------------------------------------------------------+
|                                 AURA SANDBOX CONTAINER BOUNDARY                                    |
+----------------------------------------------------------------------------------------------------+
|  HOST SYSTEM (Linux / WSL2)                                                                        |
|  ├── User: `aura-runner` (UID 1001, unprivileged, no sudo)                                        |
|  ├── Docker / Firejail Sandbox Daemon                                                              |
|      │                                                                                             |
|      ▼ (Isolated Process Boundary)                                                                 |
|  ┌──────────────────────────────────────────────────────────────────────────────────────────────┐  |
|  │ SANDBOX CONTAINER (`aura-sandbox:latest`)                                                    │  |
|  │ ├── Read-Only Root Filesystem (`/`)                                                          │  |
|  │ ├── Ephemeral Working Directory (`/workspace/sandbox/` mounted with `noexec,nosuid,nodev`)  │  |
|  │ ├── Dropped Linux Capabilities: `CAP_SYS_ADMIN`, `CAP_NET_RAW`, `CAP_DAC_OVERRIDE`          │  |
|  │ ├── Resource Limits (cgroups): Max 2 vCPU, Max 1024MB RAM, Max 100 PIDs                     │  |
|  │ └── Outbound Network Filter: Restricted by default; domain-allowlisted via DNS proxy         │  |
|  └──────────────────────────────────────────────────────────────────────────────────────────────┘  |
+----------------------------------------------------------------------------------------------------+
```

---

## 5. Tamper-Evident Audit Ledger (Cryptographic Chaining)

Every security-sensitive event (tool execution, approval resolution, task cancellation, configuration update, credential creation/deletion) is written to the immutable `audit_logs` table in PostgreSQL using a blockchain-inspired hash chain:

$$\text{log\_hash}_N = \text{HMAC-SHA256}\left(\text{previous\_log\_hash}_{N-1} \,\|\, \text{id}_N \,\|\, \text{timestamp}_N \,\|\, \text{actor\_id}_N \,\|\, \text{action}_N \,\|\, \text{details\_json}_N\right)$$

* **Verification Utility:** An automated background job verifies the hash chain integrity daily. Any manual database tampering or row modification breaks the cryptographic chain and triggers an instant security alert.

---

## 6. Bring-Your-Own-Key (BYOK) Security & Google Gemini Guidelines

AURA enforces Google's official security recommendations and enterprise secret handling protocols for all BYOK cloud providers:

### 6.1 Strict Ingestion & Decoupling Invariants
1. **Zero Client-Side Exposure:** BYOK API keys submitted via the frontend dashboard are transmitted over TLS directly to the Control Plane backend (`POST /api/v1/credentials`), validated against the provider API, encrypted immediately in memory, and stored in `credentials`. Keys are **NEVER** returned in subsequent GET responses (only key fingerprints and validation timestamps are returned).
2. **Zero Prompt Contamination:** Credentials are never passed to the LLM context window, prompt templates, or system instructions.
3. **Backend-Mediated Proxy:** All model requests route through backend provider adapters (`GeminiProvider`, `OllamaProvider`). The frontend never makes direct client-side requests to Google or external model APIs.
4. **Key Scoping & Restrictions:** Users are guided to create API keys in Google AI Studio / Google Cloud Console restricted strictly to the Gemini API (`generativelanguage.googleapis.com`) with IP/domain restrictions where applicable.
5. **Instant Revocation & Zero-Trace Deletion:** When a user deletes a BYOK provider or credential (`DELETE /api/v1/credentials/{id}`), the encrypted ciphertext is immediately purged from PostgreSQL, memory caches are invalidated, and an immutable audit log entry is recorded.

---

## 7. Emergency Kill Switch & Multi-Process Governance (AURA-507)

AURA enforces a high-priority, globally authoritative emergency kill switch capable of aborting active execution loops across all subsystems within milliseconds:

* **Cross-Process Persistent Authority:** Kill state is synchronized across independent OS processes and daemon workers via atomic persistent state files (`~/.aura/kill_state.json`) with sub-millisecond mtime verification.
* **Managed Process Registry:** All OS-level subprocesses spawned by AURA (Python, Node.js, Playwright Chromium, MCP servers) are registered with process creation timestamps (`create_time`) to prevent accidental termination of unrelated host processes upon OS PID reuse.
* **Deep Process-Tree Termination:** On Windows 11 and Linux/POSIX, recursive process tree traversal enumerates and terminates parents, children, and grandchildren with multi-pass sweeps and kernel `taskkill /F /T` fallback.
* **Subsystem Coordination:** Canonical kill sequence atomically halts subagent workers, destroys active Docker sandbox containers, terminates registered OS process trees, closes Playwright Chromium browser instances, stops MCP servers, transitions database tasks to `cancelled`, and writes a SHA-256 audit ledger entry.
* **Race-Condition Immunity:** Pre-execution boundary gating blocks tool invocation, subagent dispatch, scheduler claiming, task retries, Telegram/Webhook ingress, and HITL approval resolution during active kill state.
* **Strict Endpoint RBAC:** System kill-switch trigger requires workspace membership; recovery reset (`POST /api/v1/system/kill-switch/reset`) requires workspace `owner`/`admin` role for tenant recovery and system administrative privileges for global recovery.
* **Explicit Recovery State Machine:** Normal execution is restored exclusively via authenticated operator recovery, reconciling process/sandbox registries and writing an `EMERGENCY_KILL_SWITCH_RECOVERED` audit log.

---

## 8. Universal File Ingestion Security Pipeline & Threat Mitigations (Phase 6)

Phase 6 implements a comprehensive defense-in-depth pipeline for untrusted multi-format files:

### 8.1 Canonical Ingestion Pipeline
$$\text{Upload} \longrightarrow \text{Auth/Workspace Verify} \longrightarrow \text{MIME/Magic Bytes} \longrightarrow \text{Resource Bounds} \longrightarrow \text{Isolated Storage} \longrightarrow \text{Safe Parser} \longrightarrow \text{Sanitization Envelope} \longrightarrow \text{Vectorization} \longrightarrow \text{Audit}$$

### 8.2 Authoritative Governance vs. Defense-in-Depth
* **Authoritative Execution Governance:** `ToolRegistryService` + `AgentToolBridge` + `PolicyEngine` + `HITLApprovalService` govern all agent tool operations and autonomy levels (L0–L5). File-derived content cannot alter policy or grant tool permissions.
* **Authoritative Filesystem/Tenant Boundary:** `WorkspaceFilesystemGuard` enforces workspace path confinement and blocks path traversal, UNC, symlinks, and drive-letter breakouts. Internal storage paths are strictly masked behind opaque UUIDs.
* **Authoritative Sandboxing:** `DockerSandboxManager` provides fail-closed container isolation when code analysis or untrusted container execution is required.
* **Defense-in-Depth:** `PromptSanitizer` wraps extracted document text in `<untrusted_external_content>` tags with escaped delimiters to prevent prompt injection.
* **Capability Layer:** `ParserEngine` operates strictly as an extraction capability service.

### 8.3 Security Guarantees & Threat Mitigations
1. **Zero Host Code Execution:** Uploaded files and code repositories are strictly treated as data. No uploaded code, script, binary, or formula macro is ever executed directly on the host OS.
2. **Filesystem Isolation & Path Privacy:** All files are stored under `{WORKSPACE_ROOT}/{workspace_id}/files/{file_id}/` validated by `WorkspaceFilesystemGuard`. UNC network paths, Windows drive-letter escapes, null bytes, and symlink breakout attempts fail closed. Internal host storage paths are never leaked to frontend, LLM context, or telemetry.
3. **Zip-Bomb Defense:** ZIP archive unpacking inspects compression ratios in a streaming buffer. Ratios exceeding 10:1, file counts > 500, or uncompressed sizes > 100 MB abort immediately with `ZipBombError`.
4. **Office Macro & Active Content Disabling:** Word (`python-docx`), Excel (`openpyxl`), and PowerPoint (`python-pptx`) parsers ignore and strip macros, OLE objects, and external XML entity (XXE) activations. Workbook formulas (e.g. `=SUM(...)`, `=HYPERLINK(...)`, `=WEBSERVICE(...)`) are preserved strictly as inert data without evaluation; dynamic entities and external links are never fetched or executed.
5. **Prompt-Injection Quarantine:** Extracted document text is normalized via NFKC homoglyph resolution, stripped of zero-width characters, and wrapped in `<untrusted_external_content source_type="file_extract" file_id="...">` envelopes.
### 8.4 Multi-Tenant Vector Indexing & Hybrid Retrieval Security (AURA-603)
1. **Multi-Tenant Isolation:** Every vector retrieval query strictly constrains `workspace_id = authenticated_workspace` alongside Row-Level Security (RLS) enforcement. Approximate HNSW graph traversal is never trusted as the sole isolation boundary.
2. **Quarantine & Deletion Exclusion:** Chunks belonging to `quarantined`, `delete_requested`, or `deleted` file records are filtered at the SQL query boundary prior to scoring.
3. **Atomic Generation Safety:** Staged indexing generates embeddings outside database transactions with optimistic generation UUIDs. Stale workers or concurrent reindex operations cannot overwrite newer generations.
4. **Delete/Reindex Race Prevention:** If a file record is marked `delete_requested` or `deleted` during Stage 1 chunk/vector generation, Stage 2 transaction aborts and fails closed. Vectors can never be resurrected on a deleted file.
5. **Memory Provenance & Tombstone Isolation:** Memory facts promoted from document chunks retain structured provenance (`file_id`, `chunk_id`, `chunk_index`, `workspace_id`). File deletion cascades tombstoning strictly scoped to `source_type = 'file_intelligence'` and matching `provenance.file_id`.
6. **Telemetry & Log Privacy:** Chunk generation, indexing, retrieval, and purge events are logged to the SHA-256 tamper-evident ledger with opaque IDs and counts. Raw document text, user queries, and vector floats are never exposed in logs or telemetry spans.

---

## 9. Multimodal Voice & Vision Security Boundary (Phases 7 & 8)

1. **Untrusted Spoken & Sensory Content:** All transcribed audio (Faster-Whisper) and OCR text (RapidOCR) are treated as untrusted external data and wrapped in `<untrusted_spoken_content>` or `<untrusted_multimodal_content>` XML envelopes. Spoken or visual directives cannot bypass `OSGuardService`, `PolicyEngine`, or HITL approval gates.
2. **Ephemeral Sensing Invariant:** Camera video streams and screen captures reside in a depth-1 volatile in-memory ring buffer. No continuous frames are written to persistent disk storage or database tables.
3. **Emergency Kill Switch Integration:** Triggering the emergency kill switch instantly aborts active audio streaming, active VLM inference, and purges all volatile sensory memory buffers in $<15\text{ ms}$.

---

## 10. Governed OS, Process & Hardware Automation Security Model (Phase 9)

Phase 9 implements an enterprise-grade deterministic boundary (`OSGuardService`) governing host operating system interaction:

1. **Deterministic Action Taxonomy & Risk Mapping:** 11 OS action types mapped to 5 risk tiers (`READ_ONLY`, `LOW_RISK_WRITE`, `MEDIUM_RISK_INTERACTION`, `HIGH_RISK_SYSTEM_ACTION`, `CRITICAL_ACTION`). High and Critical risk actions (e.g. process termination, application launch, volume/brightness modification, clipboard write) mandate HMAC-SHA256 HITL approvals with exact parameter hash binding.
2. **Application Allowlist & LOLBins Denial Filter:** Application execution enforces a strict canonical allowlist (`notepad`, `calc`, `mspaint`, `write`) and permanently denylist 20 Windows Living-off-the-Land Binaries (LOLBins, including `powershell.exe`, `cmd.exe`, `wscript.exe`, `certutil.exe`, `reg.exe`, etc.). Shell metacharacters (`&`, `|`, `;`, `>`, `<`, `$`, `%`) and NUL bytes are rejected fail-closed.
3. **TOCTOU Process Identity Verification:** Process inspection and termination require verifying PID and creation timestamp (`create_time` within $\pm 0.05\text{s}$) to prevent PID reuse attacks. Core OS processes and PID $\le 4$ kernel tasks are strictly protected from termination.
4. **Coordinate Safety & Stale Observation Guard:** Mouse coordinates are clamped to physical display monitor boundaries and window bounds. Screen observations expire after $5.0\text{s}$ TTL to prevent blind clicking on outdated UI state.
5. **Bounded Hardware & Clipboard Controls:** System volume and brightness adjustments are bounded to $\le \pm 10\%$ per step. Clipboard read/write is capped at 4,096 Unicode characters with automated secret scrubbing (JWT, API keys).
6. **System Tray & Physical Emergency Hotkey:** Windows Tray runs in a dedicated STA GUI process with Named Mutex single-instance protection. Physical hotkey (`Ctrl+Alt+Shift+K`) executes Win32 `RegisterHotKey` with sub-15ms trigger and 300ms software debounce. IPC control uses Windows Named Pipes with 256-bit CSPRNG token authentication and strict command allowlisting.

