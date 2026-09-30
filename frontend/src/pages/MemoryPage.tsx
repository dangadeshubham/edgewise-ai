import React, { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Database, Eye, X } from 'lucide-react'
import { api } from '../services/api'
import type { MemoryRecordResponse } from '../types'
import { StatusBadge } from '../components/common/StatusBadge'
import { LoadingState } from '../components/common/LoadingState'
import { EmptyState } from '../components/common/EmptyState'
import { ErrorState } from '../components/common/ErrorState'
import { Pagination } from '../components/common/Pagination'
import { SearchBar } from '../components/common/SearchBar'
import { formatDateTime } from '../utils/date'

export const MemoryPage: React.FC = () => {
  const [page, setPage] = useState(1)
  const [searchQuery, setSearchQuery] = useState('')
  const [sensitivityFilter, setSensitivityFilter] = useState('')
  const [syncStatusFilter, setSyncStatusFilter] = useState('')
  const [selectedRecord, setSelectedRecord] = useState<MemoryRecordResponse | null>(null)

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['memory', page, searchQuery, sensitivityFilter, syncStatusFilter],
    queryFn: () =>
      api.listMemory(
        page,
        20,
        searchQuery || undefined,
        sensitivityFilter || undefined,
        syncStatusFilter || undefined
      ),
    refetchInterval: 15000,
  })

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-xl font-bold text-slate-100 tracking-tight">Memory Explorer</h1>
        <p className="text-xs text-slate-400 mt-0.5">
          Browse and inspect individual knowledge units, revision numbers, vector points, and placement policies.
        </p>
      </div>

      {/* Search & Filters Bar */}
      <div className="flex flex-col sm:flex-row gap-3 items-center justify-between bg-industrial-900/60 p-3 rounded-xl border border-white/10">
        <SearchBar
          value={searchQuery}
          onChange={(q) => {
            setSearchQuery(q)
            setPage(1)
          }}
          placeholder="Filter memory by content keywords or hash..."
          className="w-full sm:w-96"
        />

        <div className="flex items-center gap-2 w-full sm:w-auto font-mono text-xs">
          <select
            value={sensitivityFilter}
            onChange={(e) => {
              setSensitivityFilter(e.target.value)
              setPage(1)
            }}
            className="bg-industrial-900 border border-white/10 rounded-lg px-2.5 py-2 text-slate-300 focus:outline-none focus:border-sky-500/50"
          >
            <option value="">All Sensitivities</option>
            <option value="public">Public</option>
            <option value="internal">Internal</option>
            <option value="confidential">Confidential (Local Only)</option>
            <option value="restricted">Restricted (Local Only)</option>
          </select>

          <select
            value={syncStatusFilter}
            onChange={(e) => {
              setSyncStatusFilter(e.target.value)
              setPage(1)
            }}
            className="bg-industrial-900 border border-white/10 rounded-lg px-2.5 py-2 text-slate-300 focus:outline-none focus:border-sky-500/50"
          >
            <option value="">All Sync States</option>
            <option value="pending">Pending</option>
            <option value="synced">Synced with Cloud</option>
            <option value="conflict">Conflict</option>
            <option value="local_only">Local Only</option>
          </select>
        </div>
      </div>

      {/* Memory Records Table */}
      <div className="bg-industrial-900/80 border border-white/10 rounded-xl overflow-hidden shadow-xl flex flex-col justify-between">
        <div>
          {isLoading ? (
            <LoadingState title="Loading Knowledge Units..." />
          ) : error ? (
            <div className="p-6">
              <ErrorState
                message={error instanceof Error ? error.message : 'Failed to query memory records'}
                onRetry={() => refetch()}
              />
            </div>
          ) : !data || data.items.length === 0 ? (
            <EmptyState
              icon={<Database className="w-8 h-8 text-slate-500" />}
              title="No Memory Records Found"
              description="No knowledge records match the current filter or search criteria."
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse text-xs font-mono">
                <thead>
                  <tr className="border-b border-white/10 bg-black/20 text-slate-400">
                    <th className="py-2.5 px-4 font-medium">Record ID</th>
                    <th className="py-2.5 px-4 font-medium">Type</th>
                    <th className="py-2.5 px-4 font-medium">Content Preview</th>
                    <th className="py-2.5 px-4 font-medium">Revision</th>
                    <th className="py-2.5 px-4 font-medium">Sensitivity</th>
                    <th className="py-2.5 px-4 font-medium">Sync Status</th>
                    <th className="py-2.5 px-4 font-medium text-right">Inspect</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {data.items.map((rec) => (
                    <tr
                      key={rec.id}
                      onClick={() => setSelectedRecord(rec)}
                      className="hover:bg-white/5 cursor-pointer text-slate-300 transition-colors"
                    >
                      <td className="py-3 px-4 font-bold text-slate-100 truncate max-w-[140px]" title={rec.id}>
                        {rec.id.substring(0, 13)}...
                      </td>
                      <td className="py-3 px-4 uppercase text-slate-400">
                        {rec.record_type}
                      </td>
                      <td className="py-3 px-4 font-sans text-slate-300 truncate max-w-xs" title={rec.content}>
                        {rec.content}
                      </td>
                      <td className="py-3 px-4 text-sky-400 font-bold">
                        rev {rec.revision}
                      </td>
                      <td className="py-3 px-4">
                        <span
                          className={`px-2 py-0.5 rounded text-[10px] uppercase font-bold ${
                            ['confidential', 'restricted'].includes(rec.sensitivity.toLowerCase())
                              ? 'bg-rose-500/15 text-rose-400 border border-rose-500/30'
                              : 'bg-slate-700/30 text-slate-300'
                          }`}
                        >
                          {rec.sensitivity}
                        </span>
                      </td>
                      <td className="py-3 px-4">
                        <StatusBadge status={rec.sync_status} size="sm" />
                      </td>
                      <td className="py-3 px-4 text-right">
                        <button
                          onClick={() => setSelectedRecord(rec)}
                          className="p-1.5 rounded text-slate-400 hover:text-sky-300 hover:bg-sky-500/10 transition-colors"
                        >
                          <Eye className="w-3.5 h-3.5" />
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

      {/* Record Detail Modal */}
      {selectedRecord && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="fixed inset-0 bg-black/80 backdrop-blur-sm" onClick={() => setSelectedRecord(null)} />
          <div className="relative bg-industrial-900 border border-white/10 rounded-xl max-w-2xl w-full p-6 shadow-2xl z-10 space-y-4">
            <div className="flex items-start justify-between border-b border-white/10 pb-3">
              <div>
                <div className="flex items-center gap-2">
                  <h3 className="text-base font-bold text-slate-100 font-mono">
                    Record: {selectedRecord.id}
                  </h3>
                  <StatusBadge status={selectedRecord.sync_status} size="sm" />
                </div>
                <div className="text-[11px] font-mono text-slate-400 mt-1">
                  Revision {selectedRecord.revision} • Sensitivity: {selectedRecord.sensitivity} • Origin: {selectedRecord.origin_device || selectedRecord.device_id}
                </div>
              </div>
              <button
                onClick={() => setSelectedRecord(null)}
                className="text-slate-500 hover:text-slate-300 p-1"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Content Textarea Display */}
            <div>
              <label className="text-[10px] font-mono text-slate-400 uppercase tracking-wider block mb-1">
                Full Record Content
              </label>
              <div className="p-3 bg-black/50 border border-white/10 rounded-lg text-xs font-mono text-slate-200 leading-relaxed max-h-64 overflow-y-auto whitespace-pre-wrap">
                {selectedRecord.content}
              </div>
            </div>

            {/* Metadata Grid */}
            <div className="grid grid-cols-2 gap-3 text-xs font-mono p-3 bg-black/30 rounded-lg border border-white/5">
              <div>
                <span className="text-slate-500 block">Content Hash:</span>
                <span className="text-slate-300 break-all">{selectedRecord.content_hash}</span>
              </div>
              <div>
                <span className="text-slate-500 block">Vector Point ID:</span>
                <span className="text-sky-400 break-all">{selectedRecord.vector_point_id || 'Not embedded'}</span>
              </div>
              <div>
                <span className="text-slate-500 block">Created Timestamp:</span>
                <span className="text-slate-300">{formatDateTime(selectedRecord.created_at)}</span>
              </div>
              <div>
                <span className="text-slate-500 block">Last Updated:</span>
                <span className="text-slate-300">{formatDateTime(selectedRecord.updated_at)}</span>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
