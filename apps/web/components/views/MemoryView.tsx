'use client';

import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { auraApi } from '../../lib/api';
import { useAuraStore } from '../../lib/store';
import {
  BrainCircuit,
  Search,
  Trash2,
  Database,
  Clock,
  Layers,
  Sparkles,
  Loader2,
  Tag,
} from 'lucide-react';

export const MemoryView: React.FC = () => {
  const { activeWorkspace } = useAuraStore();
  const queryClient = useQueryClient();
  const [searchQuery, setSearchQuery] = useState('');
  const [activeSearch, setActiveSearch] = useState('');

  // Memory Records Query (list or semantic search)
  const { data: records, isLoading } = useQuery({
    queryKey: ['memory', activeWorkspace?.id, activeSearch],
    queryFn: () => {
      if (activeSearch.trim()) {
        return auraApi.memory.search(activeSearch.trim(), activeWorkspace?.id, 20);
      }
      return auraApi.memory.list(activeWorkspace?.id, 30);
    },
  });

  // Tombstone Mutation
  const tombstoneMutation = useMutation({
    mutationFn: (id: string) => auraApi.memory.tombstone(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['memory'] });
    },
  });

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setActiveSearch(searchQuery);
  };

  return (
    <div className="space-y-6 animate-in fade-in duration-200">
      {/* Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 p-5 bg-aura-surface border border-aura-subtle rounded-xl">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <BrainCircuit className="w-5 h-5 text-cyan-400" />
            <h1 className="text-base font-bold font-mono text-slate-100 uppercase tracking-wide">
              SEMANTIC MEMORY VAULT
            </h1>
          </div>
          <p className="text-xs text-slate-400">
            FastEmbed + pgvector zero-cost local semantic memory with tombstoning governance.
          </p>
        </div>

        <div className="flex items-center gap-2 text-xs font-mono bg-aura-canvas px-3 py-1.5 rounded-lg border border-aura-subtle">
          <Database className="w-3.5 h-3.5 text-emerald-400" />
          <span className="text-slate-400">EMBEDDINGS: </span>
          <span className="text-emerald-400 font-bold">FastEmbed (Local)</span>
        </div>
      </div>

      {/* Semantic Search Form */}
      <form onSubmit={handleSearch} className="flex gap-2">
        <div className="relative flex-1">
          <Search className="w-4 h-4 absolute left-3 top-3 text-slate-500" />
          <input
            type="text"
            placeholder="Semantic vector search across memory vault (e.g., 'API authentication rules', 'duckduckgo endpoints')..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full bg-aura-surface border border-aura-subtle rounded-xl pl-9 pr-4 py-2.5 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-cyan-500 font-mono"
          />
        </div>
        <button
          type="submit"
          className="px-5 py-2.5 bg-cyan-600 hover:bg-cyan-500 text-white font-mono text-xs font-bold rounded-xl shadow-lg glow-cyan flex items-center gap-1.5 transition-all"
        >
          <Sparkles className="w-3.5 h-3.5" />
          <span>SEARCH</span>
        </button>
        {activeSearch && (
          <button
            type="button"
            onClick={() => {
              setSearchQuery('');
              setActiveSearch('');
            }}
            className="px-3 py-2.5 bg-aura-elevated text-slate-400 hover:text-slate-200 rounded-xl text-xs font-mono"
          >
            Clear
          </button>
        )}
      </form>

      {/* Memory Record Grid */}
      <div className="space-y-3">
        <div className="flex items-center justify-between text-xs font-mono text-slate-400">
          <span>
            {activeSearch ? `SEARCH RESULTS FOR "${activeSearch}"` : 'RECENT MEMORY RECORDS'}
          </span>
          <span>{records?.length || 0} Records</span>
        </div>

        {isLoading ? (
          <div className="p-8 text-center text-xs font-mono text-slate-500 bg-aura-surface rounded-xl border border-aura-subtle">
            Searching semantic vector memory...
          </div>
        ) : records && records.length > 0 ? (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {records.map((rec) => (
              <div
                key={rec.id}
                className="bg-aura-surface border border-aura-subtle rounded-xl p-4 flex flex-col justify-between space-y-3 hover:border-aura-strong transition-all"
              >
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono bg-violet-500/10 text-violet-400 border border-violet-500/20">
                      <Tag className="w-3 h-3" />
                      {rec.memory_type || 'SEMANTIC'}
                    </span>
                    <span className="text-[10px] font-mono text-slate-500">
                      {new Date(rec.created_at).toLocaleDateString()}
                    </span>
                  </div>

                  <p className="text-xs text-slate-200 font-mono leading-relaxed bg-aura-canvas/50 p-2.5 rounded-lg border border-aura-subtle/40">
                    {rec.content}
                  </p>
                </div>

                <div className="flex items-center justify-between pt-2 border-t border-aura-subtle/50 text-[11px] font-mono text-slate-500">
                  <span className="truncate max-w-[200px]">
                    Source: {rec.source || 'SYSTEM'}
                  </span>
                  <button
                    onClick={() => tombstoneMutation.mutate(rec.id)}
                    disabled={tombstoneMutation.isPending}
                    className="flex items-center gap-1 text-slate-400 hover:text-rose-400 transition-colors p-1"
                    title="Tombstone Memory Record"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                    <span>TOMBSTONE</span>
                  </button>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="p-8 text-center bg-aura-surface/50 border border-aura-subtle rounded-xl text-xs font-mono text-slate-500">
            No memory records found.
          </div>
        )}
      </div>
    </div>
  );
};
