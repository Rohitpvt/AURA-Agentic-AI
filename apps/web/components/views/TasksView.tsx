'use client';

import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { auraApi } from '../../lib/api';
import { useAuraStore } from '../../lib/store';
import { Task, TaskStep } from '../../lib/types';
import { StatusBadge } from '../StatusBadge';
import { RiskBadge } from '../RiskBadge';
import {
  GitFork,
  CheckCircle2,
  AlertCircle,
  Clock,
  Play,
  Ban,
  Plus,
  RefreshCw,
  Search,
  Layers,
  ChevronRight,
  Code,
  ShieldAlert,
} from 'lucide-react';

export const TasksView: React.FC = () => {
  const { activeWorkspace, selectedTaskId, setSelectedTaskId } = useAuraStore();
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState<string>('ALL');
  const [search, setSearch] = useState('');
  const [isCreating, setIsCreating] = useState(false);
  const [newTitle, setNewTitle] = useState('');
  const [newObjective, setNewObjective] = useState('');

  // Fetch Tasks
  const { data: tasks, isLoading, refetch } = useQuery({
    queryKey: ['tasks', activeWorkspace?.id],
    queryFn: () => auraApi.tasks.list(activeWorkspace?.id, 50, 0),
  });

  // Fetch Active Task Details if selected
  const { data: activeTask, isLoading: taskDetailLoading } = useQuery({
    queryKey: ['task', selectedTaskId],
    queryFn: () => (selectedTaskId ? auraApi.tasks.get(selectedTaskId) : null),
    enabled: !!selectedTaskId,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === 'IN_PROGRESS' || status === 'PLANNING' ? 2000 : false;
    },
  });

  // Cancel Task Mutation
  const cancelMutation = useMutation({
    mutationFn: (taskId: string) => auraApi.tasks.cancel(taskId, 'Operator aborted task execution'),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tasks'] });
      queryClient.invalidateQueries({ queryKey: ['task', selectedTaskId] });
    },
  });

  // Create Task Mutation
  const createMutation = useMutation({
    mutationFn: (payload: { title: string; objective: string; workspace_id: string }) =>
      auraApi.tasks.create(payload),
    onSuccess: (newTask) => {
      setIsCreating(false);
      setNewTitle('');
      setNewObjective('');
      queryClient.invalidateQueries({ queryKey: ['tasks'] });
      setSelectedTaskId(newTask.id);
    },
  });

  const filteredTasks = (tasks || []).filter((t) => {
    if (filter !== 'ALL' && t.status !== filter) return false;
    if (search && !t.title.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  return (
    <div className="h-[calc(100vh-6rem)] flex flex-col md:flex-row gap-4 animate-in fade-in duration-200">
      {/* Left Column: Task List */}
      <div className="w-full md:w-80 bg-aura-surface border border-aura-subtle rounded-xl flex flex-col shrink-0">
        <div className="p-4 border-b border-aura-subtle space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-bold font-mono text-slate-100 flex items-center gap-2">
              <GitFork className="w-4 h-4 text-cyan-400" />
              TASKS & DAGS
            </h2>
            <button
              onClick={() => setIsCreating(true)}
              className="p-1.5 bg-cyan-600 hover:bg-cyan-500 text-white rounded-md text-xs font-mono transition-colors"
              title="Create Task"
            >
              <Plus className="w-4 h-4" />
            </button>
          </div>

          {/* Search */}
          <div className="relative">
            <Search className="w-3.5 h-3.5 absolute left-2.5 top-2.5 text-slate-500" />
            <input
              type="text"
              placeholder="Search tasks..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full bg-aura-canvas border border-aura-subtle rounded-lg pl-8 pr-3 py-1.5 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-cyan-500 font-mono"
            />
          </div>

          {/* Status Filter */}
          <select
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="w-full bg-aura-canvas border border-aura-subtle rounded-lg px-2.5 py-1 text-xs text-slate-300 focus:outline-none focus:border-cyan-500 font-mono"
          >
            <option value="ALL">All Statuses</option>
            <option value="IN_PROGRESS">Executing (In Progress)</option>
            <option value="WAITING_APPROVAL">Waiting Approval</option>
            <option value="COMPLETED">Completed</option>
            <option value="FAILED">Failed</option>
            <option value="CANCELLED">Cancelled</option>
          </select>
        </div>

        {/* Task List Items */}
        <div className="flex-1 overflow-y-auto p-2 space-y-1.5">
          {isLoading ? (
            <div className="text-center p-6 text-xs font-mono text-slate-500">
              Loading tasks...
            </div>
          ) : filteredTasks.length > 0 ? (
            filteredTasks.map((t) => {
              const isSelected = selectedTaskId === t.id;
              return (
                <div
                  key={t.id}
                  onClick={() => setSelectedTaskId(t.id)}
                  className={`p-3 rounded-lg border cursor-pointer transition-all ${
                    isSelected
                      ? 'bg-aura-elevated border-cyan-500/40 glow-cyan'
                      : 'bg-aura-canvas/40 border-aura-subtle/40 hover:bg-aura-elevated/50 hover:border-aura-subtle'
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <h4 className="text-xs font-medium text-slate-200 line-clamp-1">
                      {t.title}
                    </h4>
                    <ChevronRight className="w-3.5 h-3.5 text-slate-500 shrink-0" />
                  </div>
                  <div className="mt-2 flex items-center justify-between">
                    <StatusBadge status={t.status} />
                    <span className="text-[10px] font-mono text-slate-500">
                      {new Date(t.created_at).toLocaleTimeString([], {
                        hour: '2-digit',
                        minute: '2-digit',
                      })}
                    </span>
                  </div>
                </div>
              );
            })
          ) : (
            <div className="text-center p-8 text-xs font-mono text-slate-500">
              No tasks found.
            </div>
          )}
        </div>
      </div>

      {/* Right Column: Task DAG & Execution Inspector */}
      <div className="flex-1 bg-aura-surface border border-aura-subtle rounded-xl flex flex-col overflow-hidden">
        {selectedTaskId && activeTask ? (
          <div className="flex-1 flex flex-col h-full overflow-y-auto">
            {/* Header / Meta */}
            <div className="p-5 border-b border-aura-subtle bg-aura-surface/90 sticky top-0 z-10">
              <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <StatusBadge status={activeTask.status} />
                    <span className="text-[11px] font-mono text-slate-500">
                      ID: {activeTask.id}
                    </span>
                  </div>
                  <h2 className="text-lg font-bold text-slate-100 font-sans">
                    {activeTask.title}
                  </h2>
                </div>

                {/* Actions */}
                <div className="flex items-center gap-2">
                  {(activeTask.status === 'IN_PROGRESS' ||
                    activeTask.status === 'PLANNING' ||
                    activeTask.status === 'WAITING_APPROVAL') && (
                    <button
                      onClick={() => cancelMutation.mutate(activeTask.id)}
                      disabled={cancelMutation.isPending}
                      className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-mono text-rose-400 bg-rose-500/10 border border-rose-500/30 rounded-lg hover:bg-rose-500/20 transition-colors"
                    >
                      <Ban className="w-3.5 h-3.5" />
                      <span>ABORT TASK</span>
                    </button>
                  )}
                </div>
              </div>

              {activeTask.objective && (
                <p className="text-xs text-slate-400 mt-2 font-mono bg-aura-canvas/60 p-2.5 rounded-lg border border-aura-subtle/50">
                  <span className="text-cyan-400 font-bold">GOAL: </span>
                  {activeTask.objective}
                </p>
              )}
            </div>

            {/* Visual DAG Execution Steps */}
            <div className="p-5 space-y-4">
              <h3 className="text-xs font-bold font-mono text-slate-300 uppercase tracking-wider flex items-center gap-2">
                <GitFork className="w-4 h-4 text-cyan-400" />
                EXECUTION PLAN & STEP DAG
              </h3>

              {activeTask.steps && activeTask.steps.length > 0 ? (
                <div className="space-y-3 relative before:absolute before:left-5 before:top-4 before:bottom-4 before:w-[2px] before:bg-aura-subtle">
                  {activeTask.steps.map((step, idx) => (
                    <div
                      key={step.id || idx}
                      className="relative pl-10 animate-in fade-in"
                    >
                      {/* Node Bullet */}
                      <div
                        className={`absolute left-3.5 top-3.5 w-3.5 h-3.5 rounded-full border-2 transform -translate-x-1/2 flex items-center justify-center ${
                          step.status === 'COMPLETED'
                            ? 'bg-emerald-500 border-emerald-400'
                            : step.status === 'RUNNING'
                            ? 'bg-cyan-500 border-cyan-300 animate-ping'
                            : step.status === 'WAITING_APPROVAL'
                            ? 'bg-amber-500 border-amber-400 animate-pulse'
                            : step.status === 'FAILED'
                            ? 'bg-rose-500 border-rose-400'
                            : 'bg-aura-elevated border-slate-600'
                        }`}
                      />

                      {/* Step Card */}
                      <div className="p-4 bg-aura-elevated/70 border border-aura-subtle rounded-xl space-y-2.5">
                        <div className="flex items-start justify-between gap-2">
                          <div className="flex items-center gap-2">
                            <span className="text-xs font-mono font-bold text-cyan-400">
                              STEP {step.step_order || idx + 1}:
                            </span>
                            <h4 className="text-xs font-semibold text-slate-200">
                              {step.title}
                            </h4>
                          </div>
                          <div className="flex items-center gap-2">
                            {step.requires_approval && (
                              <RiskBadge level="HIGH" />
                            )}
                            <StatusBadge status={step.status} />
                          </div>
                        </div>

                        {step.tool_name && (
                          <div className="flex items-center gap-2 text-[11px] font-mono text-slate-400">
                            <Code className="w-3.5 h-3.5 text-violet-400" />
                            <span>Tool: <strong className="text-slate-200">{step.tool_name}</strong></span>
                          </div>
                        )}

                        {/* Tool Input Payload Preview (Sanitized) */}
                        {step.tool_input && Object.keys(step.tool_input).length > 0 && (
                          <div className="bg-aura-canvas p-2.5 rounded border border-aura-subtle/50 text-[11px] font-mono text-slate-300 overflow-x-auto">
                            <div className="text-[10px] text-slate-500 mb-1">INPUT PAYLOAD:</div>
                            <pre>{JSON.stringify(step.tool_input, null, 2)}</pre>
                          </div>
                        )}

                        {/* Tool Observation / Output Preview */}
                        {step.tool_output && Object.keys(step.tool_output).length > 0 && (
                          <div className="bg-aura-canvas p-2.5 rounded border border-emerald-500/20 text-[11px] font-mono text-emerald-300 overflow-x-auto">
                            <div className="text-[10px] text-emerald-500 mb-1">OBSERVATION:</div>
                            <pre>{JSON.stringify(step.tool_output, null, 2)}</pre>
                          </div>
                        )}

                        {step.error_message && (
                          <div className="p-2.5 bg-rose-950/40 border border-rose-500/30 rounded text-xs font-mono text-rose-300">
                            <strong>Error:</strong> {step.error_message}
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="p-8 text-center bg-aura-canvas/40 rounded-xl border border-aura-subtle text-xs font-mono text-slate-500">
                  Supervisor Planner has not generated the DAG steps yet or execution is direct.
                </div>
              )}
            </div>
          </div>
        ) : (
          <div className="h-full flex flex-col items-center justify-center text-slate-500 text-xs font-mono p-8 text-center">
            <GitFork className="w-12 h-12 text-slate-700 mb-3" />
            <p>Select a task from the list or create a new autonomous task.</p>
          </div>
        )}
      </div>

      {/* Create Task Modal */}
      {isCreating && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-sm p-4">
          <div className="w-full max-w-md bg-aura-surface border border-aura-strong rounded-xl p-5 space-y-4">
            <h3 className="text-sm font-bold font-mono text-slate-100">
              CREATE NEW AUTONOMOUS TASK
            </h3>

            <div className="space-y-3">
              <div>
                <label className="block text-xs font-mono text-slate-400 mb-1">
                  Task Title
                </label>
                <input
                  type="text"
                  placeholder="e.g. Audit workspace memory"
                  value={newTitle}
                  onChange={(e) => setNewTitle(e.target.value)}
                  className="w-full bg-aura-canvas border border-aura-subtle rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-cyan-500 font-mono"
                />
              </div>

              <div>
                <label className="block text-xs font-mono text-slate-400 mb-1">
                  Objective / Goal
                </label>
                <textarea
                  rows={3}
                  placeholder="Explain the detailed goal..."
                  value={newObjective}
                  onChange={(e) => setNewObjective(e.target.value)}
                  className="w-full bg-aura-canvas border border-aura-subtle rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-cyan-500 font-mono"
                />
              </div>
            </div>

            <div className="flex justify-end gap-2 pt-2 border-t border-aura-subtle">
              <button
                onClick={() => setIsCreating(false)}
                className="px-3 py-1.5 text-xs font-mono text-slate-400 hover:text-slate-200"
              >
                Cancel
              </button>
              <button
                onClick={() =>
                  createMutation.mutate({
                    title: newTitle || 'Untitled Task',
                    objective: newObjective,
                    workspace_id: activeWorkspace?.id || '',
                  })
                }
                disabled={!newTitle.trim() || !activeWorkspace}
                className="px-4 py-1.5 text-xs font-mono font-bold bg-cyan-600 hover:bg-cyan-500 text-white rounded-lg disabled:opacity-50"
              >
                Create Task
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
