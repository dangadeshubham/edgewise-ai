import React, { useState, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  FileText,
  Upload,
  RefreshCw,
  Layers,
  Trash2,
  X,
} from 'lucide-react'
import { api } from '../services/api'
import type { DocumentResponse } from '../types'
import { StatusBadge } from '../components/common/StatusBadge'
import { LoadingState } from '../components/common/LoadingState'
import { EmptyState } from '../components/common/EmptyState'
import { ErrorState } from '../components/common/ErrorState'
import { Pagination } from '../components/common/Pagination'
import { ConfirmDialog } from '../components/common/ConfirmDialog'

export const DocumentsPage: React.FC = () => {
  const queryClient = useQueryClient()
  const [page, setPage] = useState(1)
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null)
  const [docToDelete, setDocToDelete] = useState<DocumentResponse | null>(null)
  const [isDragOver, setIsDragOver] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Query documents list
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['documents', page],
    queryFn: () => api.listDocuments(page, 15),
    refetchInterval: 10000,
  })

  // Query selected document details
  const { data: detailData, isLoading: detailLoading } = useQuery({
    queryKey: ['documentDetail', selectedDocId],
    queryFn: () => (selectedDocId ? api.getDocument(selectedDocId) : null),
    enabled: !!selectedDocId,
  })

  // Upload Mutation
  const uploadMutation = useMutation({
    mutationFn: (file: File) => api.uploadDocument(file),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents'] })
      queryClient.invalidateQueries({ queryKey: ['dashboardMetrics'] })
    },
  })

  // Reindex Mutation
  const reindexMutation = useMutation({
    mutationFn: (id: string) => api.reindexDocument(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents'] })
      queryClient.invalidateQueries({ queryKey: ['documentDetail', selectedDocId] })
    },
  })

  // Delete Mutation
  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.deleteDocument(id),
    onSuccess: () => {
      setDocToDelete(null)
      if (selectedDocId === docToDelete?.id) setSelectedDocId(null)
      queryClient.invalidateQueries({ queryKey: ['documents'] })
      queryClient.invalidateQueries({ queryKey: ['dashboardMetrics'] })
    },
  })

  const handleFileDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragOver(false)
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      uploadMutation.mutate(e.dataTransfer.files[0])
    }
  }

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      uploadMutation.mutate(e.target.files[0])
    }
  }

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-slate-100 tracking-tight">Document Vault</h1>
          <p className="text-xs text-slate-400 mt-0.5">
            Ingest, chunk, and embed technical manuals and specifications into local Qdrant Edge memory.
          </p>
        </div>

        <button
          onClick={() => fileInputRef.current?.click()}
          disabled={uploadMutation.isPending}
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-sky-500 hover:bg-sky-400 text-slate-950 text-xs font-semibold shadow-md shadow-sky-500/20 transition-all disabled:opacity-50"
        >
          <Upload className="w-4 h-4" />
          <span>{uploadMutation.isPending ? 'Uploading...' : 'Upload File'}</span>
        </button>
        <input
          ref={fileInputRef}
          type="file"
          className="hidden"
          accept=".pdf,.txt,.md,.json,.docx"
          onChange={handleFileSelect}
        />
      </div>

      {/* Drag & Drop Upload Zone */}
      <div
        onDragOver={(e) => {
          e.preventDefault()
          setIsDragOver(true)
        }}
        onDragLeave={() => setIsDragOver(false)}
        onDrop={handleFileDrop}
        onClick={() => fileInputRef.current?.click()}
        className={`border-2 border-dashed rounded-xl p-6 text-center cursor-pointer transition-all ${
          isDragOver
            ? 'border-sky-400 bg-sky-500/10'
            : 'border-white/10 bg-industrial-900/40 hover:border-white/20'
        }`}
      >
        <Upload className="w-6 h-6 text-slate-400 mx-auto mb-2" />
        <p className="text-xs font-medium text-slate-200">
          Drop technical manuals or specifications here, or click to browse
        </p>
        <p className="text-[10px] font-mono text-slate-500 mt-1">
          Supported: PDF, TXT, MD, JSON, DOCX (Max 50MB)
        </p>
        {uploadMutation.isPending && (
          <div className="mt-3 text-xs font-mono text-sky-400 flex items-center justify-center gap-2">
            <RefreshCw className="w-3.5 h-3.5 animate-spin" />
            <span>Chunking document and computing vector embeddings...</span>
          </div>
        )}
      </div>

      {/* Upload Error Banner */}
      {uploadMutation.isError && (
        <div className="p-3.5 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs flex items-center justify-between font-mono">
          <span>{uploadMutation.error instanceof Error ? uploadMutation.error.message : 'Document upload failed.'}</span>
          <button
            type="button"
            onClick={() => uploadMutation.reset()}
            className="text-slate-400 hover:text-slate-200 ml-2"
          >
            ✕
          </button>
        </div>
      )}

      {/* Main Content Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Documents Table */}
        <div className="lg:col-span-2 bg-industrial-900/80 border border-white/10 rounded-xl overflow-hidden shadow-xl flex flex-col justify-between">
          <div>
            <div className="px-5 py-4 border-b border-white/10 flex items-center justify-between">
              <span className="text-xs font-semibold text-slate-200 uppercase tracking-wider font-mono">
                Indexed Documents ({data?.total ?? 0})
              </span>
              <button
                onClick={() => refetch()}
                className="text-slate-400 hover:text-slate-200 text-xs flex items-center gap-1"
              >
                <RefreshCw className="w-3.5 h-3.5" /> Refresh
              </button>
            </div>

            {isLoading ? (
              <LoadingState title="Loading Document Vault" />
            ) : error ? (
              <div className="p-6">
                <ErrorState message={error instanceof Error ? error.message : 'Failed to load documents'} onRetry={() => refetch()} />
              </div>
            ) : !data || data.items.length === 0 ? (
              <EmptyState
                icon={<FileText className="w-8 h-8 text-slate-500" />}
                title="No Documents Uploaded"
                description="Upload an industrial manual or PDF to begin semantic indexing."
              />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse text-xs font-mono">
                  <thead>
                    <tr className="border-b border-white/10 bg-black/20 text-slate-400">
                      <th className="py-2.5 px-4 font-medium">Filename</th>
                      <th className="py-2.5 px-4 font-medium">Status</th>
                      <th className="py-2.5 px-4 font-medium">Chunks</th>
                      <th className="py-2.5 px-4 font-medium">Size</th>
                      <th className="py-2.5 px-4 font-medium">Uploaded</th>
                      <th className="py-2.5 px-4 font-medium text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/5">
                    {data.items.map((doc) => (
                      <tr
                        key={doc.id}
                        onClick={() => setSelectedDocId(doc.id)}
                        className={`cursor-pointer transition-colors ${
                          selectedDocId === doc.id
                            ? 'bg-sky-500/10 text-sky-200'
                            : 'hover:bg-white/5 text-slate-300'
                        }`}
                      >
                        <td className="py-3 px-4 font-semibold text-slate-100 truncate max-w-[200px]" title={doc.filename}>
                          {doc.filename}
                        </td>
                        <td className="py-3 px-4">
                          <StatusBadge status={doc.status} size="sm" />
                        </td>
                        <td className="py-3 px-4 text-slate-300">
                          {doc.chunk_count}
                        </td>
                        <td className="py-3 px-4 text-slate-400">
                          {formatSize(doc.file_size_bytes)}
                        </td>
                        <td className="py-3 px-4 text-slate-400">
                          {new Date(doc.created_at).toLocaleDateString()}
                        </td>
                        <td className="py-3 px-4 text-right" onClick={(e) => e.stopPropagation()}>
                          <button
                            onClick={() => setDocToDelete(doc)}
                            className="p-1 rounded text-slate-500 hover:text-rose-400 hover:bg-rose-500/10 transition-colors"
                            title="Delete Document"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {data && (
            <Pagination
              currentPage={data.page}
              totalPages={data.pages}
              totalItems={data.total}
              pageSize={data.page_size}
              onPageChange={(p) => setPage(p)}
            />
          )}
        </div>

        {/* Document Detail & Chunks Viewer */}
        <div className="bg-industrial-900/80 border border-white/10 rounded-xl p-5 shadow-xl flex flex-col justify-between">
          {!selectedDocId ? (
            <div className="h-full flex flex-col items-center justify-center text-center p-8 text-slate-500 font-mono text-xs">
              <Layers className="w-8 h-8 mb-2 opacity-40" />
              <span>Select any document from the list to inspect chunks, hashes, and vector IDs.</span>
            </div>
          ) : detailLoading ? (
            <LoadingState title="Loading Document Chunks..." />
          ) : !detailData ? (
            <ErrorState message="Document details could not be retrieved." />
          ) : (
            <div className="space-y-4">
              <div className="flex items-start justify-between border-b border-white/10 pb-3">
                <div>
                  <h3 className="text-sm font-bold text-slate-100 truncate max-w-[200px]" title={detailData.document.filename}>
                    {detailData.document.filename}
                  </h3>
                  <div className="text-[10px] font-mono text-slate-400 mt-0.5">
                    Hash: <span className="text-slate-300">{detailData.document.content_hash.substring(0, 16)}...</span>
                  </div>
                </div>
                <button
                  onClick={() => setSelectedDocId(null)}
                  className="text-slate-500 hover:text-slate-300 p-1"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>

              {/* Action Buttons */}
              <div className="flex gap-2">
                <button
                  onClick={() => reindexMutation.mutate(detailData.document.id)}
                  disabled={reindexMutation.isPending}
                  className="flex-1 py-1.5 px-3 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-xs font-mono text-slate-300 flex items-center justify-center gap-1.5 transition-colors"
                >
                  <RefreshCw className={`w-3 h-3 ${reindexMutation.isPending ? 'animate-spin' : ''}`} />
                  <span>{reindexMutation.isPending ? 'Reindexing...' : 'Reindex Vectors'}</span>
                </button>
              </div>

              {/* Chunks List */}
              <div className="space-y-2">
                <div className="text-[10px] font-mono uppercase tracking-wider text-slate-400">
                  Extracted Chunks ({detailData.chunks.length})
                </div>
                <div className="max-h-[380px] overflow-y-auto space-y-2 pr-1 font-mono text-xs">
                  {detailData.chunks.map((chk) => (
                    <div
                      key={chk.id}
                      className="p-3 rounded-lg bg-black/40 border border-white/5 space-y-1.5"
                    >
                      <div className="flex items-center justify-between text-[10px] text-slate-400">
                        <span>Chunk #{chk.chunk_index}</span>
                        <span className="text-emerald-400 font-bold">
                          {chk.has_embedding ? '✓ Embedded' : 'Missing Vector'}
                        </span>
                      </div>
                      <p className="text-[11px] text-slate-300 line-clamp-3 leading-relaxed">
                        {chk.content_preview}
                      </p>
                      <div className="text-[9px] text-slate-500 truncate">
                        Pt: {chk.vector_point_id || 'unassigned'}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Delete Confirmation Dialog */}
      <ConfirmDialog
        isOpen={!!docToDelete}
        title="Delete Document"
        message={`Are you sure you want to permanently delete '${docToDelete?.filename}'? This will remove all associated chunks and Edge memory representations.`}
        details={`Document ID: ${docToDelete?.id}\nChunks: ${docToDelete?.chunk_count}`}
        confirmText="Delete Document"
        isDestructive
        isLoading={deleteMutation.isPending}
        onConfirm={() => docToDelete && deleteMutation.mutate(docToDelete.id)}
        onCancel={() => setDocToDelete(null)}
      />
    </div>
  )
}
