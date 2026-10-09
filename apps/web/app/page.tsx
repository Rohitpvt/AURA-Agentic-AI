'use client';

import React, { useEffect, useState } from 'react';
import { useAuraStore } from '../lib/store';
import { auraApi, setAccessToken } from '../lib/api';
import { useSSEStream } from '../hooks/useSSEStream';
import { Navbar } from '../components/Navbar';
import { Sidebar } from '../components/Sidebar';
import { KillSwitchModal } from '../components/KillSwitchModal';

// Views
import { DashboardView } from '../components/views/DashboardView';
import { ChatView } from '../components/views/ChatView';
import { TasksView } from '../components/views/TasksView';
import { ApprovalsView } from '../components/views/ApprovalsView';
import { SubagentsView } from '../components/views/SubagentsView';
import { MemoryView } from '../components/views/MemoryView';
import { ToolsView } from '../components/views/ToolsView';
import { ProvidersView } from '../components/views/ProvidersView';
import { SecurityView } from '../components/views/SecurityView';
import { FileIntelligenceView } from '../components/views/FileIntelligenceView';
import { VoiceHUDView } from '../components/views/VoiceHUDView';

import { Terminal, Lock, Key, ArrowRight, Loader2 } from 'lucide-react';

export default function MainPage() {
  const {
    user,
    setUser,
    workspaces,
    setWorkspaces,
    activeWorkspace,
    setActiveWorkspace,
    activeTab,
    killSwitchModalOpen,
    setKillSwitchModalOpen,
  } = useAuraStore();

  const [authEmail, setAuthEmail] = useState('operator@example.com');
  const [authPassword, setAuthPassword] = useState('Password123!');
  const [isRegistering, setIsRegistering] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);
  const [authLoading, setAuthLoading] = useState(false);
  const [initLoading, setInitLoading] = useState(true);

  // Real-time SSE Stream
  const { isConnected: sseConnected } = useSSEStream();

  // Try checking existing session or auto-login on mount
  useEffect(() => {
    let mounted = true;

    async function checkAuth() {
      try {
        const me = await auraApi.auth.me();
        if (mounted && me) {
          setUser(me);
          const wsList = await auraApi.workspaces.list();
          if (mounted) {
            setWorkspaces(wsList);
            if (wsList.length > 0 && !activeWorkspace) {
              setActiveWorkspace(wsList[0]);
            }
          }
        }
      } catch {
        // Not authenticated yet
      } finally {
        if (mounted) setInitLoading(false);
      }
    }

    checkAuth();
    return () => {
      mounted = false;
    };
  }, []);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setAuthError(null);
    setAuthLoading(true);

    try {
      if (isRegistering) {
        await auraApi.auth.register(authEmail, authPassword);
      }

      await auraApi.auth.login(authEmail, authPassword);
      const me = await auraApi.auth.me();
      setUser(me);

      const wsList = await auraApi.workspaces.list();
      setWorkspaces(wsList);
      if (wsList.length > 0) {
        setActiveWorkspace(wsList[0]);
      } else {
        // Create default workspace if none
        const defaultWs = await auraApi.workspaces.create('Primary Operations', 'primary');
        setWorkspaces([defaultWs]);
        setActiveWorkspace(defaultWs);
      }
    } catch (err: any) {
      setAuthError(err.message || 'Authentication failed');
    } finally {
      setAuthLoading(false);
    }
  };

  const handleLogout = async () => {
    await auraApi.auth.logout();
    setUser(null);
    setActiveWorkspace(null);
  };

  if (initLoading) {
    return (
      <div className="min-h-screen bg-aura-canvas flex items-center justify-center">
        <div className="flex items-center gap-3 text-cyan-400 font-mono text-xs animate-pulse">
          <Loader2 className="w-5 h-5 animate-spin" />
          <span>AURA CONTROL PLANE INITIALIZING...</span>
        </div>
      </div>
    );
  }

  // If not authenticated, render Login/Register Command Form
  if (!user) {
    return (
      <div className="min-h-screen bg-aura-canvas flex items-center justify-center p-4 relative overflow-hidden">
        {/* Ambient Glows */}
        <div className="absolute -top-40 -left-40 w-96 h-96 bg-cyan-500/10 rounded-full blur-3xl pointer-events-none" />
        <div className="absolute -bottom-40 -right-40 w-96 h-96 bg-violet-600/10 rounded-full blur-3xl pointer-events-none" />

        <div className="w-full max-w-md bg-aura-surface border border-aura-subtle rounded-2xl p-8 shadow-2xl relative z-10 glass-panel">
          <div className="flex items-center gap-3 mb-6">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-cyan-500 to-violet-600 p-[1px] flex items-center justify-center glow-cyan">
              <div className="w-full h-full bg-aura-canvas rounded-[11px] flex items-center justify-center">
                <span className="font-mono font-bold text-sm text-cyan-400">Λ</span>
              </div>
            </div>
            <div>
              <h1 className="font-mono font-bold text-base text-slate-100 tracking-wider">
                AURA CONTROL SURFACE
              </h1>
              <p className="text-[11px] font-mono text-slate-400">
                Authoritative Operator Gateway
              </p>
            </div>
          </div>

          <form onSubmit={handleLogin} className="space-y-4">
            <div>
              <label className="block text-xs font-mono text-slate-400 mb-1.5">
                Operator Email
              </label>
              <input
                type="email"
                required
                value={authEmail}
                onChange={(e) => setAuthEmail(e.target.value)}
                className="w-full bg-aura-canvas border border-aura-subtle rounded-lg px-3.5 py-2 text-xs text-slate-200 focus:outline-none focus:border-cyan-500 font-mono"
              />
            </div>

            <div>
              <label className="block text-xs font-mono text-slate-400 mb-1.5">
                Secret Passphrase
              </label>
              <input
                type="password"
                required
                value={authPassword}
                onChange={(e) => setAuthPassword(e.target.value)}
                className="w-full bg-aura-canvas border border-aura-subtle rounded-lg px-3.5 py-2 text-xs text-slate-200 focus:outline-none focus:border-cyan-500 font-mono"
              />
            </div>

            {authError && (
              <div className="p-3 bg-rose-950/40 border border-rose-500/30 rounded-lg text-xs font-mono text-rose-300">
                {authError}
              </div>
            )}

            <button
              type="submit"
              disabled={authLoading}
              className="w-full flex items-center justify-center gap-2 py-2.5 bg-cyan-600 hover:bg-cyan-500 text-white font-mono text-xs font-bold rounded-lg shadow-lg glow-cyan transition-all disabled:opacity-50"
            >
              {authLoading ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <ArrowRight className="w-4 h-4" />
              )}
              <span>{isRegistering ? 'REGISTER OPERATOR' : 'AUTHENTICATE & ENTER'}</span>
            </button>

            <div className="text-center pt-2">
              <button
                type="button"
                onClick={() => setIsRegistering(!isRegistering)}
                className="text-xs font-mono text-slate-500 hover:text-cyan-400 transition-colors"
              >
                {isRegistering
                  ? 'Already registered? Switch to Sign In'
                  : 'New operator node? Register here'}
              </button>
            </div>
          </form>
        </div>
      </div>
    );
  }

  // Render Main Operator Console
  const renderActiveView = () => {
    switch (activeTab) {
      case 'dashboard':
        return <DashboardView />;
      case 'voice':
        return <VoiceHUDView />;
      case 'chat':
        return <ChatView />;
      case 'tasks':
        return <TasksView />;
      case 'approvals':
        return <ApprovalsView />;
      case 'subagents':
        return <SubagentsView />;
      case 'memory':
        return <MemoryView />;
      case 'tools':
        return <ToolsView />;
      case 'providers':
        return <ProvidersView />;
      case 'security':
        return <SecurityView />;
      case 'files':
        return <FileIntelligenceView />;
      default:
        return <DashboardView />;
    }
  };

  return (
    <div className="min-h-screen bg-aura-canvas flex flex-col">
      <Navbar
        onOpenKillSwitch={() => setKillSwitchModalOpen(true)}
        sseConnected={sseConnected}
        onLogout={handleLogout}
      />

      <div className="flex-1 flex overflow-hidden">
        <Sidebar />
        <main className="flex-1 p-6 overflow-y-auto max-h-[calc(100vh-3.5rem)]">
          {renderActiveView()}
        </main>
      </div>

      {/* Kill Switch Modal */}
      <KillSwitchModal
        isOpen={killSwitchModalOpen}
        onClose={() => setKillSwitchModalOpen(false)}
      />
    </div>
  );
}
