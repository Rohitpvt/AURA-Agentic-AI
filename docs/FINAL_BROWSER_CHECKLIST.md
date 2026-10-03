# Release & Browser Verification Checklist (FINAL_BROWSER_CHECKLIST.md)
## Project Name: AURA (Autonomous Universal Reactive Agent)
**Document Version:** 1.0.0  
**Phase:** Phase 0.5 — Documentation Reconciliation & Consistency Audit  
**Classification:** Pre-Release QA & End-to-End Browser Testing Protocol  

---

## 1. Authentication & Session Verification

- [ ] **Login Flow:** User can authenticate using valid email/password credentials; invalid credentials display clear error.
- [ ] **JWT Storage:** Access tokens are stored securely in memory / HTTP-only cookies; refresh token cycle succeeds without session interruption.
- [ ] **Workspace Switcher:** Switching between workspaces updates the tenant context across all active queries and SSE listeners.
- [ ] **Session Archiving:** User can create, rename, and archive conversation sessions from the sidebar.

---

## 2. Interactive Chat & Real-Time SSE Streaming

- [ ] **Token Streaming:** Real-time text generation streams with time-to-first-token $\le 100\text{ ms}$ without UI stutter.
- [ ] **Thought Process Accordion:** Cognitive reasoning chunks display in a collapsible violet accordion with execution timer.
- [ ] **Inline Tool Cards:** Low/Medium risk tool executions render interactive summary cards with input/output payloads.
- [ ] **Auto-Scroll Behavior:** Chat window sticks to bottom during active streaming; pauses auto-scroll when user manually scrolls up.

---

## 3. Tasks, DAG Visualizer & Checkpoints

- [ ] **Task Dispatch:** Submitting a high-level goal in `/tasks` generates a multi-step DAG plan within $\le 3\text{ seconds}$.
- [ ] **Live Node Transitions:** DAG step nodes dynamically transition colors (`Pending` $\rightarrow$ `Executing` (Cyan pulse) $\rightarrow$ `Verified` (Emerald) or `Failed` (Rose)).
- [ ] **Step Output Inspector:** Clicking any DAG node opens a drawer displaying exact tool input/output JSON and verification assertions.
- [ ] **Manual Step Retry:** User can click "Retry Step" on a failed DAG node to re-trigger execution from the last committed checkpoint.

---

## 4. Human-in-the-Loop (HITL) Approval Drawer

- [ ] **Trigger Alert:** Proposing a High-Risk tool (e.g. `git_push`, `delete_file`) immediately opens the **Approval Drawer** and plays an alert tone.
- [ ] **Parameter Introspection:** Displays side-by-side JSON diff and clear plain-English risk justification.
- [ ] **Countdown Expiry:** 15-minute TTL countdown timer ticks down; gracefully transitions to `EXPIRED` if unattended.
- [ ] **Cryptographic Resolution:** Clicking "Approve" sends the signed token; agent resumes execution within $\le 500\text{ ms}$.

---

## 5. Sub-Agents, Memory & Skills

- [ ] **Sub-Agent Pool:** Displays active worker cards (Research, Coding, Synthesis) with live token consumption progress bars.
- [ ] **Memory Graph:** Renders extracted user preferences and facts; clicking "Delete" tombstones the fact and un-indexes from Honcho.
- [ ] **Skill Editor:** Monaco editor renders `SKILL.md` with syntax highlighting, YAML frontmatter validation, and version history diffs.

---

## 6. Automations & Audit Ledger

- [ ] **Cron Automation CRUD:** User can create, edit, pause, and delete recurring Cron schedules with human-readable previews.
- [ ] **Webhook Copy:** Inbound webhook URL and HMAC shared secret can be copied with one-click copy buttons.
- [ ] **Audit Hash Chain:** Audit log displays green "Hash Verified" badge indicating tamper-evident blockchain integrity.

---

## 7. Responsive Design, Accessibility & Emergency Controls

- [ ] **Dark Mode Aesthetics:** Verify consistent Tailwind slate/obsidian palette, glassmorphism borders, and zero white flashes.
- [ ] **Mobile & Tablet:** Navigation collapses cleanly into mobile bottom drawer on viewport $<768\text{px}$.
- [ ] **WCAG 2.1 AA Compliance:** Color contrast $\ge 4.5:1$ across all text; full keyboard navigation supported (Tab / Enter / Esc).
- [ ] **Emergency Kill Switch:** Clicking the Red Kill Switch immediately terminates all active agent tasks and workers in $<500\text{ ms}$.
