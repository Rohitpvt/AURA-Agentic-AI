'use client';

import React from 'react';
import { useAuraStore } from '../lib/store';
import { ShieldAlert, Radio, Cpu, LogOut, Layers, AlertOctagon } from 'lucide-react';
import { auraApi } from '../lib/api';

interface NavbarProps {
  onOpenKillSwitch: () => void;
  sseConnected: boolean;
  onLogout?: () => void;
}

export const Navbar: React.FC<NavbarProps> = ({
  onOpenKillSwitch,
  sseConnected,
  onLogout,
}) => {
  const { user, workspaces, activeWorkspace, setActiveWorkspace } = useAuraStore();

  return (
    <header className="h-14 border-b border-aura-subtle bg-aura-surface/80 backdrop-blur-md px-4 flex items-center justify-between sticky top-0 z-40">
      {/* Brand & Workspace */}
      <div className="flex items-center gap-6">
        <div className="flex items-center gap-2.5">
          <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-cyan-500 to-violet-600 p-[1px] flex items-center justify-center glow-cyan">
            <div className="w-full h-full bg-aura-canvas rounded-[7px] flex items-center justify-center">
              <span className="font-mono font-bold text-xs text-cyan-400">Λ</span>
            </div>
          </div>
          <div className="flex flex-col">
            <span className="font-mono font-bold text-sm tracking-wider text-slate-100 flex items-center gap-1.5">
              AURA
              <span className="text-[10px] px-1 py-0.2 bg-cyan-950 text-cyan-400 border border-cyan-800/60 rounded font-mono">
                OS v1.0
              </span>
            </span>
          </div>
        </div>

        {/* Workspace Switcher */}
        {workspaces && workspaces.length > 0 && (
          <div className="flex items-center gap-1.5 pl-4 border-l border-aura-subtle">
            <Layers className="w-3.5 h-3.5 text-slate-400" />
            <select
              value={activeWorkspace?.id || ''}
              onChange={(e) => {
                const ws = workspaces.find((w) => w.id === e.target.value) || null;
                setActiveWorkspace(ws);
              }}
              className="bg-aura-elevated border border-aura-subtle text-slate-200 text-xs rounded px-2 py-1 focus:outline-none focus:border-cyan-500 font-mono"
            >
              {workspaces.map((ws) => (
                <option key={ws.id} value={ws.id}>
                  {ws.name}
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

      {/* Center Status Indicators */}
      <div className="hidden md:flex items-center gap-4 text-xs font-mono">
        <div className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-aura-canvas border border-aura-subtle">
          <Radio
            className={`w-3.5 h-3.5 ${
              sseConnected ? 'text-emerald-400 animate-pulse' : 'text-amber-400 animate-spin'
            }`}
          />
          <span className={sseConnected ? 'text-emerald-400' : 'text-amber-400'}>
            {sseConnected ? 'STREAM LIVE' : 'RECONNECTING'}
          </span>
        </div>

        <div className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-aura-canvas border border-aura-subtle text-slate-400">
          <Cpu className="w-3.5 h-3.5 text-violet-400" />
          <span>ZERO-COST LOCAL OLLAMA</span>
        </div>
      </div>

      {/* Right Actions: Kill Switch & Profile */}
      <div className="flex items-center gap-3">
        {/* Emergency Kill Switch Button */}
        <button
          onClick={onOpenKillSwitch}
          className="flex items-center gap-1.5 px-3 py-1 rounded-md text-xs font-mono font-bold bg-rose-500/10 text-rose-400 border border-rose-500/40 hover:bg-rose-500/25 transition-all glow-crit focus:outline-none focus:ring-2 focus:ring-rose-500"
          title="Emergency Abort All Agent Execution"
        >
          <AlertOctagon className="w-3.5 h-3.5" />
          <span>KILL SWITCH</span>
        </button>

        {user && (
          <div className="flex items-center gap-2 pl-3 border-l border-aura-subtle">
            <div className="text-right hidden sm:block">
              <p className="text-xs font-medium text-slate-200">{user.email}</p>
              <span className="text-[10px] font-mono text-cyan-400">{user.role}</span>
            </div>
            {onLogout && (
              <button
                onClick={onLogout}
                className="p-1.5 text-slate-400 hover:text-slate-200 hover:bg-aura-elevated rounded transition-colors"
                title="Logout"
              >
                <LogOut className="w-4 h-4" />
              </button>
            )}
          </div>
        )}
      </div>
    </header>
  );
};
