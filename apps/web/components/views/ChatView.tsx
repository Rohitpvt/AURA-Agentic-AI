'use client';

import React, { useState } from 'react';
import { useAuraStore } from '../../lib/store';
import { auraApi } from '../../lib/api';
import { StatusBadge } from '../StatusBadge';
import { AuraOrb, deriveVisualState } from '../aura/AuraOrb';
import {
  Terminal,
  Send,
  Bot,
  User,
  Loader2,
  Sparkles,
  GitFork,
  ArrowRight,
  ShieldAlert,
} from 'lucide-react';

interface ChatMessage {
  id: string;
  sender: 'user' | 'aura' | 'system';
  type: 'text' | 'goal_run' | 'status_report';
  content: string;
  timestamp: string;
  runData?: {
    task_id: string;
    status: string;
    plan_summary?: string;
    requires_approval?: boolean;
  };
}

export const ChatView: React.FC = () => {
  const { activeWorkspace, setSelectedTaskId, setActiveTab } = useAuraStore();
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 'welcome',
      sender: 'aura',
      type: 'text',
      content:
        'AURA Autonomous Control Shell initialized. You can dispatch multi-step goals, ask status questions, or inspect active execution loops.',
      timestamp: new Date().toISOString(),
    },
  ]);
  const [input, setInput] = useState('');
  const [isProcessing, setIsProcessing] = useState(false);
  const [latestError, setLatestError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isProcessing || !activeWorkspace) return;

    const userMsg: ChatMessage = {
      id: `user-${Date.now()}`,
      sender: 'user',
      type: 'text',
      content: input,
      timestamp: new Date().toISOString(),
    };

    setMessages((prev) => [...prev, userMsg]);
    const goalText = input;
    setInput('');
    setIsProcessing(true);
    setLatestError(null);

    try {
      // Execute via agent API
      const res = await auraApi.agent.run({
        goal: goalText,
        workspace_id: activeWorkspace.id,
      });

      const auraResponse: ChatMessage = {
        id: `aura-${Date.now()}`,
        sender: 'aura',
        type: 'goal_run',
        content: res.message || 'Task dispatched to cognitive runtime.',
        timestamp: new Date().toISOString(),
        runData: {
          task_id: res.task_id,
          status: res.status,
          plan_summary: res.plan_summary,
          requires_approval: res.requires_approval,
        },
      };

      setMessages((prev) => [...prev, auraResponse]);
    } catch (err: any) {
      const errorMsgText = `Error executing request: ${err.message || 'Unknown runtime error'}`;
      setLatestError(errorMsgText);
      const errorMsg: ChatMessage = {
        id: `err-${Date.now()}`,
        sender: 'system',
        type: 'text',
        content: errorMsgText,
        timestamp: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setIsProcessing(false);
    }
  };

  const visualState = deriveVisualState({
    isProcessing,
    hasErrors: !!latestError,
  });

  return (
    <div className="h-[calc(100vh-6rem)] flex flex-col bg-aura-surface border border-aura-subtle rounded-xl overflow-hidden animate-in fade-in duration-200">
      {/* Header with AuraOrb Face */}
      <div className="p-3.5 border-b border-aura-subtle bg-aura-surface flex items-center justify-between">
        <div className="flex items-center gap-3">
          <AuraOrb state={visualState} size={42} showStatusBadge={false} />
          <div>
            <h2 className="text-xs font-bold font-mono text-slate-100 flex items-center gap-2">
              <span>AURA CONVERSATIONAL CONTROL SHELL</span>
              <span className="text-[10px] px-1.5 py-0.2 rounded bg-cyan-950 text-cyan-400 border border-cyan-800/60 uppercase">
                {visualState}
              </span>
            </h2>
            <p className="text-[11px] font-mono text-slate-400">
              Zero-Leakage In-Memory Session
            </p>
          </div>
        </div>
        <span className="text-[11px] font-mono text-slate-500 hidden sm:inline">
          Deterministic HITL Guardrails Active
        </span>
      </div>

      {/* Chat Messages Container */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.map((msg) => {
          const isUser = msg.sender === 'user';
          const isSystem = msg.sender === 'system';

          return (
            <div
              key={msg.id}
              className={`flex gap-3 max-w-2xl ${
                isUser ? 'ml-auto flex-row-reverse' : 'mr-auto'
              }`}
            >
              {/* Avatar */}
              <div
                className={`w-7 h-7 rounded-lg flex items-center justify-center shrink-0 ${
                  isUser
                    ? 'bg-cyan-600 text-white'
                    : isSystem
                    ? 'bg-rose-500/20 text-rose-400 border border-rose-500/40'
                    : 'bg-aura-elevated text-cyan-400 border border-cyan-500/30'
                }`}
              >
                {isUser ? (
                  <User className="w-4 h-4" />
                ) : isSystem ? (
                  <ShieldAlert className="w-4 h-4" />
                ) : (
                  <Bot className="w-4 h-4" />
                )}
              </div>

              {/* Message Bubble */}
              <div className="space-y-2">
                <div
                  className={`p-3.5 rounded-xl text-xs font-mono leading-relaxed ${
                    isUser
                      ? 'bg-cyan-950/60 border border-cyan-500/30 text-slate-100'
                      : isSystem
                      ? 'bg-rose-950/40 border border-rose-500/30 text-rose-200'
                      : 'bg-aura-elevated border border-aura-subtle text-slate-200'
                  }`}
                >
                  <p>{msg.content}</p>

                  {/* Goal Run Card */}
                  {msg.runData && (
                    <div className="mt-3 p-3 bg-aura-canvas rounded-lg border border-aura-subtle/60 space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="text-[11px] text-cyan-400 font-bold">
                          TASK: {msg.runData.task_id.substring(0, 8)}...
                        </span>
                        <StatusBadge status={msg.runData.status as any} />
                      </div>

                      {msg.runData.plan_summary && (
                        <p className="text-[11px] text-slate-400">
                          {msg.runData.plan_summary}
                        </p>
                      )}

                      <button
                        onClick={() => {
                          setSelectedTaskId(msg.runData!.task_id);
                          setActiveTab('tasks');
                        }}
                        className="w-full flex items-center justify-center gap-1.5 py-1 bg-aura-elevated hover:bg-aura-subtle text-cyan-400 border border-cyan-500/30 rounded text-[11px] transition-colors"
                      >
                        <span>INSPECT EXECUTION DAG</span>
                        <ArrowRight className="w-3 h-3" />
                      </button>
                    </div>
                  )}
                </div>
                <div
                  className={`text-[10px] font-mono text-slate-500 px-1 ${
                    isUser ? 'text-right' : 'text-left'
                  }`}
                >
                  {new Date(msg.timestamp).toLocaleTimeString()}
                </div>
              </div>
            </div>
          );
        })}

        {isProcessing && (
          <div className="flex items-center gap-2 text-xs font-mono text-cyan-400 p-3 bg-aura-elevated/50 rounded-lg border border-cyan-500/20 max-w-xs animate-pulse">
            <Loader2 className="w-4 h-4 animate-spin" />
            <span>AURA Cognitive Planner Synthesizing...</span>
          </div>
        )}
      </div>

      {/* Input Box */}
      <form
        onSubmit={handleSubmit}
        className="p-3 border-t border-aura-subtle bg-aura-surface flex gap-2"
      >
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Command AURA (e.g., 'Execute task: search duckduckgo for latest open-source LLM releases')"
          className="flex-1 bg-aura-canvas border border-aura-subtle rounded-lg px-3.5 py-2.5 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-cyan-500 font-mono"
        />
        <button
          type="submit"
          disabled={!input.trim() || isProcessing}
          className="px-4 py-2.5 bg-cyan-600 hover:bg-cyan-500 disabled:opacity-50 text-white rounded-lg text-xs font-mono font-bold flex items-center gap-1.5 shadow-lg glow-cyan transition-all"
        >
          <Send className="w-3.5 h-3.5" />
          <span>SEND</span>
        </button>
      </form>
    </div>
  );
};
