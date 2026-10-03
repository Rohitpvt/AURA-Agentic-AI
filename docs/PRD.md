# Project Requirements Document (PRD)
## Project Name: AURA (Autonomous Universal Reactive Agent)
**Document Version:** 2.0.0  
**Phase:** Phase 0.5 — Zero-Cost Architecture Reconciliation & Invariant Audit  
**Status:** Approved for Implementation Planning  
**Classification:** Technical Blueprint  

---

## 1. Executive Summary

### 1.1 Vision
AURA is an enterprise-grade **Personal Agentic AI Operating System** designed to transcend conventional reactive chatbots. It functions as a persistent, proactive, and autonomous cognitive orchestrator capable of translating high-level user goals into structured plans, delegating workloads across specialized sub-agents, executing multi-step tool-assisted workflows, maintaining continuous cross-session memory, and operating within a zero-trust deterministic safety and permission boundary.

### 1.2 Core Architectural Invariants
* **Execution over Conversation:** The conversational interface is simply one ingress gateway. The core value of AURA resides in its deterministic execution engine, memory persistence, tool orchestration, and autonomous background processing.
* **Control Plane vs. Runtime Separation:** Decouple state management, security policies, authentication, and user approvals (Control Plane) from the non-deterministic reasoning and tool execution loops (Agent Runtime).
* **THE ZERO-COST INVARIANT (Non-Negotiable):** The entire AURA core system must be buildable, runnable, and fully functional on consumer hardware without requiring any paid API, paid SaaS subscription, paid cloud platform, or per-use paid service. All cloud or paid providers are strictly optional Tier-3 adapters.
* **Deterministic Safety:** Large Language Models (LLMs) reason and generate plans, but they *never* evaluate their own security policies. All permissions, rate limits, and risk boundaries are enforced deterministically by code outside the LLM context.
* **Local-First Continuous Contextual Evolution:** Through hybrid cognitive memory (PostgreSQL + pgvector + local FastEmbed embeddings), AURA maintains persistent user modeling, project facts, and episodic recall with 100% data sovereignty and zero external API fees.

---

## 2. Problem Statement & Market Gap

| Traditional AI Chatbots / SaaS Wrappers | Emerging Multi-Agent Frameworks (LangChain/CrewAI) | AURA Operating System (Local-First) |
| :--- | :--- | :--- |
| Ephemeral session lifecycle; context lost on tab close. | Fragmented state; hardcoded Python scripts; no centralized database. | Unified PostgreSQL 16 persistence + local pgvector cognitive user modeling. |
| Incurs steep per-token cloud API bills ($100+/month). | Requires commercial API keys (OpenAI/Anthropic) to boot. | **100% Zero-Cost Local-First:** Runs on Ollama (Qwen 2.5 / Llama 3.2 / Hermes-3). |
| Reactive only; cannot perform background or scheduled tasks. | Fragile background loops; lack enterprise-grade scheduling and retry semantics. | Production-grade Cron, Webhook, and Reactive event triggers with idempotency. |
| Unsafe execution; raw LLM decides whether to run shell commands. | Ad-hoc safety prompts; easily jailbroken via prompt injection. | Strict 4-tier risk classification with cryptographically signed Human-In-The-Loop approvals. |
| Requires paid search APIs (Tavily/SerpAPI). | Brittle commercial search wrappers. | Free local web retrieval (DuckDuckGo, SearXNG, Playwright DOM extraction). |

---

## 3. Target User Personas & Hardware Baselines

### 3.1 Target Hardware Baseline (Standard PC / Laptop)
* **CPU:** 8-core modern processor (e.g. AMD Ryzen 7 4800H / Intel Core i7)
* **RAM:** 16 GB to 24 GB System RAM
* **GPU:** 4 GB to 8 GB VRAM (e.g. NVIDIA RTX 3050 / 4060) or Apple Silicon Unified Memory
* **Storage:** 50 GB free NVMe SSD space
* **OS:** Windows 11 (WSL2), Linux (Ubuntu/Debian), macOS

### 3.2 Key Use Cases
* **Goal-Driven Deep Research:** User issues a goal: *"Analyze open-source vector databases, compare their benchmarks, and write a summary report."* AURA decomposes the goal, queries DuckDuckGo/Playwright locally, synthesizes findings using local Qwen 2.5 7B, and verifies output.
* **Proactive Daily Briefing:** Every morning at 07:00 AM, local AURA Cron wakes up, inspects local calendar and local file directories, produces an executive summary, and delivers it to the Web Dashboard.
* **Repository Architecture & Security Scan:** Local AURA inspects workspace code files, detects unencrypted tokens, validates package manifests, and proposes patches inside an ephemeral Docker sandbox.

---

## 4. System Capabilities & Feature Requirements

### FR-01: Local Agentic Orchestration & Planning
* System shall parse unstructured natural language into verified execution DAGs using local open-weight models (`qwen2.5:7b` / `deepseek-r1:7b`) via Ollama.
* System shall implement the closed cognitive loop: Goal $\rightarrow$ Context Hydration $\rightarrow$ Memory Recall $\rightarrow$ Plan Generation $\rightarrow$ Risk Evaluation $\rightarrow$ Tool/Sub-agent Execution $\rightarrow$ Observation $\rightarrow$ Plan Adaptation $\rightarrow$ Verification $\rightarrow$ Memory Writeback.

### FR-02: Zero-Cost Multi-Layer Memory Management
* **Working Memory:** In-memory sliding window context buffer managing active turn history.
* **Relational State:** Local PostgreSQL 16 storing users, workspaces, sessions, messages, task DAG steps, and audit logs.
* **Cognitive Memory:** `pgvector` with local 768-dim embeddings (`FastEmbed` / `BAAI/bge-base-en-v1.5`) storing user traits, project facts, and episodic interactions with hybrid lexical (BM25 Full-Text Search) + semantic vector recall.
* **Memory Governance:** Complete CRUD over stored facts with instant user tombstoning and negative constraint injection.

### FR-03: Local Tool Registry & Free Web Retrieval
* Centralized Tool Registry validating inputs against strict Pydantic JSON Schemas.
* Zero-cost web research tools: `duckduckgo_search` (free search queries), `playwright_fetch_page` (local headless DOM rendering and markdown extraction), and local `filesystem_tools`.
* Model Context Protocol (MCP) host manager executing local `stdio` tool servers.

### FR-04: Hierarchical Sub-Agent Delegation & Guardrails
* Master Supervisor Agent capable of delegating bounded sub-tasks to isolated Worker Agents (Research, Coding, Synthesis).
* Strict limits: Maximum delegation depth of 2; maximum 4 concurrent workers; hard execution timeouts.

### FR-05: Deterministic HITL Security & Approval Engine
* Four-tier risk classification: `LOW` (auto-execute), `MEDIUM` (logged/notified), `HIGH` (mandatory approval), `CRITICAL` (double confirmation).
* HMAC-SHA256 cryptographically signed approval tokens with 15-minute TTL.
* Ephemeral container execution sandboxing (Docker/Firejail) for untrusted shell and Python code.
* Emergency Global Kill Switch (<500ms worker termination latency).

### FR-06: Optional Secure BYOK Cloud Model Support (Google Gemini & Beyond)
* System shall provide a provider-neutral model abstraction (`ModelProvider`) supporting both local zero-cost models (Ollama) and optional user-supplied cloud credentials (Google Gemini BYOK).
* System shall store BYOK credentials encrypted at rest using AES-256-GCM, with zero client-side exposure and zero inclusion in prompts.
* System shall support deterministic routing modes: `LOCAL_ONLY` (default), `BYOK_ONLY`, and `AUTO` (with automatic fallback to local Ollama upon cloud rate limit or network disruption).
* System shall provide explicit cost and billing badges (`LOCAL_ZERO_COST`, `BYOK_FREE_TIER`, `BYOK_POTENTIALLY_BILLABLE`) and task-level token budgets.

---

## 5. Non-Functional Requirements (NFR)

* **NFR-01 (Zero Service Cost Invariant):** Total mandatory recurring API/SaaS/cloud cost for the entire core application must be exactly **$0.00**. BYOK cloud models are strictly optional.
* **NFR-02 (Local Token Latency):** Local LLM inference on baseline hardware (AMD Ryzen 7 / RTX 3050 4GB) must deliver $\ge 15\text{ tokens/sec}$ on 7B models and $\ge 40\text{ tokens/sec}$ on 3B models.
* **NFR-03 (Data Privacy):** Prompts, source code, documents, and memory records must remain 100% local by default; zero network telemetry sent to third-party AI companies.
* **NFR-04 (Offline Operation):** System must be capable of executing internal tasks, memory recall, and code analysis with zero active internet connection in `LOCAL_ONLY` mode.
* **NFR-05 (Zero Secret Leakage):** User-supplied BYOK credentials shall never be exposed to frontend JavaScript runtimes, browser storage, unencrypted databases, logs, or agent prompts.
