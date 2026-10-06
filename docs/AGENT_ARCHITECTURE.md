# Agent Architecture & Runtime Specification (AGENT_ARCHITECTURE.md)
## Project Name: AURA (Autonomous Universal Reactive Agent)
**Document Version:** 9.6.0  
**Phase:** Phase 9 — Governed OS & Hardware Automation (COMPLETE & ACCEPTED) | Phase 1–9 Master Validated  
**Classification:** Local Cognitive Runtime & Multi-Agent Architecture  

---

## 1. Local Agentic Cognitive Loop

The core execution cycle of AURA translates raw goals into verified state transitions through a 10-stage deterministic-cognitive loop running 100% locally:

```
[1. GOAL INGESTION]
       │
       ▼
[2. CONTEXT HYDRATION & LOCAL MEMORY RECALL] (Postgres HNSW Vector + FTS Query)
       │
       ▼
[3. DECOMPOSITION & PLAN DAG GENERATION] (Ollama: `qwen2.5:7b` / `deepseek-r1:7b`)
       │
       ▼
[4. DETERMINISTIC RISK EVALUATION] (Local Python Policy Gate: Low/Med/High/Critical)
       │
  ┌────┴────────────────────────┐
  ▼                             ▼
[5a. PASS: EXECUTE STEP]     [5b. SUSPEND: HUMAN APPROVAL REQUIRED]
  │                             │ (User Approves Signed Token in UI)
  │                             ▼
  ├─────────────────────────────┘
  ▼
[6. LOCAL TOOL / SUB-AGENT DISPATCH] (Sandboxed MCP / Ephemeral Docker)
       │
       ▼
[7. OBSERVATION & RESULT SANITIZATION]
       │
       ▼
[8. DYNAMIC ADAPTATION & RE-PLANNING] (If error or unexpected output)
       │
       ▼
[9. FORMAL VERIFICATION & ASSERTION CHECK]
       │
       ▼
[10. LOCAL MEMORY WRITEBACK & RESULT NOTIFICATION]
```

---

## 2. Hermes Agent Engine: Zero-Cost Local Substrate

We evaluate and configure the **Hermes Agent framework (Nous Research)** as the local execution substrate.

### 2.1 Capability Evaluation & Local Integration Boundary

| Hermes Capability | Local Implementation | Zero-Cost Invariant Compliance |
| :--- | :--- | :--- |
| **Procedural Skill Learning (`SKILL.md`)** | Directly Reused | 100% Free / File-based. Skills saved in `./skills/` and PostgreSQL. |
| **Local Model Execution** | Ollama Local Endpoint (`http://localhost:11434/v1`) | **100% Free / Zero API Billing.** No Nous Portal cloud account needed. |
| **Tool Calling & MCP** | Local Python Tool Registry & Local MCP `stdio` | 100% Free / Local subprocess execution. |
| **Terminal / Host Isolation** | Ephemeral Docker / Firejail Sandboxes | 100% Free / Local container isolation. |
| **Cognitive Memory** | Replaced with local PostgreSQL + `pgvector` + FastEmbed | **100% Free / Zero SaaS dependency.** |

---

## 3. Local Hardware-Adaptive Model Tiering Matrix

AURA abstracts model selection across four functional tiers tailored for an 8-core CPU + 24GB RAM + 4GB VRAM GPU machine:

```
+====================================================================================================+
|                                  LOCAL MODEL ROUTING TIERS                                         |
+====================================================================================================+
       │                                │                              │                   │
       ▼                                ▼                              ▼                   ▼
+--------------------+        +--------------------+        +--------------------+  +--------------------+
| 1. GENERAL & TOOLS |        |   2. FAST TIER     |        | 3. REASONING TIER  |  | 4. EMBEDDING TIER  |
+--------------------+        +--------------------+        +--------------------+  +--------------------+
| `qwen2.5:7b-inst`  |        | `llama3.2:3b-inst` |        | `deepseek-r1:7b`   |  | FastEmbed (CPU)    |
| `hermes3:8b-llama` |        | `qwen2.5:3b-inst`  |        | `deepseek-r1:8b`   |  | `bge-base-en-v1.5` |
+--------------------+        +--------------------+        +--------------------+  +--------------------+
| GPU Offload: ~60%  |        | GPU Offload: 100%  |        | GPU Offload: ~60%  |  | In-Memory CPU      |
| Speed: ~20 tok/sec |        | Speed: ~50 tok/sec |        | Speed: ~18 tok/sec |  | Latency: <10ms     |
| Usage:             |        | Usage:             |        | Usage:             |  | Usage:             |
| - Tool Invocation  |        | - Fact Extraction  |        | - Complex Planning |  | - HNSW Vector Search|
| - DAG Step Exec    |        | - Intent Routing   |        | - DAG Synthesis    |  | - Semantic Recall  |
+--------------------+        +--------------------+        +--------------------+  +--------------------+
```

---

## 4. Hierarchical Sub-Agent Delegation Architecture

Sub-agents run as **lightweight local worker threads** dispatched by the Master Supervisor Agent:

1. **Recursion Limit:** Hard-capped at **depth 2** (Master $\rightarrow$ Subagent $\rightarrow$ Leaf Worker).
2. **Concurrency Limit:** Max **2–4 concurrent worker threads** to prevent RAM/VRAM thrashing on local hardware.
3. **Context Slicing:** Sub-agents receive bounded context slices ($\le 4\text{k tokens}$) and return structured JSON summaries.
4. **Local Resource Arbiter:** If local GPU VRAM is occupied by a 7B reasoning model, sub-agent workers execute using the ultra-fast 3B model or CPU threads.

---

## 5. Provider-Neutral Model Interface & BYOK Routing Architecture

To decouple the Agent Core from specific LLM runtimes, AURA routes all inference through a unified, provider-neutral abstraction governed by deterministic policy:

```
                          AURA AGENT CORE
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │  ModelProviderFactory   │
                    └────────────┬────────────┘
                                 │
                  ┌──────────────┴──────────────┐
                  ▼                             ▼
        ┌──────────────────┐          ┌──────────────────┐
        │  OllamaProvider  │          │  GeminiProvider  │
        └─────────┬────────┘          └────────┬─────────┘
                  │                            │
             (LOCAL ONLY)               (OPTIONAL BYOK)
                  │                            │
                  ▼                            ▼
            Local Daemon                  Google GenAI
        `http://localhost:11434`        `generativelanguage.googleapis.com`
```

### 5.1 Provider Routing Policies
The deterministic Policy Engine selects the active provider based on workspace configuration and task classification:

* **`LOCAL_ONLY` (Default & Invariant Base):** All requests are routed exclusively to `OllamaProvider`. Cloud provider connections are blocked at the socket level.
* **`BYOK_ONLY`:** Requests are routed to the user's configured cloud provider (e.g. `GeminiProvider` using a validated encrypted API key).
* **`AUTO` (Smart Escalation with Safe Local Fallback):**
  1. Routine tasks (chat, extraction, summarization, tool formatting) execute on local Ollama models.
  2. High-complexity synthesis or ultra-long-context analysis tasks escalate to `GeminiProvider` *only if* the user has configured valid BYOK credentials and the task does not contain restricted private data.
  3. If cloud rate limits (HTTP 429), quota limits, or network timeouts occur, the router **automatically falls back to local Ollama execution** without task disruption.

### 5.2 Deterministic Governance & Cost Control
* **No LLM Self-Routing:** The language model cannot decide its own provider or allocate cloud spend. Routing is enforced in Python before dispatch.
* **Cost Classification Badges:** Tasks display explicit billing badges: `LOCAL_ZERO_COST`, `BYOK_FREE_TIER`, or `BYOK_POTENTIALLY_BILLABLE`.
* **Zero Silent Fallback to Paid Providers:** The system will never initiate a paid cloud call unless explicitly configured by the user.

