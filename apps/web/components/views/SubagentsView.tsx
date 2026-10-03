'use client';

import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { auraApi } from '../../lib/api';
import {
  Bot,
  Cpu,
  ShieldCheck,
  Activity,
  Layers,
  CheckCircle2,
  Clock,
  AlertCircle,
} from 'lucide-react';

export const SubagentsView: React.FC = () => {
  const { data: sandboxStatus, isLoading: sandboxLoading } = useQuery({
    queryKey: ['sandbox-status'],
    queryFn: () => auraApi.system.sandboxStatus(),
    refetchInterval: 5000,
  });

  const { data: agentHealth } = useQuery({
    queryKey: ['agent-health'],
    queryFn: () => auraApi.agent.health(),
    refetchInterval: 5000,
  });

  // Architectural Subagent Pool Archetypes
  const subagentArchetypes = [
    {
      role: 'SUPERVISOR_PLANNER',
      description: 'Synthesizes Task DAGs, validates step dependencies, and orchestrates worker allocation.',
      tier: 'Tier 1 (Cognitive Orchestration)',
      defaultProvider: 'Ollama (qwen2.5 / hermes)',
      maxConcurrency: 1,
      status: 'ONLINE',
    },
    {
      role: 'RESEARCH_SEARCHER',
      description: 'Executes DuckDuckGo searches and retrieves web context within SSRF-enforced network sandbox.',
      tier: 'Tier 2 (Worker Sub-Agent)',
      defaultProvider: 'Ollama (qwen2.5 / hermes)',
      maxConcurrency: 2,
      status: 'IDLE',
    },
    {
      role: 'MEMORY_SYNTHESIZER',
      description: 'Performs semantic vector search (FastEmbed) and updates episodic memory nodes.',
      tier: 'Tier 2 (Worker Sub-Agent)',
      defaultProvider: 'FastEmbed / Local',
      maxConcurrency: 1,
      status: 'IDLE',
    },
    {
      role: 'VERIFICATION_AUDITOR',
      description: 'Inspects tool observations, verifies completion criteria, and generates final user summaries.',
      tier: 'Tier 2 (Worker Sub-Agent)',
      defaultProvider: 'Ollama (qwen2.5 / hermes)',
      maxConcurrency: 1,
      status: 'IDLE',
    },
  ];

  return (
    <div className="space-y-6 animate-in fade-in duration-200">
      {/* Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 p-5 bg-aura-surface border border-aura-subtle rounded-xl">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <Bot className="w-5 h-5 text-violet-400" />
            <h1 className="text-base font-bold font-mono text-slate-100 uppercase tracking-wide">
              BOUNDED SUB-AGENT WORKER POOL
            </h1>
          </div>
          <p className="text-xs text-slate-400">
            Isolated local worker pools for parallelized task execution with enforced concurrency boundaries.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <div className="px-3 py-1.5 bg-aura-canvas border border-aura-subtle rounded-lg text-xs font-mono flex items-center gap-2">
            <span className="text-slate-400">ACTIVE WORKERS:</span>
            <span className="text-cyan-400 font-bold">
              {sandboxStatus?.active_workers ?? agentHealth?.active_workers ?? 0} /{' '}
              {sandboxStatus?.max_workers ?? 4}
            </span>
          </div>
        </div>
      </div>

      {/* Pool Concurrency Metrics */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="p-4 bg-aura-surface border border-aura-subtle rounded-xl">
          <div className="text-xs font-mono text-slate-400 mb-1 flex items-center justify-between">
            <span>CONCURRENCY ENFORCEMENT</span>
            <ShieldCheck className="w-4 h-4 text-emerald-400" />
          </div>
          <div className="text-lg font-bold font-mono text-slate-100">
            {sandboxStatus?.sandbox_enforced ? 'HARD BOUNDED (CAP: 4)' : 'BOUNDED'}
          </div>
          <p className="text-[11px] text-slate-500 mt-1 font-mono">
            Sub-agents cannot spawn unbounded child workers.
          </p>
        </div>

        <div className="p-4 bg-aura-surface border border-aura-subtle rounded-xl">
          <div className="text-xs font-mono text-slate-400 mb-1 flex items-center justify-between">
            <span>ISOLATION BOUNDARY</span>
            <Activity className="w-4 h-4 text-cyan-400" />
          </div>
          <div className="text-lg font-bold font-mono text-cyan-400">
            {sandboxStatus?.isolation_type || 'SANDBOX_ENFORCED'}
          </div>
          <p className="text-[11px] text-slate-500 mt-1 font-mono">
            In-process async worker pools with memory separation.
          </p>
        </div>

        <div className="p-4 bg-aura-surface border border-aura-subtle rounded-xl">
          <div className="text-xs font-mono text-slate-400 mb-1 flex items-center justify-between">
            <span>TOOL GOVERNANCE</span>
            <Layers className="w-4 h-4 text-violet-400" />
          </div>
          <div className="text-lg font-bold font-mono text-slate-100">
            AgentToolBridge
          </div>
          <p className="text-[11px] text-slate-500 mt-1 font-mono">
            Sub-agents route all calls through supervisor authority.
          </p>
        </div>
      </div>

      {/* Archetypes / Active Worker Matrix */}
      <div className="space-y-3">
        <h2 className="text-xs font-bold font-mono text-slate-300 uppercase tracking-wider">
          SUB-AGENT ARCHETYPES & ROLES
        </h2>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {subagentArchetypes.map((arch) => (
            <div
              key={arch.role}
              className="bg-aura-surface border border-aura-subtle rounded-xl p-5 space-y-3"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2.5">
                  <div className="p-2 bg-aura-canvas rounded-lg border border-aura-subtle text-violet-400">
                    <Bot className="w-4 h-4" />
                  </div>
                  <div>
                    <h3 className="text-xs font-bold font-mono text-slate-200">
                      {arch.role}
                    </h3>
                    <span className="text-[10px] font-mono text-cyan-400">
                      {arch.tier}
                    </span>
                  </div>
                </div>

                <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                  {arch.status}
                </span>
              </div>

              <p className="text-xs text-slate-400 font-sans leading-relaxed">
                {arch.description}
              </p>

              <div className="pt-3 border-t border-aura-subtle/60 flex items-center justify-between text-[11px] font-mono text-slate-500">
                <span>Inference: <strong className="text-slate-300">{arch.defaultProvider}</strong></span>
                <span>Max Pool: <strong className="text-slate-300">{arch.maxConcurrency}</strong></span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
