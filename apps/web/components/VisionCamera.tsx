'use client';

import React, { useState, useRef, useEffect, useCallback } from 'react';
import { api } from '../lib/api';
import { useAuraStore } from '../lib/store';

export type CameraPrivacyState =
  | 'camera_stopped'
  | 'camera_requested'
  | 'camera_permitted'
  | 'camera_active'
  | 'camera_unavailable'
  | 'kill_switched';

interface VisionCameraProps {
  workspaceId?: string;
  onStateChange?: (state: CameraPrivacyState) => void;
}

const FRAME_HEADER_SIZE = 26;
const STREAM_TYPE_CAMERA = 0x02;

export const VisionCamera: React.FC<VisionCameraProps> = ({ workspaceId, onStateChange }) => {
  const activeWorkspace = useAuraStore((state) => state.activeWorkspace);
  const targetWsId = workspaceId || activeWorkspace?.id;

  const [cameraState, setCameraState] = useState<CameraPrivacyState>('camera_stopped');
  const [targetFps, setTargetFps] = useState<number>(2.0); // 2 FPS default, 5 FPS max
  const [framesAccepted, setFramesAccepted] = useState<number>(0);
  const [framesDropped, setFramesDropped] = useState<number>(0);
  const [currentSeq, setCurrentSeq] = useState<number>(0);
  const [lastRttMs, setLastRttMs] = useState<number | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const timerRef = useRef<NodeJS.Timeout | null>(null);
  const seqCounterRef = useRef<number>(1);
  const frameSentTimeMap = useRef<Map<number, number>>(new Map());

  const updateState = (st: CameraPrivacyState) => {
    setCameraState(st);
    onStateChange?.(st);
  };

  // Pack 26-byte Big-Endian binary header
  const packHeader = (
    streamType: number,
    sourceId: number,
    seq: number,
    timestampNs: bigint,
    width: number,
    height: number,
    payloadLen: number
  ): Uint8Array => {
    const buffer = new ArrayBuffer(FRAME_HEADER_SIZE);
    const view = new DataView(buffer);
    view.setUint8(0, streamType);
    view.setUint8(1, sourceId);
    view.setUint32(2, seq, false); // Big-Endian
    view.setBigUint64(6, timestampNs, false); // Big-Endian
    view.setUint32(14, width, false); // Big-Endian
    view.setUint32(18, height, false); // Big-Endian
    view.setUint32(22, payloadLen, false); // Big-Endian
    return new Uint8Array(buffer);
  };

  // Release camera media tracks cleanly
  const releaseCameraTracks = useCallback(() => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => {
        try {
          track.stop();
        } catch {
          // ignore
        }
      });
      streamRef.current = null;
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
  }, []);

  // Stop camera streaming session
  const stopCamera = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }

    if (wsRef.current) {
      try {
        if (wsRef.current.readyState === WebSocket.OPEN) {
          wsRef.current.send(JSON.stringify({ type: 'stop' }));
        }
        wsRef.current.close();
      } catch {
        // ignore
      }
      wsRef.current = null;
    }

    releaseCameraTracks();
    updateState('camera_stopped');
  }, [releaseCameraTracks]);

  // Clean teardown on unmount
  useEffect(() => {
    return () => {
      stopCamera();
    };
  }, [stopCamera]);

  // Capture single frame from video and send over WebSocket
  const captureAndSendFrame = useCallback(() => {
    if (!videoRef.current || !canvasRef.current || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      return;
    }

    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (video.videoWidth === 0 || video.videoHeight === 0) {
      return;
    }

    // Set canvas dimensions proportional to video (bounded to 1280x720)
    let w = video.videoWidth;
    let h = video.videoHeight;
    const maxW = 1280;
    const maxH = 720;
    if (w > maxW || h > maxH) {
      const scale = Math.min(maxW / w, maxH / h);
      w = Math.round(w * scale);
      h = Math.round(h * scale);
    }

    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    ctx.drawImage(video, 0, 0, w, h);

    canvas.toBlob(
      async (blob) => {
        if (!blob || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;

        const arrayBuffer = await blob.arrayBuffer();
        const payloadBytes = new Uint8Array(arrayBuffer);
        const seq = seqCounterRef.current++;
        setCurrentSeq(seq);

        const nowNs = BigInt(Date.now()) * BigInt(1000000);
        const headerBytes = packHeader(
          STREAM_TYPE_CAMERA,
          0,
          seq,
          nowNs,
          w,
          h,
          payloadBytes.byteLength
        );

        // Concatenate header (26 bytes) + WebP payload
        const combined = new Uint8Array(FRAME_HEADER_SIZE + payloadBytes.byteLength);
        combined.set(headerBytes, 0);
        combined.set(payloadBytes, FRAME_HEADER_SIZE);

        frameSentTimeMap.current.set(seq, performance.now());
        wsRef.current.send(combined.buffer);
      },
      'image/webp',
      0.80
    );
  }, []);

  // Start live camera acquisition and streaming
  const startCamera = async () => {
    if (!targetWsId) {
      setErrorMsg('No active workspace selected.');
      return;
    }

    setErrorMsg(null);
    updateState('camera_requested');

    try {
      // 1. Request camera media stream from browser
      const stream = await navigator.mediaDevices.getUserMedia({
        video: {
          width: { ideal: 1280, max: 1920 },
          height: { ideal: 720, max: 1080 },
          frameRate: { ideal: targetFps, max: 5.0 },
        },
        audio: false,
      });

      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
      }
      updateState('camera_permitted');

      // 2. Obtain short-lived single-use vision ticket
      const ticketRes = await api.vision.getTicket(targetWsId, 60, 'camera_stream');
      const ticketToken = ticketRes.ticket;

      // 3. Connect to duplex WebSocket on backend
      const baseUrl = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000/api/v1';
      const wsBase = baseUrl.replace(/^http/, 'ws');
      const wsUrl = `${wsBase}/vision/stream?ticket=${encodeURIComponent(ticketToken)}&workspace_id=${encodeURIComponent(targetWsId)}`;

      const ws = new WebSocket(wsUrl);
      ws.binaryType = 'arraybuffer';
      wsRef.current = ws;

      ws.onopen = () => {
        updateState('camera_active');
        seqCounterRef.current = 1;
        setFramesAccepted(0);
        setFramesDropped(0);

        // Start sampling timer (cadence = 1000ms / targetFps)
        const intervalMs = Math.max(200, Math.round(1000 / targetFps));
        timerRef.current = setInterval(captureAndSendFrame, intervalMs);
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === 'frame_accepted') {
            setFramesAccepted((prev) => prev + 1);
            if (msg.sequence_number && frameSentTimeMap.current.has(msg.sequence_number)) {
              const sentAt = frameSentTimeMap.current.get(msg.sequence_number)!;
              setLastRttMs(Math.round(performance.now() - sentAt));
              frameSentTimeMap.current.delete(msg.sequence_number);
            }
          } else if (msg.type === 'frame_dropped') {
            setFramesDropped((prev) => prev + 1);
          } else if (msg.type === 'kill_switch') {
            updateState('kill_switched');
            stopCamera();
            setErrorMsg('Emergency Kill Switch is ACTIVE: Vision operations aborted.');
          } else if (msg.type === 'error') {
            setErrorMsg(msg.message || 'Vision transport error');
          }
        } catch {
          // ignore non-json messages
        }
      };

      ws.onerror = () => {
        setErrorMsg('WebSocket transport error encountered.');
        stopCamera();
      };

      ws.onclose = () => {
        if (cameraState === 'camera_active') {
          updateState('camera_stopped');
        }
      };
    } catch (err: any) {
      releaseCameraTracks();
      if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
        updateState('camera_unavailable');
        setErrorMsg('Camera access permission was denied by the browser.');
      } else if (err.name === 'NotFoundError' || err.name === 'DevicesNotFoundError') {
        updateState('camera_unavailable');
        setErrorMsg('No compatible camera device found on system.');
      } else {
        updateState('camera_unavailable');
        setErrorMsg(err.message || 'Failed to acquire camera.');
      }
    }
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 text-slate-100 shadow-xl max-w-2xl">
      {/* Header & Privacy Status */}
      <div className="flex items-center justify-between pb-4 border-b border-slate-800 mb-4">
        <div>
          <h3 className="text-lg font-bold text-slate-100 flex items-center gap-2">
            <span className="inline-block w-2.5 h-2.5 rounded-full bg-cyan-400 animate-pulse"></span>
            AURA Live Camera Transport (AURA-803)
          </h3>
          <p className="text-xs text-slate-400">
            Local-first WebP transport over 26-byte binary WebSocket (Max 5.0 FPS)
          </p>
        </div>

        {/* State Badge */}
        <div>
          {cameraState === 'camera_active' && (
            <span className="px-2.5 py-1 bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 text-xs font-semibold rounded-full flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-ping"></span>
              STREAMING
            </span>
          )}
          {cameraState === 'camera_permitted' && (
            <span className="px-2.5 py-1 bg-cyan-500/20 text-cyan-400 border border-cyan-500/30 text-xs font-semibold rounded-full">
              PERMITTED
            </span>
          )}
          {cameraState === 'camera_requested' && (
            <span className="px-2.5 py-1 bg-amber-500/20 text-amber-400 border border-amber-500/30 text-xs font-semibold rounded-full animate-pulse">
              PROMPTING...
            </span>
          )}
          {cameraState === 'camera_stopped' && (
            <span className="px-2.5 py-1 bg-slate-700 text-slate-300 text-xs font-semibold rounded-full">
              STOPPED
            </span>
          )}
          {cameraState === 'camera_unavailable' && (
            <span className="px-2.5 py-1 bg-rose-500/20 text-rose-400 border border-rose-500/30 text-xs font-semibold rounded-full">
              UNAVAILABLE
            </span>
          )}
          {cameraState === 'kill_switched' && (
            <span className="px-2.5 py-1 bg-red-600 text-white text-xs font-bold rounded-full">
              KILL-SWITCHED
            </span>
          )}
        </div>
      </div>

      {/* Error Banner */}
      {errorMsg && (
        <div className="mb-4 p-3 bg-rose-950/50 border border-rose-800/80 rounded-lg text-rose-200 text-xs flex items-center justify-between">
          <span>{errorMsg}</span>
          <button onClick={() => setErrorMsg(null)} className="text-rose-400 hover:text-rose-200">
            ✕
          </button>
        </div>
      )}

      {/* Video Preview & Canvas Area */}
      <div className="relative bg-slate-950 rounded-lg overflow-hidden aspect-video flex items-center justify-center border border-slate-800/80 mb-4">
        <video
          ref={videoRef}
          className={`w-full h-full object-cover ${cameraState === 'camera_active' ? 'block' : 'hidden'}`}
          playsInline
          muted
        />
        <canvas ref={canvasRef} className="hidden" />

        {cameraState !== 'camera_active' && (
          <div className="text-center p-6 text-slate-500">
            <svg
              className="w-12 h-12 mx-auto mb-2 text-slate-600"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1.5}
                d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z"
              />
            </svg>
            <p className="text-sm">Camera feed is currently offline</p>
            <p className="text-xs text-slate-600 mt-1">Browser permission prompt will appear upon activation</p>
          </div>
        )}

        {/* Live Overlay Telemetry */}
        {cameraState === 'camera_active' && (
          <div className="absolute top-2 left-2 bg-slate-900/80 backdrop-blur-md px-2.5 py-1 rounded text-[11px] font-mono text-cyan-300 border border-cyan-500/30 flex items-center gap-2">
            <span>Seq: #{currentSeq}</span>
            <span>•</span>
            <span>RTT: {lastRttMs !== null ? `${lastRttMs}ms` : '--'}</span>
          </div>
        )}
      </div>

      {/* Telemetry Metrics Bar */}
      <div className="grid grid-cols-4 gap-2 mb-4 text-center text-xs">
        <div className="bg-slate-950/60 p-2.5 rounded-lg border border-slate-800">
          <div className="text-slate-400 text-[10px] uppercase font-semibold">Accepted</div>
          <div className="text-emerald-400 font-bold text-sm">{framesAccepted}</div>
        </div>
        <div className="bg-slate-950/60 p-2.5 rounded-lg border border-slate-800">
          <div className="text-slate-400 text-[10px] uppercase font-semibold">Dropped</div>
          <div className="text-amber-400 font-bold text-sm">{framesDropped}</div>
        </div>
        <div className="bg-slate-950/60 p-2.5 rounded-lg border border-slate-800">
          <div className="text-slate-400 text-[10px] uppercase font-semibold">Sampling FPS</div>
          <div className="text-cyan-400 font-bold text-sm">{targetFps.toFixed(1)} FPS</div>
        </div>
        <div className="bg-slate-950/60 p-2.5 rounded-lg border border-slate-800">
          <div className="text-slate-400 text-[10px] uppercase font-semibold">Buffer Depth</div>
          <div className="text-slate-300 font-bold text-sm">1 Frame</div>
        </div>
      </div>

      {/* Controls */}
      <div className="flex items-center justify-between pt-2">
        <div className="flex items-center gap-3">
          <span className="text-xs text-slate-400">Rate Target:</span>
          <div className="flex items-center gap-1.5">
            {[1.0, 2.0, 4.0, 5.0].map((fps) => (
              <button
                key={fps}
                disabled={cameraState === 'camera_active'}
                onClick={() => setTargetFps(fps)}
                className={`px-2.5 py-1 text-xs rounded font-medium transition ${
                  targetFps === fps
                    ? 'bg-cyan-600 text-white font-bold'
                    : 'bg-slate-800 text-slate-400 hover:text-slate-200'
                } ${cameraState === 'camera_active' ? 'opacity-50 cursor-not-allowed' : ''}`}
              >
                {fps.toFixed(1)} FPS
              </button>
            ))}
          </div>
        </div>

        <div>
          {cameraState === 'camera_active' ? (
            <button
              onClick={stopCamera}
              className="px-4 py-2 bg-rose-600 hover:bg-rose-500 text-white text-xs font-bold rounded-lg shadow-lg transition flex items-center gap-1.5"
            >
              <span className="w-2 h-2 rounded-full bg-white"></span>
              Stop Camera Feed
            </button>
          ) : (
            <button
              onClick={startCamera}
              className="px-4 py-2 bg-cyan-600 hover:bg-cyan-500 text-white text-xs font-bold rounded-lg shadow-lg shadow-cyan-600/20 transition flex items-center gap-1.5"
            >
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              Start Camera Feed
            </button>
          )}
        </div>
      </div>

      {/* Privacy Notice Banner */}
      <div className="mt-4 pt-3 border-t border-slate-800/80 text-[11px] text-slate-400 flex items-center gap-2">
        <svg className="w-3.5 h-3.5 text-cyan-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
        </svg>
        <span>
          <strong>Ephemeral Memory Guarantee:</strong> Raw camera frames exist only in volatile RAM for downstream inspection and are never written to disk or logged.
        </span>
      </div>
    </div>
  );
};
