'use client';

import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { auraApi } from '../../lib/api';
import { ProviderStatus, ModelInfo } from '../../lib/types';
import {
  Cpu,
  Key,
  ShieldCheck,
  CheckCircle2,
  AlertCircle,
  Plus,
  Trash2,
  Database,
  Lock,
  Loader2,
  ExternalLink,
} from 'lucide-react';

import { useAuraStore } from '../../lib/store';

export const ProvidersView: React.FC = () => {
  const { activeWorkspace } = useAuraStore();
  const queryClient = useQueryClient();
  const [isEnrolling, setIsEnrolling] = useState(false);
  const [provider, setProvider] = useState('gemini');
  const [apiKey, setApiKey] = useState('');
  const [label, setLabel] = useState('');
  const [enrollSuccess, setEnrollSuccess] = useState<string | null>(null);

  // Queries
  const { data: providers, isLoading: providersLoading } = useQuery({
    queryKey: ['providers-status', activeWorkspace?.id],
    queryFn: () => auraApi.providers.status(activeWorkspace?.id),
  });

  const { data: models } = useQuery({
    queryKey: ['models-list'],
    queryFn: () => auraApi.providers.models(),
  });

  // Enroll Credential Mutation (Write-only payload)
  const enrollMutation = useMutation({
    mutationFn: async (payload: { provider: string; api_key: string; label?: string }) => {
      if (!activeWorkspace) throw new Error('No active workspace selected');
      const provConfigs = await auraApi.providers.status(activeWorkspace.id);
      let targetConfig = provConfigs.find((c: any) => c.provider_type === payload.provider || c.provider === payload.provider);
      return auraApi.providers.enrollCredential({
        workspace_id: activeWorkspace.id,
        provider_config_id: (targetConfig as any)?.id || activeWorkspace.id,
        secret: payload.api_key,
        label: payload.label,
      });
    },
    onSuccess: (res) => {
      setApiKey(''); // Cleared immediately from memory
      setLabel('');
      setIsEnrolling(false);
      setEnrollSuccess(`Credential enrolled successfully. Fingerprint: ${res.key_fingerprint || 'Configured'}`);
      queryClient.invalidateQueries({ queryKey: ['providers-status'] });
    },
  });

  // Revoke Credential Mutation
  const revokeMutation = useMutation({
    mutationFn: (prov: string) => auraApi.providers.revokeCredential(prov),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['providers-status'] });
    },
  });

  return (
    <div className="space-y-6 animate-in fade-in duration-200">
      {/* Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 p-5 bg-aura-surface border border-aura-subtle rounded-xl">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <Cpu className="w-5 h-5 text-cyan-400" />
            <h1 className="text-base font-bold font-mono text-slate-100 uppercase tracking-wide">
              MODEL PROVIDERS & SECURE BYOK VAULT
            </h1>
          </div>
          <p className="text-xs text-slate-400">
            Multi-tier inference routing: 100% Zero-Cost Local Ollama baseline + Optional Secure BYOK Gemini.
          </p>
        </div>

        <button
          onClick={() => setIsEnrolling(true)}
          className="flex items-center gap-1.5 px-4 py-2 bg-cyan-600 hover:bg-cyan-500 text-white rounded-lg text-xs font-mono font-bold shadow-lg glow-cyan transition-all"
        >
          <Key className="w-3.5 h-3.5" />
          <span>ENROLL BYOK CREDENTIAL</span>
        </button>
      </div>

      {enrollSuccess && (
        <div className="p-3 bg-emerald-950/40 border border-emerald-500/30 rounded-xl text-xs font-mono text-emerald-300 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
            <span>{enrollSuccess}</span>
          </div>
          <button
            onClick={() => setEnrollSuccess(null)}
            className="text-slate-400 hover:text-slate-200 text-xs"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Provider Status Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Tier 1: Local Ollama */}
        <div className="bg-aura-surface border border-emerald-500/30 rounded-xl p-5 space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="p-2 bg-emerald-500/10 text-emerald-400 rounded-lg border border-emerald-500/20">
                <Database className="w-5 h-5" />
              </div>
              <div>
                <h3 className="text-sm font-bold font-mono text-slate-100">
                  Ollama (Local Inference)
                </h3>
                <span className="text-[10px] font-mono text-emerald-400 font-semibold">
                  100% ZERO-COST BASELINE
                </span>
              </div>
            </div>

            <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
              ● PRIMARY DEFAULT
            </span>
          </div>

          <p className="text-xs text-slate-400 font-sans leading-relaxed">
            Local open-weights model runner executing in-process or local daemon. No external API calls, zero billing risk, no data leaves your machine.
          </p>

          <div className="p-3 bg-aura-canvas rounded-lg border border-aura-subtle text-xs font-mono space-y-1.5">
            <div className="flex justify-between text-slate-400">
              <span>Default Models:</span>
              <span className="text-slate-200">qwen2.5:7b, hermes3:8b</span>
            </div>
            <div className="flex justify-between text-slate-400">
              <span>Endpoint:</span>
              <span className="text-slate-200">http://127.0.0.1:11434</span>
            </div>
          </div>
        </div>

        {/* Tier 2: Google Gemini (BYOK) */}
        <div className="bg-aura-surface border border-aura-subtle rounded-xl p-5 space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="p-2 bg-violet-500/10 text-violet-400 rounded-lg border border-violet-500/20">
                <Cpu className="w-5 h-5" />
              </div>
              <div>
                <h3 className="text-sm font-bold font-mono text-slate-100">
                  Google Gemini (BYOK)
                </h3>
                <span className="text-[10px] font-mono text-violet-400 font-semibold">
                  OPTIONAL CLOUD EXTENSION
                </span>
              </div>
            </div>

            <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700">
              POTENTIALLY BILLABLE
            </span>
          </div>

          <p className="text-xs text-slate-400 font-sans leading-relaxed">
            Bring Your Own Key for cloud reasoning via Google AI Studio. Keys are encrypted with AES-256-GCM and never exposed to the client.
          </p>

          <div className="p-3 bg-aura-canvas rounded-lg border border-aura-subtle text-xs font-mono space-y-1.5">
            <div className="flex justify-between text-slate-400">
              <span>Supported Models:</span>
              <span className="text-slate-200">gemini-2.5-flash, gemini-2.5-pro</span>
            </div>
            <div className="flex justify-between text-slate-400">
              <span>Storage Security:</span>
              <span className="text-emerald-400 font-bold">Write-Only Key Vault</span>
            </div>
          </div>
        </div>
      </div>

      {/* Model Catalog Table */}
      {models && models.length > 0 && (
        <div className="space-y-3 pt-4">
          <h2 className="text-xs font-bold font-mono text-slate-300 uppercase tracking-wider">
            DISCOVERED INFERENCE MODELS
          </h2>

          <div className="bg-aura-surface border border-aura-subtle rounded-xl overflow-hidden">
            <table className="w-full text-left text-xs font-mono">
              <thead className="bg-aura-canvas border-b border-aura-subtle text-slate-400">
                <tr>
                  <th className="p-3">Model ID</th>
                  <th className="p-3">Provider</th>
                  <th className="p-3">Cost Tier</th>
                  <th className="p-3">Default</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-aura-subtle">
                {models.map((m) => (
                  <tr key={m.id} className="hover:bg-aura-elevated/40">
                    <td className="p-3 text-slate-200 font-bold">{m.id}</td>
                    <td className="p-3 text-slate-400">{m.provider}</td>
                    <td className="p-3">
                      <span
                        className={`px-2 py-0.5 rounded text-[10px] border ${
                          m.tier === 'FREE_LOCAL'
                            ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
                            : 'bg-violet-500/10 text-violet-400 border-violet-500/30'
                        }`}
                      >
                        {m.tier}
                      </span>
                    </td>
                    <td className="p-3 text-slate-400">
                      {m.is_default ? '★ Primary' : '-'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Enroll Modal */}
      {isEnrolling && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
          <div className="w-full max-w-md bg-aura-surface border border-aura-strong rounded-xl p-5 space-y-4">
            <h3 className="text-sm font-bold font-mono text-slate-100 flex items-center gap-2">
              <Key className="w-4 h-4 text-cyan-400" />
              ENROLL SECURE BYOK CREDENTIAL
            </h3>

            <div className="p-3 bg-amber-500/10 border border-amber-500/30 rounded-lg text-xs font-mono text-amber-300">
              🔒 Security Invariant: The secret key is sent once to the backend for AES-256-GCM encryption. It is NEVER stored in localStorage or echoed in API responses.
            </div>

            <div className="space-y-3">
              <div>
                <label className="block text-xs font-mono text-slate-400 mb-1">
                  Provider
                </label>
                <select
                  value={provider}
                  onChange={(e) => setProvider(e.target.value)}
                  className="w-full bg-aura-canvas border border-aura-subtle rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-cyan-500 font-mono"
                >
                  <option value="gemini">Google Gemini (AI Studio)</option>
                </select>
              </div>

              <div>
                <label className="block text-xs font-mono text-slate-400 mb-1">
                  API Key / Secret
                </label>
                <input
                  type="password"
                  placeholder="Paste your provider API key..."
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  className="w-full bg-aura-canvas border border-aura-subtle rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-cyan-500 font-mono"
                />
              </div>

              <div>
                <label className="block text-xs font-mono text-slate-400 mb-1">
                  Label (Optional)
                </label>
                <input
                  type="text"
                  placeholder="e.g. Production AI Studio Key"
                  value={label}
                  onChange={(e) => setLabel(e.target.value)}
                  className="w-full bg-aura-canvas border border-aura-subtle rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-cyan-500 font-mono"
                />
              </div>
            </div>

            <div className="flex justify-end gap-2 pt-2 border-t border-aura-subtle">
              <button
                onClick={() => {
                  setApiKey('');
                  setIsEnrolling(false);
                }}
                className="px-3 py-1.5 text-xs font-mono text-slate-400 hover:text-slate-200"
              >
                Cancel
              </button>
              <button
                disabled={!apiKey.trim() || enrollMutation.isPending}
                onClick={() =>
                  enrollMutation.mutate({
                    provider,
                    api_key: apiKey,
                    label,
                  })
                }
                className="flex items-center gap-1.5 px-4 py-1.5 bg-cyan-600 hover:bg-cyan-500 disabled:opacity-50 text-white rounded-lg text-xs font-mono font-bold"
              >
                {enrollMutation.isPending && (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                )}
                <span>ENROLL KEY</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
