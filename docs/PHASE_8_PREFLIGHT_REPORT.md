# AURA Phase 8 — Continuous Screen, Camera & Live Multimodal Vision
## Preflight & Implementation Readiness Audit Report
**Document Version:** 1.0.0  
**Status:** AUDIT COMPLETE & LOCKED (READY FOR AUTHORIZATION)  
**Hardware Profile:** AMD Ryzen 7 4800H (8C/16T), 24 GB RAM, NVIDIA RTX 3050 (4 GB VRAM), Windows 11  
**Cloud Cost Invariant:** $0.00 (100% Zero-Cost Local-First Substrate)  

---

## 1. Executive Summary & Readiness Assessment

Phase 7 (Real-Time Local Voice & Speech System) is officially complete and accepted with 383/383 passing tests and clean production builds.

This preflight audit establishes the architectural blueprint, hardware budget allocations, security invariants, streaming protocols, and task breakdown for **Phase 8: Continuous Screen, Camera & Live Multimodal Vision**.

### Readiness Verdict:
```text
PHASE 8 PREFLIGHT = PASSED & LOCKED
IMPLEMENTATION STATUS = PENDING EXPLICIT USER AUTHORIZATION
```

---

## 2. Canonical Phase 8 Scope & Strict Boundary Locks

### In-Scope (Phase 8 Only):
1. **Multi-Monitor Screen Capture:** Local high-performance desktop snapshot and continuous frame capture (`mss`, Windows GDI `BitBlt`, Per-Monitor v2 DPI awareness).
2. **Active-Window Awareness:** OS-level window hierarchy, active application title, PID, and bounding coordinate tracking (`pygetwindow`, `GetForegroundWindow`).
3. **Live Camera Ingestion:** Ephemeral camera video frame ingestion via Web standard `getUserMedia` and WebSocket streaming gateway.
4. **Continuous Local OCR:** Sub-100ms text and bounding-box extraction with SSIM delta filtering (`rapidocr-onnxruntime` on existing ONNX engine / `pytesseract`).
5. **Real-Time Screen VLM Reasoning:** Adaptive on-demand and keyframe visual understanding via quantized `Moondream2` (~1.86B, 1.2 GB VRAM).
6. **Visual Overlays & HUD:** Next.js Vision HUD with real-time canvas stream preview, OCR bounding overlays, and privacy status.
7. **Governed Agent Tools:** `inspect_current_screen`, `inspect_active_window`, `inspect_camera_frame`, `query_visible_text`.

### Explicit Boundary Exclusions (Locked Out):
* **Phase 9 (OS Automation):** No PyAutoGUI mouse clicks, keystrokes, window-move automation, hardware volume/brightness control, or system tray hotkeys.
* **Phase 10 (Interactive Browser & Daemons):** No Playwright browser DOM clicks/form-filling, cookie vaults, or Windows background services.

---

## 3. Hardware Budget & Resource Allocation (RTX 3050 4 GB VRAM)

```text
============================ RESOURCE ALLOCATION MATRIX ============================
Component                   Engine / Model               RAM Budget     VRAM Budget     Target Latency
------------------------------------------------------------------------------------
Screen Capture (1-2 FPS)    mss (Windows GDI)            ~30 MB         0 MB (CPU/GDI)  <= 15 ms
Active-Window Hook          ctypes / pygetwindow         ~5 MB          0 MB            <= 5 ms
Camera Frame Ingestion      WebSocket / WebP             ~25 MB         0 MB            <= 20 ms
Continuous Local OCR        RapidOCR / ONNX Runtime      ~80 MB         0 MB (CPU ONNX) <= 100 ms
Real-Time Screen VLM        Moondream2 (int4 / int8)     ~250 MB        1.2 GB (VRAM)   <= 900 ms
Existing STT / TTS (P7)     Faster-Whisper + Piper       ~300 MB        0.4 GB (VRAM)   <= 250 ms
Host OS & Desktop Plane     Windows 11 + FastAPI + DB    ~2.5 GB        0.8 GB (DWM)    N/A
------------------------------------------------------------------------------------
TOTAL ALLOCATED                                          ~3.2 GB / 24GB 2.4 GB / 4.0GB  PASS
HEADROOM AVAILABLE                                       20.8 GB RAM    1.6 GB VRAM     PASS
====================================================================================
```

---

## 4. Architectural Invariants & Flow

```text
[ Desktop Screen / Camera ]
         │
         ▼
[ Capture Capability (mss / getUserMedia) ] (Max 2-5 FPS, SSIM Delta Filtering)
         │
         ├──────────────────────────────────────────┐
         ▼                                          ▼
[ Continuous Local OCR (ONNX) ]           [ Visual Delta Detector ]
 (RapidOCR / Bounding Boxes)               (Scene Change Trigger)
         │                                          │
         └────────────────────┬─────────────────────┘
                              ▼
           [ <untrusted_multimodal_content> ] (Prompt-Injection Defense)
                              │
                              ▼
               [ Agent Runtime Engine & Planner ]
                              │
                ┌─────────────┴─────────────┐
                ▼                           ▼
      [ Governed Vision Tools ]    [ Policy & HITL Gate ]
     (inspect_current_screen)      (Destructive Action Check)
                │                           │
                └─────────────┬─────────────┘
                              ▼
                 [ Audit & OTel Telemetry ]
               (Zero Raw Image/Audio Storage)
```

---

## 5. Security & Privacy Guarantees

1. **Ephemeral Frame Invariant:** Continuous visual frames exist strictly in volatile memory (circular buffer depth = 1). Zero video or screenshot files written to disk or database.
2. **Untrusted Multimodal Envelope:** All visual descriptions, screen transcriptions, and OCR texts entering agent reasoning are wrapped in `<untrusted_multimodal_content>` XML blocks.
3. **No Direct Capability-to-Tool Execution:** Continuous sensors NEVER directly invoke tools. Actions are proposed by the Agent Planner and governed by PolicyEngine and HITL.
4. **Emergency Kill-Switch Authority:** Activating the global kill switch immediately terminates screen capture threads, camera WebSocket streams, and active VLM/OCR processing.

---

## 6. Granular Phase 8 Task Breakdown

| Task ID | Task Title | Scope & Deliverables | Dependencies |
| :--- | :--- | :--- | :--- |
| **AURA-801** | Multi-Monitor Screen & Active-Window Capture | `ScreenCaptureService`, `mss` multi-monitor discovery, per-monitor DPI v2 scaling, active-window bounding boxes (`pygetwindow`), SSIM frame delta detection ($\ge 5\%$). | Phase 7 |
| **AURA-802** | Continuous Local OCR & Text Bounding Extraction | `ContinuousOCRService`, sub-100ms OCR via `rapidocr-onnxruntime` / `pytesseract`, text deduplication cache, `<untrusted_multimodal_content>` envelope. | AURA-801 |
| **AURA-803** | Live Camera Ingestion & Duplex Vision Transport | `CameraVisionService`, ticket-authenticated WebSocket `/api/v1/vision/stream`, Web standard `getUserMedia`, single-frame ephemeral ring buffer. | AURA-801, AURA-704 |
| **AURA-804** | Real-Time Screen VLM, Governed Tools & Next.js HUD | `inspect_current_screen`, `inspect_active_window`, `query_visible_text` governed tools, Next.js Vision HUD component with canvas preview and bounding overlays, Kill-Switch integration. | AURA-802, AURA-803 |

---

## 7. Next Step

Awaiting explicit user authorization before starting **AURA-801**.
