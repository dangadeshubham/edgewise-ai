import React, { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  RefreshCw,
  Cloud,
  CloudOff,
  AlertOctagon,
  Clock,
  CheckCircle2,
  Eye,
} from 'lucide-react'
import { api } from '../services/api'
import type { SyncQueueItem } from '../types'
import { StatusBadge } from '../components/common/StatusBadge'
import { LoadingState } from '../components/common/LoadingState'
import { EmptyState } from '../components/common/EmptyState'
import { Pagination } from '../components/common/Pagination'
import { formatTime, formatDate, formatDateTime } from '../utils/date'

export const SyncPage: React.FC = () => {
  const queryClient = useQueryClient()
  const [queuePage, setQueuePage] = useState(1)
  const [historyPage, setHistoryPage] = useState(1)
  const [selectedQueueItem, setSelectedQueueItem] = useState<SyncQueueItem | null>(null)

  // Status Query
  const { data: status } = useQuery({
    queryKey: ['syncStatus'],
    queryFn: api.getSyncStatus,
    refetchInterval: 10000,
  })

  // Queue Query
  const { data: queueData, isLoading: queueLoading } = useQuery({
    queryKey: ['syncQueue', queuePage],
    queryFn: () => api.getSyncQueue(queuePage, 10),
    refetchInterval: 10000,
  })

  // History Query
  const { data: historyData, isLoading: historyLoading } = useQuery({
    queryKey: ['syncHistory', historyPage],
    queryFn: () => api.getSyncHistory(historyPage, 10),
    refetchInterval: 15000,
  })

  // Real Sync Run Mutation
  const syncMutation = useMutation({
    mutationFn: () => api.runSync(20, true),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['syncStatus'] })
      queryClient.invalidateQueries({ queryKey: ['syncQueue'] })
      queryClient.invalidateQueries({ queryKey: ['syncHistory'] })
      queryClient.invalidateQueries({ queryKey: ['dashboardMetrics'] })
    },
  })

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-slate-100 tracking-tight">Synchronization Center</h1>
          <p className="text-xs text-slate-400 mt-0.5">
            Durable SQLite synchronization queue and real bidirectional Qdrant Server pipeline.
          </p>
        </div>

        <button
          onClick={() => syncMutation.mutate()}
          disabled={syncMutation.isPending}
          className="flex items-center gap-2 px-4 py-2.5 rounded-lg bg-sky-500 hover:bg-sky-400 text-slate-950 text-xs font-semibold shadow-md shadow-sky-500/20 transition-all disabled:opacity-50"
        >
          <RefreshCw className={`w-4 h-4 ${syncMutation.isPending ? 'animate-spin' : ''}`} />
          <span>{syncMutation.isPending ? 'Executing Sync Cycle...' : 'SYNC NOW'}</span>
        </button>
      </div>

      {/* Sync Execution Feedback Banner */}
      {syncMutation.data && (
        <div className="p-4 rounded-xl bg-sky-500/10 border border-sky-500/30 text-sky-200 text-xs font-mono flex items-center justify-between">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-400" />
            <span>
              Sync Cycle Completed in {(syncMutation.data.duration_ms ?? 0).toFixed(0)}ms: Uploaded {syncMutation.data.uploaded ?? 0}, Deleted {syncMutation.data.deleted ?? 0}, Failures {syncMutation.data.failed_count ?? 0}
            </span>
          </div>
          <span className="text-[10px] text-slate-400">
            {syncMutation.data.snapshot_applied ? 'Cloud Snapshot Ingested' : 'Cloud Unchanged'}
          </span>
        </div>
      )}

      {/* Status Highlights Grid */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        {/* Remote Server Reachability */}
        <div className="p-4 rounded-xl bg-industrial-900/80 border border-white/10 flex items-center justify-between">
          <div>
            <span className="text-[10px] font-mono uppercase tracking-wider text-slate-400 block">
              Qdrant Server
            </span>
            <div className="text-sm font-bold font-mono text-slate-200 mt-1">
              {status?.cloud_available ? 'Connected' : 'Unavailable'}
            </div>
            <span className="text-[10px] font-mono text-slate-500 truncate block max-w-[150px]" title={status?.cloud_url || ''}>
              {status?.cloud_url || 'http://localhost:6333'}
            </span>
          </div>
          <div className={`p-2 rounded-lg ${status?.cloud_available ? 'bg-emerald-500/15 text-emerald-400' : 'bg-rose-500/15 text-rose-400'}`}>
            {status?.cloud_available ? <Cloud className="w-5 h-5" /> : <CloudOff className="w-5 h-5" />}
          </div>
        </div>

        {/* Queue Backlog */}
        <div className="p-4 rounded-xl bg-industrial-900/80 border border-white/10 flex items-center justify-between">
          <div>
            <span className="text-[10px] font-mono uppercase tracking-wider text-slate-400 block">
              Pending Queue
            </span>
            <div className="text-xl font-bold font-mono text-sky-400 mt-1">
              {status?.pending_count ?? 0}
            </div>
            <span className="text-[10px] text-slate-500 font-mono">
              Processing: {status?.processing_count ?? 0}
            </span>
          </div>
          <div className="p-2 rounded-lg bg-sky-500/15 text-sky-400">
            <RefreshCw className="w-5 h-5" />
          </div>
        </div>

        {/* Failed / Terminal Items */}
        <div className="p-4 rounded-xl bg-industrial-900/80 border border-white/10 flex items-center justify-between">
          <div>
            <span className="text-[10px] font-mono uppercase tracking-wider text-slate-400 block">
              Failed Retries
            </span>
            <div className={`text-xl font-bold font-mono mt-1 ${status?.failed_count ? 'text-rose-400' : 'text-slate-200'}`}>
              {status?.failed_count ?? 0}
            </div>
            <span className="text-[10px] text-slate-500 font-mono">
              Dead Letter: {status?.dead_letter_count ?? 0}
            </span>
          </div>
          <div className="p-2 rounded-lg bg-rose-500/15 text-rose-400">
            <AlertOctagon className="w-5 h-5" />
          </div>
        </div>

        {/* Last Successful Sync */}
        <div className="p-4 rounded-xl bg-industrial-900/80 border border-white/10 flex items-center justify-between">
          <div>
            <span className="text-[10px] font-mono uppercase tracking-wider text-slate-400 block">
              Last Cloud Sync
            </span>
            <div className="text-xs font-mono font-semibold text-slate-200 mt-1">
              {formatTime(status?.last_cloud_sync_time, 'Pending initial')}
            </div>
            <span className="text-[10px] text-slate-500 font-mono">
              {status?.last_cloud_sync_time
                ? formatDate(status.last_cloud_sync_time)
                : 'Offline queue active'}
            </span>
          </div>
          <div className="p-2 rounded-lg bg-white/5 text-slate-400">
            <Clock className="w-5 h-5" />
          </div>
        </div>
      </div>

      {/* Durable Sync Queue Table */}
      <div className="bg-industrial-900/80 border border-white/10 rounded-xl overflow-hidden shadow-xl">
        <div className="px-5 py-4 border-b border-white/10 flex items-center justify-between">
          <div>
            <h2 className="text-xs font-semibold text-slate-200 uppercase tracking-wider font-mono">
              Active Sync Queue (SQLite Durable Queue)
            </h2>
            <p className="text-[11px] text-slate-400 mt-0.5">
              Tasks waiting for Qdrant Server synchronization with exponential backoff.
            </p>
          </div>
          <span className="text-xs font-mono text-slate-400">{queueData?.total ?? 0} items</span>
        </div>

        {queueLoading ? (
          <LoadingState title="Loading Sync Queue..." />
        ) : !queueData || queueData.items.length === 0 ? (
          <EmptyState
            icon={<CheckCircle2 className="w-8 h-8 text-emerald-400" />}
            title="Sync Queue Clean"
            description="All local records and chunks are in sync with Qdrant Server."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse text-xs font-mono">
              <thead>
                <tr className="border-b border-white/10 bg-black/20 text-slate-400">
                  <th className="py-2.5 px-4 font-medium">Record ID</th>
                  <th className="py-2.5 px-4 font-medium">Entity</th>
                  <th className="py-2.5 px-4 font-medium">Operation</th>
                  <th className="py-2.5 px-4 font-medium">Status</th>
                  <th className="py-2.5 px-4 font-medium">Revision</th>
                  <th className="py-2.5 px-4 font-medium">Retries</th>
                  <th className="py-2.5 px-4 font-medium">Queued At</th>
                  <th className="py-2.5 px-4 font-medium text-right">Details</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {queueData.items.map((item) => (
                  <tr
                    key={item.id}
                    onClick={() => setSelectedQueueItem(item)}
                    className="hover:bg-white/5 cursor-pointer text-slate-300 transition-colors"
                  >
                    <td className="py-3 px-4 font-bold text-slate-100 truncate max-w-[130px]" title={item.record_id || (item as any).entity_id || item.id}>
                      {(item.record_id || (item as any).entity_id || item.id || '').substring(0, 12)}...
                    </td>
                    <td className="py-3 px-4 text-slate-400 uppercase">{item.record_type || (item as any).entity_type}</td>
                    <td className="py-3 px-4 font-bold text-sky-400 uppercase">{item.operation}</td>
                    <td className="py-3 px-4">
                      <StatusBadge status={item.status} size="sm" />
                    </td>
                    <td className="py-3 px-4 text-slate-300">rev {item.revision ?? 1}</td>
                    <td className="py-3 px-4 text-slate-400">
                      {item.retry_count} / {item.max_retries}
                    </td>
                    <td className="py-3 px-4 text-slate-400">
                      {formatTime(item.created_at)}
                    </td>
                    <td className="py-3 px-4 text-right">
                      <button
                        onClick={() => setSelectedQueueItem(item)}
                        className="p-1 rounded text-slate-400 hover:text-sky-300 hover:bg-sky-500/10"
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

        {queueData && (
          <Pagination
            currentPage={queueData.page}
            totalPages={queueData.pages}
            totalItems={queueData.total}
            pageSize={queueData.page_size}
            onPageChange={(p) => setQueuePage(p)}
          />
        )}
      </div>

      {/* Sync History Table */}
      <div className="bg-industrial-900/80 border border-white/10 rounded-xl overflow-hidden shadow-xl">
        <div className="px-5 py-4 border-b border-white/10 flex items-center justify-between">
          <h2 className="text-xs font-semibold text-slate-200 uppercase tracking-wider font-mono">
            Historical Sync Attempts & Latencies
          </h2>
          <span className="text-xs font-mono text-slate-400">{historyData?.total ?? 0} attempts</span>
        </div>

        {historyLoading ? (
          <LoadingState title="Loading Historical Telemetry..." />
        ) : !historyData || historyData.items.length === 0 ? (
          <EmptyState
            icon={<Clock className="w-8 h-8 text-slate-500" />}
            title="No Sync History Recorded"
            description="Sync attempts will be recorded here when synchronization runs."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse text-xs font-mono">
              <thead>
                <tr className="border-b border-white/10 bg-black/20 text-slate-400">
                  <th className="py-2.5 px-4 font-medium">Attempt ID</th>
                  <th className="py-2.5 px-4 font-medium">Record ID</th>
                  <th className="py-2.5 px-4 font-medium">Status</th>
                  <th className="py-2.5 px-4 font-medium">Attempt #</th>
                  <th className="py-2.5 px-4 font-medium">Duration</th>
                  <th className="py-2.5 px-4 font-medium">Attempted At</th>
                  <th className="py-2.5 px-4 font-medium">Error Category</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {historyData.items.map((att) => (
                  <tr key={att.id} className="hover:bg-white/5 text-slate-300">
                    <td className="py-2.5 px-4 text-slate-400 truncate max-w-[100px]">{att.id.substring(0, 8)}...</td>
                    <td className="py-2.5 px-4 font-semibold text-slate-200 truncate max-w-[130px]">{att.record_id || '--'}</td>
                    <td className="py-2.5 px-4">
                      <StatusBadge status={att.status} size="sm" />
                    </td>
                    <td className="py-2.5 px-4 text-slate-400">#{att.attempt_number}</td>
                    <td className="py-2.5 px-4 text-slate-300 font-bold">
                      {att.duration_ms !== null && att.duration_ms !== undefined ? `${att.duration_ms.toFixed(1)} ms` : '--'}
                    </td>
                    <td className="py-2.5 px-4 text-slate-400">
                      {formatTime(att.attempted_at)}
                    </td>
                    <td className="py-2.5 px-4 text-rose-300 truncate max-w-[150px]">
                      {att.error_category || 'none'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {historyData && (
          <Pagination
            currentPage={historyData.page}
            totalPages={historyData.pages}
            totalItems={historyData.total}
            pageSize={historyData.page_size}
            onPageChange={(p) => setHistoryPage(p)}
          />
        )}
      </div>

      {/* Queue Item Detail Modal */}
      {selectedQueueItem && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="fixed inset-0 bg-black/80 backdrop-blur-sm" onClick={() => setSelectedQueueItem(null)} />
          <div className="relative bg-industrial-900 border border-white/10 rounded-xl max-w-lg w-full p-6 shadow-2xl z-10 space-y-4 font-mono text-xs">
            <div className="flex items-center justify-between border-b border-white/10 pb-3">
              <h3 className="text-sm font-bold text-slate-100">Queue Item Telemetry</h3>
              <button onClick={() => setSelectedQueueItem(null)} className="text-slate-500 hover:text-slate-300 p-1">
                ✕
              </button>
            </div>

            <div className="space-y-2 p-3 bg-black/40 rounded-lg border border-white/5">
              <div className="flex justify-between">
                <span className="text-slate-500">Queue ID:</span>
                <span className="text-slate-300">{selectedQueueItem.id}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500">Record ID:</span>
                <span className="text-sky-400 font-bold">{selectedQueueItem.record_id || (selectedQueueItem as any).entity_id || selectedQueueItem.id}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500">Entity Type:</span>
                <span className="text-slate-300 uppercase">{selectedQueueItem.record_type || (selectedQueueItem as any).entity_type}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500">Operation:</span>
                <span className="text-emerald-400 font-bold uppercase">{selectedQueueItem.operation}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500">Current Status:</span>
                <StatusBadge status={selectedQueueItem.status} size="sm" />
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500">Revision:</span>
                <span className="text-slate-200">rev {selectedQueueItem.revision ?? 1}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500">Retry Progress:</span>
                <span className="text-slate-300">{selectedQueueItem.retry_count} / {selectedQueueItem.max_retries} attempts</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500">Queued Timestamp:</span>
                <span className="text-slate-400">{formatDateTime(selectedQueueItem.created_at)}</span>
              </div>
              {selectedQueueItem.scheduled_at && (
                <div className="flex justify-between">
                  <span className="text-slate-500">Next Backoff Execution:</span>
                  <span className="text-amber-400">{formatTime(selectedQueueItem.scheduled_at)}</span>
                </div>
              )}
              {selectedQueueItem.last_error_message && (
                <div className="pt-2 border-t border-white/10 text-rose-300 text-[11px] break-words">
                  Last Error ({selectedQueueItem.last_error_category}): {selectedQueueItem.last_error_message}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
