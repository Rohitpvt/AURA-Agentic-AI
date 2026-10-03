# Technical Requirements Document (TRD)
## Project Name: AURA (Autonomous Universal Reactive Agent)
**Document Version:** 1.0.0  
**Phase:** Phase 0.5 — Documentation Reconciliation & Consistency Audit  
**Classification:** Technical Requirements & Engineering Constraints  

---

## 1. Document Scope & Boundary

This document defines the **formal technical requirements, protocol constraints, performance SLAs, and interface specifications** governing the engineering implementation of AURA.

> [!NOTE]
> For specific library versions, runtime dependency selections, and comparative trade-off evaluations, consult the companion document [**TECH_STACK.md**](file:///C:/Users/rghos/OneDrive%20-%20Vivekananda%20Institute%20of%20Professional%20Studies/PROJECTS/Agentic%20AI/docs/TECH_STACK.md).

---

## 2. Engineering Protocol & Transport Standards

### 2.1 API & Network Protocols
* **REST API:** All synchronous client-to-server operations must conform to OpenAPI 3.1 specifications over TLS 1.3 (HTTPS). Request/response bodies must use UTF-8 encoded JSON.
* **Real-time Streaming:** Token streaming, thinking steps, and step execution progress must use **Server-Sent Events (SSE)** (`text/event-stream`) over HTTP/2 with automatic client reconnect.
* **Internal Event Bus:** Asynchronous worker coordination and kill-switch broadcasts must use Redis Pub/Sub or PostgreSQL `LISTEN/NOTIFY`.
* **Model Context Protocol (MCP):** External tool server communication must adhere to the 2024-11-05 MCP specification supporting both `stdio` (local subprocess pipes) and `SSE` (remote HTTP).

### 2.2 Data Integrity & Security Standards
* **Cryptographic Signing:** All Human-in-the-Loop (HITL) approval tokens must be signed using **HMAC-SHA256** with an ephemeral salt and a SHA256 parameter hash binding.
* **Audit Hash Chaining:** Every security-sensitive audit event must implement SHA-256 blockchain-style hash chaining ($\text{Hash}_N = \text{SHA256}(\text{Hash}_{N-1} + \text{Payload}_N)$).
* **Secret Encryption:** Third-party credentials stored in PostgreSQL must be encrypted at rest using **AES-256-GCM** with authenticated associated data (AAD) bound to the `workspace_id`.

---

## 3. System Performance & Scalability SLAs

| Metric | Target SLA | Measurement Boundary |
| :--- | :--- | :--- |
| **API Gateway Ingress Overhead** | $\le 50\text{ ms}$ (p95) | Time from ingress socket accept to worker dispatch (excluding LLM inference). |
| **SSE Time-to-First-Token (TTFT)** | $\le 100\text{ ms}$ (p95) | Time between upstream model output generation and frontend SSE event delivery. |
| **Kill Switch Propagation** | $\le 500\text{ ms}$ (p99) | Time from kill-switch trigger to termination of all active worker threads and sub-agents. |
| **Database Query Latency** | $\le 15\text{ ms}$ (p95) | Execution time for indexed session, task, and memory queries in PostgreSQL. |
| **Worker Concurrency** | $\ge 50$ active tasks | Concurrent task execution pipelines on a standard 4 vCPU / 16 GB RAM baseline node. |

---

## 4. Hardware & Operating Environment Requirements

* **Primary Operating System:** Linux (Ubuntu 22.04 LTS / 24.04 LTS, Debian 12) in production.
* **Development Environment:** Windows 11 with WSL2 (Ubuntu), macOS (Apple Silicon M1+), or native Linux.
* **Minimum Host Resources (Cloud/VPS):**
  * CPU: 4 vCPU cores ($x86\_64$ or ARM64)
  * RAM: 8 GB minimum (16 GB recommended for multi-agent workloads)
  * Storage: 50 GB NVMe SSD with automated daily WAL backups
  * Network: Outbound HTTPS (port 443) to configured LLM gateways.

---

## 5. Architectural Compliance & Validation Gates

1. **Deterministic Separation Gate:** Under no circumstances may application state (tasks, users, approvals) be managed purely in LLM context windows or unstructured file logs. State must persist to PostgreSQL.
2. **Deterministic Risk Gate:** LLM reasoning models are prohibited from evaluating their own execution permissions. Policy evaluation must occur in deterministic Python code.
3. **Secret Isolation Gate:** LLM prompt payloads are strictly forbidden from containing unencrypted third-party API keys or credentials.
4. **BYOK Security Gate:** All user-supplied cloud credentials (e.g. Google Gemini API keys) must be encrypted at rest with AES-256-GCM using an out-of-database master key (`AURA_MASTER_ENCRYPTION_KEY`) and must never be transmitted to the browser client or logged.
5. **Zero-Cost Fallback Gate:** In the event of cloud provider timeout, rate limit (HTTP 429), or credential revocation, the Model Router must deterministically fall back to local Ollama execution without failing the parent workflow.
