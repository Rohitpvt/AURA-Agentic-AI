'use client';

import React from 'react';
import { useAuraStore, ActiveTab } from '../lib/store';
import {
  LayoutDashboard,
  Terminal,
  GitFork,
  ShieldAlert,
  Bot,
  BrainCircuit,
  FileText,
  Wrench,
  Cpu,
  Lock,
  Mic,
} from 'lucide-react';

export const Sidebar: React.FC = () => {
  const { activeTab, setActiveTab, pendingApprovals } = useAuraStore();

  const navItems: { id: ActiveTab; label: string; icon: React.ReactNode; badge?: number }[] = [
    {
      id: 'dashboard',
      label: 'Dashboard',
      icon: <LayoutDashboard className="w-4 h-4" />,
    },
    {
      id: 'voice',
      label: 'Voice HUD',
      icon: <Mic className="w-4 h-4 text-cyan-400" />,
    },
    {
      id: 'chat',
      label: 'Command / Chat',
      icon: <Terminal className="w-4 h-4" />,
    },
    {
      id: 'tasks',
      label: 'Task & DAG Flow',
      icon: <GitFork className="w-4 h-4" />,
    },
    {
      id: 'approvals',
      label: 'HITL Approvals',
      icon: <ShieldAlert className="w-4 h-4" />,
      badge: pendingApprovals?.length || 0,
    },
    {
      id: 'subagents',
      label: 'Sub-Agent Pool',
      icon: <Bot className="w-4 h-4" />,
    },
    {
      id: 'memory',
      label: 'Memory Vault',
      icon: <BrainCircuit className="w-4 h-4" />,
    },
    {
      id: 'files',
      label: 'Files & Docs',
      icon: <FileText className="w-4 h-4" />,
    },
    {
      id: 'tools',
      label: 'Tools & MCP',
      icon: <Wrench className="w-4 h-4" />,
    },
    {
      id: 'providers',
      label: 'Model Providers',
      icon: <Cpu className="w-4 h-4" />,
    },
    {
      id: 'security',
      label: 'Security & Audit',
      icon: <Lock className="w-4 h-4" />,
    },
  ];

  return (
    <aside className="w-64 bg-aura-surface border-r border-aura-subtle flex flex-col justify-between p-3 select-none">
      <div className="space-y-1">
        <div className="px-3 py-2 text-[10px] font-mono font-semibold tracking-wider text-slate-500 uppercase">
          Autonomous Console
        </div>
        {navItems.map((item) => {
          const isActive = activeTab === item.id;
          return (
            <button
              key={item.id}
              onClick={() => setActiveTab(item.id)}
              className={`w-full flex items-center justify-between px-3 py-2 rounded-md text-xs font-medium transition-all ${
                isActive
                  ? 'bg-aura-elevated text-cyan-400 border border-cyan-500/30 glow-cyan'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-aura-elevated/50'
              }`}
            >
              <div className="flex items-center gap-2.5">
                <span className={isActive ? 'text-cyan-400' : 'text-slate-400'}>
                  {item.icon}
                </span>
                <span>{item.label}</span>
              </div>
              {item.badge !== undefined && item.badge > 0 && (
                <span className="px-1.5 py-0.2 rounded-full text-[10px] font-mono font-bold bg-amber-500/20 text-amber-400 border border-amber-500/40 animate-pulse">
                  {item.badge}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Footer Info */}
      <div className="p-3 bg-aura-canvas/60 rounded-lg border border-aura-subtle/40 text-[11px] font-mono text-slate-500 space-y-1">
        <div className="flex justify-between">
          <span>COGNITIVE ENGINE</span>
          <span className="text-cyan-400">AURA-NATIVE</span>
        </div>
        <div className="flex justify-between">
          <span>SANDBOX MODE</span>
          <span className="text-emerald-400">ENFORCED</span>
        </div>
      </div>
    </aside>
  );
};
