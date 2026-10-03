'use client';

import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { auraApi } from '../../lib/api';
import { useAuraStore } from '../../lib/store';
import { ApprovalRequest } from '../../lib/types';
import { RiskBadge } from '../RiskBadge';
import {
  ShieldAlert,
  CheckCircle2,
  XCircle,
  Clock,
  Code,
  Lock,
  Loader2,
  AlertTriangle,
} from 'lucide-react';

export const ApprovalsView: React.FC = () => {
  const { activeWorkspace } = useAuraStore();
  const queryClient = useQueryClient();
  const [rejectReason, setRejectReason] = useState<{ [id: string]: string }>({});
  const [activeModal, setActiveModal] = useState<{
    id: string;
    type: 'APPROVE' | 'REJECT';
    approval: ApprovalRequest;
  } | null>(null);

  // Fetch approvals
  const { data: approvals, isLoading } = useQuery({
    queryKey: ['approvals', activeWorkspace?.id],
    queryFn: () => auraApi.approvals.list(activeWorkspace?.id),
    refetchInterval: 4000,
  });

  // Resolve Mutation
  const resolveMutation = useMutation({
    mutationFn: async ({
      id,
      decision,
      reason,
      token,
    }: {
      id: string;
      decision: 'APPROVED' | 'REJECTED';
      reason?: string;
      token?: string;
    }) => {
      return auraApi.approvals.resolve(id, decision, reason, token);
    },
    onSuccess: () => {
      setActiveModal(null);
      queryClient.invalidateQueries({ queryKey: ['approvals'] });
      queryClient.invalidateQueries({ queryKey: ['tasks'] });
    },
  });

  const pendingList = approvals?.filter((a) => a.status === 'PENDING') || [];
  const resolvedList = approvals?.filter((a) => a.status !== 'PENDING') || [];

  return (
    <div className="space-y-6 animate-in fade-in duration-200">
      {/* Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 p-5 bg-aura-surface border border-aura-subtle rounded-xl">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <ShieldAlert className="w-5 h-5 text-amber-400" />
            <h1 className="text-base font-bold font-mono text-slate-100 uppercase tracking-wide">
              HUMAN-IN-THE-LOOP (HITL) APPROVAL CENTER
            </h1>
          </div>
          <p className="text-xs text-slate-400">
            Authoritative gate for High and Critical risk side-effects. Execution is suspended until approved by the operator.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <div className="px-3 py-1.5 bg-aura-canvas border border-aura-subtle rounded-lg text-xs font-mono">
            <span className="text-slate-400">PENDING: </span>
            <span className="text-amber-400 font-bold">{pendingList.length}</span>
          </div>
        </div>
      </div>

      {/* Pending Approvals Section */}
      <div className="space-y-4">
        <h2 className="text-xs font-bold font-mono text-amber-300 uppercase tracking-wider flex items-center gap-2">
          <AlertTriangle className="w-4 h-4" />
          PENDING APPROVAL REQUESTS ({pendingList.length})
        </h2>

        {isLoading ? (
          <div className="p-8 text-center text-xs font-mono text-slate-500 bg-aura-surface rounded-xl border border-aura-subtle">
            Loading approval gates...
          </div>
        ) : pendingList.length > 0 ? (
          <div className="grid grid-cols-1 gap-4">
            {pendingList.map((appr) => (
              <div
                key={appr.id}
                className="bg-aura-surface border border-amber-500/30 rounded-xl p-5 space-y-4 glow-amber"
              >
                <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2 border-b border-aura-subtle/60 pb-3">
                  <div className="flex items-center gap-3">
                    <RiskBadge level={appr.risk_level} />
                    <h3 className="text-sm font-bold font-mono text-slate-100">
                      Tool Invocation: <span className="text-cyan-400">{appr.tool_name}</span>
                    </h3>
                  </div>
                  <div className="flex items-center gap-2 text-[11px] font-mono text-slate-400">
                    <Clock className="w-3.5 h-3.5 text-amber-400" />
                    <span>Expires: {new Date(appr.expires_at).toLocaleTimeString()}</span>
                  </div>
                </div>

                {/* Reason / Context */}
                <div className="p-3 bg-aura-canvas rounded-lg border border-aura-subtle text-xs font-mono text-slate-300">
                  <span className="text-slate-500">REASON: </span>
                  {appr.reason || 'Agent requested tool execution requiring explicit authorization.'}
                </div>

                {/* Sanitized Parameters Viewer */}
                <div>
                  <div className="text-[11px] font-mono text-slate-400 mb-1 flex items-center gap-1.5">
                    <Code className="w-3.5 h-3.5 text-violet-400" />
                    <span>SANITIZED PARAMETER PAYLOAD:</span>
                  </div>
                  <pre className="p-3 bg-aura-canvas border border-aura-subtle rounded-lg text-xs font-mono text-cyan-300 overflow-x-auto max-h-48">
                    {JSON.stringify(appr.sanitized_params, null, 2)}
                  </pre>
                </div>

                {/* Action Buttons */}
                <div className="flex flex-col sm:flex-row items-center justify-between gap-3 pt-3 border-t border-aura-subtle">
                  <div className="flex items-center gap-2 text-[11px] font-mono text-slate-500 truncate">
                    <Lock className="w-3.5 h-3.5" />
                    <span>Task ID: {appr.task_id}</span>
                  </div>

                  <div className="flex items-center gap-2 w-full sm:w-auto">
                    <button
                      onClick={() =>
                        setActiveModal({
                          id: appr.id,
                          type: 'REJECT',
                          approval: appr,
                        })
                      }
                      className="flex-1 sm:flex-none flex items-center justify-center gap-1.5 px-4 py-2 bg-rose-500/10 hover:bg-rose-500/20 text-rose-400 border border-rose-500/30 rounded-lg text-xs font-mono font-bold transition-all"
                    >
                      <XCircle className="w-4 h-4" />
                      <span>REJECT</span>
                    </button>
                    <button
                      onClick={() =>
                        setActiveModal({
                          id: appr.id,
                          type: 'APPROVE',
                          approval: appr,
                        })
                      }
                      className="flex-1 sm:flex-none flex items-center justify-center gap-1.5 px-5 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-mono font-bold shadow-lg transition-all"
                    >
                      <CheckCircle2 className="w-4 h-4" />
                      <span>AUTHORIZE & RESUME</span>
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="p-8 text-center bg-aura-surface/50 border border-aura-subtle rounded-xl text-xs font-mono text-slate-500">
            No pending approval requests. Agent execution is clear of high-risk gates.
          </div>
        )}
      </div>

      {/* Decision Confirmation Modal */}
      {activeModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
          <div className="w-full max-w-md bg-aura-surface border border-aura-strong rounded-xl p-5 space-y-4">
            <h3 className="text-sm font-bold font-mono text-slate-100 flex items-center gap-2">
              {activeModal.type === 'APPROVE' ? (
                <>
                  <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                  CONFIRM AUTHORIZATION
                </>
              ) : (
                <>
                  <XCircle className="w-4 h-4 text-rose-400" />
                  CONFIRM REJECTION
                </>
              )}
            </h3>

            <p className="text-xs text-slate-300 font-mono">
              {activeModal.type === 'APPROVE'
                ? `You are authorizing tool '${activeModal.approval.tool_name}'. The agent execution loop will immediately resume.`
                : `You are rejecting tool '${activeModal.approval.tool_name}'. The step will be marked failed or cancelled.`}
            </p>

            <div>
              <label className="block text-xs font-mono text-slate-400 mb-1">
                Audit Note / Reason
              </label>
              <input
                type="text"
                placeholder={
                  activeModal.type === 'APPROVE'
                    ? 'Verified side-effect safety'
                    : 'Disallowed parameter or action'
                }
                value={rejectReason[activeModal.id] || ''}
                onChange={(e) =>
                  setRejectReason({
                    ...rejectReason,
                    [activeModal.id]: e.target.value,
                  })
                }
                className="w-full bg-aura-canvas border border-aura-subtle rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-cyan-500 font-mono"
              />
            </div>

            <div className="flex justify-end gap-2 pt-2 border-t border-aura-subtle">
              <button
                onClick={() => setActiveModal(null)}
                className="px-3 py-1.5 text-xs font-mono text-slate-400 hover:text-slate-200"
              >
                Cancel
              </button>
              <button
                disabled={resolveMutation.isPending}
                onClick={() =>
                  resolveMutation.mutate({
                    id: activeModal.id,
                    decision: activeModal.type === 'APPROVE' ? 'APPROVED' : 'REJECTED',
                    reason: rejectReason[activeModal.id],
                    token: activeModal.approval.approval_token,
                  })
                }
                className={`px-4 py-1.5 text-xs font-mono font-bold text-white rounded-lg flex items-center gap-1.5 ${
                  activeModal.type === 'APPROVE'
                    ? 'bg-emerald-600 hover:bg-emerald-500'
                    : 'bg-rose-600 hover:bg-rose-500'
                }`}
              >
                {resolveMutation.isPending && (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                )}
                <span>SUBMIT DECISION</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Resolved Approvals History */}
      {resolvedList.length > 0 && (
        <div className="space-y-3 pt-6 border-t border-aura-subtle">
          <h3 className="text-xs font-bold font-mono text-slate-400 uppercase tracking-wider">
            RECENTLY RESOLVED GATES
          </h3>
          <div className="space-y-2">
            {resolvedList.map((appr) => (
              <div
                key={appr.id}
                className="p-3 bg-aura-surface/60 border border-aura-subtle/50 rounded-lg flex items-center justify-between text-xs font-mono"
              >
                <div className="flex items-center gap-3">
                  <span
                    className={`font-bold ${
                      appr.status === 'APPROVED' ? 'text-emerald-400' : 'text-rose-400'
                    }`}
                  >
                    {appr.status}
                  </span>
                  <span className="text-slate-300">{appr.tool_name}</span>
                </div>
                <span className="text-slate-500 text-[11px]">
                  {new Date(appr.requested_at).toLocaleString()}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
