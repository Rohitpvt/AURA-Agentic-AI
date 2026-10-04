'use client';

import React, { useEffect, useState, useCallback } from 'react';
import { auraApi } from '../lib/api';
import { useAuraStore } from '../lib/store';

interface DetectedElement {
  label: string;
  description: string;
  confidence: number;
  bounding_box?: [number, number, number, number];
  polygon?: number[][];
  normalized_box?: [number, number, number, number];
  coordinate_space?: string;
}

interface VisionObservationData {
  observation_id: string;
  workspace_id: string;
  source_type: string;
  source_id: string;
  timestamp: number;
  summary: string;
  detected_elements: DetectedElement[];
  coordinate_space: string;
  confidence: number;
  model: string;
  device: string;
  processing_duration_ms: number;
  degraded: boolean;
  untrusted_content_envelope: string;
  is_untrusted_content: boolean;
  security_flags?: string[];
  ocr_context_summary?: string;
  window_info?: {
    window_title: string;
    process_name?: string;
    bounds?: { left: number; top: number; width: number; height: number };
  };
}

interface HUDState {
  workspace_id: string;
  screen_active: boolean;
  camera_active: boolean;
  ocr_status: string;
  vlm_status: string;
  kill_switch_active: boolean;
  latest_observation?: VisionObservationData | null;
}

export function VisionHUD() {
  const activeWorkspace = useAuraStore((state) => state.activeWorkspace);
  const [hudState, setHudState] = useState<HUDState | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [isInspecting, setIsInspecting] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'overview' | 'observation' | 'ocr' | 'privacy'>('overview');

  const fetchHUDState = useCallback(async () => {
    try {
      setIsLoading(true);
      const res = await auraApi.vision.getHUDState(activeWorkspace?.id);
      setHudState(res);
      setErrorMessage(null);
    } catch (err: any) {
      setErrorMessage(err?.message || 'Failed to connect to Vision subsystem');
    } finally {
      setIsLoading(false);
    }
  }, [activeWorkspace?.id]);

  useEffect(() => {
    fetchHUDState();
    const interval = setInterval(fetchHUDState, 5000);
    return () => clearInterval(interval);
  }, [fetchHUDState]);

  const handleInspect = async (sourceType: 'screen' | 'active_window' | 'camera') => {
    try {
      setIsInspecting(true);
      setErrorMessage(null);
      const res = await auraApi.vision.inspectVLM(
        { source_type: sourceType, detail_level: 'standard' },
        activeWorkspace?.id
      );
      setHudState((prev) => (prev ? { ...prev, latest_observation: res } : null));
      setActiveTab('observation');
    } catch (err: any) {
      setErrorMessage(err?.message || `Failed to inspect ${sourceType}`);
    } finally {
      setIsInspecting(false);
    }
  };

  const handleClearCache = async () => {
    try {
      await auraApi.vision.clearVLMCache(activeWorkspace?.id);
      await fetchHUDState();
    } catch (err: any) {
      setErrorMessage(err?.message || 'Failed to clear VLM cache');
    }
  };

  const obs = hudState?.latest_observation;

  return (
    <div className="flex flex-col bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-2xl text-slate-100 font-sans">
      {/* HUD Header */}
      <div className="flex items-center justify-between px-6 py-4 bg-slate-950/80 border-b border-slate-800">
        <div className="flex items-center space-x-3">
          <div className="relative flex items-center justify-center w-8 h-8 rounded-lg bg-indigo-500/10 border border-indigo-500/30 text-indigo-400 font-mono text-sm font-bold">
            👁️
          </div>
          <div>
            <h2 className="text-base font-semibold tracking-wide text-slate-100 flex items-center space-x-2">
              <span>AURA Vision HUD</span>
              <span className="text-xs px-2 py-0.5 rounded-full font-mono bg-indigo-900/50 text-indigo-300 border border-indigo-700/50">
                Phase 8.4
              </span>
            </h2>
            <p className="text-xs text-slate-400">Real-Time Screen & Multimodal Vision Intelligence</p>
          </div>
        </div>

        {/* Global Kill Switch & Connectivity Badges */}
        <div className="flex items-center space-x-3">
          <div
            className={`px-3 py-1 rounded-full text-xs font-mono font-medium border flex items-center space-x-1.5 ${
              hudState?.kill_switch_active
                ? 'bg-rose-950/80 text-rose-300 border-rose-800 animate-pulse'
                : 'bg-emerald-950/50 text-emerald-300 border-emerald-800/60'
            }`}
          >
            <span
              className={`w-2 h-2 rounded-full ${
                hudState?.kill_switch_active ? 'bg-rose-500' : 'bg-emerald-500'
              }`}
            />
            <span>{hudState?.kill_switch_active ? 'KILL SWITCH ACTIVE' : 'SYSTEM ARMED'}</span>
          </div>

          <button
            onClick={fetchHUDState}
            disabled={isLoading || isInspecting}
            className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 transition-colors border border-slate-700 text-xs"
            title="Refresh HUD State"
          >
            🔄
          </button>
        </div>
      </div>

      {/* Subsystem Pipeline Status Grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 p-4 bg-slate-950/40 border-b border-slate-800/80">
        {/* Screen Sensing */}
        <div className="flex flex-col p-3 rounded-lg bg-slate-800/40 border border-slate-700/50">
          <span className="text-xs font-mono text-slate-400">SCREEN SENSING (AURA-801)</span>
          <div className="flex items-center space-x-2 mt-1">
            <span
              className={`w-2.5 h-2.5 rounded-full ${
                hudState?.screen_active ? 'bg-emerald-400 animate-pulse' : 'bg-slate-600'
              }`}
            />
            <span className="text-sm font-semibold text-slate-200">
              {hudState?.screen_active ? 'ACTIVE (Depth-1)' : 'IDLE'}
            </span>
          </div>
        </div>

        {/* Camera Ingestion */}
        <div className="flex flex-col p-3 rounded-lg bg-slate-800/40 border border-slate-700/50">
          <span className="text-xs font-mono text-slate-400">CAMERA TRANSPORT (AURA-803)</span>
          <div className="flex items-center space-x-2 mt-1">
            <span
              className={`w-2.5 h-2.5 rounded-full ${
                hudState?.camera_active ? 'bg-indigo-400 animate-pulse' : 'bg-slate-600'
              }`}
            />
            <span className="text-sm font-semibold text-slate-200">
              {hudState?.camera_active ? 'STREAMING (5 FPS)' : 'STOPPED'}
            </span>
          </div>
        </div>

        {/* OCR Engine */}
        <div className="flex flex-col p-3 rounded-lg bg-slate-800/40 border border-slate-700/50">
          <span className="text-xs font-mono text-slate-400">LOCAL OCR (AURA-802)</span>
          <div className="flex items-center space-x-2 mt-1">
            <span
              className={`w-2.5 h-2.5 rounded-full ${
                hudState?.ocr_status === 'ready'
                  ? 'bg-emerald-400'
                  : hudState?.ocr_status === 'kill_switched'
                  ? 'bg-rose-500'
                  : 'bg-amber-400'
              }`}
            />
            <span className="text-sm font-semibold text-slate-200 uppercase">
              {hudState?.ocr_status || 'READY'} (1 Hz)
            </span>
          </div>
        </div>

        {/* VLM Engine */}
        <div className="flex flex-col p-3 rounded-lg bg-slate-800/40 border border-slate-700/50">
          <span className="text-xs font-mono text-slate-400">VISION VLM (AURA-804)</span>
          <div className="flex items-center space-x-2 mt-1">
            <span
              className={`w-2.5 h-2.5 rounded-full ${
                hudState?.vlm_status === 'processing'
                  ? 'bg-blue-400 animate-spin'
                  : hudState?.vlm_status === 'ready'
                  ? 'bg-emerald-400'
                  : 'bg-amber-400'
              }`}
            />
            <span className="text-sm font-semibold text-slate-200 uppercase">
              {hudState?.vlm_status || 'READY'} (CPU / 0.2 FPS)
            </span>
          </div>
        </div>
      </div>

      {/* Control Actions & Navigation Tabs */}
      <div className="flex items-center justify-between px-6 py-2.5 bg-slate-900 border-b border-slate-800">
        <div className="flex space-x-2">
          <button
            onClick={() => setActiveTab('overview')}
            className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
              activeTab === 'overview'
                ? 'bg-indigo-600 text-white shadow'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'
            }`}
          >
            Sensing Controls
          </button>
          <button
            onClick={() => setActiveTab('observation')}
            className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
              activeTab === 'observation'
                ? 'bg-indigo-600 text-white shadow'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'
            }`}
          >
            Latest Observation {obs && '✨'}
          </button>
          <button
            onClick={() => setActiveTab('privacy')}
            className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
              activeTab === 'privacy'
                ? 'bg-indigo-600 text-white shadow'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'
            }`}
          >
            Privacy Invariants
          </button>
        </div>

        {/* Governed On-Demand Trigger Actions */}
        <div className="flex items-center space-x-2">
          <button
            onClick={() => handleInspect('screen')}
            disabled={isInspecting || hudState?.kill_switch_active}
            className="px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium border border-slate-700 disabled:opacity-50 transition-colors"
          >
            {isInspecting ? 'Processing...' : '📸 Inspect Screen'}
          </button>
          <button
            onClick={() => handleInspect('active_window')}
            disabled={isInspecting || hudState?.kill_switch_active}
            className="px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium border border-slate-700 disabled:opacity-50 transition-colors"
          >
            🪟 Inspect Window
          </button>
          <button
            onClick={() => handleInspect('camera')}
            disabled={isInspecting || hudState?.kill_switch_active || !hudState?.camera_active}
            className="px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium border border-slate-700 disabled:opacity-50 transition-colors"
          >
            📹 Inspect Camera
          </button>
        </div>
      </div>

      {/* Error / Alert Banner */}
      {errorMessage && (
        <div className="mx-6 mt-4 p-3 rounded-lg bg-rose-950/60 border border-rose-800/80 text-rose-200 text-xs flex items-center justify-between">
          <span>⚠️ {errorMessage}</span>
          <button
            onClick={() => setErrorMessage(null)}
            className="text-rose-400 hover:text-rose-200 font-bold"
          >
            ✕
          </button>
        </div>
      )}

      {/* Tab Body Viewports */}
      <div className="p-6">
        {activeTab === 'overview' && (
          <div className="space-y-4">
            <div className="p-4 rounded-xl bg-slate-950/60 border border-slate-800">
              <h3 className="text-sm font-semibold text-slate-200 mb-2">Governed Vision Engine Topology</h3>
              <p className="text-xs text-slate-400 leading-relaxed">
                Project AURA operates on a 100% local-first vision pipeline. The primary reasoning LLM runs on GPU, while
                the Vision VLM (Moondream2 / Qwen2-VL) is strictly allocated to the host CPU with a 0.2 FPS rate ceiling.
                Visual frames exist only in volatile single-depth memory and are purged immediately upon session closure or Kill Switch engagement.
              </p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="p-3.5 rounded-lg bg-slate-950/40 border border-slate-800">
                <span className="text-xs font-mono text-indigo-400">1. Rate Limiting Governance</span>
                <p className="text-xs text-slate-300 mt-1">
                  Enforces a hard 0.2 FPS ceiling (min 5.0s delta) for VLM and 1.0 Hz for OCR, preserving system responsiveness.
                </p>
              </div>
              <div className="p-3.5 rounded-lg bg-slate-950/40 border border-slate-800">
                <span className="text-xs font-mono text-indigo-400">2. Untrusted Enveloping</span>
                <p className="text-xs text-slate-300 mt-1">
                  All OCR and VLM textual outputs are wrapped in tamper-evident XML security envelopes to prevent indirect prompt injection.
                </p>
              </div>
              <div className="p-3.5 rounded-lg bg-slate-950/40 border border-slate-800">
                <span className="text-xs font-mono text-indigo-400">3. Ephemeral Depth-1 Buffer</span>
                <p className="text-xs text-slate-300 mt-1">
                  Only the single newest frame is retained. Zero raw pixels are written to disk storage, SQLite, or audit logs.
                </p>
              </div>
            </div>
          </div>
        )}

        {activeTab === 'observation' && (
          <div className="space-y-4">
            {obs ? (
              <div className="space-y-4">
                {/* Observation Metadata Header */}
                <div className="flex flex-wrap items-center justify-between p-3 rounded-lg bg-slate-950/70 border border-slate-800 text-xs font-mono">
                  <div className="flex items-center space-x-3">
                    <span className="text-slate-400">OBS ID:</span>
                    <span className="text-indigo-300">{obs.observation_id.slice(0, 8)}...</span>
                    <span className="text-slate-500">|</span>
                    <span className="text-slate-400">SOURCE:</span>
                    <span className="text-emerald-300 uppercase">{obs.source_type}</span>
                    <span className="text-slate-500">|</span>
                    <span className="text-slate-400">MODEL:</span>
                    <span className="text-amber-300">{obs.model} ({obs.device})</span>
                  </div>

                  <div className="flex items-center space-x-3 mt-2 sm:mt-0">
                    <span className="text-slate-400">LATENCY:</span>
                    <span className="text-slate-200">{obs.processing_duration_ms}ms</span>
                    <span className="text-slate-500">|</span>
                    <span className="text-slate-400">CONFIDENCE:</span>
                    <span className="text-emerald-400 font-bold">{(obs.confidence * 100).toFixed(0)}%</span>
                  </div>
                </div>

                {/* Summary Viewport */}
                <div className="p-4 rounded-xl bg-slate-950/60 border border-slate-800">
                  <span className="text-xs font-mono text-slate-400 block mb-1">SCENE SUMMARY</span>
                  <p className="text-sm text-slate-100 leading-relaxed">{obs.summary}</p>
                </div>

                {/* Detected UI Elements & Geometry */}
                {obs.detected_elements && obs.detected_elements.length > 0 && (
                  <div className="p-4 rounded-xl bg-slate-950/60 border border-slate-800">
                    <span className="text-xs font-mono text-slate-400 block mb-2">
                      DETECTED VISUAL ELEMENTS ({obs.detected_elements.length}) — COORDINATES: {obs.coordinate_space}
                    </span>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                      {obs.detected_elements.map((el, idx) => (
                        <div key={idx} className="p-2.5 rounded bg-slate-900/80 border border-slate-800 text-xs">
                          <div className="flex justify-between items-center font-mono text-indigo-300">
                            <span>{el.label}</span>
                            <span className="text-slate-400 font-normal">{(el.confidence * 100).toFixed(0)}%</span>
                          </div>
                          <p className="text-slate-300 mt-0.5">{el.description}</p>
                          {el.bounding_box && (
                            <span className="text-[10px] font-mono text-slate-500 block mt-1">
                              Box: [{el.bounding_box.join(', ')}]
                            </span>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Untrusted XML Containment Envelope */}
                <div className="p-4 rounded-xl bg-slate-950/80 border border-amber-900/40">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs font-mono text-amber-400 flex items-center space-x-1">
                      <span>🛡️ Untrusted Multimodal Content Envelope</span>
                    </span>
                    <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-amber-950 text-amber-300 border border-amber-800/50">
                      INJECTION ISOLATED
                    </span>
                  </div>
                  <pre className="text-[11px] font-mono bg-slate-900 p-3 rounded border border-slate-800 text-slate-300 overflow-x-auto whitespace-pre-wrap max-h-48">
                    {obs.untrusted_content_envelope}
                  </pre>
                </div>

                <div className="flex justify-end">
                  <button
                    onClick={handleClearCache}
                    className="px-3 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-medium border border-slate-700 transition-colors"
                  >
                    🗑️ Clear Observation Cache
                  </button>
                </div>
              </div>
            ) : (
              <div className="p-8 text-center rounded-xl bg-slate-950/40 border border-slate-800">
                <p className="text-slate-400 text-sm">No visual observation in volatile memory.</p>
                <p className="text-slate-500 text-xs mt-1">Click "Inspect Screen" or "Inspect Window" to acquire real-time visual reasoning.</p>
              </div>
            )}
          </div>
        )}

        {activeTab === 'privacy' && (
          <div className="space-y-4">
            <div className="p-4 rounded-xl bg-slate-950/60 border border-emerald-900/40 space-y-3">
              <h3 className="text-sm font-semibold text-emerald-300 flex items-center space-x-2">
                <span>🔒 Privacy & Ephemeral Memory Guarantees</span>
              </h3>
              <ul className="text-xs text-slate-300 space-y-2 list-disc list-inside">
                <li><strong className="text-slate-100">Zero Persistent Storage:</strong> Screen captures and camera frames exist exclusively in volatile memory for the duration of inference.</li>
                <li><strong className="text-slate-100">No Raw Pixel Logging:</strong> Telemetry spans, logs, and audit ledgers record only execution metadata and bounding coordinates; raw image bytes are strictly excluded.</li>
                <li><strong className="text-slate-100">User Permission Boundary:</strong> Camera capture strictly adheres to browser <code className="font-mono text-indigo-300">getUserMedia</code> prompts and releases media tracks on stop.</li>
                <li><strong className="text-slate-100">Zero Cloud Operating Cost:</strong> 100% of OCR and VLM processing is performed locally on host CPU without transmitting data to external cloud APIs.</li>
                <li><strong className="text-slate-100">Kill Switch Fail-Closed Policy:</strong> Engaging the Emergency Kill Switch immediately terminates running VLM inference and purges all visual caches.</li>
              </ul>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
