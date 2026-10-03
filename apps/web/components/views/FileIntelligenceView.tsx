'use client';

import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  FileText,
  Upload,
  Search,
  RefreshCw,
  Trash2,
  Eye,
  Sparkles,
  Table,
  Code,
  BrainCircuit,
  AlertTriangle,
  CheckCircle2,
  Clock,
  Shield,
  Layers,
  FileCode,
  FileSpreadsheet,
  FileArchive,
  X,
  Plus,
} from 'lucide-react';
import { api } from '../../lib/api';
import { useAuraStore } from '../../lib/store';
import {
  FileRecord,
  FilePreview,
  FileSummary,
  SpreadsheetAnalysis,
  CodebaseAnalysis,
  FileSearchResult,
} from '../../lib/types';

export const FileIntelligenceView: React.FC = () => {
  const { activeWorkspace } = useAuraStore();
  const [files, setFiles] = useState<FileRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<FileSearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);

  // Modals state
  const [previewFile, setPreviewFile] = useState<FilePreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [summaryData, setSummaryData] = useState<FileSummary | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [spreadsheetData, setSpreadsheetData] = useState<SpreadsheetAnalysis | null>(null);
  const [spreadsheetLoading, setSpreadsheetLoading] = useState(false);
  const [codebaseData, setCodebaseData] = useState<CodebaseAnalysis | null>(null);
  const [codebaseLoading, setCodebaseLoading] = useState(false);

  // Memory promotion modal
  const [promoteModalOpen, setPromoteModalOpen] = useState(false);
  const [selectedFileForMemory, setSelectedFileForMemory] = useState<FileRecord | null>(null);
  const [selectedChunkId, setSelectedChunkId] = useState<string | null>(null);
  const [factStatement, setFactStatement] = useState('');
  const [promotingMemory, setPromotingMemory] = useState(false);
  const [memorySuccessMsg, setMemorySuccessMsg] = useState<string | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isDragActive, setIsDragActive] = useState(false);

  const fetchFiles = useCallback(async () => {
    if (!activeWorkspace) return;
    try {
      setLoading(true);
      setError(null);
      const res = await api.files.list({ workspaceId: activeWorkspace.id });
      setFiles(res.items || []);
    } catch (err: any) {
      setError(err.message || 'Failed to load workspace files');
    } finally {
      setLoading(false);
    }
  }, [activeWorkspace]);

  useEffect(() => {
    fetchFiles();
  }, [fetchFiles]);

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const uploadedFiles = e.target.files;
    if (!uploadedFiles || uploadedFiles.length === 0 || !activeWorkspace) return;

    try {
      setUploading(true);
      setError(null);
      for (let i = 0; i < uploadedFiles.length; i++) {
        await api.files.upload(uploadedFiles[i], activeWorkspace.id);
      }
      await fetchFiles();
    } catch (err: any) {
      setError(err.message || 'File upload failed');
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragActive(false);
    if (!e.dataTransfer.files || e.dataTransfer.files.length === 0 || !activeWorkspace) return;

    try {
      setUploading(true);
      setError(null);
      for (let i = 0; i < e.dataTransfer.files.length; i++) {
        await api.files.upload(e.dataTransfer.files[i], activeWorkspace.id);
      }
      await fetchFiles();
    } catch (err: any) {
      setError(err.message || 'File upload failed');
    } finally {
      setUploading(false);
    }
  };

  const handleExtract = async (fileId: string) => {
    if (!activeWorkspace) return;
    try {
      await api.files.extract(fileId, {}, activeWorkspace.id);
      await fetchFiles();
    } catch (err: any) {
      setError(err.message || 'Extraction request failed');
    }
  };

  const handleIndex = async (fileId: string) => {
    if (!activeWorkspace) return;
    try {
      await api.files.index(fileId, true, activeWorkspace.id);
      await fetchFiles();
    } catch (err: any) {
      setError(err.message || 'Indexing request failed');
    }
  };

  const handlePreview = async (fileId: string) => {
    if (!activeWorkspace) return;
    try {
      setPreviewLoading(true);
      const res = await api.files.preview(fileId, activeWorkspace.id);
      setPreviewFile(res);
    } catch (err: any) {
      setError(err.message || 'Failed to preview file');
    } finally {
      setPreviewLoading(false);
    }
  };

  const handleSummary = async (fileId: string) => {
    if (!activeWorkspace) return;
    try {
      setSummaryLoading(true);
      const res = await api.files.summary(fileId, {}, activeWorkspace.id);
      setSummaryData(res);
    } catch (err: any) {
      setError(err.message || 'Failed to synthesize summary');
    } finally {
      setSummaryLoading(false);
    }
  };

  const handleAnalyzeSpreadsheet = async (fileId: string) => {
    if (!activeWorkspace) return;
    try {
      setSpreadsheetLoading(true);
      const res = await api.files.analyzeSpreadsheet(fileId, {}, activeWorkspace.id);
      setSpreadsheetData(res);
    } catch (err: any) {
      setError(err.message || 'Spreadsheet analysis failed');
    } finally {
      setSpreadsheetLoading(false);
    }
  };

  const handleAnalyzeCodebase = async (fileId: string) => {
    if (!activeWorkspace) return;
    try {
      setCodebaseLoading(true);
      const res = await api.files.analyzeCodebase(fileId, {}, activeWorkspace.id);
      setCodebaseData(res);
    } catch (err: any) {
      setError(err.message || 'Codebase analysis failed');
    } finally {
      setCodebaseLoading(false);
    }
  };

  const handleDelete = async (fileId: string) => {
    if (!activeWorkspace || !confirm('Are you sure you want to delete this file and cascade tombstone linked cognitive memories?')) return;
    try {
      await api.files.delete(fileId, activeWorkspace.id);
      await fetchFiles();
    } catch (err: any) {
      setError(err.message || 'Delete operation failed');
    }
  };

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!searchQuery.trim() || !activeWorkspace) return;
    try {
      setSearching(true);
      const res = await api.files.search(searchQuery, { workspaceId: activeWorkspace.id });
      setSearchResults(res.results || []);
      setSearchOpen(true);
    } catch (err: any) {
      setError(err.message || 'Search execution failed');
    } finally {
      setSearching(false);
    }
  };

  const handlePromoteMemorySubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedFileForMemory || !factStatement.trim() || !activeWorkspace) return;

    try {
      setPromotingMemory(true);
      setMemorySuccessMsg(null);
      await api.files.promoteMemory(
        selectedFileForMemory.id,
        {
          fact_statement: factStatement,
          chunk_id: selectedChunkId || undefined,
          tags: ['file_intelligence', selectedFileForMemory.file_extension],
        },
        activeWorkspace.id
      );
      setMemorySuccessMsg('Cognitive memory record successfully created with 11-field provenance lineage.');
      setTimeout(() => {
        setPromoteModalOpen(false);
        setFactStatement('');
        setSelectedChunkId(null);
        setMemorySuccessMsg(null);
      }, 1800);
    } catch (err: any) {
      setError(err.message || 'Failed to promote finding to memory');
    } finally {
      setPromotingMemory(false);
    }
  };

  const getFormatIcon = (ext: string) => {
    const cleanExt = ext.toLowerCase().replace('.', '');
    if (['xlsx', 'csv'].includes(cleanExt)) return <FileSpreadsheet className="w-4 h-4 text-emerald-400" />;
    if (['zip', 'tar', 'gz'].includes(cleanExt)) return <FileArchive className="w-4 h-4 text-amber-400" />;
    if (['py', 'js', 'ts', 'html', 'css', 'sql', 'go', 'rs', 'java', 'c', 'cpp'].includes(cleanExt))
      return <FileCode className="w-4 h-4 text-cyan-400" />;
    return <FileText className="w-4 h-4 text-blue-400" />;
  };

  return (
    <div className="space-y-6">
      {/* Header & Stats */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 bg-aura-surface border border-aura-subtle rounded-lg p-5">
        <div>
          <div className="flex items-center gap-2">
            <Layers className="w-5 h-5 text-cyan-400" />
            <h1 className="text-base font-semibold text-slate-100">Files & Document Intelligence</h1>
            <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
              AURA-604 Governed
            </span>
          </div>
          <p className="text-xs text-slate-400 mt-1">
            Governed multi-format ingestion, structural extraction, 768-dim FastEmbed vector search, and cognitive memory lineage.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={() => fetchFiles()}
            disabled={loading}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium bg-aura-elevated border border-slate-700 text-slate-300 hover:text-slate-100 hover:bg-aura-elevated/80 transition-all"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium bg-cyan-500/20 border border-cyan-500/40 text-cyan-300 hover:bg-cyan-500/30 transition-all glow-cyan"
          >
            <Upload className="w-3.5 h-3.5" />
            {uploading ? 'Uploading...' : 'Upload File'}
          </button>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            className="hidden"
            onChange={handleFileUpload}
          />
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-2.5 p-3.5 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-xs">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          <span>{error}</span>
          <button onClick={() => setError(null)} className="ml-auto text-slate-400 hover:text-slate-200">
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {/* Drag & Drop Upload Zone */}
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setIsDragActive(true);
        }}
        onDragLeave={() => setIsDragActive(false)}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
        className={`border-2 border-dashed rounded-lg p-6 flex flex-col items-center justify-center cursor-pointer transition-all ${
          isDragActive
            ? 'border-cyan-400 bg-cyan-500/10 glow-cyan'
            : 'border-slate-800 hover:border-slate-700 bg-aura-surface/50'
        }`}
      >
        <Upload className={`w-8 h-8 mb-2 ${isDragActive ? 'text-cyan-400' : 'text-slate-500'}`} />
        <p className="text-xs font-medium text-slate-200">
          Drag and drop multi-format documents, spreadsheets, or code archives here
        </p>
        <p className="text-[11px] text-slate-500 mt-1">
          Supports PDF, DOCX, XLSX, PPTX, TXT, MD, CSV, ZIP (Max 50 MB)
        </p>
      </div>

      {/* Search Bar */}
      <form onSubmit={handleSearch} className="flex gap-2">
        <div className="relative flex-1">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search documents via 768-dim hybrid dense semantic + lexical vector search..."
            className="w-full bg-aura-surface border border-aura-subtle rounded-md pl-9 pr-4 py-2 text-xs text-slate-200 placeholder:text-slate-500 focus:outline-none focus:border-cyan-500/50"
          />
        </div>
        <button
          type="submit"
          disabled={searching || !searchQuery.trim()}
          className="px-4 py-2 rounded-md text-xs font-medium bg-cyan-500/20 border border-cyan-500/40 text-cyan-300 hover:bg-cyan-500/30 transition-all disabled:opacity-50"
        >
          {searching ? 'Searching...' : 'Hybrid Search'}
        </button>
      </form>

      {/* Hybrid Search Results Drawer */}
      {searchOpen && (
        <div className="bg-aura-surface border border-aura-subtle rounded-lg p-4 space-y-3">
          <div className="flex items-center justify-between border-b border-slate-800 pb-2">
            <div className="flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-cyan-400" />
              <h3 className="text-xs font-semibold text-slate-200">
                Hybrid Search Results ({searchResults.length} matches)
              </h3>
            </div>
            <button onClick={() => setSearchOpen(false)} className="text-slate-400 hover:text-slate-200">
              <X className="w-3.5 h-3.5" />
            </button>
          </div>

          {searchResults.length === 0 ? (
            <p className="text-xs text-slate-500 py-3">No relevant passages matched the dual acceptance gate.</p>
          ) : (
            <div className="space-y-2.5 max-h-80 overflow-y-auto pr-1">
              {searchResults.map((item, idx) => (
                <div key={idx} className="p-3 rounded-md bg-aura-elevated/40 border border-slate-800 space-y-2">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      {getFormatIcon(item.mime_type)}
                      <span className="text-xs font-medium text-slate-200">{item.original_filename}</span>
                      {item.source_location && Object.keys(item.source_location).length > 0 && (
                        <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-slate-800 text-slate-400">
                          {item.source_location.page ? `p. ${item.source_location.page}` : ''}
                          {item.source_location.sheet ? `Sheet: ${item.source_location.sheet}` : ''}
                          {item.source_location.section ? `§ ${item.source_location.section}` : ''}
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] font-mono text-cyan-400 font-semibold">
                        Score: {(item.hybrid_score * 100).toFixed(1)}%
                      </span>
                      <button
                        onClick={() => {
                          const matchedFile = files.find((f) => f.id === item.file_id);
                          setSelectedFileForMemory(matchedFile || { id: item.file_id, original_filename: item.original_filename, file_extension: 'md' } as any);
                          setSelectedChunkId(item.chunk_id);
                          setFactStatement(item.chunk_text);
                          setPromoteModalOpen(true);
                        }}
                        className="px-2 py-0.5 rounded text-[10px] font-medium bg-purple-500/20 border border-purple-500/40 text-purple-300 hover:bg-purple-500/30 flex items-center gap-1"
                      >
                        <BrainCircuit className="w-2.5 h-2.5" />
                        Promote to Memory
                      </button>
                    </div>
                  </div>
                  <p className="text-xs text-slate-300 bg-black/30 p-2 rounded border border-slate-900 font-mono text-[11px] whitespace-pre-wrap">
                    {item.chunk_text}
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Files Table */}
      <div className="bg-aura-surface border border-aura-subtle rounded-lg overflow-hidden">
        <div className="px-4 py-3 border-b border-slate-800 flex items-center justify-between">
          <span className="text-xs font-semibold text-slate-200">Registered Files ({files.length})</span>
        </div>

        {files.length === 0 ? (
          <div className="py-12 text-center text-slate-500 text-xs">
            No files registered in this workspace. Upload a file above to begin.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs text-slate-300">
              <thead className="bg-aura-elevated/50 text-[11px] font-medium text-slate-400 uppercase tracking-wider border-b border-slate-800">
                <tr>
                  <th className="px-4 py-3">Filename</th>
                  <th className="px-4 py-3">Size</th>
                  <th className="px-4 py-3">Extraction Status</th>
                  <th className="px-4 py-3">Vector Index Status</th>
                  <th className="px-4 py-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {files.map((file) => {
                  const vectorInfo = file.metadata?.vector_index || {};
                  const vectorStatus = vectorInfo.status || 'none';

                  return (
                    <tr key={file.id} className="hover:bg-aura-elevated/30 transition-all">
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2.5">
                          {getFormatIcon(file.file_extension)}
                          <div>
                            <div className="font-medium text-slate-100">{file.original_filename}</div>
                            <div className="text-[10px] font-mono text-slate-500">{file.mime_type}</div>
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-3 font-mono text-slate-400">
                        {(file.size_bytes / 1024).toFixed(1)} KB
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono font-medium ${
                            file.status === 'indexed'
                              ? 'bg-blue-500/10 text-blue-400 border border-blue-500/20'
                              : file.status === 'parsing'
                              ? 'bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 animate-pulse'
                              : file.status === 'failed'
                              ? 'bg-red-500/10 text-red-400 border border-red-500/20'
                              : 'bg-slate-800 text-slate-400'
                          }`}
                        >
                          {file.status === 'indexed' && <CheckCircle2 className="w-2.5 h-2.5" />}
                          {file.status === 'parsing' && <Clock className="w-2.5 h-2.5" />}
                          {file.status.toUpperCase()}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono font-medium ${
                            vectorStatus === 'ready'
                              ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                              : vectorStatus === 'indexing'
                              ? 'bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 animate-pulse'
                              : vectorStatus === 'failed'
                              ? 'bg-red-500/10 text-red-400 border border-red-500/20'
                              : 'bg-slate-800 text-slate-500'
                          }`}
                        >
                          {vectorStatus === 'ready' && <CheckCircle2 className="w-2.5 h-2.5" />}
                          {vectorStatus === 'ready'
                            ? `READY (${vectorInfo.chunks_count || 0} chunks)`
                            : vectorStatus.toUpperCase()}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right">
                        <div className="flex items-center justify-end gap-1.5">
                          <button
                            onClick={() => handlePreview(file.id)}
                            title="Preview Content (Inert)"
                            className="p-1.5 rounded hover:bg-slate-800 text-slate-400 hover:text-slate-200 transition-all"
                          >
                            <Eye className="w-3.5 h-3.5" />
                          </button>
                          <button
                            onClick={() => handleSummary(file.id)}
                            title="Synthesize Executive Summary"
                            className="p-1.5 rounded hover:bg-slate-800 text-purple-400 hover:text-purple-300 transition-all"
                          >
                            <Sparkles className="w-3.5 h-3.5" />
                          </button>
                          {['xlsx', 'csv'].includes(file.file_extension.replace('.', '')) && (
                            <button
                              onClick={() => handleAnalyzeSpreadsheet(file.id)}
                              title="Inspect Spreadsheet Schema"
                              className="p-1.5 rounded hover:bg-slate-800 text-emerald-400 hover:text-emerald-300 transition-all"
                            >
                              <Table className="w-3.5 h-3.5" />
                            </button>
                          )}
                          {['zip', 'py', 'js', 'ts'].includes(file.file_extension.replace('.', '')) && (
                            <button
                              onClick={() => handleAnalyzeCodebase(file.id)}
                              title="Analyze Codebase AST"
                              className="p-1.5 rounded hover:bg-slate-800 text-cyan-400 hover:text-cyan-300 transition-all"
                            >
                              <Code className="w-3.5 h-3.5" />
                            </button>
                          )}
                          <button
                            onClick={() => {
                              setSelectedFileForMemory(file);
                              setFactStatement(`Key findings from document ${file.original_filename}`);
                              setPromoteModalOpen(true);
                            }}
                            title="Promote to Cognitive Memory"
                            className="p-1.5 rounded hover:bg-slate-800 text-blue-400 hover:text-blue-300 transition-all"
                          >
                            <BrainCircuit className="w-3.5 h-3.5" />
                          </button>
                          <button
                            onClick={() => handleIndex(file.id)}
                            title="Index Vectors (FastEmbed)"
                            className="p-1.5 rounded hover:bg-slate-800 text-emerald-400 hover:text-emerald-300 transition-all"
                          >
                            <Layers className="w-3.5 h-3.5" />
                          </button>
                          <button
                            onClick={() => handleDelete(file.id)}
                            title="Delete File"
                            className="p-1.5 rounded hover:bg-red-500/20 text-red-400 hover:text-red-300 transition-all"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Inert Content Preview Modal */}
      {previewFile && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
          <div className="bg-aura-surface border border-aura-subtle rounded-lg max-w-3xl w-full max-h-[85vh] flex flex-col overflow-hidden shadow-2xl">
            <div className="px-5 py-3 border-b border-slate-800 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Shield className="w-4 h-4 text-cyan-400" />
                <span className="text-xs font-semibold text-slate-200">
                  Preview: {previewFile.original_filename}
                </span>
                <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-amber-500/10 text-amber-400 border border-amber-500/20">
                  {previewFile.security_badge}
                </span>
              </div>
              <button onClick={() => setPreviewFile(null)} className="text-slate-400 hover:text-slate-200">
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="p-5 overflow-y-auto flex-1 font-mono text-xs text-slate-300 bg-black/40 whitespace-pre-wrap select-text">
              {previewFile.content || '(No readable textual preview available)'}
            </div>
            {previewFile.is_truncated && (
              <div className="px-5 py-2 bg-amber-500/10 border-t border-amber-500/20 text-[11px] text-amber-400">
                Content preview truncated at 100 KB budget limit.
              </div>
            )}
          </div>
        </div>
      )}

      {/* Document Synthesis / Summary Modal */}
      {summaryData && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
          <div className="bg-aura-surface border border-aura-subtle rounded-lg max-w-2xl w-full max-h-[80vh] flex flex-col overflow-hidden shadow-2xl">
            <div className="px-5 py-3 border-b border-slate-800 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-purple-400" />
                <span className="text-xs font-semibold text-slate-200">Executive Summary: {summaryData.title}</span>
                <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-purple-500/10 text-purple-400 border border-purple-500/20">
                  {summaryData.status}
                </span>
              </div>
              <button onClick={() => setSummaryData(null)} className="text-slate-400 hover:text-slate-200">
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="p-5 overflow-y-auto space-y-4 text-xs">
              <div>
                <h4 className="font-semibold text-slate-300 mb-1">Overview</h4>
                <p className="text-slate-400 leading-relaxed">{summaryData.executive_summary}</p>
              </div>
              {summaryData.key_takeaways && summaryData.key_takeaways.length > 0 && (
                <div>
                  <h4 className="font-semibold text-slate-300 mb-1.5">Key Takeaways</h4>
                  <ul className="list-disc pl-4 space-y-1 text-slate-400">
                    {summaryData.key_takeaways.map((takeaway, i) => (
                      <li key={i}>{takeaway}</li>
                    ))}
                  </ul>
                </div>
              )}
              {summaryData.citations && summaryData.citations.length > 0 && (
                <div>
                  <h4 className="font-semibold text-slate-300 mb-1.5">Source Citations</h4>
                  <div className="flex flex-wrap gap-1.5">
                    {summaryData.citations.map((cite, i) => (
                      <span key={i} className="px-2 py-0.5 rounded text-[10px] font-mono bg-slate-800 text-slate-400">
                        {cite.section || 'Section'} {cite.page ? `(p. ${cite.page})` : ''}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Spreadsheet Analysis Modal */}
      {spreadsheetData && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
          <div className="bg-aura-surface border border-aura-subtle rounded-lg max-w-4xl w-full max-h-[85vh] flex flex-col overflow-hidden shadow-2xl">
            <div className="px-5 py-3 border-b border-slate-800 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Table className="w-4 h-4 text-emerald-400" />
                <span className="text-xs font-semibold text-slate-200">
                  Spreadsheet Schema ({spreadsheetData.total_sheets} Sheets)
                </span>
                {spreadsheetData.has_macros && (
                  <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-amber-500/10 text-amber-400 border border-amber-500/20">
                    VBA Macros Neutralized
                  </span>
                )}
              </div>
              <button onClick={() => setSpreadsheetData(null)} className="text-slate-400 hover:text-slate-200">
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="p-5 overflow-y-auto space-y-5 text-xs">
              {spreadsheetData.sheets.map((sheet, idx) => (
                <div key={idx} className="space-y-2">
                  <div className="flex items-center justify-between text-slate-300 font-medium">
                    <span>Worksheet: {sheet.name}</span>
                    <span className="text-[11px] font-mono text-slate-500">
                      {sheet.row_count} rows × {sheet.column_count} cols ({sheet.formulas_detected} inert formulas)
                    </span>
                  </div>
                  <div className="overflow-x-auto border border-slate-800 rounded bg-black/40">
                    <table className="w-full text-left text-[11px]">
                      <thead className="bg-slate-900 text-slate-400 border-b border-slate-800">
                        <tr>
                          {sheet.columns.map((col, i) => (
                            <th key={i} className="px-3 py-2 font-mono">{col}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-800 text-slate-300">
                        {sheet.sample_rows.map((row, rIdx) => (
                          <tr key={rIdx}>
                            {sheet.columns.map((col, cIdx) => (
                              <td key={cIdx} className="px-3 py-1.5 font-mono">{row[col] || ''}</td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Codebase Analysis Modal */}
      {codebaseData && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
          <div className="bg-aura-surface border border-aura-subtle rounded-lg max-w-3xl w-full max-h-[85vh] flex flex-col overflow-hidden shadow-2xl">
            <div className="px-5 py-3 border-b border-slate-800 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Code className="w-4 h-4 text-cyan-400" />
                <span className="text-xs font-semibold text-slate-200">
                  Codebase Analysis ({codebaseData.total_files} Files)
                </span>
              </div>
              <button onClick={() => setCodebaseData(null)} className="text-slate-400 hover:text-slate-200">
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="p-5 overflow-y-auto space-y-4 text-xs">
              <div>
                <h4 className="font-semibold text-slate-300 mb-1.5">Languages</h4>
                <div className="flex flex-wrap gap-2">
                  {Object.entries(codebaseData.languages).map(([lang, count]) => (
                    <span key={lang} className="px-2 py-0.5 rounded text-[10px] font-mono bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
                      {lang}: {count}
                    </span>
                  ))}
                </div>
              </div>
              {codebaseData.dependencies && codebaseData.dependencies.length > 0 && (
                <div>
                  <h4 className="font-semibold text-slate-300 mb-1.5">Dependencies</h4>
                  <div className="flex flex-wrap gap-1.5">
                    {codebaseData.dependencies.map((dep, i) => (
                      <span key={i} className="px-2 py-0.5 rounded text-[10px] font-mono bg-slate-800 text-slate-400">
                        {dep}
                      </span>
                    ))}
                  </div>
                </div>
              )}
              {codebaseData.symbols && codebaseData.symbols.length > 0 && (
                <div>
                  <h4 className="font-semibold text-slate-300 mb-1.5">AST Symbols Discovered</h4>
                  <div className="max-h-60 overflow-y-auto divide-y divide-slate-800 bg-black/40 rounded border border-slate-800">
                    {codebaseData.symbols.map((sym, i) => (
                      <div key={i} className="p-2 flex items-center justify-between font-mono text-[11px]">
                        <span className="text-cyan-300 font-medium">{sym.name} ({sym.type})</span>
                        <span className="text-slate-500">{sym.file}:{sym.line || 1}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Memory Promotion Modal */}
      {promoteModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
          <form onSubmit={handlePromoteMemorySubmit} className="bg-aura-surface border border-aura-subtle rounded-lg max-w-lg w-full overflow-hidden shadow-2xl">
            <div className="px-5 py-3.5 border-b border-slate-800 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <BrainCircuit className="w-4 h-4 text-purple-400" />
                <span className="text-xs font-semibold text-slate-200">Promote Finding to Cognitive Memory</span>
              </div>
              <button type="button" onClick={() => setPromoteModalOpen(false)} className="text-slate-400 hover:text-slate-200">
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="p-5 space-y-4 text-xs">
              <div className="p-2.5 rounded bg-slate-900 border border-slate-800 text-slate-400 text-[11px] space-y-1 font-mono">
                <div>Source File: {selectedFileForMemory?.original_filename}</div>
                <div>Source Type: file_intelligence (11-field JSONB provenance)</div>
              </div>

              <div>
                <label className="block text-slate-300 font-medium mb-1">Fact Statement</label>
                <textarea
                  rows={4}
                  value={factStatement}
                  onChange={(e) => setFactStatement(e.target.value)}
                  placeholder="Enter the extracted insight or durable fact statement to store in cognitive memory..."
                  className="w-full bg-black/40 border border-slate-800 rounded p-2.5 text-xs text-slate-200 focus:outline-none focus:border-purple-500/50"
                  required
                />
              </div>

              {memorySuccessMsg && (
                <div className="p-2.5 rounded bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 text-xs flex items-center gap-2">
                  <CheckCircle2 className="w-4 h-4 shrink-0" />
                  <span>{memorySuccessMsg}</span>
                </div>
              )}
            </div>
            <div className="px-5 py-3 border-t border-slate-800 flex justify-end gap-2 bg-aura-elevated/40">
              <button
                type="button"
                onClick={() => setPromoteModalOpen(false)}
                className="px-3 py-1.5 rounded text-xs text-slate-400 hover:text-slate-200"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={promotingMemory || !factStatement.trim()}
                className="px-3 py-1.5 rounded text-xs font-medium bg-purple-500/20 border border-purple-500/40 text-purple-300 hover:bg-purple-500/30 disabled:opacity-50 flex items-center gap-1.5"
              >
                <BrainCircuit className="w-3.5 h-3.5" />
                {promotingMemory ? 'Promoting...' : 'Confirm Promotion'}
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
};
