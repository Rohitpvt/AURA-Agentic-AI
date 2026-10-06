# Skill Architecture Specification (SKILL_ARCHITECTURE.md)
## Project Name: AURA (Autonomous Universal Reactive Agent)
**Document Version:** 9.6.0  
**Phase:** Phase 9 — Governed OS & Hardware Automation (COMPLETE & ACCEPTED) | Phase 1–9 Master Validated  
**Classification:** Procedural Learning & Skill Governance  

---

## 1. Skill Format Specification (`SKILL.md`)

AURA adopts a standardized, human-readable, and version-controlled skill package format:

```markdown
---
name: "repository_security_audit"
version: "1.2.0"
category: "development"
description: "Performs an exhaustive security audit of a code repository, detecting exposed secrets, vulnerable dependencies, and insecure coding patterns."
author: "AURA Core Team"
permissions:
  - "github_read"
  - "read_file"
  - "run_sandboxed_linter"
preconditions:
  - "Target repository path or GitHub URL must be provided"
  - "Workspace must have access to package manifests (package.json / requirements.txt)"
triggers:
  - "audit repository security"
  - "check repo for vulnerabilities"
  - "security scan on codebase"
parameters:
  repo_path:
    type: "string"
    description: "Path to repository or GitHub remote URL"
    required: true
  severity_threshold:
    type: "string"
    enum: ["low", "medium", "high", "critical"]
    default: "medium"
---

# Workflow Recipe: Repository Security Audit

## Step 1: Ingestion & Dependency Tree Analysis
1. Inspect package manifest (`package.json`, `Cargo.toml`, `requirements.txt`).
2. Run dependency vulnerability tool inside sandbox.
3. Assert: Dependency scan must output structured CVE JSON report.

## Step 2: Secret Scanning & Static Pattern Analysis
1. Search codebase for regex patterns matching API keys, private certificates, and environment tokens.
2. Flag any unencrypted secrets found in tracked git files.

## Step 3: Synthesis & Remediation Plan
1. Aggregate all findings categorized by CVSS severity.
2. Propose concrete patch snippets for vulnerable dependencies.
3. Write finalized markdown report to `./audit/security-report.md`.
```

---

## 2. Skill Lifecycle & Dynamic Loading Pipeline

```
[User Intent / Scheduled Task]
              │
              ▼
[1. Semantic Matcher & Trigger Evaluator]
    (Compares goal embedding against Skill Catalog trigger vectors)
              │
              ▼
[2. Precondition & Permission Validator]
    (Validates required tools & environmental preconditions in PostgreSQL)
              │
              ▼
[3. Version Resolution & Skill Hydration]
    (Loads latest published `skill_versions` record for the workspace)
              │
              ▼
[4. Context Injection]
    (Injects Skill Recipe Markdown into LLM System / Workflow Envelope)
              │
              ▼
[5. Execution & Step Verification]
              │
              ▼
[6. Telemetry & Success Rate Logging]
```

---

## 3. Initial Core Skill Catalog (Phase 1 MVP)

| Skill Slug | Category | Description | Primary Tools Utilized |
| :--- | :--- | :--- | :--- |
| `daily_executive_brief` | productivity | Gathers daily calendar events, unread high-priority emails, and GitHub issues to generate a synthesized morning briefing. | `get_calendar_events`, `fetch_unread_emails`, `github_list_issues`. |
| `deep_research_topic` | research | Decomposes a research topic across multiple parallel sub-agents, conducts web search, synthesizes data, and produces a cited brief. | `web_search`, `read_web_page`, `write_file`. |
| `repo_architecture_analysis` | development | Scans a software repository, generates component diagrams, analyzes code organization, and documents technical debt. | `list_dir`, `read_file`, `grep_search`. |
| `meeting_prep_brief` | productivity | Analyzes participants and agenda for upcoming calendar events, retrieving past conversational notes and project facts. | `get_calendar_events`, `query_cognitive_memory`, `read_file`. |
| `weekly_review_synthesis` | productivity | Synthesizes all completed tasks, pending approvals, and project milestones across the past 7 days into an executive review. | `query_tasks`, `query_audit_logs`, `write_file`. |

---

## 4. Controlled Self-Improvement & Evolution Loop

AURA supports procedural evolution while prohibiting uncontrolled self-modifying code in production:

```
[Agent Runs & Task Executions]
              │
              ▼
[Execution Telemetry Collector (Langfuse / OpenTelemetry)]
  - Tracks step failures, retry counts, latency, and user edits
              │
              ▼
[Offline Skill Optimizer (DSPy / GEPA Pipeline)]
  - Evaluates low-performing skills (Success Rate < 85%)
  - Generates optimized prompt recipes and improved assertions
              │
              ▼
[Draft New Version in PostgreSQL: `is_published: FALSE`]
              │
              ▼
[Admin Review Gate in Web Dashboard]
  - Displays side-by-side Diff of old vs proposed skill version
  - Architect/Admin approves promotion -> `is_published: TRUE`
```
