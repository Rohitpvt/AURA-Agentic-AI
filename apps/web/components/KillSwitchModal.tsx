'use client';

import React, { useState } from 'react';
import { AlertOctagon, X, CheckCircle2, Loader2 } from 'lucide-react';
import { auraApi } from '../lib/api';
import { KillSwitchResponse } from '../lib/types';

interface KillSwitchModalProps {
  isOpen: boolean;
  onClose: () => void;
  onActivated?: (res: KillSwitchResponse) => void;
}

export const KillSwitchModal: React.FC<KillSwitchModalProps> = ({
  isOpen,
  onClose,
  onActivated,
}) => {
  const [reason, setReason] = useState('');
  const [isExecuting, setIsExecuting] = useState(false);
  const [result, setResult] = useState<KillSwitchResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (!isOpen) return null;

  const handleActivate = async () => {
    setIsExecuting(true);
    setError(null);
    try {
      const res = await auraApi.system.killSwitch(reason || 'Operator triggered manual kill switch');
      setResult(res);
      if (onActivated) {
        onActivated(res);
      }
    } catch (err: any) {
      setError(err.message || 'Failed to trigger kill switch on backend authority');
    } finally {
      setIsExecuting(false);
    }
  };

  const handleReset = () => {
    setResult(null);
    setError(null);
    setReason('');
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-md p-4 animate-in fade-in duration-200">
      <div className="w-full max-w-lg bg-aura-surface border border-rose-500/40 rounded-xl shadow-2xl p-6 relative glow-crit">
        <button
          onClick={handleReset}
          className="absolute top-4 right-4 text-slate-400 hover:text-slate-200"
        >
          <X className="w-5 h-5" />
        </button>

        <div className="flex items-start gap-4">
          <div className="p-3 bg-rose-500/20 text-rose-400 rounded-lg border border-rose-500/30">
            <AlertOctagon className="w-8 h-8 animate-pulse" />
          </div>
          <div className="flex-1">
            <h3 className="text-lg font-bold text-slate-100 font-mono tracking-wide">
              EMERGENCY KILL SWITCH
            </h3>
            <p className="text-xs text-slate-400 mt-1">
              Backend authoritative termination of all running tasks, agent loops, sub-agent worker pools, and tool executions.
            </p>
          </div>
        </div>

        {!result ? (
          <div className="mt-6 space-y-4">
            <div className="p-3 bg-aura-canvas/80 rounded-lg border border-rose-500/20 text-xs font-mono text-rose-300">
              ⚠️ WARNING: This will immediately cancel all active cognitive cycles and revoke pending execution locks across the workspace.
            </div>

            <div>
              <label className="block text-xs font-mono text-slate-300 mb-1.5">
                Audit Reason (Required for Telemetry Log)
              </label>
              <input
                type="text"
                placeholder="e.g., Rogue tool invocation or manual operator override"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                className="w-full bg-aura-canvas border border-aura-subtle rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-rose-500 font-mono"
              />
            </div>

            {error && (
              <div className="p-3 bg-rose-950/50 border border-rose-800 text-xs text-rose-200 rounded-lg font-mono">
                {error}
              </div>
            )}

            <div className="flex items-center justify-end gap-3 mt-6 pt-4 border-t border-aura-subtle">
              <button
                type="button"
                onClick={handleReset}
                className="px-4 py-2 text-xs font-mono text-slate-400 hover:text-slate-200 rounded-lg hover:bg-aura-elevated"
              >
                Dismiss
              </button>
              <button
                type="button"
                disabled={isExecuting}
                onClick={handleActivate}
                className="flex items-center gap-2 px-4 py-2 text-xs font-mono font-bold bg-rose-600 hover:bg-rose-500 text-white rounded-lg shadow-lg transition-all focus:outline-none focus:ring-2 focus:ring-rose-400 disabled:opacity-50"
              >
                {isExecuting ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    ABORTING RUNTIME...
                  </>
                ) : (
                  <>
                    <AlertOctagon className="w-4 h-4" />
                    CONFIRM ABORT ALL
                  </>
                )}
              </button>
            </div>
          </div>
        ) : (
          <div className="mt-6 space-y-4">
            <div className="p-4 bg-emerald-950/40 border border-emerald-500/30 rounded-lg">
              <div className="flex items-center gap-2 text-emerald-400 font-mono font-bold text-sm">
                <CheckCircle2 className="w-5 h-5" />
                EXECUTION TERMINATED BY BACKEND
              </div>
              <p className="text-xs text-slate-300 mt-2 font-mono">{result.message}</p>
              <div className="mt-3 grid grid-cols-3 gap-2 text-center text-xs font-mono">
                <div className="p-2 bg-aura-canvas rounded border border-aura-subtle">
                  <div className="text-rose-400 font-bold">{result.cancelled_runs_count}</div>
                  <div className="text-[10px] text-slate-400">Agent Runs</div>
                </div>
                <div className="p-2 bg-aura-canvas rounded border border-aura-subtle">
                  <div className="text-rose-400 font-bold">{result.cancelled_tasks_count}</div>
                  <div className="text-[10px] text-slate-400">Tasks</div>
                </div>
                <div className="p-2 bg-aura-canvas rounded border border-aura-subtle">
                  <div className="text-rose-400 font-bold">{result.aborted_workers_count}</div>
                  <div className="text-[10px] text-slate-400">Workers</div>
                </div>
              </div>
            </div>

            <div className="flex justify-end pt-2">
              <button
                onClick={handleReset}
                className="px-4 py-2 text-xs font-mono bg-aura-elevated text-slate-200 border border-aura-subtle rounded-lg hover:bg-aura-subtle"
              >
                Close Console
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
