# AURA Visual Identity System — AuraOrb (Agentic AI Face)

## 1. Overview & Purpose
**AuraOrb** is the authoritative animated visual presence and "Face of AURA" in the frontend application (`apps/web`). It embodies the cognitive and operational state of the AURA local-first agentic operating system through real-time particle dynamics, WebGL acceleration, and harmonic waveforms inspired by state-driven conversational visualizers.

---

## 2. Core Invariants & Architectural Boundaries
* **Strict Downstream Observer Architecture:**
  $$\text{Existing AURA Runtime} \longrightarrow \text{Existing API/Event/State} \longrightarrow \text{UI State Adapter} \longrightarrow \text{AuraOrb}$$
  AuraOrb **never** drives, invokes, or modifies runtime logic, tool execution, or security policies. It is purely a presentation-layer consumer of sanitized UI state.
* **Zero Backend Changes:** 100% frontend implementation. No modifications to `AgentToolBridge`, `ToolRegistryService`, HITL tokens, kill switch authority, vault, file transfer, session manager, or API contracts.
* **$0 Local-First Cost Floor:** Uses self-contained local WebGL/Canvas mathematical shaders with zero external rendering APIs, CDNs, or third-party cloud services.
* **Zero Secret Leakage:** No credentials, access tokens, API keys, or private payload secrets are accepted, stored, or processed by the visualizer.
* **Passive Audio Safety:** No microphone permissions are requested upon component mount. Audio reactivity is completely optional and gracefully falls back to synthetic cadence when unmetered.

---

## 3. Visual State Model (10 States)

| Visual State | Visual Intent & Topology | Primary Color / Glow | State Semantics & ARIA Description |
| :--- | :--- | :--- | :--- |
| `idle` | Organic spherical breathing motion; calm presence | Cyan (`#06B6D4`) | *AURA is idle and ready* |
| `listening` | Surface membrane ripples; responsive to acoustic input | Sky Blue (`#38BDF8`) | *AURA is listening for user input* |
| `thinking` | Dual-axis gyroscopic lattice rotation; structured lattice | Violet (`#8B5CF6`) | *AURA is thinking and synthesizing plan* |
| `searching` | Concentric orbital radar bands; scanning sweeps | Cyan / Indigo (`#06B6D4`, `#818CF8`) | *AURA is searching and gathering information* |
| `speaking` | Harmonic radial waveforms; vocal frequency displacement | Emerald (`#10B981`) | *AURA is speaking* |
| `done` | Settling outward flare decaying gently to idle | Emerald (`#10B981`) | *AURA completed task execution* |
| `waiting_for_approval` | Rhythmic amber beacon with slowly orbiting guard nodes | Amber / Gold (`#F59E0B`) | *AURA is waiting for human-in-the-loop approval* |
| `error` | Controlled jitter; localized crimson disturbance | Red / Rose (`#EF4444`) | *AURA encountered an error* |
| `degraded` | Muted slate cloud; reduced particle density | Slate (`#64748B`) | *AURA is operating in degraded mode* |
| `emergency_stop` | Absolute zero velocity; locked crimson containment shield | Crimson Red (`#EF4444`) | *AURA is stopped by emergency kill switch* |

---

## 4. Strict State Priority Hierarchy
Security and runtime ground truth always take precedence over cosmetic or conversational states:

$$\begin{aligned}
\text{EMERGENCY\_STOP} &\succ \text{WAITING\_FOR\_APPROVAL} \succ \text{ERROR} \succ \text{SPEAKING} \\
&\succ \text{SEARCHING} \succ \text{THINKING} \succ \text{LISTENING} \succ \text{DONE} \succ \text{DEGRADED} \succ \text{IDLE}
\end{aligned}$$

* If the emergency kill switch triggers while the assistant is speaking or searching, AuraOrb immediately freezes into `emergency_stop` within the same frame.
* If a task halts at a Human-In-The-Loop approval gate, `waiting_for_approval` overrides thinking and idle states until authorized.

---

## 5. WebGL & Canvas 2D Fallback Engine
* **Adaptive Particle Density:** Renders 700–2200 particles distributed via Fibonacci golden spiral lattice across a 3D unit sphere, scaling dynamically with viewport size and device pixel ratio (`dpr`).
* **High-Performance Canvas 2D Fallback:** Automatically activated if WebGL context creation fails, rendering 3D perspective projection with additive alpha composite blending.
* **Lifecycle & Memory Safety:**
  - Full resource disposal on unmount (`gl.deleteProgram`, `gl.deleteBuffer`, `cancelAnimationFrame`, `ResizeObserver.disconnect`).
  - Automatic animation pausing when browser tab is inactive (`document.visibilityState === 'hidden'`), eliminating background CPU/GPU drain.
  - `prefers-reduced-motion` compliance: automatically slows/freezes dynamic turbulence into a serene static orb.

---

## 6. Component API Reference

```tsx
import { AuraOrb, deriveVisualState } from '@/components/aura/AuraOrb';

// Declarative Rendering
<AuraOrb
  state={deriveVisualState({
    killSwitchActive: false,
    pendingApprovalsCount: 0,
    voiceState: 'SPEAKING',
  })}
  size={160}
  showStatusBadge={true}
  showCaption={true}
  caption="Autonomous goal dispatched to sandboxed cognitive worker pool."
/>
```

---

## 7. Verification Evidence
* **Frontend Vitest Suite:** `50/50 PASS` (`tests/frontend.test.ts` + `tests/auraOrb.test.ts`)
* **Next.js 15 Production Build:** `PASS` (`Compiled successfully in 11.6s`, static routes generated)
* **Backend Pytest Regression Suite:** `880/880 PASS` across all subsystems (100% non-regression)
