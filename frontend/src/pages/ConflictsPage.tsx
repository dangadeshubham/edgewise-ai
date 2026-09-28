import React, { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  GitCompare,
  Home,
  Cloud,
  Split,
  Edit3,
  XCircle,
  RefreshCw,
  Sparkles,
  ShieldAlert,
  CheckCircle2,
} from 'lucide-react'
import { api } from '../services/api'
import type { ConflictResolveRequest } from '../types'
import { StatusBadge } from '../components/common/StatusBadge'
import { FilterBar } from '../components/common/FilterBar'
import type { FilterOption } from '../components/common/FilterBar'
import { LoadingState } from '../components/common/LoadingState'
import { EmptyState } from '../components/common/EmptyState'
import { ErrorState } from '../components/common/ErrorState'
import { ConfirmDialog } from '../components/common/ConfirmDialog'

export const ConflictsPage: React.FC = () => {
  const queryClient = useQueryClient()
  const [statusFilter, setStatusFilter] = useState('')
  const [selectedConflictId, setSelectedConflictId] = useState<string | null>(null)
  const [operatorName, setOperatorName] = useState('operator')
  const [resolutionNotes, setResolutionNotes] = useState('')
  const [customMode, setCustomMode] = useState<'merge' | 'manual' | null>(null)
  const [customContent, setCustomContent] = useState('')
  const [isAiSuggestion, setIsAiSuggestion] = useState(false)
  const [resolutionError, setResolutionError] = useState<string | null>(null)
  const [confirmDialog, setConfirmDialog] = useState<{
    isOpen: boolean
    title: string
    message: string
    details?: string
    action: () => void
  }>({
    isOpen: false,
    title: '',
    message: '',
    action: () => {},
  })

  // List Conflicts
  const { data: listData, isLoading: listLoading, refetch: refetchList } = useQuery({
    queryKey: ['conflicts', statusFilter],
    queryFn: () => api.listConflicts(statusFilter || undefined, 'newest', 50),
    refetchInterval: 10000,
  })

  // Selected Conflict Detail
  const { data: detailData, isLoading: detailLoading } = useQuery({
    queryKey: ['conflictDetail', selectedConflictId],
    queryFn: () => (selectedConflictId ? api.getConflict(selectedConflictId) : null),
    enabled: !!selectedConflictId,
  })

  // Query Audit History for Conflict
  const { data: auditData } = useQuery({
    queryKey: ['conflictActivity', selectedConflictId],
    queryFn: () => (selectedConflictId ? api.listActivity(1, 20, 'conflict') : null),
    enabled: !!selectedConflictId,
  })

  // Claim Mutation
  const claimMutation = useMutation({
    mutationFn: () => {
      if (!selectedConflictId || !detailData) throw new Error('No conflict selected')
      return api.claimConflict(selectedConflictId, operatorName, detailData.conflict.version)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['conflicts'] })
      queryClient.invalidateQueries({ queryKey: ['conflictDetail', selectedConflictId] })
      queryClient.invalidateQueries({ queryKey: ['dashboardMetrics'] })
    },
  })

  // Resolve Mutation
  const resolveMutation = useMutation({
    mutationFn: (payload: ConflictResolveRequest) => {
      if (!selectedConflictId) throw new Error('No conflict selected')
      return api.resolveConflict(selectedConflictId, payload)
    },
    onSuccess: () => {
      setResolutionError(null)
      setCustomMode(null)
      setCustomContent('')
      setIsAiSuggestion(false)
      setConfirmDialog((prev) => ({ ...prev, isOpen: false }))
      queryClient.invalidateQueries({ queryKey: ['conflicts'] })
      queryClient.invalidateQueries({ queryKey: ['conflictDetail', selectedConflictId] })
      queryClient.invalidateQueries({ queryKey: ['dashboardMetrics'] })
    },
    onError: (err: any) => {
      setResolutionError(err.message || 'Resolution failed')
      setConfirmDialog((prev) => ({ ...prev, isOpen: false }))
    },
  })

  // Dismiss Mutation
  const dismissMutation = useMutation({
    mutationFn: () => {
      if (!selectedConflictId || !detailData) throw new Error('No conflict selected')
      return api.dismissConflict(selectedConflictId, operatorName, resolutionNotes, detailData.conflict.version)
    },
    onSuccess: () => {
      setConfirmDialog((prev) => ({ ...prev, isOpen: false }))
      queryClient.invalidateQueries({ queryKey: ['conflicts'] })
      queryClient.invalidateQueries({ queryKey: ['conflictDetail', selectedConflictId] })
      queryClient.invalidateQueries({ queryKey: ['dashboardMetrics'] })
    },
  })

  // Suggest Merge Mutation
  const suggestMergeMutation = useMutation({
    mutationFn: () => {
      if (!selectedConflictId) throw new Error('No conflict selected')
      return api.suggestMerge(selectedConflictId)
    },
    onSuccess: (data) => {
      setCustomMode('merge')
      setCustomContent(data.suggested_content)
      setIsAiSuggestion(true)
    },
  })

  const conflict = detailData?.conflict
  const isActionable = conflict && (conflict.status === 'open' || conflict.status === 'in_review')

  const filterOptions: FilterOption[] = [
    { id: '', label: 'All', count: listData?.total },
    { id: 'open', label: 'Open', count: listData?.open_count },
    { id: 'in_review', label: 'In Review', count: listData?.in_review_count },
    { id: 'resolved', label: 'Resolved', count: listData?.resolved_count },
    { id: 'dismissed', label: 'Dismissed', count: listData?.dismissed_count },
  ]

  const handleKeepLocal = () => {
    if (!conflict) return
    setConfirmDialog({
      isOpen: true,
      title: 'Keep Local Version',
      message: 'Preserve the local version as authoritative. A monotonic revision will be assigned and enqueued for cloud upload.',
      details: `Record: ${conflict.record_id}\nLocal Revision: ${conflict.local_revision}\nCloud Revision: ${conflict.cloud_revision}`,
      action: () =>
        resolveMutation.mutate({
          resolution: 'keep_local',
          resolved_by: operatorName,
          notes: resolutionNotes || undefined,
          expected_version: conflict.version,
        }),
    })
  }

  const handleKeepCloud = () => {
    if (!conflict) return
    setConfirmDialog({
      isOpen: true,
      title: 'Keep Cloud Version',
      message: 'Adopt the remote cloud version. Local SQLite records and Qdrant Edge memory vectors will be overwritten with the cloud content.',
      details: `Record: ${conflict.record_id}\nOverwrites Local Hash: ${conflict.local_content_hash}\nAdopts Cloud Hash: ${conflict.cloud_content_hash}`,
      action: () =>
        resolveMutation.mutate({
          resolution: 'keep_cloud',
          resolved_by: operatorName,
          notes: resolutionNotes || undefined,
          expected_version: conflict.version,
        }),
    })
  }

  const handleDismiss = () => {
    if (!conflict) return
    setConfirmDialog({
      isOpen: true,
      title: 'Dismiss Conflict',
      message: 'Quarantine and close this conflict without altering local or remote state.',
      details: `Conflict ID: ${conflict.id}`,
      action: () => dismissMutation.mutate(),
    })
  }

  const handleCustomSubmit = () => {
    if (!conflict || !customContent.trim() || !customMode) return
    setConfirmDialog({
      isOpen: true,
      title: `Apply ${customMode === 'merge' ? 'Merged Consensus' : 'Manual Override'}`,
      message: 'Submit custom content as the authoritative record. A new revision will be embedded in Edge memory and queued for sync.',
      details: `Length: ${customContent.length} chars\nMode: ${customMode}`,
      action: () =>
        resolveMutation.mutate({
          resolution: customMode,
          merged_content: customMode === 'merge' ? customContent : undefined,
          manual_content: customMode === 'manual' ? customContent : undefined,
          resolved_by: operatorName,
          notes: resolutionNotes || undefined,
          expected_version: conflict.version,
        }),
    })
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-xl font-bold text-slate-100 tracking-tight">Conflict Management</h1>
        <p className="text-xs text-slate-400 mt-0.5">
          Review divergent knowledge revisions between Edge and Cloud. Both versions are quarantined until resolved.
        </p>
      </div>

      {/* Filter Tabs */}
      <FilterBar
        options={filterOptions}
        selectedId={statusFilter}
        onSelect={(id) => setStatusFilter(id)}
      />

      {/* Main Grid: Sidebar List + Workspace */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 min-h-[550px]">
        {/* Conflicts List Sidebar */}
        <div className="lg:col-span-4 bg-industrial-900/80 border border-white/10 rounded-xl p-4 flex flex-col justify-between shadow-xl">
          <div className="space-y-3">
            <div className="flex items-center justify-between pb-2 border-b border-white/10 text-xs font-mono text-slate-400">
              <span>Detected Conflicts ({listData?.total ?? 0})</span>
              <button onClick={() => refetchList()} className="hover:text-slate-200">
                <RefreshCw className="w-3.5 h-3.5" />
              </button>
            </div>

            {listLoading ? (
              <LoadingState title="Loading Conflicts..." />
            ) : !listData || listData.items.length === 0 ? (
              <EmptyState
                icon={<CheckCircle2 className="w-8 h-8 text-emerald-400" />}
                title="Zero Conflicts"
                description="No divergent versions found in local quarantine."
              />
            ) : (
              <div className="space-y-2 max-h-[580px] overflow-y-auto pr-1">
                {listData.items.map((c) => (
                  <div
                    key={c.id}
                    onClick={() => setSelectedConflictId(c.id)}
                    className={`p-3 rounded-lg border text-xs font-mono cursor-pointer transition-all ${
                      selectedConflictId === c.id
                        ? 'bg-sky-500/10 border-sky-500/40 text-slate-100 shadow-sm'
                        : 'bg-black/30 border-white/5 hover:border-white/15 text-slate-300'
                    }`}
                  >
                    <div className="flex items-center justify-between mb-1.5">
                      <StatusBadge status={c.status} size="sm" />
                      <span className="text-[10px] text-slate-500">v{c.version}</span>
                    </div>
                    <div className="font-bold text-slate-200 truncate" title={c.record_id || (c as any).entity_id}>
                      {c.record_id || (c as any).entity_id}
                    </div>
                    <div className="flex justify-between text-[11px] text-slate-400 mt-1">
                      <span>Local: rev {c.local_revision}</span>
                      <span>Cloud: rev {c.cloud_revision}</span>
                    </div>
                    <div className="text-[10px] text-slate-500 mt-1">
                      {new Date(c.created_at || (c as any).detected_at || Date.now()).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Workspace: Side-by-Side Diff & Resolution */}
        <div className="lg:col-span-8 bg-industrial-900/80 border border-white/10 rounded-xl p-5 shadow-xl">
          {!selectedConflictId ? (
            <div className="h-full flex flex-col items-center justify-center text-center p-12 text-slate-500 font-mono text-xs">
              <GitCompare className="w-10 h-10 mb-3 opacity-30" />
              <span>Select any conflict from the left list to review side-by-side diffs and apply resolution.</span>
            </div>
          ) : detailLoading ? (
            <LoadingState title="Computing Side-by-Side Diff..." />
          ) : !detailData || !conflict ? (
            <ErrorState message="Failed to load conflict details." />
          ) : (
            <div className="space-y-5">
              {/* Conflict Header */}
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-4 rounded-lg bg-black/40 border border-white/5">
                <div>
                  <div className="flex items-center gap-2">
                    <StatusBadge status={conflict.status} size="sm" />
                    <span className="font-mono text-xs uppercase px-2 py-0.5 rounded bg-white/5 text-slate-300">
                      {conflict.record_type}
                    </span>
                    <span className="font-mono text-xs text-slate-500">
                      Lock Version: {conflict.version}
                    </span>
                  </div>
                  <div className="font-mono text-xs text-slate-200 font-bold mt-1">
                    Record ID: {conflict.record_id}
                  </div>
                </div>

                {conflict.status === 'open' && (
                  <button
                    onClick={() => claimMutation.mutate()}
                    disabled={claimMutation.isPending}
                    className="px-3 py-1.5 rounded-lg bg-sky-500/20 hover:bg-sky-500/30 border border-sky-500/40 text-sky-300 text-xs font-mono font-medium transition-colors"
                  >
                    👤 Claim for Review
                  </button>
                )}
              </div>

              {/* Side-by-Side Diff View */}
              <div className="space-y-2">
                <div className="flex items-center justify-between text-xs font-mono">
                  <span className="font-semibold text-slate-300">Side-by-Side Comparison</span>
                  <div className="flex gap-3 text-[11px]">
                    <span className="text-emerald-400">+{detailData.additions_count} additions</span>
                    <span className="text-rose-400">-{detailData.deletions_count} deletions</span>
                    <span className="text-slate-500">{detailData.unchanged_count} unchanged</span>
                  </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  {/* Local Column */}
                  <div className="border border-white/10 rounded-lg overflow-hidden bg-black/50 flex flex-col">
                    <div className="p-2.5 bg-industrial-950 border-b border-white/10 flex justify-between items-center text-xs font-mono">
                      <span className="font-bold text-slate-200">LOCAL VERSION</span>
                      <span className="text-slate-400">rev {conflict.local_revision}</span>
                    </div>
                    <div className="p-3 text-xs font-mono max-h-56 overflow-y-auto space-y-0.5">
                      {detailData.lines.map((ln, i) => (
                        <div
                          key={i}
                          className={`px-1.5 py-0.5 rounded ${
                            ln.line_type === 'removed'
                              ? 'bg-rose-500/20 text-rose-300 border-l-2 border-rose-500'
                              : ln.line_type === 'unchanged'
                              ? 'text-slate-400'
                              : 'opacity-20'
                          }`}
                        >
                          {ln.line_type === 'removed' ? `- ${ln.content}` : ln.line_type === 'unchanged' ? `  ${ln.content}` : '\u00A0'}
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Cloud Column */}
                  <div className="border border-white/10 rounded-lg overflow-hidden bg-black/50 flex flex-col">
                    <div className="p-2.5 bg-industrial-950 border-b border-white/10 flex justify-between items-center text-xs font-mono">
                      <span className="font-bold text-slate-200">CLOUD VERSION</span>
                      <span className="text-slate-400">rev {conflict.cloud_revision}</span>
                    </div>
                    <div className="p-3 text-xs font-mono max-h-56 overflow-y-auto space-y-0.5">
                      {detailData.lines.map((ln, i) => (
                        <div
                          key={i}
                          className={`px-1.5 py-0.5 rounded ${
                            ln.line_type === 'added'
                              ? 'bg-emerald-500/20 text-emerald-300 border-l-2 border-emerald-500'
                              : ln.line_type === 'unchanged'
                              ? 'text-slate-400'
                              : 'opacity-20'
                          }`}
                        >
                          {ln.line_type === 'added' ? `+ ${ln.content}` : ln.line_type === 'unchanged' ? `  ${ln.content}` : '\u00A0'}
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>

              {/* Structured Metadata Diff */}
              <div className="border border-white/10 rounded-lg overflow-hidden bg-black/30 text-xs font-mono">
                <table className="w-full text-left">
                  <thead className="bg-black/40 text-slate-500 border-b border-white/10">
                    <tr>
                      <th className="py-1.5 px-3">Metadata Field</th>
                      <th className="py-1.5 px-3">Local State</th>
                      <th className="py-1.5 px-3">Cloud State</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/5">
                    {detailData.metadata_diffs.map((md) => (
                      <tr key={md.field_name} className={md.is_different ? 'text-amber-300 font-bold' : 'text-slate-400'}>
                        <td className="py-1.5 px-3 text-slate-300">{md.field_name}</td>
                        <td className="py-1.5 px-3">{String(md.local_value)}</td>
                        <td className="py-1.5 px-3">{String(md.cloud_value)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Error Banner */}
              {resolutionError && (
                <div className="p-3 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs flex items-center justify-between font-mono">
                  <span>{resolutionError}</span>
                  <button
                    type="button"
                    onClick={() => setResolutionError(null)}
                    className="text-slate-400 hover:text-slate-200 ml-2"
                  >
                    ✕
                  </button>
                </div>
              )}

              {/* Resolution Action Bar */}
              <div className="p-4 rounded-xl bg-industrial-950/80 border border-white/10 space-y-4">
                <div className="flex items-center justify-between text-xs font-mono">
                  <span className="font-semibold text-slate-200 uppercase tracking-wider">
                    Authoritative Resolution
                  </span>
                  {!isActionable && (
                    <span className="text-emerald-400 font-bold">
                      ✓ Resolved via {conflict.resolution}
                    </span>
                  )}
                </div>

                <div className="grid grid-cols-2 sm:grid-cols-5 gap-2 font-mono text-xs">
                  <button
                    onClick={handleKeepLocal}
                    disabled={!isActionable}
                    className="p-2.5 rounded-lg border border-emerald-500/40 bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-300 flex flex-col items-center gap-1 transition-all disabled:opacity-30 disabled:pointer-events-none"
                  >
                    <Home className="w-4 h-4" />
                    <span>Keep Local</span>
                  </button>

                  <button
                    onClick={handleKeepCloud}
                    disabled={!isActionable}
                    className="p-2.5 rounded-lg border border-sky-500/40 bg-sky-500/10 hover:bg-sky-500/20 text-sky-300 flex flex-col items-center gap-1 transition-all disabled:opacity-30 disabled:pointer-events-none"
                  >
                    <Cloud className="w-4 h-4" />
                    <span>Keep Cloud</span>
                  </button>

                  <button
                    onClick={() => {
                      setCustomMode('merge')
                      setCustomContent(conflict.local_content_preview || '')
                      setIsAiSuggestion(false)
                    }}
                    disabled={!isActionable}
                    className="p-2.5 rounded-lg border border-purple-500/40 bg-purple-500/10 hover:bg-purple-500/20 text-purple-300 flex flex-col items-center gap-1 transition-all disabled:opacity-30 disabled:pointer-events-none"
                  >
                    <Split className="w-4 h-4" />
                    <span>Merge</span>
                  </button>

                  <button
                    onClick={() => {
                      setCustomMode('manual')
                      setCustomContent('')
                      setIsAiSuggestion(false)
                    }}
                    disabled={!isActionable}
                    className="p-2.5 rounded-lg border border-amber-500/40 bg-amber-500/10 hover:bg-amber-500/20 text-amber-300 flex flex-col items-center gap-1 transition-all disabled:opacity-30 disabled:pointer-events-none"
                  >
                    <Edit3 className="w-4 h-4" />
                    <span>Manual</span>
                  </button>

                  <button
                    onClick={handleDismiss}
                    disabled={!isActionable}
                    className="p-2.5 rounded-lg border border-white/10 bg-white/5 hover:bg-white/10 text-slate-400 flex flex-col items-center gap-1 transition-all disabled:opacity-30 disabled:pointer-events-none"
                  >
                    <XCircle className="w-4 h-4" />
                    <span>Dismiss</span>
                  </button>
                </div>

                {/* Custom Content Editor (Merge / Manual) */}
                {customMode && (
                  <div className="p-4 rounded-lg bg-black/60 border border-sky-500/40 space-y-3 font-mono text-xs">
                    <div className="flex items-center justify-between">
                      <span className="text-sky-300 font-semibold uppercase">
                        {customMode === 'merge' ? 'Merge Consensus Editor' : 'Manual Override Editor'}
                      </span>
                      {customMode === 'merge' && (
                        <button
                          type="button"
                          onClick={() => suggestMergeMutation.mutate()}
                          disabled={suggestMergeMutation.isPending}
                          className="flex items-center gap-1 px-2.5 py-1 rounded bg-purple-500/20 border border-purple-500/40 text-purple-200 text-[11px] hover:bg-purple-500/30 transition-colors"
                        >
                          <Sparkles className="w-3 h-3 text-purple-300" />
                          <span>Suggested Merge</span>
                        </button>
                      )}
                    </div>

                    {isAiSuggestion && (
                      <div className="p-2 rounded bg-amber-500/10 border border-amber-500/30 text-amber-300 text-[11px] flex items-center gap-2">
                        <ShieldAlert className="w-4 h-4 shrink-0" />
                        <span>Suggested Merge: Review and modify before saving. Requires operator approval.</span>
                      </div>
                    )}

                    <textarea
                      rows={5}
                      value={customContent}
                      onChange={(e) => setCustomContent(e.target.value)}
                      placeholder="Enter or modify the final authoritative content..."
                      className="w-full bg-industrial-900 border border-white/10 rounded-lg p-3 text-slate-200 focus:outline-none focus:border-sky-500 text-xs"
                    />

                    <div className="flex items-center justify-between">
                      <span className="text-slate-500 text-[10px]">
                        {customContent.length} characters
                      </span>
                      <button
                        onClick={handleCustomSubmit}
                        disabled={!customContent.trim() || resolveMutation.isPending}
                        className="px-4 py-2 rounded-lg bg-sky-500 hover:bg-sky-400 text-slate-950 font-bold transition-colors disabled:opacity-50"
                      >
                        {resolveMutation.isPending ? 'Saving...' : 'Apply Authoritative Content'}
                      </button>
                    </div>
                  </div>
                )}

                {/* Operator Inputs */}
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs font-mono pt-2 border-t border-white/5">
                  <div>
                    <label className="text-slate-500 block mb-1">Operator Signature</label>
                    <input
                      type="text"
                      value={operatorName}
                      onChange={(e) => setOperatorName(e.target.value)}
                      className="w-full bg-black/40 border border-white/10 rounded-lg px-3 py-1.5 text-slate-200 focus:outline-none"
                    />
                  </div>
                  <div>
                    <label className="text-slate-500 block mb-1">Resolution Justification</label>
                    <input
                      type="text"
                      value={resolutionNotes}
                      onChange={(e) => setResolutionNotes(e.target.value)}
                      placeholder="e.g. Field sensor calibration verified"
                      className="w-full bg-black/40 border border-white/10 rounded-lg px-3 py-1.5 text-slate-200 focus:outline-none"
                    />
                  </div>
                </div>

                {/* Conflict Audit Trail */}
                {auditData && auditData.items && auditData.items.length > 0 && (
                  <div className="pt-3 border-t border-white/5 font-mono">
                    <span className="text-[10px] text-slate-500 uppercase tracking-wider block mb-2">
                      Recent System Audit Events
                    </span>
                    <div className="space-y-1.5 max-h-36 overflow-y-auto">
                      {auditData.items.slice(0, 5).map((ev) => (
                        <div
                          key={ev.id}
                          className="flex items-center justify-between p-2 rounded bg-black/30 border border-white/5 text-[11px]"
                        >
                          <span className="text-slate-300">{ev.event_type}</span>
                          <span className="text-slate-500">{new Date(ev.created_at).toLocaleTimeString()}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Confirmation Dialog */}
      <ConfirmDialog
        isOpen={confirmDialog.isOpen}
        title={confirmDialog.title}
        message={confirmDialog.message}
        details={confirmDialog.details}
        isLoading={resolveMutation.isPending || dismissMutation.isPending}
        onConfirm={confirmDialog.action}
        onCancel={() => setConfirmDialog((prev) => ({ ...prev, isOpen: false }))}
      />
    </div>
  )
}
