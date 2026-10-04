# Tool Architecture & Registry Specification (TOOL_ARCHITECTURE.md)
## Project Name: AURA (Autonomous Universal Reactive Agent)
**Document Version:** 1.0.0  
**Phase:** Phase 0 — Architecture & Foundation  
**Classification:** Tool Execution & Extensibility Architecture  

---

## 1. Conceptual Taxonomy: Tools vs. Skills vs. Sub-Agents

To ensure absolute architectural clarity, AURA establishes rigid conceptual boundaries:

| Concept | Definition | Execution Unit | Statefulness | Example |
| :--- | :--- | :--- | :--- | :--- |
| **TOOL** | An **atomic capability** that performs a single deterministic input $\rightarrow$ output operation or side-effect. | Deterministic function / API call / MCP command. | Stateless. | `github_create_issue`, `web_search`, `read_file_content`. |
| **SKILL** | A **versioned procedural recipe** combining multiple tools, prompts, assertions, and domain heuristics into a reusable workflow. | Markdown / YAML specification (`SKILL.md`) parsed by runtime. | Stateful orchestration across turns. | `repo_security_audit`, `daily_executive_brief`, `pr_code_review`. |
| **SUB-AGENT** | An **isolated reasoning worker** with its own bounded context window, budget, and tool access, dispatched by the Master Supervisor. | Autonomous LLM loop running within runtime sandbox. | Stateful cognitive worker. | `Research Agent`, `Coding Agent`, `Synthesis Agent`. |

---

## 2. Tool Registry Specification & Schema

Every tool registered in AURA must define complete metadata compliant with the following specification:

```typescript
interface ToolDefinition {
  name: string; // Unique identifier: e.g. "github_create_issue"
  displayName: string; // Human-readable name: e.g. "Create GitHub Issue"
  description: string; // Precise LLM instruction describing purpose & when to call
  category: "web" | "code" | "file" | "comms" | "database" | "system";
  provider: "native" | "mcp_server" | "custom_script";
  riskLevel: "low" | "medium" | "high" | "critical";
  inputSchema: Record<string, any>; // JSON Schema / OpenAPI 3.1 parameter definitions
  outputSchema: Record<string, any>; // Expected output structure
  timeoutSeconds: number; // Max execution time (default: 30s)
  rateLimitPerMinute: number; // Max calls per minute
  requiresApproval: boolean; // Overrides risk level if true
  isAllowedInBackground: boolean; // Permitted during autonomous Cron/Webhook runs
  requiredSecrets: string[]; // List of secret keys injected by proxy (e.g. ["GITHUB_TOKEN"])
}
```

---

## 3. Four-Tier Risk Classification & Policy Engine

AURA enforces a deterministic risk model. An LLM cannot execute tools with risk beyond the session's pre-authorized policy without triggering a Human-in-the-Loop (HITL) gate.

```
+----------------------------------------------------------------------------------------------------+
|                                    FOUR-TIER RISK CLASSIFICATION                                   |
+-------------------+-----------------------------+-----------------------+--------------------------+
| RISK TIER         | DESCRIPTION                 | EXECUTION POLICY      | EXAMPLES                 |
+-------------------+-----------------------------+-----------------------+--------------------------+
| 1. LOW            | Read-only operations with   | Auto-execute;         | web_search, read_file,   |
|                   | no external side effects.   | Log to traces.        | list_dir, get_calendar.  |
+-------------------+-----------------------------+-----------------------+--------------------------+
| 2. MEDIUM         | Non-destructive write /     | Auto-execute if L>=2; | write_file (workspace),  |
|                   | sandboxed headless browser. | Notify dashboard.     | web_extract (Playwright),|
|                   |                             |                       | create_issue, add_event. |
+-------------------+-----------------------------+-----------------------+--------------------------+
| 3. HIGH           | External side effects or    | SUSPEND EXECUTION;    | send_email, git_push,    |
|                   | permanent modifications.    | Require signed token. | send_slack_message.      |
+-------------------+-----------------------------+-----------------------+--------------------------+
| 4. CRITICAL       | Destructive actions or host | HARD BLOCK in auto;   | delete_database_table,   |
|                   | system commands.            | Multi-factor approval.| execute_raw_shell_root.  |
+-------------------+-----------------------------+-----------------------+--------------------------+
```

---

## 3.1. Built-in Headless Web Extraction (`web_extract`)

AURA provides local zero-cost headless web extraction powered by Playwright Chromium:

* **Name:** `web_extract`
* **Risk Tier:** `Medium`
* **Execution Boundary:** Ephemeral, non-persistent `BrowserContext` (`accept_downloads=False`, `service_workers='block'`, `permissions=[]`).
* **SSRF Governance:** 3-layer defense (Pre-navigation URL validation, navigation redirect interception, and subresource request route filtering).
* **Resource Quotas:** Max 2 concurrent extractions, max 5 MB content budget, max 30s timeout, max 10 redirects.
* **Untrusted Content:** All extracted Markdown/text is encapsulated in an untrusted content envelope (`is_untrusted_content = True`).

---

## 4. Secret Injection Proxy (Credential Isolation)

**Security Invariant:** Large Language Models and untrusted MCP scripts must *never* have direct access to raw API keys, OAuth tokens, or database passwords.

```
[LLM Runtime]
      │
      │ 1. Invokes: tool_call("github_create_issue", { title: "Fix bug", body: "..." })
      ▼ (No Secrets in LLM Payload)
[AURA Secret Injection Proxy]
      │
      │ 2. Authenticates Task & Workspace ID
      │ 3. Fetches Encrypted Secret from PostgreSQL / Vault
      │ 4. Decrypts via AES-256-GCM in Ephemeral Memory
      │ 5. Injects: Header "Authorization: Bearer ghp_98124..."
      ▼
[External API / GitHub MCP Server]
      │
      │ 6. Executes and returns data
      ▼
[AURA Output Redactor & Sanitizer]
      │ (Masks any accidental token reflection)
      ▼
[LLM Runtime Context]
```

---

## 5. Sandboxed Execution Engine

All tool calls involving code execution (Python, Node.js) or shell command evaluation are isolated from the host operating system:

1. **Local Development (WSL2 / Docker Desktop):**
   * Commands run inside ephemeral Docker containers (`aura-sandbox:latest`) mounted with a read-only root and a temporary volume scoped strictly to `./workspace/sandbox/`.
2. **Production Linux (Firejail / cgroups / gVisor):**
   * Restricted network namespace (no outbound access except approved package registries).
   * Strict CPU cap (max 2 cores) and memory ceiling (max 1 GB RAM).
   * Ephemeral file system automatically wiped upon process termination.

---

## 6. Phase 6 File Intelligence Tools

Phase 6 registers native, governed file analysis capabilities in the `ToolRegistryService`:

| Tool Name | Display Name | Category | Risk Level | Description | Input Parameters |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `inspect_file` | Inspect File Metadata | `file` | `low` | Read file metadata, page/sheet structure, and preview text. | `file_id: string`, `max_lines?: int` |
| `summarize_document` | Summarize Document | `file` | `low` | Generate structured summary of a multi-page PDF or Word document. | `file_id: string`, `focus_topic?: string` |
| `analyze_spreadsheet` | Analyze Spreadsheet | `file` | `low` | Inspect spreadsheet sheets, headers, cell matrices, and statistical distributions. | `file_id: string`, `sheet_name?: string`, `cell_range?: string` |
| `codebase_analysis` | Codebase Analysis | `code` | `low` | Analyze structural symbols, imports, functions, and file hierarchy from a codebase ZIP. | `file_id: string`, `target_language?: string` |
| `search_files` | Search Workspace Files | `file` | `low` | Perform hybrid dense (FastEmbed 768-dim) + lexical search across all ingested workspace files. | `query: string`, `top_k?: int`, `file_id?: string` |

All file intelligence tools operate strictly in read-only mode and output results wrapped in `<untrusted_external_content>` envelopes.

---

## 7. Multimodal Vision & Sensory Inspection Tools (Phases 7 & 8)

Multimodal vision tools are registered in the `ToolRegistryService` and governed strictly through `AgentToolBridge` and `PolicyEngine`. Continuous sensors (screen frame grabbers, camera WebSockets, background OCR engines) run as passive capability infrastructure and are NOT exposed as generic agent tools.

Only explicit inspection queries are governed tools:

| Tool Name | Display Name | Category | Risk Level | Description | Input Parameters | Phase |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `inspect_image` | Inspect Static Workspace Image | `vision` | `low` | Inspects an uploaded static image file via local VLM (Moondream2) or OCR. | `file_id: string`, `prompt?: string` | Phase 7 |
| `inspect_current_screen` | Inspect Current Desktop Screen | `vision` | `low` | Captures a high-resolution snapshot of the desktop, executes OCR and VLM reasoning. | `monitor_id?: int`, `prompt?: string` | Phase 8 |
| `inspect_active_window` | Inspect Active Application Window | `vision` | `low` | Crops capture bounds to the active foreground window rectangle and extracts content. | `prompt?: string` | Phase 8 |
| `inspect_camera_frame` | Inspect Live Camera Frame | `vision` | `low` | Ingests the latest ephemeral webcam frame from the video buffer for VLM analysis. | `prompt?: string` | Phase 8 |
| `query_visible_text` | Query Visible Screen / Window Text | `vision` | `low` | Executes targeted local OCR across the screen or ROI to extract text and bounding boxes. | `roi?: object`, `filter_query?: string` | Phase 8 |

All vision inspection tools operate in read-only mode and output data strictly wrapped in `<untrusted_multimodal_content>` XML envelopes.


