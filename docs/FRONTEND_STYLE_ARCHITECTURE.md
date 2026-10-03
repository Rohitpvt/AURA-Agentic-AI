# Frontend Style Architecture & Design System (FRONTEND_STYLE_ARCHITECTURE.md)
## Project Name: AURA (Autonomous Universal Reactive Agent)
**Document Version:** 1.0.0  
**Phase:** Phase 0.5 — Documentation Reconciliation & Consistency Audit  
**Classification:** Visual Design System, Design Tokens & Component Styling  

---

## 1. Design System Philosophy & Aesthetic Principles

AURA is engineered with a **command-center aesthetic**: dark-mode first, high information density, sleek glassmorphism accents, and crystal-clear visual hierarchy. It avoids whimsical decorations in favor of authoritative, real-time telemetry representation.

> [!NOTE]
> For information architecture, routing, state management, and API data-fetching architecture, consult [**FRONTEND_ARCHITECTURE.md**](file:///C:/Users/rghos/OneDrive%20-%20Vivekananda%20Institute%20of%20Professional%20Studies/PROJECTS/Agentic%20AI/docs/FRONTEND_ARCHITECTURE.md).

---

## 2. Design Tokens & Color Palette

### 2.1 Background & Surface Tokens (Dark Mode Baseline)
* `--aura-bg-canvas`: `#090D16` (Deep Obsidian / Black-Blue)
* `--aura-bg-surface`: `#111726` (Sleek Slate Layer 1)
* `--aura-bg-elevated`: `#192238` (Elevated Card / Modal Surface)
* `--aura-bg-subtle`: `#222E4B` (Hover / Active Background)
* `--aura-border-subtle`: `rgba(255, 255, 255, 0.08)` (Fine Hairline Border)
* `--aura-border-strong`: `rgba(255, 255, 255, 0.16)` (Selected / Focused Border)

### 2.2 Semantic & Risk Tokens
* **Primary / Accent:** `--aura-accent-cyan`: `#06B6D4` (Cyan 500 — Active Agent / Primary Buttons)
* **Reasoning / Cognitive:** `--aura-cognitive-violet`: `#8B5CF6` (Violet 500 — Planner / Thought Process)
* **Risk Tier: LOW:** `--aura-risk-low`: `#10B981` (Emerald 500 — Auto-executed / Safe)
* **Risk Tier: MEDIUM:** `--aura-risk-med`: `#3B82F6` (Blue 500 — Workspace Writes / Notified)
* **Risk Tier: HIGH:** `--aura-risk-high`: `#F59E0B` (Amber 500 — Approval Gate / External Side Effects)
* **Risk Tier: CRITICAL:** `--aura-risk-crit`: `#EF4444` (Rose 500 — Destructive Actions / Kill Switch)

---

## 3. Typography Hierarchy

* **UI & Body Typography:** `Inter`, system-ui, -apple-system, sans-serif.
  * Weights: `400` (Regular), `500` (Medium), `600` (Semi-Bold), `700` (Bold).
* **Code, Logs & Telemetry:** `JetBrains Mono`, `Fira Code`, monospace.
  * Used for: Tool payloads, diff previews, audit hashes, prompt envelopes, and DAG step inputs/outputs.

| Scale | Size / Line Height | Font Family | Usage |
| :--- | :--- | :--- | :--- |
| **Display 1** | 28px / 36px (Bold) | `Inter` | Page Headers / Main Dashboard Metrics |
| **Heading 2** | 20px / 28px (Semi-Bold)| `Inter` | Section Titles, View Headers |
| **Heading 3** | 16px / 24px (Medium) | `Inter` | Card Headers, Modal Titles |
| **Body Standard** | 14px / 20px (Regular) | `Inter` | Chat Text, Task Descriptions, Form Inputs |
| **Body Small** | 12px / 16px (Regular) | `Inter` | Metadata, Timestamps, Badges |
| **Code / Log** | 13px / 20px (Regular) | `JetBrains Mono` | Tool Payloads, JSON Viewer, Terminal Logs |

---

## 4. Component Visual Rules & States

### 4.1 Risk Badges
```html
<!-- Risk Low Badge -->
<span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-mono bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">LOW</span>

<!-- Risk High Badge (Requires HITL) -->
<span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-mono bg-amber-500/10 text-amber-400 border border-amber-500/30 animate-pulse">HIGH APPROVAL</span>
```

### 4.2 Interactive DAG Nodes
* **Pending:** Border dashed `rgba(255,255,255,0.15)`, text muted `slate-400`.
* **Executing:** Border solid `cyan-500`, background `cyan-500/10`, cyan subtle pulse animation.
* **Awaiting Approval:** Border solid `amber-500`, background `amber-500/10`, glowing amber ring.
* **Completed / Verified:** Border solid `emerald-500/40`, background `emerald-500/5`, emerald check icon.
* **Failed:** Border solid `rose-500`, background `rose-500/10`, rose warning icon.

---

## 5. Accessibility & Responsive Standards

* **Contrast Ratio:** All body text meets WCAG 2.1 AA standards ($\ge 4.5:1$ contrast against dark background).
* **Focus States:** Every interactive button and input displays an explicit focus ring (`focus-visible:ring-2 focus-visible:ring-cyan-500`).
* **Responsive Breakpoints:**
  * **Desktop (Command Center):** $\ge 1280\text{px}$ (3-column layout: Nav Sidebar + Main Workspace + Telemetry/Inspector Drawer).
  * **Tablet (Focused Ops):** $768\text{px} - 1279\text{px}$ (2-column layout with collapsible inspector).
  * **Mobile (Notification & Approval):** $< 768\text{px}$ (Single-column layout with bottom navigation drawer optimized for quick HITL approvals and status checking).
