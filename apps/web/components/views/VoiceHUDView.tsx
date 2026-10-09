'use client';

import React, { useEffect, useRef, useState } from 'react';
import { useAuraStore } from '../../lib/store';
import { auraApi } from '../../lib/api';
import { VoiceSessionState, VoiceHUDTranscript } from '../../lib/types';
import { AuraOrb, deriveVisualState } from '../aura/AuraOrb';
import {
  Mic,
  MicOff,
  Square,
  AlertCircle,
  Volume2,
  VolumeX,
  Radio,
  Sparkles,
  Zap,
  Image as ImageIcon,
  ShieldAlert,
  CheckCircle2,
  XCircle,
  Play,
  RotateCcw,
  Layers,
  Cpu,
  Eye,
  Loader2,
} from 'lucide-react';

export const VoiceHUDView: React.FC = () => {
  const { activeWorkspace, pendingApprovals, removePendingApproval } = useAuraStore();

  // Voice Session States
  const [sessionState, setSessionState] = useState<VoiceSessionState>('IDLE');
  const [isConnected, setIsConnected] = useState<boolean>(false);
  const [ticket, setTicket] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [transcripts, setTranscripts] = useState<VoiceHUDTranscript[]>([]);
  const [isMuted, setIsMuted] = useState<boolean>(false);
  const [audioGain, setAudioGain] = useState<number>(1.0);
  const [activeModel, setActiveModel] = useState<string>('Whisper-Small (STT) + Kokoro (TTS)');

  // Multimodal Static Context State (AURA-705)
  const [multimodalImage, setMultimodalImage] = useState<{
    file: File | null;
    previewUrl: string | null;
    description: string | null;
    modelUsed: string | null;
    isAnalyzing: boolean;
  }>({
    file: null,
    previewUrl: null,
    description: null,
    modelUsed: null,
    isAnalyzing: false,
  });

  // Resumed Task State
  const [resumedTaskNotice, setResumedTaskNotice] = useState<string | null>(null);

  // Audio & WebSocket Refs
  const wsRef = useRef<WebSocket | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const animFrameRef = useRef<number | null>(null);

  // Auto-scroll transcript feed
  const transcriptEndRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [transcripts]);

  // Audio Visualizer Canvas Loop
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let phase = 0;

    const renderWave = () => {
      const width = canvas.width;
      const height = canvas.height;
      ctx.clearRect(0, 0, width, height);

      // Gradient based on state
      let colorPrimary = 'rgba(6, 182, 212, '; // Cyan (Listening / Idle)
      let colorSecondary = 'rgba(59, 130, 246, '; // Blue

      if (sessionState === 'TRANSCRIBING') {
        colorPrimary = 'rgba(245, 158, 11, '; // Amber
        colorSecondary = 'rgba(234, 88, 12, ';
      } else if (sessionState === 'THINKING') {
        colorPrimary = 'rgba(168, 85, 247, '; // Violet
        colorSecondary = 'rgba(99, 102, 241, ';
      } else if (sessionState === 'SPEAKING') {
        colorPrimary = 'rgba(16, 185, 129, '; // Emerald
        colorSecondary = 'rgba(6, 182, 212, ';
      } else if (sessionState === 'INTERRUPTED') {
        colorPrimary = 'rgba(249, 115, 22, '; // Orange
        colorSecondary = 'rgba(239, 68, 68, ';
      } else if (sessionState === 'ERROR' || sessionState === 'CANCELLED') {
        colorPrimary = 'rgba(239, 68, 68, '; // Red
        colorSecondary = 'rgba(185, 28, 28, ';
      }

      // Draw dynamic visualizer waves
      const bufferLength = analyserRef.current?.frequencyBinCount || 64;
      const dataArray = new Uint8Array(bufferLength);
      if (analyserRef.current && sessionState === 'LISTENING') {
        analyserRef.current.getByteFrequencyData(dataArray);
      }

      const numBars = 48;
      const barWidth = width / numBars;

      for (let i = 0; i < numBars; i++) {
        let value = 10;
        if (sessionState === 'LISTENING') {
          value = Math.max(12, (dataArray[i % bufferLength] / 255) * height * 0.85);
        } else if (sessionState === 'SPEAKING') {
          value = Math.max(15, Math.sin(phase + i * 0.25) * (height * 0.35) + height * 0.45);
        } else if (sessionState === 'THINKING') {
          value = Math.max(10, Math.sin(phase * 2 + i * 0.4) * (height * 0.2) + height * 0.25);
        } else if (sessionState === 'TRANSCRIBING') {
          value = Math.max(14, Math.cos(phase * 1.5 + i * 0.3) * (height * 0.28) + height * 0.3);
        } else {
          value = 6 + Math.sin(phase + i * 0.1) * 4;
        }

        const x = i * barWidth;
        const y = (height - value) / 2;

        const grad = ctx.createLinearGradient(0, y, 0, y + value);
        grad.addColorStop(0, colorPrimary + '0.9)');
        grad.addColorStop(1, colorSecondary + '0.2)');

        ctx.fillStyle = grad;
        ctx.beginPath();
        ctx.roundRect(x + 2, y, barWidth - 4, value, 4);
        ctx.fill();
      }

      phase += 0.08;
      animFrameRef.current = requestAnimationFrame(renderWave);
    };

    renderWave();

    return () => {
      if (animFrameRef.current) {
        cancelAnimationFrame(animFrameRef.current);
      }
    };
  }, [sessionState]);

  // Clean up on unmount
  useEffect(() => {
    return () => {
      stopSession();
    };
  }, []);

  // Start Voice Session
  const startSession = async () => {
    try {
      setErrorMessage(null);
      setSessionState('LISTENING');

      // 1. Get authenticated ticket from AURA-704 Gateway
      const ticketData = await auraApi.voice.getTicket(activeWorkspace?.id);
      setTicket(ticketData.ticket);

      // 2. Initialize Web Audio API
      const AudioContextClass = window.AudioContext || (window as any).webkitAudioContext;
      const audioCtx = new AudioContextClass();
      audioContextRef.current = audioCtx;

      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 128;
      analyserRef.current = analyser;

      // 3. Request user microphone (if available)
      if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
        try {
          const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
          mediaStreamRef.current = stream;
          const source = audioCtx.createMediaStreamSource(stream);
          source.connect(analyser);
        } catch {
          // Microphone fallback in sandboxed test environments
        }
      }

      // 4. Connect WebSocket via ticket to backend
      const baseUrl = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000/api/v1';
      const wsBase = baseUrl.replace(/^http/, 'ws');
      const wsUrl = ticketData.websocket_url
        ? (ticketData.websocket_url.startsWith('ws')
            ? ticketData.websocket_url
            : `${wsBase}${ticketData.websocket_url.replace('/api/v1', '')}`)
        : `${wsBase}/voice/stream?ticket=${ticketData.ticket}${activeWorkspace?.id ? `&workspace_id=${activeWorkspace.id}` : ''}`;

      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        setIsConnected(true);
        setTranscripts((prev) => [
          ...prev,
          {
            id: String(Date.now()),
            speaker: 'system',
            text: 'Authenticated duplex voice stream established. Listening for speech...',
            timestamp: new Date().toLocaleTimeString(),
          },
        ]);
      };

      ws.onmessage = (event) => {
        try {
          if (typeof event.data === 'string') {
            const data = JSON.parse(event.data);
            if (data.type === 'state_change') {
              setSessionState(data.state);
            } else if (data.type === 'transcription_final') {
              setSessionState('THINKING');
              setTranscripts((prev) => [
                ...prev,
                {
                  id: String(Date.now()),
                  speaker: 'user',
                  text: data.text,
                  timestamp: new Date().toLocaleTimeString(),
                  is_untrusted: true,
                  envelope_type: 'spoken',
                },
              ]);
            } else if (data.type === 'agent_response_text') {
              setSessionState('SPEAKING');
              setTranscripts((prev) => [
                ...prev,
                {
                  id: String(Date.now()),
                  speaker: 'agent',
                  text: data.text,
                  timestamp: new Date().toLocaleTimeString(),
                },
              ]);
            } else if (data.type === 'interrupted') {
              setSessionState('INTERRUPTED');
              setTimeout(() => setSessionState('LISTENING'), 1200);
            }
          }
        } catch {
          // Handled frame
        }
      };

      ws.onerror = () => {
        setSessionState('ERROR');
        setErrorMessage('WebSocket connection encountered an error.');
      };

      ws.onclose = () => {
        setIsConnected(false);
        setSessionState('IDLE');
      };
    } catch (err: any) {
      setSessionState('ERROR');
      setErrorMessage(err.message || 'Failed to initialize voice session ticket.');
    }
  };

  // Stop / Disconnect Voice Session
  const stopSession = () => {
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach((track) => track.stop());
      mediaStreamRef.current = null;
    }
    if (audioContextRef.current && audioContextRef.current.state !== 'closed') {
      audioContextRef.current.close().catch(() => {});
      audioContextRef.current = null;
    }
    setIsConnected(false);
    setSessionState('IDLE');
  };

  // Barge-In / Interruption Trigger
  const handleBargeIn = () => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ action: 'interrupt' }));
    }
    setSessionState('INTERRUPTED');
    setTranscripts((prev) => [
      ...prev,
      {
        id: String(Date.now()),
        speaker: 'system',
        text: '⚡ Barge-in signal sent. Agent speech aborted immediately.',
        timestamp: new Date().toLocaleTimeString(),
      },
    ]);
    setTimeout(() => {
      setSessionState('LISTENING');
    }, 1000);
  };

  // Emergency Cancellation Trigger
  const handleCancel = () => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ action: 'cancel' }));
    }
    setSessionState('CANCELLED');
    setTimeout(() => {
      stopSession();
    }, 800);
  };

  // Multimodal Image Drop / Upload Handler
  const handleImageUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const preview = URL.createObjectURL(file);
    setMultimodalImage({
      file,
      previewUrl: preview,
      description: null,
      modelUsed: null,
      isAnalyzing: false,
    });
  };

  // Trigger Static Image Inspection (Moondream2 / OCR)
  const handleAnalyzeImage = async () => {
    if (!multimodalImage.file) return;

    setMultimodalImage((prev) => ({ ...prev, isAnalyzing: true }));
    try {
      // 1. Upload file
      const uploadedFile = await auraApi.files.upload(
        multimodalImage.file,
        activeWorkspace?.id
      );

      // 2. Execute static vision inspection
      const result = await auraApi.voice.inspectImage(
        uploadedFile.file.id,
        'Inspect this diagram and provide key visual takeaways for voice context',
        'moondream',
        activeWorkspace?.id
      );

      setMultimodalImage((prev) => ({
        ...prev,
        isAnalyzing: false,
        description: result?.result?.description || 'Image inspected successfully.',
        modelUsed: result?.result?.model_used || 'moondream2',
      }));

      // Append to transcript
      setTranscripts((prev) => [
        ...prev,
        {
          id: String(Date.now()),
          speaker: 'user',
          text: `[Visual Context Attached: ${multimodalImage.file?.name}] ${result?.result?.description || ''}`,
          timestamp: new Date().toLocaleTimeString(),
          is_untrusted: true,
          envelope_type: 'multimodal',
        },
      ]);
    } catch (err: any) {
      setMultimodalImage((prev) => ({ ...prev, isAnalyzing: false }));
      setErrorMessage(`Multimodal inspection failed: ${err.message}`);
    }
  };

  // Resolve HITL Approval and Resume Task
  const handleApproveAndResume = async (approvalId: string, taskId: string) => {
    try {
      await auraApi.approvals.resolve(approvalId, 'APPROVED', 'Approved via Voice HUD interface');
      removePendingApproval(approvalId);

      // Trigger deterministic task recovery
      const resumed = await auraApi.tasks.resume(taskId, activeWorkspace?.id);
      setResumedTaskNotice(`Task '${resumed.title}' resumed successfully from verified checkpoint.`);
      setTimeout(() => setResumedTaskNotice(null), 6000);
    } catch (err: any) {
      setErrorMessage(`Failed to resume task: ${err.message}`);
    }
  };

  // Status Badge Colors & Glow
  const getStateBadgeConfig = () => {
    switch (sessionState) {
      case 'LISTENING':
        return {
          bg: 'bg-cyan-500/20 text-cyan-400 border-cyan-500/40 glow-cyan',
          icon: <Radio className="w-3.5 h-3.5 animate-pulse" />,
          label: 'LISTENING',
        };
      case 'TRANSCRIBING':
        return {
          bg: 'bg-amber-500/20 text-amber-400 border-amber-500/40 animate-pulse',
          icon: <Sparkles className="w-3.5 h-3.5" />,
          label: 'TRANSCRIBING',
        };
      case 'THINKING':
        return {
          bg: 'bg-purple-500/20 text-purple-300 border-purple-500/40 animate-pulse',
          icon: <Cpu className="w-3.5 h-3.5 animate-spin" />,
          label: 'THINKING',
        };
      case 'SPEAKING':
        return {
          bg: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/40 glow-emerald',
          icon: <Volume2 className="w-3.5 h-3.5 animate-bounce" />,
          label: 'SPEAKING',
        };
      case 'INTERRUPTED':
        return {
          bg: 'bg-orange-500/20 text-orange-400 border-orange-500/40',
          icon: <Zap className="w-3.5 h-3.5" />,
          label: 'INTERRUPTED',
        };
      case 'CANCELLED':
        return {
          bg: 'bg-rose-500/20 text-rose-400 border-rose-500/40',
          icon: <XCircle className="w-3.5 h-3.5" />,
          label: 'CANCELLED',
        };
      case 'ERROR':
        return {
          bg: 'bg-red-500/20 text-red-400 border-red-500/40',
          icon: <AlertCircle className="w-3.5 h-3.5" />,
          label: 'ERROR',
        };
      default:
        return {
          bg: 'bg-slate-800/60 text-slate-400 border-slate-700',
          icon: <Radio className="w-3.5 h-3.5" />,
          label: 'IDLE',
        };
    }
  };

  const stateBadge = getStateBadgeConfig();

  return (
    <div className="space-y-6 max-w-7xl mx-auto pb-12" id="voice-hud-view">
      {/* Top Header Card */}
      <div className="bg-aura-elevated border border-aura-subtle rounded-xl p-6 shadow-2xl relative overflow-hidden backdrop-blur-md">
        <div className="absolute -top-24 -right-24 w-72 h-72 bg-cyan-500/10 rounded-full blur-3xl pointer-events-none" />
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 relative z-10">
          <div>
            <div className="flex items-center gap-3">
              <div className="p-2.5 rounded-lg bg-cyan-500/10 border border-cyan-500/30 text-cyan-400">
                <Mic className="w-6 h-6" />
              </div>
              <div>
                <h1 className="text-xl font-bold text-slate-100 flex items-center gap-2 font-mono">
                  VOICE COGNITIVE HUD
                  <span className="text-[10px] px-2 py-0.5 rounded bg-cyan-950/80 text-cyan-300 border border-cyan-700/50">
                    AURA-706
                  </span>
                </h1>
                <p className="text-xs text-slate-400 mt-0.5">
                  Ultra-low latency duplex acoustic stream & deterministic checkpoint recovery
                </p>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-3">
            {/* Live State Badge */}
            <div
              className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs font-mono font-bold tracking-wider transition-all ${stateBadge.bg}`}
            >
              {stateBadge.icon}
              <span>{stateBadge.label}</span>
            </div>

            {/* Connection Indicator */}
            <div className="flex items-center gap-2 px-3 py-1.5 bg-aura-canvas/80 border border-aura-subtle rounded-lg text-xs font-mono">
              <span
                className={`w-2 h-2 rounded-full ${
                  isConnected ? 'bg-emerald-400 animate-pulse' : 'bg-slate-600'
                }`}
              />
              <span className="text-slate-300">
                {isConnected ? 'GATEWAY CONNECTED' : 'DISCONNECTED'}
              </span>
            </div>
          </div>
        </div>

        {/* Resumed Task Notice Banner */}
        {resumedTaskNotice && (
          <div className="mt-4 p-3 bg-emerald-950/60 border border-emerald-500/40 rounded-lg text-xs text-emerald-300 flex items-center gap-2 font-mono">
            <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
            <span>{resumedTaskNotice}</span>
          </div>
        )}

        {/* Error Banner */}
        {errorMessage && (
          <div className="mt-4 p-3 bg-red-950/60 border border-red-500/40 rounded-lg text-xs text-red-300 flex items-center gap-2 font-mono">
            <AlertCircle className="w-4 h-4 text-red-400 shrink-0" />
            <span>{errorMessage}</span>
          </div>
        )}
      </div>

      {/* HITL Approvals Resumption Banner (If pending) */}
      {pendingApprovals && pendingApprovals.length > 0 && (
        <div className="bg-amber-950/40 border border-amber-500/50 rounded-xl p-4 shadow-lg backdrop-blur-md">
          <div className="flex items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className="p-2 bg-amber-500/20 rounded-lg text-amber-400 border border-amber-500/30">
                <ShieldAlert className="w-5 h-5 animate-pulse" />
              </div>
              <div>
                <h2 className="text-sm font-bold text-amber-300 font-mono">
                  PENDING HUMAN-IN-THE-LOOP APPROVAL ({pendingApprovals.length})
                </h2>
                <p className="text-xs text-slate-300 mt-0.5">
                  Task paused at high-risk step. Resolving approval will trigger automatic DAG checkpoint resumption.
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2">
              {pendingApprovals.slice(0, 1).map((appr) => (
                <div key={appr.id} className="flex items-center gap-2">
                  <span className="text-xs font-mono text-amber-400 bg-amber-950/80 px-2.5 py-1 rounded border border-amber-600/40">
                    Tool: {appr.tool_name}
                  </span>
                  <button
                    onClick={() => handleApproveAndResume(appr.id, appr.task_id)}
                    className="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-mono font-bold transition-all shadow-md"
                  >
                    <CheckCircle2 className="w-3.5 h-3.5" />
                    <span>Approve & Resume Task</span>
                  </button>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Main HUD Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Column: Visualizer & Controls (2 cols on large) */}
        <div className="lg:col-span-2 space-y-6">
          {/* Audio Visualization Stage */}
          <div className="bg-aura-elevated border border-aura-subtle rounded-xl p-6 relative overflow-hidden shadow-2xl flex flex-col items-center justify-center min-h-[360px]">
            <div className="w-full flex items-center justify-between text-xs font-mono text-slate-400 mb-4">
              <span className="flex items-center gap-1.5">
                <Sparkles className="w-3.5 h-3.5 text-cyan-400" />
                ACOUSTIC SPECTRUM & COGNITIVE PRESENCE
              </span>
              <span className="text-slate-500">16kHz PCM • Web Audio Analyser</span>
            </div>

            {/* Central AuraOrb Face of AURA */}
            <div className="my-3 flex flex-col items-center justify-center">
              <AuraOrb
                state={deriveVisualState({
                  voiceState: sessionState,
                  hasErrors: !!errorMessage || sessionState === 'ERROR',
                })}
                size={150}
                showStatusBadge
                showCaption
                caption={transcripts.filter((t) => t.speaker === 'agent').slice(-1)[0]?.text || null}
              />
            </div>

            {/* Canvas Spectrum Display */}
            <div className="w-full h-24 flex items-center justify-center relative mt-2">
              <canvas
                ref={canvasRef}
                width={700}
                height={90}
                className="w-full h-full rounded-lg bg-aura-canvas/60 border border-aura-subtle/40"
              />
            </div>

            {/* Futuristic Central Mic & Control Bar */}
            <div className="mt-6 flex flex-wrap items-center justify-center gap-4 w-full">
              {sessionState === 'IDLE' || sessionState === 'ERROR' ? (
                <button
                  id="btn-voice-start"
                  onClick={startSession}
                  className="flex items-center gap-3 px-8 py-3.5 bg-gradient-to-r from-cyan-600 to-blue-600 hover:from-cyan-500 hover:to-blue-500 text-white rounded-xl font-mono text-sm font-bold shadow-xl glow-cyan transition-all transform hover:scale-105 active:scale-95"
                >
                  <Mic className="w-5 h-5" />
                  <span>START VOICE SESSION</span>
                </button>
              ) : (
                <>
                  <button
                    id="btn-voice-stop"
                    onClick={stopSession}
                    className="flex items-center gap-2 px-6 py-3 bg-red-600/80 hover:bg-red-500 text-white rounded-xl font-mono text-xs font-bold transition-all shadow-lg"
                  >
                    <MicOff className="w-4 h-4" />
                    <span>STOP MIC</span>
                  </button>

                  <button
                    id="btn-voice-barge-in"
                    onClick={handleBargeIn}
                    className="flex items-center gap-2 px-6 py-3 bg-amber-600/80 hover:bg-amber-500 text-white rounded-xl font-mono text-xs font-bold transition-all shadow-lg"
                  >
                    <Zap className="w-4 h-4" />
                    <span>BARGE-IN / INTERRUPT</span>
                  </button>

                  <button
                    id="btn-voice-cancel"
                    onClick={handleCancel}
                    className="flex items-center gap-2 px-5 py-3 bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-600 rounded-xl font-mono text-xs font-semibold transition-all"
                  >
                    <Square className="w-4 h-4 text-rose-400" />
                    <span>CANCEL</span>
                  </button>
                </>
              )}
            </div>
          </div>

          {/* Real-time Dialogue & Transcript Feed */}
          <div className="bg-aura-elevated border border-aura-subtle rounded-xl p-6 shadow-xl flex flex-col h-[340px]">
            <div className="flex items-center justify-between pb-3 border-b border-aura-subtle/60 text-xs font-mono text-slate-400">
              <span className="flex items-center gap-2">
                <Layers className="w-4 h-4 text-cyan-400" />
                REAL-TIME SPOKEN TRANSCRIPT FEED
              </span>
              <span className="text-[11px] text-slate-500">
                Untrusted Envelopes Enforced
              </span>
            </div>

            <div className="flex-1 overflow-y-auto space-y-3 py-4 pr-2 font-mono text-xs">
              {transcripts.length === 0 ? (
                <div className="h-full flex flex-col items-center justify-center text-slate-500 gap-2">
                  <Radio className="w-8 h-8 opacity-40 text-cyan-400 animate-pulse" />
                  <span>Awaiting voice stream input...</span>
                </div>
              ) : (
                transcripts.map((t) => (
                  <div
                    key={t.id}
                    className={`p-3 rounded-lg border transition-all ${
                      t.speaker === 'user'
                        ? 'bg-cyan-950/40 border-cyan-500/30 text-slate-200'
                        : t.speaker === 'agent'
                        ? 'bg-aura-surface border-blue-500/30 text-slate-100'
                        : 'bg-aura-canvas/80 border-aura-subtle text-slate-400 italic'
                    }`}
                  >
                    <div className="flex items-center justify-between text-[10px] text-slate-500 mb-1">
                      <span className="font-bold uppercase tracking-wider text-cyan-400">
                        {t.speaker === 'user'
                          ? 'OPERATOR (SPOKEN)'
                          : t.speaker === 'agent'
                          ? 'AURA AGENT (SYNTHESIZED)'
                          : 'SYSTEM TELEMETRY'}
                      </span>
                      <span>{t.timestamp}</span>
                    </div>
                    {t.is_untrusted && (
                      <div className="text-[10px] text-amber-400 mb-1 font-semibold">
                        &lt;untrusted_{t.envelope_type || 'spoken'}_content&gt;
                      </div>
                    )}
                    <p className="text-xs leading-relaxed">{t.text}</p>
                  </div>
                ))
              )}
              <div ref={transcriptEndRef} />
            </div>
          </div>
        </div>

        {/* Right Column: Multimodal Static Inspection & Pipeline Telemetry */}
        <div className="space-y-6">
          {/* Multimodal Image Context (AURA-705 Integration) */}
          <div className="bg-aura-elevated border border-aura-subtle rounded-xl p-5 shadow-xl">
            <div className="flex items-center gap-2 text-xs font-mono text-slate-300 mb-3 font-bold">
              <ImageIcon className="w-4 h-4 text-violet-400" />
              <span>MULTIMODAL CONTEXT ATTACHMENT</span>
            </div>
            <p className="text-[11px] text-slate-400 mb-3">
              Attach a static image diagram or screenshot for local VLM / OCR inspection.
            </p>

            {/* Dropzone / Upload area */}
            <div className="border border-dashed border-aura-subtle hover:border-violet-500/50 rounded-lg p-4 text-center bg-aura-canvas/40 transition-colors">
              {multimodalImage.previewUrl ? (
                <div className="space-y-3">
                  <div className="relative w-full h-32 rounded overflow-hidden border border-aura-subtle">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={multimodalImage.previewUrl}
                      alt="Multimodal context"
                      className="w-full h-full object-cover"
                    />
                  </div>
                  <div className="flex items-center justify-between text-[11px] font-mono text-slate-400">
                    <span className="truncate max-w-[150px]">
                      {multimodalImage.file?.name}
                    </span>
                    <button
                      onClick={() =>
                        setMultimodalImage({
                          file: null,
                          previewUrl: null,
                          description: null,
                          modelUsed: null,
                          isAnalyzing: false,
                        })
                      }
                      className="text-rose-400 hover:text-rose-300"
                    >
                      Remove
                    </button>
                  </div>

                  <button
                    onClick={handleAnalyzeImage}
                    disabled={multimodalImage.isAnalyzing}
                    className="w-full py-2 bg-violet-600 hover:bg-violet-500 text-white rounded-lg text-xs font-mono font-bold flex items-center justify-center gap-2 shadow-md transition-all disabled:opacity-50"
                  >
                    {multimodalImage.isAnalyzing ? (
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    ) : (
                      <Eye className="w-3.5 h-3.5" />
                    )}
                    <span>
                      {multimodalImage.isAnalyzing
                        ? 'INSPECTING VLM...'
                        : 'INSPECT WITH MOONDREAM2'}
                    </span>
                  </button>
                </div>
              ) : (
                <label className="cursor-pointer flex flex-col items-center justify-center py-4 gap-2">
                  <ImageIcon className="w-8 h-8 text-slate-500" />
                  <span className="text-xs font-mono text-cyan-400 font-semibold">
                    Click to select static image
                  </span>
                  <span className="text-[10px] text-slate-500 font-mono">
                    PNG, JPEG, WebP (Max 10MB)
                  </span>
                  <input
                    type="file"
                    accept="image/*"
                    onChange={handleImageUpload}
                    className="hidden"
                  />
                </label>
              )}
            </div>

            {multimodalImage.description && (
              <div className="mt-3 p-3 bg-violet-950/40 border border-violet-500/30 rounded-lg text-xs font-mono">
                <div className="text-[10px] text-violet-300 font-bold mb-1">
                  VLM RESULT ({multimodalImage.modelUsed})
                </div>
                <p className="text-slate-300 text-[11px] leading-relaxed">
                  {multimodalImage.description}
                </p>
              </div>
            )}
          </div>

          {/* Voice Engine Governance & Pipeline Specs */}
          <div className="bg-aura-elevated border border-aura-subtle rounded-xl p-5 shadow-xl space-y-4">
            <div className="flex items-center gap-2 text-xs font-mono text-slate-300 font-bold">
              <Cpu className="w-4 h-4 text-cyan-400" />
              <span>PIPELINE GOVERNANCE & METRICS</span>
            </div>

            <div className="space-y-2.5 font-mono text-xs">
              <div className="flex justify-between p-2 rounded bg-aura-canvas/60 border border-aura-subtle/40">
                <span className="text-slate-400">STT ENGINE</span>
                <span className="text-cyan-400 font-semibold">faster-whisper</span>
              </div>
              <div className="flex justify-between p-2 rounded bg-aura-canvas/60 border border-aura-subtle/40">
                <span className="text-slate-400">TTS ENGINE</span>
                <span className="text-emerald-400 font-semibold">Kokoro / Piper</span>
              </div>
              <div className="flex justify-between p-2 rounded bg-aura-canvas/60 border border-aura-subtle/40">
                <span className="text-slate-400">VAD BARGE-IN</span>
                <span className="text-violet-400 font-semibold">Silero VAD (&lt;50ms)</span>
              </div>
              <div className="flex justify-between p-2 rounded bg-aura-canvas/60 border border-aura-subtle/40">
                <span className="text-slate-400">SECURITY ISOLATION</span>
                <span className="text-amber-400 font-semibold">Ephemeral PCM (No disk)</span>
              </div>
              <div className="flex justify-between p-2 rounded bg-aura-canvas/60 border border-aura-subtle/40">
                <span className="text-slate-400">CLOUD COST FLOOR</span>
                <span className="text-emerald-400 font-bold">$0.00 (100% Local)</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
