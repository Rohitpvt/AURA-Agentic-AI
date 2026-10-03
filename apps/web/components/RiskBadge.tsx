import React from 'react';
import { RiskLevel } from '../lib/types';

interface RiskBadgeProps {
  level: RiskLevel;
  className?: string;
}

export const RiskBadge: React.FC<RiskBadgeProps> = ({ level, className = '' }) => {
  switch (level) {
    case 'LOW':
      return (
        <span
          className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-mono bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 ${className}`}
        >
          LOW
        </span>
      );
    case 'MEDIUM':
      return (
        <span
          className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-mono bg-blue-500/10 text-blue-400 border border-blue-500/20 ${className}`}
        >
          MEDIUM
        </span>
      );
    case 'HIGH':
      return (
        <span
          className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-mono bg-amber-500/10 text-amber-400 border border-amber-500/30 animate-pulse ${className}`}
        >
          HIGH APPROVAL
        </span>
      );
    case 'CRITICAL':
      return (
        <span
          className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-mono bg-rose-500/15 text-rose-400 border border-rose-500/40 animate-pulse ${className}`}
        >
          CRITICAL GATE
        </span>
      );
    default:
      return (
        <span
          className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-mono bg-slate-500/10 text-slate-400 border border-slate-500/20 ${className}`}
        >
          {level}
        </span>
      );
  }
};
