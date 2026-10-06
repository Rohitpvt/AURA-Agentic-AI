# API Specification (API_SPECIFICATION.md)
## Project Name: AURA (Autonomous Universal Reactive Agent)
**Document Version:** 9.6.0  
**Phase:** Phase 9 — Governed OS & Hardware Automation (COMPLETE & ACCEPTED) | Phase 1–9 Master Validated  
**Classification:** REST, SSE & WebSocket Protocol Specification  

---

## 1. REST API Endpoints & Contracts

### 1.1 Base URL & Authentication
* **Base URL:** `/api/v1`
* **Authentication Header:** `Authorization: Bearer <JWT_TOKEN>` or `X-AURA-API-KEY: <API_KEY>`
* **Standard Error Envelope:**
```json
{
  "success": false,
  "error": {
    "code": "RESOURCE_NOT_FOUND",
    "message": "The requested task does not exist or has been deleted.",
    "details": {}
  },
  "timestamp": "2026-09-30T20:57:00Z"
}
```

---

### 1.2 Core REST Endpoints Table

| Category | Method | Path | Description | Risk / Access |
| :--- | :--- | :--- | :--- | :--- |
| **Auth** | `POST` | `/auth/login` | Authenticate user & return JWT token. | Public |
| **Auth** | `POST` | `/auth/refresh` | Refresh expired access token. | Member |
| **Workspaces** | `GET` | `/workspaces` | List accessible workspaces for user. | Member |
| **Sessions** | `GET` | `/sessions` | List conversational sessions. | Member |
| **Sessions** | `POST` | `/sessions` | Create a new conversational session. | Member |
| **Sessions** | `GET` | `/sessions/{id}/messages` | Retrieve session turn history. | Member |
| **Tasks** | `GET` | `/tasks` | List tasks with status/priority filtering. | Member |
| **Tasks** | `POST` | `/tasks` | Dispatch a new autonomous user goal. | Member |
| **Tasks** | `GET` | `/tasks/{id}` | Retrieve task detail with step DAG. | Member |
| **Tasks** | `POST` | `/tasks/{id}/cancel` | Abort an active task execution. | Member |
| **Tasks** | `POST` | `/tasks/{id}/resume` | Deterministically resume task from verified checkpoint. | Member |
| **Voice** | `POST` | `/voice/ticket` | Issue short-lived ticket for WebSocket voice stream. | Member |
| **Voice** | `WS` | `/voice/stream` | Authenticated duplex binary audio & VAD stream. | Member (Ticket) |
| **Vision** | `POST` | `/vision/ticket` | Issue short-lived ticket for WebSocket camera vision stream. | Member |
| **Vision** | `WS` | `/vision/stream` | Authenticated duplex camera frame streaming (26-byte Big-Endian header). | Member (Ticket) |
| **Vision** | `POST` | `/vision/ocr/screen` | Capture desktop and perform local RapidOCR text extraction. | Member |
| **Vision** | `POST` | `/vision/ocr/window` | Crop active window and perform local RapidOCR text extraction. | Member |
| **Vision** | `POST` | `/vision/vlm/query` | Inspect desktop or camera frame with local CPU VLM (Moondream2/Qwen2-VL). | Member |
| **Approvals** | `GET` | `/approvals` | List pending Human-in-the-Loop approvals. | Member |
| **Approvals** | `POST` | `/approvals/{id}/resolve` | Approve or Reject a tool execution token. | Admin / Owner |
| **Tools** | `GET` | `/tools` | List registered tools and JSON schemas. | Member |
| **Skills** | `GET` | `/skills` | List active procedural skills. | Member |
| **Skills** | `POST` | `/skills` | Register or update a custom skill. | Admin |
| **Automations** | `GET` | `/automations` | List scheduled Cron and Webhook automations. | Member |
| **Automations** | `POST` | `/automations` | Create or update an automation rule. | Admin |
| **Webhooks** | `POST` | `/webhooks` | Configure a new inbound webhook endpoint. | Member |
| **Webhooks** | `GET` | `/webhooks` | List webhook endpoints for workspace. | Member |
| **Webhooks** | `POST` | `/webhooks/{id}/rotate-secret`| Rotate HMAC secret for webhook. | Member |
| **Webhooks** | `POST` | `/webhooks/ingress/{public_id}` | Public ingress for HMAC-signed webhooks. | Public (HMAC) |
| **Telegram** | `POST` | `/telegram/integrations` | Configure a new Telegram Bot integration. | Member |
| **Telegram** | `GET` | `/telegram/integrations` | List Telegram Bot integrations (tokens masked). | Member |
| **Telegram** | `POST` | `/telegram/integrations/{id}/pairings` | Generate one-time 15-min pairing token. | Member |
| **Telegram** | `GET` | `/telegram/integrations/{id}/pairings` | List active paired Telegram chats. | Member |
| **Telegram** | `DELETE`| `/telegram/integrations/{id}/pairings/{pid}` | Revoke an active Telegram chat pairing. | Member |
| **Memory** | `GET` | `/memory/records` | List stored facts, user preferences, and memories.| Member |
| **Memory** | `DELETE`| `/memory/records/{id}` | Tombstone / delete a memory record. | Member |
| **Files** | `POST` | `/files/upload` | Upload multi-part file to workspace storage. | Member |
| **Files** | `GET` | `/files` | List ingested files with parsing status & metadata. | Member |
| **Files** | `GET` | `/files/{id}` | Retrieve file details, chunks, and metadata. | Member |
| **Files** | `GET` | `/files/{id}/chunks` | List structural chunks with embeddings & tokens. | Member |
| **Files** | `POST` | `/files/{id}/index` | Trigger structural chunking & FastEmbed vector index. | Member |
| **Files** | `GET` | `/files/{id}/content` | Retrieve sanitized text preview / structure. | Member |
| **Files** | `DELETE`| `/files/{id}` | Delete file, cascade purge chunks, and audit. | Member |
| **Files** | `POST` | `/files/search` | Semantic hybrid search across workspace documents. | Member |
| **Files** | `POST` | `/files/{id}/qa` | Document question answering & citation synthesis. | Member |
| **Providers** | `GET` | `/providers` | List available model providers and routing modes. | Member |
| **Providers** | `POST` | `/providers` | Configure a model provider (Ollama, Gemini BYOK). | Admin / Owner |
| **Providers** | `PUT` | `/providers/{id}` | Update provider options and routing policy. | Admin / Owner |
| **Credentials** | `POST` | `/credentials` | Securely enroll and encrypt a BYOK API key. | Admin / Owner |
| **Credentials** | `GET` | `/credentials` | List registered key fingerprints & health. | Admin / Owner |
| **Credentials** | `DELETE`| `/credentials/{id}` | Revoke and purge an encrypted credential. | Admin / Owner |
| **Telemetry** | `GET` | `/telemetry/hardware` | Read-only host CPU, RAM, GPU, and battery telemetry. | Member |
| **Audit** | `GET` | `/audit/logs` | Query tamper-evident audit ledger. | Admin / Owner |
| **System** | `POST` | `/system/kill-switch` | Emergency circuit breaker to halt all runs (<15ms). | Admin / Owner |
| **System** | `POST` | `/system/kill-switch/reset` | Authenticated recovery reset after emergency abort. | Admin / Owner |
| **System** | `GET` | `/system/kill-switch/status` | Read active kill-switch status and recovery state. | Member | |

---

### 1.3 Key Payload Contracts

#### `POST /api/v1/tasks` (Dispatch User Goal)
```json
{
  "workspace_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "session_id": "4a12ec21-8f12-4c22-b511-9a221f8221b3",
  "title": "Analyze Repository Security",
  "goal": "Scan the current workspace for hardcoded API keys and outdated dependencies, then generate a security report.",
  "autonomy_level": 2,
  "budget_max_tokens": 50000,
  "budget_max_cost_cents": 200,
  "timeout_seconds": 1200
}
```

#### `POST /api/v1/approvals/{id}/resolve` (HITL Resolution)
```json
{
  "status": "approved", // "approved" or "rejected"
  "signed_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "resolution_notes": "Approved git commit to hotfix branch"
}
```

#### `POST /api/v1/credentials` (Enroll Encrypted BYOK Credential)
```json
{
  "workspace_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "provider_config_id": "8c2def3e-4c8e-4fbe-8a1a-3c0e8c4ecf7e",
  "credential_type": "api_key",
  "secret": "AIzaSyD-EXAMPLE_KEY_STRING_HERE"
}
```
*Response returns 201 Created with fingerprint only; secret is never returned:*
```json
{
  "success": true,
  "data": {
    "id": "7a1b2c3d-4e5f-6a7b-8c9d-0e1f2a3b4c5d",
    "provider_type": "gemini",
    "key_fingerprint": "AIza...4f8a",
    "is_valid": true,
    "last_validated_at": "2026-09-30T22:45:00Z"
  }
}
```

#### `POST /api/v1/providers` (Configure Model Provider)
```json
{
  "workspace_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "provider_type": "gemini",
  "display_name": "Google Gemini (BYOK)",
  "is_enabled": true,
  "routing_mode": "auto",
  "default_model": "gemini-2.5-flash",
  "api_endpoint": "https://generativelanguage.googleapis.com/v1beta",
  "config_options": {
    "timeout_seconds": 30,
    "max_tokens": 8192,
    "temperature": 0.2
  },
  "billing_tier": "byok_free_tier"
}
```

---

## 2. Real-Time Streaming Protocols (SSE & WebSockets)

### 2.1 Server-Sent Events (SSE): `/api/v1/tasks/{id}/stream`
Stream of structured agent events emitted during task execution:

```
event: plan_created
data: {"step_count": 3, "steps": [{"number": 1, "title": "Scan repo"}, {"number": 2, "title": "Check CVEs"}, {"number": 3, "title": "Generate Report"}]}

event: step_started
data: {"step_number": 1, "title": "Scan repo", "tool_name": "list_dir"}

event: thought_chunk
data: {"delta": "Inspecting project root for dependency manifests..."}

event: tool_call_requested
data: {"tool_name": "read_file", "params": {"file_path": "package.json"}, "risk_level": "low"}

event: step_completed
data: {"step_number": 1, "status": "completed", "output_preview": "Found package.json with 14 dependencies"}

event: task_completed
data: {"task_id": "4a12ec21...", "result_summary": "Security scan completed. 0 CVEs found.", "total_tokens": 12450, "total_cost_cents": 1.25}
```

---

## 3. Webhook Ingress Protocol: `/api/v1/webhooks/ingress/{webhook_id}`

* **Signature Verification:** Requires `X-AURA-Signature: sha256=<HMAC_HEX>` calculated using the automation's shared secret key.
* **Idempotency Guarantee:** Requires `X-Idempotency-Key: <UUID>` header; duplicated events received within 24 hours return HTTP 200 without re-triggering the agent runtime.

---

## 4. Universal File Intelligence Endpoints (Phase 6)

All endpoints require standard Bearer JWT authentication and operate strictly within the caller's authorized `workspace_id`. Internal storage paths are never exposed.

### 4.1 Upload File: `POST /api/v1/files/upload`
* **Content-Type:** `multipart/form-data`
* **Form Parameters:**
  - `file`: Binary file stream (max 50 MB)
* **Response (HTTP 201 Created):**
```json
{
  "file_id": "8f3b2a19-9831-4c12-b34e-72cb6582a941",
  "workspace_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "original_filename": "Q3_Financial_Report.pdf",
  "safe_filename": "q3_financial_report.pdf",
  "mime_type": "application/pdf",
  "size_bytes": 1458920,
  "sha256_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "status": "uploaded",
  "created_at": "2026-10-02T18:00:00Z"
}
```

### 4.2 List Files: `GET /api/v1/files`
* **Query Parameters:** `page?: int`, `limit?: int`, `status?: str`, `search?: str`
* **Response (HTTP 200 OK):**
```json
{
  "items": [
    {
      "file_id": "8f3b2a19-9831-4c12-b34e-72cb6582a941",
      "original_filename": "Q3_Financial_Report.pdf",
      "mime_type": "application/pdf",
      "size_bytes": 1458920,
      "status": "indexed",
      "chunk_count": 18,
      "created_at": "2026-10-02T18:00:00Z"
    }
  ],
  "total": 1,
  "page": 1,
  "limit": 20
}
```

### 4.3 Get File Details: `GET /api/v1/files/{file_id}`
* **Response (HTTP 200 OK):**
```json
{
  "file_id": "8f3b2a19-9831-4c12-b34e-72cb6582a941",
  "workspace_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "original_filename": "Q3_Financial_Report.pdf",
  "mime_type": "application/pdf",
  "size_bytes": 1458920,
  "sha256_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "status": "indexed",
  "metadata": {
    "page_count": 12,
    "title": "Quarterly Performance",
    "author": "Finance Team"
  },
  "security_flags": [],
  "chunk_count": 18,
  "created_at": "2026-10-02T18:00:00Z",
  "updated_at": "2026-10-02T18:00:05Z"
}
```

### 4.4 Search File Chunks: `POST /api/v1/files/search`
* **Request Body:**
```json
{
  "query": "What were the Q3 operating margins?",
  "top_k": 5,
  "file_id": "8f3b2a19-9831-4c12-b34e-72cb6582a941"
}
```
* **Response (HTTP 200 OK):**
```json
{
  "query": "What were the Q3 operating margins?",
  "results": [
    {
      "chunk_id": "c7a10294-819a-4f51-bfa0-94028bc64a12",
      "file_id": "8f3b2a19-9831-4c12-b34e-72cb6582a941",
      "filename": "Q3_Financial_Report.pdf",
      "chunk_index": 4,
      "chunk_text": "Operating margin expanded by 240 bps to 28.4%...",
      "score": 0.884,
      "source_location": {
        "page": 5,
        "section": "Operating Results"
      }
    }
  ]
}
```

### 4.5 Delete File (Idempotent): `DELETE /api/v1/files/{file_id}`
* **Response (HTTP 200 OK):**
```json
{
  "file_id": "8f3b2a19-9831-4c12-b34e-72cb6582a941",
  "status": "deleted",
  "purged_storage": true,
  "purged_chunks": 18,
  "purged_at": "2026-10-02T18:05:00Z"
}
```

---

## 5. Real-Time Voice & Speech Endpoints (Phase 7)

### 5.1 Issue Voice Ticket: `POST /api/v1/voice/ticket`
* **Headers:** `Authorization: Bearer <JWT_TOKEN>`
* **Response (HTTP 200 OK):**
```json
{
  "ticket": "vkt_8f912c...",
  "expires_in": 60,
  "ws_url": "ws://localhost:8000/api/v1/voice/stream?ticket=vkt_8f912c..."
}
```

### 5.2 Duplex Voice Stream: `WS /api/v1/voice/stream?ticket={ticket}`
* **Handshake:** Single-use cryptographic ticket (60-second TTL), validated against `workspace_id`.
* **Framing Protocol:** 256-bit session nonce handshake, binary Int16 PCM audio streaming (16 kHz, 1-channel, 20ms frames), JSON control frames for VAD speech events, interruption barge-in, and transcripts.

---

## 6. Continuous Screen, Camera & Live Multimodal Vision Endpoints (Phase 8)

### 6.1 Discover Desktop Monitors: `GET /api/v1/vision/monitors`
* **Headers:** `Authorization: Bearer <JWT_TOKEN>`
* **Response (HTTP 200 OK):**
```json
{
  "monitors": [
    {
      "monitor_id": 1,
      "name": "Primary Display",
      "width": 1920,
      "height": 1080,
      "left": 0,
      "top": 0,
      "is_primary": true,
      "dpi_scale": 1.0
    }
  ]
}
```

### 6.2 Get Active Window Context: `GET /api/v1/vision/active-window`
* **Headers:** `Authorization: Bearer <JWT_TOKEN>`
* **Response (HTTP 200 OK):**
```json
{
  "window_title": "Visual Studio Code - Agentic AI",
  "process_name": "Code.exe",
  "pid": 14208,
  "bounds": {
    "left": 0,
    "top": 0,
    "width": 1920,
    "height": 1040
  },
  "is_maximized": true
}
```

### 6.3 Issue Vision Streaming Ticket: `POST /api/v1/vision/ticket`
* **Headers:** `Authorization: Bearer <JWT_TOKEN>`
* **Response (HTTP 200 OK):**
```json
{
  "ticket": "vst_1a4b9e...",
  "expires_in": 60,
  "ws_url": "ws://localhost:8000/api/v1/vision/stream?ticket=vst_1a4b9e..."
}
```

### 6.4 Duplex Vision Stream: `WS /api/v1/vision/stream?ticket={ticket}`
* **Handshake:** Single-use ticket verified against caller's `workspace_id`.
* **Binary Frame Structure (Fixed 26-Byte Header + WebP Payload):**
  - Offset `0` (`uint8`): `stream_type` (`0x01`=Screen, `0x02`=Camera, `0x03`=Window)
  - Offset `1` (`uint8`): `source_id` (Monitor ID or Camera Index)
  - Offset `2` (`uint32` BE): `sequence_number` (Monotonic counter)
  - Offset `6` (`uint64` BE): `timestamp_ns` (Nanosecond timestamp)
  - Offset `14` (`uint32` BE): `width` (Frame pixel width)
  - Offset `18` (`uint32` BE): `height` (Frame pixel height)
  - Offset `22` (`uint32` BE): `payload_length` (Length $N$ of WebP bytes)
  - Offset `26` (`bytes[N]`): Ephemeral compressed WebP frame payload.


