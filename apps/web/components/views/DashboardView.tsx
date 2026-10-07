'use client';

import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { auraApi } from '../../lib/api';
import { useAuraStore } from '../../lib/store';
import { StatusBadge } from '../StatusBadge';
import { RiskBadge } from '../RiskBadge';
import { AuraOrb, deriveVisualState } from '../aura/AuraOrb';
import {
  Activity,
  Cpu,
  ShieldAlert,
  ArrowRight,
  Terminal,
  Play,
  Layers,
  Database,
  Radio,
  CheckCircle2,
  AlertCircle,
} from 'lucide-react';

export const DashboardView: React.FC = () => {
  const { activeWorkspace, setActiveTab, setSelectedTaskId, recentEvents } = useAuraStore();
  const [quickGoal, setQuickGoal] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  // Queries
  const { data: tasks, isLoading: tasksLoading } = useQuery({
    queryKey: ['tasks', activeWorkspace?.id],
    queryFn: () => auraApi.tasks.list(activeWorkspace?.id, 5, 0),
  });

  const { data: approvals } = useQuery({
    queryKey: ['approvals', activeWorkspace?.id],
    queryFn: () => auraApi.approvals.list(activeWorkspace?.id),
    refetchInterval: 5000,
  });

  const { data: providers } = useQuery({
    queryKey: ['providers'],
    queryFn: () => auraApi.providers.status(),
  });

  const { data: agentHealth } = useQuery({
    queryKey: ['agent-health'],
    queryFn: () => auraApi.agent.health(),
    refetchInterval: 10000,
  });

  const handleLaunchGoal = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!quickGoal.trim() || !activeWorkspace) return;

    setIsSubmitting(true);
    setSubmitError(null);
    try {
      const res = await auraApi.agent.run({
        goal: quickGoal,
        workspace_id: activeWorkspace.id,
      });
      setQuickGoal('');
      setSelectedTaskId(res.task_id);
      setActiveTab('tasks');
    } catch (err: any) {
      setSubmitError(err.message || 'Failed to dispatch goal');
    } finally {
      setIsSubmitting(false);
    }
  };

  const pendingApprovalsCount = approvals?.filter((a) => a.status === 'PENDING').length || 0;

  // Derive visual state for the AuraOrb
  const visualState = deriveVisualState({
    pendingApprovalsCount,
    isProcessing: isSubmitting,
    hasErrors: !!submitError,
    isDegraded: agentHealth?.status === 'DEGRADED',
    taskStatus: tasks && tasks.length > 0 ? tasks[0].status : null,
  });

  return (
    <div className="space-y-6 animate-in fade-in duration-200">
      {/* Top Welcome & Quick Goal Banner with AuraOrb Face */}
      <div className="p-6 bg-gradient-to-r from-aura-surface via-aura-elevated to-aura-surface border border-aura-subtle rounded-xl relative overflow-hidden">
        <div className="absolute top-0 right-0 p-8 opacity-10 pointer-events-none">
          <Terminal className="w-48 h-48 text-cyan-400" />
        </div>

        <div className="relative z-10 flex flex-col md:flex-row items-center justify-between gap-6">
          <div className="max-w-2xl flex-1">
            <div className="flex items-center gap-2 mb-2">
              <span className="w-2 h-2 rounded-full bg-cyan-400 animate-pulse glow-cyan" />
              <span className="text-xs font-mono text-cyan-400 font-semibold tracking-wider uppercase">
                Autonomous Command Terminal
              </span>
            </div>
            <h1 className="text-2xl font-bold text-slate-100 font-sans tracking-tight">
              Welcome to AURA Command Center
            </h1>
            <p className="text-xs text-slate-400 mt-1">
              Zero-cost local cognitive orchestrator with deterministic HITL governance and sandboxed worker pools.
            </p>

            <form onSubmit={handleLaunchGoal} className="mt-5 flex gap-2">
              <div className="relative flex-1">
                <input
                  type="text"
                  value={quickGoal}
                  onChange={(e) => setQuickGoal(e.target.value)}
                  placeholder="Dispatch autonomous goal (e.g., 'Research duckduckgo API and summarize findings in memory')"
                  className="w-full bg-aura-canvas/90 border border-aura-subtle rounded-lg px-4 py-2.5 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500 font-mono"
                />
              </div>
              <button
                type="submit"
                disabled={isSubmitting || !quickGoal.trim()}
                className="flex items-center gap-2 px-5 py-2.5 bg-cyan-600 hover:bg-cyan-500 disabled:opacity-50 text-white font-mono text-xs font-bold rounded-lg shadow-lg glow-cyan transition-all"
              >
                <Play className="w-3.5 h-3.5 fill-current" />
                <span>DISPATCH GOAL</span>
              </button>
            </form>

            {submitError && (
              <p className="mt-2 text-xs font-mono text-rose-400">{submitError}</p>
            )}
          </div>

          {/* AuraOrb AI Face Presence */}
          <div className="flex flex-col items-center justify-center shrink-0 pr-4">
            <AuraOrb
              state={visualState}
              size={120}
              showStatusBadge
              interactive
              className="transition-transform hover:scale-105"
            />
          </div>
        </div>
      </div>

      {/* HITL Alert Banner (If Any Pending) */}
      {pendingApprovalsCount > 0 && (
        <div className="p-4 bg-amber-500/10 border border-amber-500/30 rounded-xl flex items-center justify-between glow-amber animate-pulse">
          <div className="flex items-center gap-3">
            <ShieldAlert className="w-5 h-5 text-amber-400" />
            <div>
              <h4 className="text-xs font-bold font-mono text-amber-300">
                ACTION REQUIRED: {pendingApprovalsCount} PENDING HUMAN-IN-THE-LOOP APPROVAL(S)
              </h4>
              <p className="text-[11px] text-amber-400/80 mt-0.5">
                Execution paused at high/critical risk tool boundaries.
              </p>
            </div>
          </div>
          <button
            onClick={() => setActiveTab('approvals')}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-amber-500 hover:bg-amber-400 text-slate-950 font-mono text-xs font-bold rounded-md transition-colors"
          >
            <span>REVIEW APPROVALS</span>
            <ArrowRight className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {/* Metrics Row */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Metric 1: System Status */}
        <div className="p-4 bg-aura-surface border border-aura-subtle rounded-xl">
          <div className="flex items-center justify-between text-xs text-slate-400 mb-2">
            <span className="font-mono">RUNTIME ENGINE</span>
            <Activity className="w-4 h-4 text-cyan-400" />
          </div>
          <div className="text-lg font-bold font-mono text-slate-100 flex items-center gap-2">
            <span>{agentHealth?.status || 'ONLINE'}</span>
            <span className="text-xs px-2 py-0.5 bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 rounded">
              READY
            </span>
          </div>
          <p className="text-[11px] text-slate-500 mt-1 font-mono">
            Uptime: {agentHealth?.uptime ? `${Math.floor(agentHealth.uptime / 60)}m` : 'Active'}
          </p>
        </div>

        {/* Metric 2: Sub-Agent Workers */}
        <div className="p-4 bg-aura-surface border border-aura-subtle rounded-xl">
          <div className="flex items-center justify-between text-xs text-slate-400 mb-2">
            <span className="font-mono">SUB-AGENT POOL</span>
            <Cpu className="w-4 h-4 text-violet-400" />
          </div>
          <div className="text-lg font-bold font-mono text-slate-100">
            {agentHealth?.active_workers || 0} / 4 Active
          </div>
          <p className="text-[11px] text-slate-500 mt-1 font-mono">Max Concurrency Cap: 4</p>
        </div>

        {/* Metric 3: Active Workspace */}
        <div className="p-4 bg-aura-surface border border-aura-subtle rounded-xl">
          <div className="flex items-center justify-between text-xs text-slate-400 mb-2">
            <span className="font-mono">WORKSPACE TENANCY</span>
            <Layers className="w-4 h-4 text-cyan-400" />
          </div>
          <div className="text-lg font-bold font-mono text-slate-100 truncate">
            {activeWorkspace?.name || 'Default Workspace'}
          </div>
          <p className="text-[11px] text-slate-500 mt-1 font-mono truncate">
            ID: {activeWorkspace?.id ? `${activeWorkspace.id.substring(0, 12)}...` : 'None'}
          </p>
        </div>

        {/* Metric 4: Primary Provider */}
        <div className="p-4 bg-aura-surface border border-aura-subtle rounded-xl">
          <div className="flex items-center justify-between text-xs text-slate-400 mb-2">
            <span className="font-mono">PRIMARY INFERENCE</span>
            <Database className="w-4 h-4 text-emerald-400" />
          </div>
          <div className="text-lg font-bold font-mono text-emerald-400">
            Ollama (Zero-Cost)
          </div>
          <p className="text-[11px] text-slate-500 mt-1 font-mono">qwen2.5 / hermes</p>
        </div>
      </div>

      {/* Two Column Layout: Recent Tasks & Real-Time Telemetry */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Recent Tasks */}
        <div className="bg-aura-surface border border-aura-subtle rounded-xl p-5 flex flex-col">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-bold font-mono text-slate-200 flex items-center gap-2">
              <Layers className="w-4 h-4 text-cyan-400" />
              RECENT TASK EXECUTION
            </h3>
            <button
              onClick={() => setActiveTab('tasks')}
              className="text-xs font-mono text-cyan-400 hover:text-cyan-300 flex items-center gap-1"
            >
              <span>View All</span>
              <ArrowRight className="w-3 h-3" />
            </button>
          </div>

          <div className="space-y-2.5 flex-1">
            {tasksLoading ? (
              <div className="text-xs text-slate-500 font-mono p-4 text-center">
                Loading task telemetry...
              </div>
            ) : tasks && tasks.length > 0 ? (
              tasks.map((task) => (
                <div
                  key={task.id}
                  onClick={() => {
                    setSelectedTaskId(task.id);
                    setActiveTab('tasks');
                  }}
                  className="p-3 bg-aura-canvas/60 hover:bg-aura-elevated border border-aura-subtle/50 hover:border-cyan-500/30 rounded-lg cursor-pointer transition-all flex items-center justify-between"
                >
                  <div className="flex-1 pr-3">
                    <h4 className="text-xs font-medium text-slate-200 truncate">
                      {task.title || task.objective || 'Untitled Autonomous Task'}
                    </h4>
                    <span className="text-[10px] font-mono text-slate-500 mt-0.5 block">
                      {new Date(task.created_at).toLocaleString()}
                    </span>
                  </div>
                  <StatusBadge status={task.status} />
                </div>
              ))
            ) : (
              <div className="text-xs text-slate-500 font-mono p-8 text-center bg-aura-canvas/30 rounded-lg border border-aura-subtle/30">
                No tasks executed in this workspace yet.
              </div>
            )}
          </div>
        </div>

        {/* Real-Time Live Telemetry Stream */}
        <div className="bg-aura-surface border border-aura-subtle rounded-xl p-5 flex flex-col">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-bold font-mono text-slate-200 flex items-center gap-2">
              <Radio className="w-4 h-4 text-emerald-400 animate-pulse" />
              REAL-TIME RUNTIME TELEMETRY
            </h3>
            <span className="text-[10px] font-mono text-slate-500">
              {recentEvents.length} Events Logged
            </span>
          </div>

          <div className="bg-aura-canvas border border-aura-subtle rounded-lg p-3 h-64 overflow-y-auto space-y-2 font-mono text-xs">
            {recentEvents.length > 0 ? (
              recentEvents.map((ev, idx) => (
                <div
                  key={idx}
                  className="p-2 bg-aura-surface/60 rounded border border-aura-subtle/40 text-[11px] flex items-start gap-2"
                >
                  <span className="text-[10px] text-cyan-400 font-bold px-1.5 py-0.2 bg-cyan-950/60 rounded border border-cyan-800/40 shrink-0">
                    {ev.event_type}
                  </span>
                  <div className="flex-1 text-slate-300 break-all">
                    {JSON.stringify(ev.payload)}
                  </div>
                  <span className="text-[9px] text-slate-500 shrink-0">
                    {new Date(ev.timestamp).toLocaleTimeString()}
                  </span>
                </div>
              ))
            ) : (
              <div className="h-full flex flex-col items-center justify-center text-slate-500 text-xs">
                <Radio className="w-6 h-6 mb-2 opacity-40 text-emerald-400 animate-pulse" />
                <span>Listening for real-time SSE execution events...</span>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
