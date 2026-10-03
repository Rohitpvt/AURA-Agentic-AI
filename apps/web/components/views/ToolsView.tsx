'use client';

import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { auraApi } from '../../lib/api';
import { ToolDefinition, MCPServer } from '../../lib/types';
import { RiskBadge } from '../RiskBadge';
import {
  Wrench,
  PlugZap,
  ShieldCheck,
  Plus,
  Server,
  Layers,
  CheckCircle2,
  AlertTriangle,
  Code,
  Globe,
  Database,
  Terminal,
} from 'lucide-react';

export const ToolsView: React.FC = () => {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<'tools' | 'mcp'>('tools');
  const [isRegisteringMcp, setIsRegisteringMcp] = useState(false);
  const [mcpName, setMcpName] = useState('');
  const [mcpCommand, setMcpCommand] = useState('');
  const [mcpArgs, setMcpArgs] = useState('');

  // Queries
  const { data: tools, isLoading: toolsLoading } = useQuery({
    queryKey: ['tools'],
    queryFn: () => auraApi.tools.list(),
  });

  const { data: mcpServers, isLoading: mcpLoading } = useQuery({
    queryKey: ['mcp-servers'],
    queryFn: () => auraApi.tools.listMcpServers(),
  });

  // Register MCP Server Mutation
  const registerMcpMutation = useMutation({
    mutationFn: (payload: { name: string; transport: string; command: string; args: string[] }) =>
      auraApi.tools.registerMcpServer(payload),
    onSuccess: () => {
      setIsRegisteringMcp(false);
      setMcpName('');
      setMcpCommand('');
      setMcpArgs('');
      queryClient.invalidateQueries({ queryKey: ['mcp-servers'] });
    },
  });

  const getCategoryIcon = (category: string) => {
    switch (category) {
      case 'BROWSER':
      case 'SEARCH':
        return <Globe className="w-4 h-4 text-cyan-400" />;
      case 'MEMORY':
        return <Database className="w-4 h-4 text-violet-400" />;
      case 'MCP':
        return <PlugZap className="w-4 h-4 text-emerald-400" />;
      default:
        return <Terminal className="w-4 h-4 text-slate-400" />;
    }
  };

  return (
    <div className="space-y-6 animate-in fade-in duration-200">
      {/* Header & Sub-Navigation */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 p-5 bg-aura-surface border border-aura-subtle rounded-xl">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <Wrench className="w-5 h-5 text-cyan-400" />
            <h1 className="text-base font-bold font-mono text-slate-100 uppercase tracking-wide">
              TOOL REGISTRY & MCP INTEGRATIONS
            </h1>
          </div>
          <p className="text-xs text-slate-400">
            Authoritative tool governance via AgentToolBridge with risk level classification and SSRF containment.
          </p>
        </div>

        <div className="flex items-center gap-2 bg-aura-canvas p-1 rounded-lg border border-aura-subtle">
          <button
            onClick={() => setActiveTab('tools')}
            className={`px-3 py-1 rounded text-xs font-mono font-medium transition-all ${
              activeTab === 'tools'
                ? 'bg-aura-elevated text-cyan-400 border border-cyan-500/30'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            Registered Tools ({tools?.length || 0})
          </button>
          <button
            onClick={() => setActiveTab('mcp')}
            className={`px-3 py-1 rounded text-xs font-mono font-medium transition-all ${
              activeTab === 'mcp'
                ? 'bg-aura-elevated text-cyan-400 border border-cyan-500/30'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            MCP Servers ({mcpServers?.length || 0})
          </button>
        </div>
      </div>

      {activeTab === 'tools' ? (
        /* Tools Catalog */
        <div className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {toolsLoading ? (
              <div className="col-span-full p-8 text-center text-xs font-mono text-slate-500 bg-aura-surface rounded-xl border border-aura-subtle">
                Loading tool definitions...
              </div>
            ) : tools && tools.length > 0 ? (
              tools.map((tool) => (
                <div
                  key={tool.name}
                  className="bg-aura-surface border border-aura-subtle rounded-xl p-4 flex flex-col justify-between space-y-3 hover:border-aura-strong transition-all"
                >
                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <div className="p-1.5 bg-aura-canvas rounded border border-aura-subtle">
                          {getCategoryIcon(tool.category)}
                        </div>
                        <h3 className="text-xs font-bold font-mono text-slate-100">
                          {tool.name}
                        </h3>
                      </div>
                      <RiskBadge level={tool.risk_level} />
                    </div>

                    <p className="text-xs text-slate-400 font-sans leading-relaxed">
                      {tool.description}
                    </p>
                  </div>

                  <div className="pt-3 border-t border-aura-subtle/50 flex items-center justify-between text-[11px] font-mono text-slate-500">
                    <span>Category: <strong className="text-slate-300">{tool.category}</strong></span>
                    <span className={tool.is_available ? 'text-emerald-400' : 'text-slate-500'}>
                      {tool.is_available ? '● AVAILABLE' : '○ UNAVAILABLE'}
                    </span>
                  </div>
                </div>
              ))
            ) : (
              <div className="col-span-full p-8 text-center bg-aura-surface/50 border border-aura-subtle rounded-xl text-xs font-mono text-slate-500">
                No tools registered in AgentToolBridge.
              </div>
            )}
          </div>
        </div>
      ) : (
        /* MCP Server Management */
        <div className="space-y-4">
          <div className="flex justify-between items-center">
            <h2 className="text-xs font-bold font-mono text-slate-300 uppercase tracking-wider">
              CONFIGURED MCP CLIENT HOSTS
            </h2>
            <button
              onClick={() => setIsRegisteringMcp(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-cyan-600 hover:bg-cyan-500 text-white rounded-lg text-xs font-mono font-bold transition-all shadow-lg"
            >
              <Plus className="w-3.5 h-3.5" />
              <span>REGISTER MCP SERVER</span>
            </button>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {mcpLoading ? (
              <div className="col-span-full p-8 text-center text-xs font-mono text-slate-500 bg-aura-surface rounded-xl border border-aura-subtle">
                Loading MCP servers...
              </div>
            ) : mcpServers && mcpServers.length > 0 ? (
              mcpServers.map((server) => (
                <div
                  key={server.name}
                  className="bg-aura-surface border border-aura-subtle rounded-xl p-5 space-y-3"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <PlugZap className="w-4 h-4 text-emerald-400" />
                      <h3 className="text-xs font-bold font-mono text-slate-100">
                        {server.name}
                      </h3>
                    </div>
                    <span
                      className={`text-[10px] font-mono px-2 py-0.5 rounded border ${
                        server.status === 'CONNECTED'
                          ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
                          : 'bg-slate-800 text-slate-400 border-slate-700'
                      }`}
                    >
                      {server.status}
                    </span>
                  </div>

                  <div className="p-2.5 bg-aura-canvas rounded-lg border border-aura-subtle/50 text-[11px] font-mono text-slate-300 space-y-1">
                    <div>Transport: <strong className="text-cyan-400">{server.transport}</strong></div>
                    {server.command && (
                      <div className="truncate">Command: <span className="text-slate-400">{server.command}</span></div>
                    )}
                  </div>

                  <div className="pt-2 flex items-center justify-between text-[11px] font-mono text-slate-500">
                    <span>Exported Tools: <strong className="text-slate-300">{server.tools_count || 0}</strong></span>
                  </div>
                </div>
              ))
            ) : (
              <div className="col-span-full p-8 text-center bg-aura-surface/50 border border-aura-subtle rounded-xl text-xs font-mono text-slate-500">
                No MCP servers registered. AURA uses native sandboxed tools by default.
              </div>
            )}
          </div>
        </div>
      )}

      {/* Register MCP Server Modal */}
      {isRegisteringMcp && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
          <div className="w-full max-w-md bg-aura-surface border border-aura-strong rounded-xl p-5 space-y-4">
            <h3 className="text-sm font-bold font-mono text-slate-100 flex items-center gap-2">
              <PlugZap className="w-4 h-4 text-emerald-400" />
              REGISTER MCP SERVER
            </h3>

            <p className="text-xs text-slate-400 font-sans">
              Connect an external Model Context Protocol server. Executable commands are validated against backend sandbox policy.
            </p>

            <div className="space-y-3">
              <div>
                <label className="block text-xs font-mono text-slate-400 mb-1">
                  Server Name
                </label>
                <input
                  type="text"
                  placeholder="e.g. filesystem-server"
                  value={mcpName}
                  onChange={(e) => setMcpName(e.target.value)}
                  className="w-full bg-aura-canvas border border-aura-subtle rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-cyan-500 font-mono"
                />
              </div>

              <div>
                <label className="block text-xs font-mono text-slate-400 mb-1">
                  Executable Command
                </label>
                <input
                  type="text"
                  placeholder="e.g. npx or python"
                  value={mcpCommand}
                  onChange={(e) => setMcpCommand(e.target.value)}
                  className="w-full bg-aura-canvas border border-aura-subtle rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-cyan-500 font-mono"
                />
              </div>

              <div>
                <label className="block text-xs font-mono text-slate-400 mb-1">
                  Arguments (Space-separated)
                </label>
                <input
                  type="text"
                  placeholder="e.g. -y @modelcontextprotocol/server-filesystem /tmp"
                  value={mcpArgs}
                  onChange={(e) => setMcpArgs(e.target.value)}
                  className="w-full bg-aura-canvas border border-aura-subtle rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-cyan-500 font-mono"
                />
              </div>
            </div>

            <div className="flex justify-end gap-2 pt-2 border-t border-aura-subtle">
              <button
                onClick={() => setIsRegisteringMcp(false)}
                className="px-3 py-1.5 text-xs font-mono text-slate-400 hover:text-slate-200"
              >
                Cancel
              </button>
              <button
                onClick={() =>
                  registerMcpMutation.mutate({
                    name: mcpName,
                    transport: 'stdio',
                    command: mcpCommand,
                    args: mcpArgs ? mcpArgs.split(' ') : [],
                  })
                }
                disabled={!mcpName.trim() || !mcpCommand.trim() || registerMcpMutation.isPending}
                className="px-4 py-1.5 text-xs font-mono font-bold bg-cyan-600 hover:bg-cyan-500 text-white rounded-lg disabled:opacity-50"
              >
                Register Server
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
