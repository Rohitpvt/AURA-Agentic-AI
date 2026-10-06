# Integration Plan & Zero-Cost Strategy (INTEGRATION_PLAN.md)
## Project Name: AURA (Autonomous Universal Reactive Agent)
**Document Version:** 9.6.0  
**Phase:** Phase 9 — Governed OS & Hardware Automation (COMPLETE & ACCEPTED) | Phase 1–9 Master Validated  
**Classification:** Third-Party Integrations & Zero-Cost Protocol Strategy  

---

## 1. Zero-Cost Integration Matrix (Phase 1 MVP)

Every core integration in AURA operates **100% free of charge** without mandatory paid APIs, cloud subscriptions, or credit cards:

| Integration | Free / Local Protocol | Authentication | Read Capabilities | Write Capabilities | Cost Category | Approval Required? |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1. Web Search & Scraping** | **DuckDuckGo Search (`duckduckgo-search`) + Playwright Headless** | None (Zero API Key) | Search queries, web page text extraction, markdown conversion. | None (Read-only). | **100% FREE SOFTWARE / NO BILLING** | No (Auto) |
| **2. GitHub Developer** | **Git CLI + GitHub REST API (MCP Server)** | Free Personal Access Token (PAT) | List repos, read code, view PRs/issues, fetch diffs, search code. | Create issues, add comments, create PR branches, commit code. | **FREE API (No billing required for standard PAT)** | Write = Yes; Read = No |
| **3. Sandboxed Filesystem** | **Local Scoped Workspace MCP (`stdio`)** | Path Jail Boundary (`/workspace/data/`) | Read files, list directories, search files via ripgrep. | Create files, edit file lines, delete scratch files. | **100% LOCAL / FREE** | Delete = Yes; Edit = No |
| **4. Calendar & Scheduling** | **Local CalDAV / SQLite Calendar or Free Google OAuth2** | Local DB / Free Google Cloud OAuth Client ID | Fetch events, check availability, read attendee details. | Create calendar events, update event times, delete meetings. | **100% FREE (Zero billing required on Google Cloud OAuth)** | Delete = Yes; Create = No |
| **5. Email Communications** | **Standard IMAP / SMTP (Python `aioimaplib` / `aiosmtplib`)** | Scoped App Password (e.g. Gmail / Fastmail / Local Mail) | Fetch unread messages, search threads, extract attachments. | Draft emails, send email messages, flag/archive threads. | **100% FREE STANDARD PROTOCOL** | **Send = ALWAYS YES (HITL)** |

---

## 2. Zero-Cost Web Retrieval Deep-Dive

To eliminate paid search API dependencies (Tavily/SerpAPI), AURA implements a local two-step retrieval pipeline:

```
[Agent Requests Web Search: e.g. "Latest PostgreSQL 16 vector benchmarks"]
                               │
                               ▼
[1. DuckDuckGo Search / Local SearXNG Meta-Search]
  - Invokes `duckduckgo_search.DDGS().text(query, max_results=5)`
  - Returns top-5 URLs, titles, and snippets in <800ms with ZERO API keys
                               │
                               ▼
[2. Playwright Headless Web Scraper (Python)]
  - Spawns local headless Chromium instance
  - Navigates to target URL with 10s timeout
  - Strips `<script>`, `<style>`, `<nav>`, `<footer>` tags
  - Converts clean DOM into markdown text
                               │
                               ▼
[3. Ingest Clean Markdown Context into Local LLM Window]
```

---

## 3. Model Context Protocol (MCP) Local Execution Blueprint

```
+====================================================================================================+
|                                  LOCAL MCP CLIENT ARCHITECTURE                                     |
+====================================================================================================+
|  AURA CONTROL PLANE (FastAPI)                                                                      |
|  ├── MCP Subprocess Host (`stdio` transport)                                                       |
|  │   ├── GitHub MCP Server (`npx -y @modelcontextprotocol/server-github`)                          |
|  │   ├── Filesystem MCP Server (`npx -y @modelcontextprotocol/server-filesystem ./workspace`)     |
|  │   └── PostgreSQL MCP Server (`npx -y @modelcontextprotocol/server-postgres`)                    |
|  │                                                                                                 |
|  └── Dynamic Tool Filter (Exposes only workspace-approved tools to local Ollama context)           |
+----------------------------------------------------------------------------------------------------+
```

---

## 4. Google Gemini Bring-Your-Own-Key (BYOK) Adapter

The Google Gemini adapter allows users to connect their own Google AI Studio / Vertex AI credentials to AURA as an optional Tier-3 provider without violating the Zero-Cost Local-First core architecture.

### 4.1 Specification & Protocol
* **Authentication Method:** Backend-only HTTP header `x-goog-api-key` or Bearer Token. Never exposed to frontend or stored in plaintext.
* **SDK / Transport:** `google-genai` Python SDK or direct HTTP client targeting:
  - Base URL: `https://generativelanguage.googleapis.com/v1beta/`
  - OpenAI Compatibility Endpoint: `https://generativelanguage.googleapis.com/v1beta/openai/chat/completions`
* **Supported Models (Verified Active Google Documentation):**
  - `gemini-2.5-flash`: Primary high-speed reasoning & tool execution (1M token context window).
  - `gemini-2.5-pro`: Deep analytical decomposition and advanced coding (2M token context window).
  - *(Decommissioned models: gemini-2.0-flash, gemini-1.5-flash, gemini-1.5-pro are retired from active baseline)*
* **Cost & Quota Transparency:**
  - Free Tier: Google AI Studio provides rate-limited free tiers (RPM/RPD limits).
  - Billable Tier: Google Cloud Pay-As-You-Go accounts incur usage fees directly from Google.
  - AURA enforces task token budgets and provides explicit UI billing badges.
* **Error & Fallback Handling:**
  - HTTP 429 (Rate Limit / Quota Exceeded) $\rightarrow$ Instantly falls back to local Ollama without task failure.
  - HTTP 401/403 (Invalid / Revoked Key) $\rightarrow$ Marks credential invalid in DB, logs security audit, falls back to local Ollama.

