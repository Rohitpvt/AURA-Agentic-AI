'use client';

import React, { useState } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import { auraApi } from '../../lib/api';
import { useAuraStore } from '../../lib/store';
import { AuditVerifyResult } from '../../lib/types';
import {
  Lock,
  ShieldCheck,
  ShieldAlert,
  CheckCircle2,
  AlertTriangle,
  FileCheck2,
  Activity,
  Layers,
  KeyRound,
  Loader2,
} from 'lucide-react';

export const SecurityView: React.FC = () => {
  const { activeWorkspace } = useAuraStore();
  const [verifyResult, setVerifyResult] = useState<AuditVerifyResult | null>(null);

  // Queries
  const { data: sandboxStatus, isLoading: sandboxLoading } = useQuery({
    queryKey: ['sandbox-status'],
    queryFn: () => auraApi.system.sandboxStatus(),
  });

  // Audit Verification Mutation
  const verifyMutation = useMutation({
    mutationFn: () => auraApi.system.verifyAuditLedger(activeWorkspace?.id),
    onSuccess: (res) => {
      setVerifyResult(res);
    },
  });

  return (
    <div className="space-y-6 animate-in fade-in duration-200">
      {/* Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 p-5 bg-aura-surface border border-aura-subtle rounded-xl">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <Lock className="w-5 h-5 text-emerald-400" />
            <h1 className="text-base font-bold font-mono text-slate-100 uppercase tracking-wide">
              SECURITY POSTURE & AUDIT VERIFICATION
            </h1>
          </div>
          <p className="text-xs text-slate-400">
            Authoritative system security metrics, sandbox isolation boundaries, and cryptographic audit hash chain verification.
          </p>
        </div>

        <button
          onClick={() => verifyMutation.mutate()}
          disabled={verifyMutation.isPending}
          className="flex items-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-mono font-bold shadow-lg transition-all"
        >
          {verifyMutation.isPending ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <FileCheck2 className="w-4 h-4" />
          )}
          <span>VERIFY AUDIT LEDGER INTEGRITY</span>
        </button>
      </div>

      {/* Audit Verification Card */}
      {verifyResult && (
        <div
          className={`p-5 rounded-xl border ${
            verifyResult.verified
              ? 'bg-emerald-950/30 border-emerald-500/40 text-emerald-300 glow-cyan'
              : 'bg-rose-950/40 border-rose-500/40 text-rose-300 glow-crit'
          }`}
        >
          <div className="flex items-center gap-3">
            {verifyResult.verified ? (
              <CheckCircle2 className="w-6 h-6 text-emerald-400 shrink-0" />
            ) : (
              <AlertTriangle className="w-6 h-6 text-rose-400 shrink-0" />
            )}
            <div>
              <h3 className="text-sm font-bold font-mono">
                {verifyResult.verified
                  ? 'SHA-256 AUDIT LEDGER CHAIN VERIFIED UNTAMPERED'
                  : 'AUDIT LEDGER CORRUPTION DETECTED'}
              </h3>
              <p className="text-xs mt-1 font-mono text-slate-300">
                {verifyResult.message}
              </p>
            </div>
          </div>

          <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs font-mono">
            <div className="p-3 bg-aura-canvas rounded-lg border border-aura-subtle">
              <span className="text-slate-500 block mb-1">TOTAL AUDIT ENTRIES:</span>
              <span className="text-slate-100 font-bold">{verifyResult.total_entries}</span>
            </div>
            {verifyResult.head_hash && (
              <div className="p-3 bg-aura-canvas rounded-lg border border-aura-subtle truncate">
                <span className="text-slate-500 block mb-1">HEAD SHA-256 HASH:</span>
                <span className="text-cyan-400 font-mono">{verifyResult.head_hash}</span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Security Pillars Grid */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Pillar 1: Sandbox Enforcement */}
        <div className="bg-aura-surface border border-aura-subtle rounded-xl p-5 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-mono text-slate-400">ISOLATION POSTURE</span>
            <ShieldCheck className="w-4 h-4 text-emerald-400" />
          </div>
          <div className="text-lg font-bold font-mono text-slate-100">
            {sandboxStatus?.sandbox_enforced ? 'SANDBOX ACTIVE' : 'LOCAL ENFORCED'}
          </div>
          <p className="text-xs text-slate-400 font-sans leading-relaxed">
            All sub-agent execution loops and tool invocations run within isolated memory boundaries with strict parameter allowlists.
          </p>
        </div>

        {/* Pillar 2: SSRF Protection */}
        <div className="bg-aura-surface border border-aura-subtle rounded-xl p-5 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-mono text-slate-400">NETWORK BOUNDARY</span>
            <Activity className="w-4 h-4 text-cyan-400" />
          </div>
          <div className="text-lg font-bold font-mono text-cyan-400">
            SSRF PROTECTION
          </div>
          <p className="text-xs text-slate-400 font-sans leading-relaxed">
            Private IPv4/IPv6 blocks (127.0.0.1, 10.0.0.0/8, 192.168.0.0/16, 169.254.169.254) are rejected unconditionally at socket level.
          </p>
        </div>

        {/* Pillar 3: Zero-Leakage Secrets */}
        <div className="bg-aura-surface border border-aura-subtle rounded-xl p-5 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-mono text-slate-400">KEY SECURITY</span>
            <KeyRound className="w-4 h-4 text-violet-400" />
          </div>
          <div className="text-lg font-bold font-mono text-violet-400">
            AES-256-GCM VAULT
          </div>
          <p className="text-xs text-slate-400 font-sans leading-relaxed">
            BYOK credentials encrypted with PBKDF2 derived keys. Secrets never traverse into frontend client state or localStorage.
          </p>
        </div>
      </div>

      {/* Tenancy & Resource Quotas */}
      <div className="bg-aura-surface border border-aura-subtle rounded-xl p-5 space-y-3">
        <h3 className="text-xs font-bold font-mono text-slate-300 uppercase tracking-wider flex items-center gap-2">
          <Layers className="w-4 h-4 text-cyan-400" />
          WORKSPACE TENANCY ISOLATION & QUOTAS
        </h3>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs font-mono">
          <div className="p-3 bg-aura-canvas rounded-lg border border-aura-subtle">
            <div className="text-slate-500">MAX CONCURRENT WORKERS</div>
            <div className="text-slate-200 font-bold mt-1">4 per Workspace</div>
          </div>
          <div className="p-3 bg-aura-canvas rounded-lg border border-aura-subtle">
            <div className="text-slate-500">STEP TIMEOUT CAP</div>
            <div className="text-slate-200 font-bold mt-1">120 Seconds</div>
          </div>
          <div className="p-3 bg-aura-canvas rounded-lg border border-aura-subtle">
            <div className="text-slate-500">KILL SWITCH LATENCY TARGET</div>
            <div className="text-emerald-400 font-bold mt-1">&lt; 100ms Abort</div>
          </div>
        </div>
      </div>
    </div>
  );
};
