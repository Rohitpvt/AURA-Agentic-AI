import React from 'react';
import { TaskStatus, TaskStepStatus } from '../lib/types';
import { Clock, Loader2, ShieldAlert, CheckCircle2, XCircle, Ban, PlayCircle } from 'lucide-react';

interface StatusBadgeProps {
  status: TaskStatus | TaskStepStatus;
  className?: string;
}

export const StatusBadge: React.FC<StatusBadgeProps> = ({ status, className = '' }) => {
  switch (status) {
    case 'PENDING':
    case 'READY':
      return (
        <span
          className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs font-mono bg-slate-800/60 text-slate-400 border border-slate-700/50 ${className}`}
        >
          <Clock className="w-3 h-3" />
          {status}
        </span>
      );
    case 'PLANNING':
      return (
        <span
          className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs font-mono bg-purple-500/10 text-purple-400 border border-purple-500/30 animate-pulse ${className}`}
        >
          <Loader2 className="w-3 h-3 animate-spin" />
          PLANNING
        </span>
      );
    case 'IN_PROGRESS':
    case 'RUNNING':
      return (
        <span
          className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs font-mono bg-cyan-500/10 text-cyan-400 border border-cyan-500/30 glow-cyan ${className}`}
        >
          <PlayCircle className="w-3 h-3 animate-pulse" />
          EXECUTING
        </span>
      );
    case 'WAITING_APPROVAL':
      return (
        <span
          className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs font-mono bg-amber-500/10 text-amber-400 border border-amber-500/40 animate-pulse glow-amber ${className}`}
        >
          <ShieldAlert className="w-3 h-3" />
          WAITING APPROVAL
        </span>
      );
    case 'VERIFYING':
      return (
        <span
          className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs font-mono bg-indigo-500/10 text-indigo-400 border border-indigo-500/30 ${className}`}
        >
          <Loader2 className="w-3 h-3 animate-spin" />
          VERIFYING
        </span>
      );
    case 'COMPLETED':
      return (
        <span
          className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs font-mono bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 ${className}`}
        >
          <CheckCircle2 className="w-3 h-3" />
          COMPLETED
        </span>
      );
    case 'FAILED':
      return (
        <span
          className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs font-mono bg-rose-500/10 text-rose-400 border border-rose-500/30 glow-crit ${className}`}
        >
          <XCircle className="w-3 h-3" />
          FAILED
        </span>
      );
    case 'CANCELLED':
    case 'SKIPPED':
      return (
        <span
          className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs font-mono bg-zinc-800 text-zinc-400 border border-zinc-700 ${className}`}
        >
          <Ban className="w-3 h-3" />
          {status}
        </span>
      );
    default:
      return (
        <span
          className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs font-mono bg-slate-800 text-slate-300 border border-slate-700 ${className}`}
        >
          {status}
        </span>
      );
  }
};
