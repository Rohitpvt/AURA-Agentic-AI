# Frontend Information Architecture & Design Specification (FRONTEND_ARCHITECTURE.md)
## Project Name: AURA (Autonomous Universal Reactive Agent)
**Document Version:** 1.0.0  
**Phase:** Phase 0 — Architecture & Foundation  
**Classification:** Frontend UI/UX & Information Architecture  

---

## 1. Information Architecture & Navigation Topology

The AURA Web Dashboard is structured as an authoritative Command Center representing the agent's real-time state:

```
+====================================================================================================+
|                                    AURA NAVIGATION STRUCTURE                                       |
+====================================================================================================+
|                                                                                                    |
|  [CORE WORKSPACE]                [AGENTIC OPERATIONS]               [SYSTEM & GOVERNANCE]         |
|  ├── 1. Dashboard (Overview)     ├── 5. Sub-Agents (Worker Pool)    ├── 9. Integrations (MCP/API)  |
|  ├── 2. Chat & Copilot (Direct)  ├── 6. Memory Graph (Cognitive)    ├── 10. Approvals (HITL Gate)  |
|  ├── 3. Tasks & Plans (DAG View) ├── 7. Skills Store & Editor       ├── 11. Activity & Audit Logs  |
|  ├── 4. Automations (Cron/Hooks) ├── 8. Tool Registry (Schemas)     ├── 12. Settings & Policies    |
|                                                                                                    |
+====================================================================================================+
```

---

## 2. Core View Specifications

| View Name | Primary Functionality & Interactive Elements | State & Data Requirements |
| :--- | :--- | :--- |
| **1. Dashboard** | Executive summary: active tasks, upcoming scheduled runs, pending approvals badge, token/cost burn meter, system health status. | Aggregated stats via TanStack Query (5s poll / SSE update). |
| **2. Chat & Copilot** | Real-time conversational interface with streaming token responses, inline tool execution cards, thought-trace collapsible accordions. | SSE stream `/api/v1/sessions/{id}/stream` + optimistic turn updates. |
| **3. Tasks & Plans** | Visual DAG execution graph showing plan steps, status badges (Pending, Executing, Verified, Failed), step outputs, and manual retry triggers. | Real-time WebSocket task progress + step checkpoint tree. |
| **4. Automations** | Manage recurring Cron jobs, webhook endpoints, trigger schedules, delivery channels, and run histories. | Full CRUD over `automations` table + webhook secret generator. |
| **5. Sub-Agents** | Live visualizer of active worker pool (Research, Coding, Analysis, Synthesis), assigned token budgets, and sub-task outputs. | Dynamic worker card grid with live token consumption progress bars. |
| **6. Memory Graph** | Interactive visualization of Honcho user modeling, personal traits, project facts, with direct inline edit/tombstone capabilities. | Filterable data table + semantic network graph view. |
| **7. File Intelligence** | Drag-and-drop universal file upload, document list, processing status, document preview, structural chunk inspector, and Q&A chat drawer. | Multi-part upload progress, TanStack Query `/api/v1/files`, SSE extraction status. |
| **8. Skills Editor** | Markdown editor for `SKILL.md` packages, YAML metadata validator, version history diff viewer, and promotion review queue. | Monaco Editor / Markdown preview + SemVer release manager. |
| **9. Tool Registry** | Interactive catalogue of registered tools, JSON Schema viewer, risk level badges, rate limit monitors, and manual test runners. | Schema introspection view with copyable parameter templates. |
| **10. Integrations** | Manage MCP servers (`stdio`/`SSE`), API credentials, OAuth connections (GitHub, Google), and connection health diagnostics. | Encrypted credential submission modals + MCP status pings. |
| **11. Approval Center** | Critical HITL review drawer: side-by-side view of requested tool action, exact parameters, risk justification, and Approve/Reject controls. | High-priority SSE event trigger with audio alert & countdown timer. |
| **12. Audit Ledger** | Filterable, tamper-evident log viewer with cryptographic hash validation indicators and full actor/timestamp attribution. | Paginated server-side table with JSON details drawer. |
| **13. Settings** | Model routing configuration, default autonomy levels, budget hard ceilings, API key management, and Emergency Kill Switch. | Form validation with instant confirmation dialogs for kill switch. |


---

## 3. Frontend Architecture & Technology Decisions

* **Framework:** Next.js 15+ with App Router (`/app`), React Server Components (RSC) for initial page hydration, and Client Components for dynamic real-time interfaces.
* **Language & Types:** TypeScript 5.5+ with strict mode enabled; all API contracts generated from backend Pydantic schemas via OpenAPI TypeScript codegen.
* **Styling & Design System:** Tailwind CSS v4 with curated design tokens (Tailored Slate/Zinc palette, dark mode by default, subtle glassmorphism borders, accessible typography via `Inter` & `JetBrains Mono`).
* **State Management:**
  * Server State: TanStack Query v5 (React Query) for caching, background refetching, and query invalidation.
  * Ephemeral UI State: Zustand for local layout state (sidebar toggle, active tabs, modal drawers).
  * Streaming State: Custom React hook (`useSSEStream`) handling auto-reconnect, JSON parsing, and token buffering.
* **Component Primitives:** Radix UI / Shadcn UI accessible primitives for dialogs, dropdowns, tooltips, and sliders.
