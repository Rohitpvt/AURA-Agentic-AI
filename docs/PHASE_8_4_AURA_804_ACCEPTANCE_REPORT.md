# PHASE 8.4 ACCEPTANCE REPORT: AURA-804 — REAL-TIME SCREEN VLM, GOVERNED VISION TOOLS & NEXT.JS VISION HUD

**Milestone:** AURA-804 (Phase 8.4 - Vision Intelligence & Multimodal UI Layer)  
**Date:** October 4, 2026  
**Status:** COMPLETE & ACCEPTED  
**Commit Baseline:** `f398b19` (AURA-803)  
**Target Hardware:** AMD Ryzen 7 4800H (8C/16T), 24 GB DDR4 RAM, NVIDIA GeForce RTX 3050 Laptop GPU (4 GB VRAM), Windows 11 Home  

---

## 1. EXECUTIVE SUMMARY

AURA-804 completes the entire **Phase 8 (Desktop Sensing & Real-Time Multimodal Vision Layer)** by establishing the local vision intelligence pipeline that allows AURA to perceive and interpret visual state across desktop screens, active application windows, and live browser camera feeds.

The milestone enforces the canonical Phase 8 resource policy:
- **Zero Cloud Dependence:** 100% local inference ($0.00 mandatory operating cost). Zero cloud VLM/OCR calls, zero silent paid fallbacks.
- **VRAM Conservation:** Primary LLM remains on GPU; Vision VLM (`Moondream2` / `Qwen2-VL 2B`) resides strictly on **CPU** (`VLM_DEVICE = "cpu"`) to prevent VRAM starvation on the 4 GB RTX 3050.
- **Strict Rate Ceiling:** Maximum **0.2 FPS** (minimum 5.0 seconds between VLM inferences), serialized across a single worker with `asyncio.Lock()`.
- **Ephemeral Depth-1 Buffering:** Newest-frame-wins volatile in-memory caching. Zero disk storage, zero database persistence, zero visual surveillance archives.
- **Multimodal Untrusted Containment:** All VLM and OCR outputs are strictly classified as untrusted sensory observations and contained within `<untrusted_multimodal_content origin="..." model="...">` XML envelopes with active prompt injection scanning.
- **4 Governed Vision Tools:** Canonical read-only tools registered in `BUILTIN_TOOLS` (`risk_level = "low"`) executing through `ToolRegistryService` and `AgentToolBridge`.
- **Next.js Vision HUD:** Production-grade visual status indicator communicating Screen Sensing, Live Camera, Continuous OCR, Local VLM, and Emergency Kill Switch states with strict privacy guarantees.

---

## 2. ARCHITECTURAL TOPOLOGY & SUBSYSTEM INTEGRATION

```text
┌──────────────────────────────────────────────────────────────────────────────────┐
│                             SENSORY INPUT STAGE                                  │
│                                                                                  │
│   ┌────────────────────────┐  ┌────────────────────────┐  ┌──────────────────┐   │
│   │ AURA-801 ScreenCapture │  │ AURA-802 ContinuousOCR │  │ AURA-803 Camera  │   │
│   │ (Depth-1 WebP, mss)    │  │ (RapidOCR ONNX @ 1 Hz) │  │ (2-5 FPS, 26-B)  │   │
│   └───────────┬────────────┘  └───────────┬────────────┘  └────────┬─────────┘   │
└───────────────┼───────────────────────────┼────────────────────────┼─────────────┘
                │                           │                        │
                ▼                           ▼                        ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                             VLM REASONING PIPELINE                               │
│                                                                                  │
│   Rate Ceiling: 0.2 FPS (>=5.0s) ──► Single Worker Lock (asyncio.Lock)          │
│                                                                                  │
│   Prompt Construction:                                                           │
│     [SYSTEM INSTRUCTION: Objective local visual sensor]                          │
│     [TRUSTED CONTEXT: Dimensions, monitor ID, active window title/PID]           │
│     [UNTRUSTED OCR CONTEXT: Screen text references (sanitized)]                  │
│     [ANALYSIS REQUEST: User focus query]                                         │
│                                                                                  │
│   Local Substrate: Ollama /api/generate (Moondream2 / Qwen2-VL @ CPU)            │
│   Fallback Behavior: Structured Degraded Observation (Zero Cloud Fallback)       │
└───────────────────────────────────────┬──────────────────────────────────────────┘
                                        │
                                        ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                            SECURITY & GOVERNANCE GATE                            │
│                                                                                  │
│   Prompt Injection Scanner ──► Wrap <untrusted_multimodal_content> XML envelope  │
│                                                                                  │
│   4 Governed Tools (BUILTIN_TOOLS, risk_level = "low"):                          │
│     1. inspect_current_screen                                                    │
│     2. inspect_active_window                                                     │
│     3. inspect_camera_frame                                                      │
│     4. query_visible_text                                                        │
│                                                                                  │
│   Execution Authority: Agent ──► AgentToolBridge ──► ToolRegistryService         │
│   Emergency Kill Switch: Immediate abort, connection close & cache purge         │
└───────────────────────────────────────┬──────────────────────────────────────────┘
                                        │
                                        ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                       NEXT.JS VISION HUD & STREAMING UI                          │
│                                                                                  │
│   Sensing Grid: Screen Capture | Live Camera | Local OCR | Vision VLM            │
│   Privacy Guarantee: Safe Camera Active/Stopped (No false LED claim)             │
│   Observation Card: Summary, confidence, latency, untrusted envelope, geometry   │
└──────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. GOVERNED VISION TOOLS SPECIFICATION

All four vision tools are registered in `BUILTIN_TOOLS` with `risk_level: "low"` and execute strictly via `ToolRegistryService`:

| Tool Name | Input Parameters | Output Contract | Coordinate Space | Risk Level |
| :--- | :--- | :--- | :--- | :--- |
| `inspect_current_screen` | `monitor_id` (int), `prompt` (str), `detail_level` (str), `model` (str), `include_ocr_context` (bool) | `VisionObservationResponse` (summary, confidence, envelope, duration, model) | `captured_frame` / `screen` | `low` |
| `inspect_active_window` | `prompt` (str), `detail_level` (str), `model` (str), `include_ocr_context` (bool) | `VisionObservationResponse` (summary, `window_info` [title, PID, bounds], envelope) | `active_window` | `low` |
| `inspect_camera_frame` | `prompt` (str), `detail_level` (str), `model` (str) | `VisionObservationResponse` (summary, confidence, envelope; safe inactive status if no live frame) | `captured_frame` | `low` |
| `query_visible_text` | `query` (str), `min_confidence` (float), `case_sensitive` (bool), `monitor_id` (int) | Structured OCR regions list (text, confidence, bbox `[x,y,w,h]`, polygon, normalized bbox) | `captured_frame` | `low` |

---

## 4. SECURITY & PRIVACY INVARIANTS VERIFICATION

1. **Ticket Secret Redaction in Logs & Telemetry:**
   - Regex patterns in `apps/api/app/core/redaction.py` redact URL query parameter tickets (`[?&]ticket=...`), `session_nonce`, and token patterns into `[REDACTED_TICKET]`.
   - Prohibited telemetry key substrings in `apps/api/app/core/telemetry.py` sanitize all span attributes containing `"ticket"`, `"vision_ticket"`, or `"nonce"`.
2. **Untrusted Multimodal Containment:**
   - All visual descriptions and OCR text are wrapped in `<untrusted_multimodal_content origin="..." model="...">` with delimiter escaping (`[ESCAPED_DELIMITER:...]`) preventing agent prompt injection.
3. **Emergency Kill Switch Authority:**
   - Setting kill switch active immediately aborts active VLM inference, blocks tool execution with `AuthorizationError`, and purges all volatile observation buffers (`clear_observation_cache`).
4. **Zero Persistent Storage:**
   - Zero disk persistence, zero database storage for visual frames or VLM outputs. Retention is strictly volatile depth-1 in-memory replacement.
5. **Camera Privacy:**
   - HUD reports `CAMERA ACTIVE` or `CAMERA STOPPED` based strictly on active application session status without falsely claiming hardware LED state.

---

## 5. QUANTITATIVE HARDWARE BENCHMARK RESULTS

Benchmarked on host machine (AMD Ryzen 7 4800H 8C/16T, 24 GB RAM, Windows 11):

```text
================================================================================================
AURA-804 VISION VLM & GOVERNED VISION TOOLS HARDWARE BENCHMARK
================================================================================================
Operation                           |      Min |     Mean |      P50 |      P95 |      P99 |      Max
------------------------------------------------------------------------------------------------
Screen Capture & Encode             |  85.948ms| 107.662ms|  90.539ms| 102.030ms| 927.291ms| 927.291ms
Camera Binary Header Pack           |   0.001ms|   0.001ms|   0.001ms|   0.001ms|   0.003ms|   0.011ms
Camera Binary Header Unpack         |   0.001ms|   0.002ms|   0.002ms|   0.002ms|   0.009ms|   0.015ms
RapidOCR Inference (CPU)            | 275.378ms| 301.521ms| 286.000ms| 319.322ms| 523.673ms| 523.673ms
Prompt Injection & Envelope         |   0.025ms|   0.026ms|   0.025ms|   0.027ms|   0.043ms|   0.051ms
Governed Tool (query_text)          |   0.076ms|   0.108ms|   0.089ms|   0.244ms|   0.263ms|   0.263ms
Governed Tool (inspect_cam)         |   0.142ms|   0.209ms|   0.195ms|   0.344ms|   0.537ms|   0.537ms
Vision HUD State Aggregate          |   1.146ms|   1.751ms|   1.685ms|   2.247ms|   2.504ms|   4.403ms
================================================================================================
```

---

## 6. REGRESSION & TEST VERIFICATION SUMMARY

| Test Suite | Total Tests | Status | Execution Time |
| :--- | :--- | :--- | :--- |
| `tests/test_vision_vlm_governed.py` (Dedicated AURA-804 Backend Suite) | 13 | PASSED | 0.37s |
| `tests/benchmark_aura804_vision_vlm.py` (Hardware Benchmark) | 8 Suites | PASSED | ~15s |
| `tests/verify_aura804_live_vision.py` (Live Windows Desktop Validation) | 7 Steps | PASSED | ~18s |
| Full Backend Regression Suite (`pytest tests/ -v`) | 419 | PASSED | 236.27s |
| Frontend Vitest Suite (`npm test`) | 33 | PASSED | 1.78s |
| Production Web Build (`npm run build`) | 4 Pages | PASSED | 4.8s |

---

## 7. PHASE BOUNDARY & NEXT MILESTONES

With the completion and acceptance of AURA-804, **Phase 8 is 100% COMPLETE**.

```text
Phase 8 State:
  AURA-801: Desktop Screen Capture & Multi-Monitor Topology  ──► ACCEPTED
  AURA-802: Continuous Local OCR & Text Extraction Engine    ──► ACCEPTED
  AURA-803: Live Camera Ingestion & Duplex Vision Transport ──► ACCEPTED
  AURA-804: Real-Time Screen VLM, Governed Tools & HUD      ──► COMPLETE & ACCEPTED

Phase 9 (OS Automation, Process Control & PyAutoGUI)        ──► NOT STARTED
Phase 10 (Interactive Browser Automation & Cookie Vault)     ──► NOT STARTED
```

**AURA Phase 8 is complete, and explicit authorization is required before Phase 9.**
