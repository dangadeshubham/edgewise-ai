import React, { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Activity, RefreshCw } from 'lucide-react'
import { api } from '../services/api'
import { FilterBar } from '../components/common/FilterBar'
import type { FilterOption } from '../components/common/FilterBar'
import { LoadingState } from '../components/common/LoadingState'
import { EmptyState } from '../components/common/EmptyState'
import { ErrorState } from '../components/common/ErrorState'
import { Pagination } from '../components/common/Pagination'

export const ActivityPage: React.FC = () => {
  const [page, setPage] = useState(1)
  const [entityFilter, setEntityFilter] = useState('')

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['activity', page, entityFilter],
    queryFn: () => api.listActivity(page, 25, entityFilter || undefined),
    refetchInterval: 10000,
  })

  const filterOptions: FilterOption[] = [
    { id: '', label: 'All Operations' },
    { id: 'document', label: 'Documents' },
    { id: 'memory_record', label: 'Memory Records' },
    { id: 'sync', label: 'Sync Queue' },
    { id: 'conflict', label: 'Conflicts' },
    { id: 'connectivity', label: 'Connectivity' },
  ]

  const getSeverityBadge = (severity?: string | null) => {
    switch ((severity || 'info').toLowerCase()) {
      case 'warning':
        return 'bg-amber-500/10 text-amber-400 border-amber-500/30'
      case 'error':
        return 'bg-rose-500/10 text-rose-400 border-rose-500/30'
      default:
        return 'bg-sky-500/10 text-sky-400 border-sky-500/30'
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-100 tracking-tight">System Audit Trail</h1>
          <p className="text-xs text-slate-400 mt-0.5">
            Immutable SQLite operation activity log for compliance, synchronization, and traceability.
          </p>
        </div>
        <button
          onClick={() => refetch()}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-xs font-mono text-slate-300 transition-colors"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          <span>Refresh</span>
        </button>
      </div>

      {/* Filter Bar */}
      <FilterBar
        options={filterOptions}
        selectedId={entityFilter}
        onSelect={(id) => {
          setEntityFilter(id)
          setPage(1)
        }}
      />

      {/* Activity Timeline List */}
      <div className="bg-industrial-900/80 border border-white/10 rounded-xl overflow-hidden shadow-xl flex flex-col justify-between">
        <div>
          {isLoading ? (
            <LoadingState title="Loading Audit Events..." />
          ) : error ? (
            <div className="p-6">
              <ErrorState message={error instanceof Error ? error.message : 'Failed to query activity log'} onRetry={() => refetch()} />
            </div>
          ) : !data || data.items.length === 0 ? (
            <EmptyState
              icon={<Activity className="w-8 h-8 text-slate-500" />}
              title="No Activity Events"
              description="No audit logs recorded for this category."
            />
          ) : (
            <div className="divide-y divide-white/5">
              {data.items.map((ev) => (
                <div key={ev.id} className="p-4 hover:bg-white/5 transition-colors flex items-start justify-between gap-4 font-mono text-xs">
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <span className={`px-2 py-0.5 rounded text-[10px] uppercase font-bold border ${getSeverityBadge(ev.severity)}`}>
                        {ev.severity}
                      </span>
                      <span className="font-bold text-slate-200">{ev.event_type}</span>
                      {ev.entity_type && (
                        <span className="text-slate-500 uppercase text-[10px]">
                          [{ev.entity_type} {ev.entity_id ? `• ${ev.entity_id.substring(0, 8)}...` : ''}]
                        </span>
                      )}
                    </div>
                    <p className="text-slate-300 font-sans text-xs leading-relaxed">{ev.description}</p>
                    {ev.details && Object.keys(ev.details).length > 0 && (
                      <div className="text-[10px] text-slate-500 max-w-2xl truncate">
                        {JSON.stringify(ev.details)}
                      </div>
                    )}
                  </div>
                  <div className="text-right shrink-0 text-slate-400 text-[11px]">
                    <div>{new Date(ev.created_at).toLocaleTimeString()}</div>
                    <div className="text-[10px] text-slate-500">{new Date(ev.created_at).toLocaleDateString()}</div>
                  </div>
                </div>
              ))}
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
    </div>
  )
}
