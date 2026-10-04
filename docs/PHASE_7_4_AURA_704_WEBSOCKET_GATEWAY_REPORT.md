# AURA-704: Authenticated WebSocket Gateway & Session Ticket Transport Acceptance Report

## 1. Executive Summary

Milestone **AURA-704** implements the secure, authenticated WebSocket gateway and session ticket transport layer for real-time voice streaming in AURA Phase 7. The implementation strictly adheres to the two-step authentication pattern, where short-lived, single-use voice tickets are issued over HTTPS and consumed atomically during the WebSocket upgrade handshake. Long-lived JWT tokens are never exposed in WebSocket URLs or browser connection strings.

All **17** AURA-704 unit, integration, and security tests pass cleanly, bringing total backend test suite coverage to **333 passing tests** (316 baseline + 17 AURA-704 additions) and frontend coverage to **18 passing tests** (351 total tests across the repository).

---

## 2. Architecture & Security Invariants

### 2.1 Two-Step Authentication Flow

```
+------------------+         HTTPS POST /api/v1/voice/ticket          +-------------------------+
|                  | -----------------------------------------------> |                         |
|  Client Browser  |   (Bearer JWT + workspace_id)                    |   VoiceTicketService    |
|                  | <----------------------------------------------- |   (FastAPI Auth Guard)  |
|                  |     201 Created (single-use ticket token)        +-------------------------+
+------------------+                                                               |
         |                                                                         |
         | WebSocket Upgrade: /api/v1/voice/stream?ticket=<token>                  |
         v                                                                         v
+------------------+         Atomic Consume & Validation              +-------------------------+
|                  | -----------------------------------------------> |  - Validate TTL (60s)   |
| WebSocket Gate   |                                                  |  - Check Nonce / Replay |
|                  | <----------------------------------------------- |  - Enforce Workspace    |
+------------------+           Session Initialized Frame              +-------------------------+
         |                       (256-bit Session Nonce)                           |
         |                                                                         v
         | Binary PCM Frames / JSON Control                           +-------------------------+
         +==========================================================> |   VoiceSessionManager   |
                                                                      |   (AURA-703 Engine)     |
                                                                      +-------------------------+
```

### 2.2 Security Contracts

1. **Short-Lived Single-Use Ticket (`VoiceTicket`):**
   - Issued via `POST /api/v1/voice/ticket` requiring full Bearer JWT authentication and workspace membership validation.
   - 60-second default TTL.
   - Cryptographically secure random token generated via `secrets.token_urlsafe(32)`.
   - Bound explicitly to `user_id` and `workspace_id`.
   - Atomically consumed under an asynchronous lock (`asyncio.Lock()`) during WebSocket handshake.
   - Replay attempts and expired tickets are immediately rejected with `401 Unauthorized` or WebSocket close code `1008 (Policy Violation)`.

2. **Canonical 256-Bit Session Nonce:**
   - Generated via `secrets.token_bytes(32)` providing 256 bits of raw CSPRNG entropy.
   - Represented as a 64-character lowercase hex string (`token_bytes(32).hex()`).
   - Bound to `session_id`, `workspace_id`, and `user_id`.
   - Transmitted in the initial `session_init` control frame.

3. **Workspace Tenancy & Isolation:**
   - Ticket issuance strictly validates workspace membership (`user_id` in target `workspace_id`).
   - Cross-workspace ticket consumption is prevented with strict `AuthorizationError`.
   - Session lookup and execution are completely partitioned by `workspace_id`.

4. **Binary Audio Transport Framing:**
   - Standard 12-byte little-endian header:
     - `SeqNum`: `uint32` (4 bytes, unsigned int `<I`)
     - `TimestampMs`: `uint64` (8 bytes, unsigned long long `<Q`)
   - Payload: 16 kHz, 16-bit Mono PCM (`Int16LE`) samples.
   - Strict validation: Malformed headers (< 12 bytes), odd PCM byte lengths (non-16-bit aligned), and oversized frames are rejected.

5. **Bidirectional JSON Control Messaging:**
   - `barge_in`: Triggers immediate cooperative speech turn interruption in `VoiceSessionManager`.
   - `cancel`: Cancels ongoing TTS streaming and resets session state to `IDLE`.
   - `ping` / `pong`: Liveness heartbeat.
   - `status`: Real-time session state interrogation.

6. **Kill-Switch Integration:**
   - Checked at ticket issuance and continuously during WebSocket session lifecycle via `KillSwitchManager`.
   - Active kill switch sends a `kill_switch` frame and terminates the WebSocket connection cleanly.

7. **Ephemeral Privacy & Zero Persistence:**
   - Raw binary audio frames are processed in memory and zeroed upon turn completion or session teardown.
   - Zero raw PCM is written to PostgreSQL, disk, application logs, OpenTelemetry traces, or audit trails.

---

## 3. Empirical Latency & Performance Benchmarks

Measured on **CPU (AMD64 Family 23 Model 96 Stepping 1, AuthenticAMD), Windows 11**, with $N = 50$ reproducible trials per metric using `apps/api/tests/benchmark_aura704_gateway.py`:

| Metric | Target Boundary | Min | Mean | p50 | p95 | p99 | Max | Result |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Ticket Issuance Latency** | $\le 5.0\text{ ms}$ | 0.0365 ms | 0.0519 ms | 0.0474 ms | 0.0832 ms | **0.1112 ms** | 0.1299 ms | **PASS** |
| **WebSocket Handshake & Init** | $\le 25.0\text{ ms}$ | 2.4395 ms | 3.9169 ms | 3.4592 ms | 7.3208 ms | **8.8745 ms** | 9.0157 ms | **PASS** |
| **Binary Frame Ingestion Overhead**| $\le 10.0\text{ ms}$ | 0.4456 ms | 0.8889 ms | 0.7491 ms | 1.8606 ms | **2.3124 ms** | 2.4615 ms | **PASS** |
| **Disconnect Cleanup Latency** | $\le 10.0\text{ ms}$ | 0.0324 ms | 0.0731 ms | 0.0609 ms | 0.1405 ms | **0.2190 ms** | 0.2343 ms | **PASS** |

---

## 4. Test Verification Suite Summary

### 4.1 AURA-704 Test Suite (`test_voice_websocket_gateway.py`) — 17/17 Passed
1. `test_voice_ticket_service_issue_and_validate`: Ticket creation, TTL expiration calculation, and initial state.
2. `test_voice_ticket_service_single_use_and_replay_rejection`: Single-use atomic consumption and replay rejection.
3. `test_voice_ticket_service_ttl_expiration`: Expiration boundary enforcement.
4. `test_voice_ticket_service_concurrent_replay_race`: 10 concurrent consume attempts resulting in exactly 1 success and 9 rejections.
5. `test_voice_ticket_service_workspace_mismatch_rejection`: Rejection of cross-workspace ticket consumption.
6. `test_256_bit_session_nonce_properties`: 50-sample CSPRNG verification of 32-byte entropy and 64-char hex format.
7. `test_binary_audio_frame_packing_and_unpacking`: 12-byte `<IQ` header and PCM payload packing/unpacking.
8. `test_binary_audio_frame_malformed_rejection`: Rejection of short headers, empty payloads, and odd-byte PCM payloads.
9. `test_voice_ticket_endpoint_authenticated_issuance`: `POST /api/v1/voice/ticket` HTTP 201 response with valid claims.
10. `test_voice_ticket_endpoint_unauthenticated_rejection`: HTTP 401 on missing JWT.
11. `test_voice_ticket_endpoint_unauthorized_non_member_rejection`: HTTP 403 when requesting ticket for a non-member workspace.
12. `test_websocket_stream_successful_handshake_and_init`: Valid ticket connection and receipt of `session_init` frame with 256-bit nonce.
13. `test_websocket_stream_rejected_for_invalid_ticket`: WebSocket connection rejection on bogus ticket.
14. `test_websocket_stream_rejected_for_replayed_ticket`: WebSocket connection rejection on replayed ticket.
15. `test_websocket_stream_binary_audio_ingestion_and_ping_control`: Binary PCM frame ingestion and ping/pong control handling.
16. `test_websocket_stream_barge_in_and_cancel_control_frames`: Client control frame dispatch (`barge_in`, `cancel`) and state transition.
17. `test_websocket_stream_kill_switch_immediate_termination`: Immediate session termination upon kill switch activation.

### 4.2 Repository-Wide Test Counts
- **Voice Module Suite (AURA-701 + 702 + 703 + 704):** **51 passed** in 1.92s
- **Full Backend Regression Suite:** **333 passed** (0 failures, 100% passing)
- **Frontend Regression Suite:** **18 passed** (0 failures, 100% passing)
- **Total Test Count:** **351 passed** across the full stack

---

## 5. Implementation Files

| Component | File Path |
| :--- | :--- |
| Voice Ticket Service | `apps/api/app/services/voice/ticket_service.py` |
| Voice REST & WS Endpoints | `apps/api/app/api/v1/endpoints/voice.py` |
| Voice Module Package Root | `apps/api/app/services/voice/__init__.py` |
| API Router Mounting | `apps/api/app/api/v1/router.py` |
| Gateway Tests | `apps/api/tests/test_voice_websocket_gateway.py` |
| Empirical Benchmark Script | `apps/api/tests/benchmark_aura704_gateway.py` |
