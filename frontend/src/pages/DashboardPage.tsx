import React from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  Layers,
  Database,
  RefreshCw,
  GitCompare,
  HardDrive,
  Clock,
  ArrowRight,
  Cpu,
  Bot,
} from 'lucide-react'
import { api } from '../services/api'
import { MetricCard } from '../components/common/MetricCard'
import { StatusBadge } from '../components/common/StatusBadge'
import { LoadingState } from '../components/common/LoadingState'
import { ErrorState } from '../components/common/ErrorState'

export const DashboardPage: React.FC = () => {
  const queryClient = useQueryClient()

  const {
    data: metrics,
    isLoading: metricsLoading,
    error: metricsError,
    refetch: refetchMetrics,
  } = useQuery({
    queryKey: ['dashboardMetrics'],
    queryFn: api.getDashboardMetrics,
    refetchInterval: 15000,
  })

  const { data: connectivity } = useQuery({
    queryKey: ['connectivity'],
    queryFn: api.getConnectivity,
    refetchInterval: 15000,
  })

  // Quick sync mutation
  const syncMutation = useMutation({
    mutationFn: () => api.runSync(20, true),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dashboardMetrics'] })
      queryClient.invalidateQueries({ queryKey: ['syncStatus'] })
    },
  })

  if (metricsLoading) {
    return <LoadingState title="Loading Operational Metrics" message="Gathering state from local database and Qdrant Edge." />
  }

  if (metricsError) {
    return (
      <ErrorState
        title="Failed to Load Dashboard Telemetry"
        message={metricsError instanceof Error ? metricsError.message : 'Unknown database error'}
        onRetry={() => refetchMetrics()}
      />
    )
  }

  const formatBytes = (bytes?: number | null) => {
    if (!bytes) return '0 B'
    const k = 1024
    const sizes = ['B', 'KB', 'MB', 'GB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`
  }

  return (
    <div className="space-y-6">
      {/* Top Welcome / Status Hero */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 p-6 rounded-2xl bg-gradient-to-r from-industrial-900 to-industrial-850 border border-white/10 shadow-xl">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-bold text-slate-100 tracking-tight">
              Operational Intelligence Node
            </h1>
            <StatusBadge status={connectivity?.state || 'offline'} size="sm" />
          </div>
          <p className="text-xs text-slate-400 mt-1">
            Node: <span className="text-slate-200 font-mono font-medium">{metrics?.current_device_name}</span> ({metrics?.current_device_id}) • Site:{' '}
            <span className="text-slate-200">{metrics?.current_device_site}</span>
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={() => syncMutation.mutate()}
            disabled={syncMutation.isPending}
            className="flex items-center gap-2 px-3.5 py-2 rounded-lg bg-sky-500 hover:bg-sky-400 text-slate-950 text-xs font-semibold shadow-md shadow-sky-500/20 transition-all disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${syncMutation.isPending ? 'animate-spin' : ''}`} />
            <span>{syncMutation.isPending ? 'Syncing...' : 'Sync Cloud'}</span>
          </button>
          <Link
            to="/copilot"
            className="flex items-center gap-2 px-3.5 py-2 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-xs font-medium text-slate-200 transition-all"
          >
            <Bot className="w-3.5 h-3.5 text-sky-400" />
            <span>Launch Copilot</span>
          </Link>
        </div>
      </div>

      {/* Primary Key Metric Cards Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          title="Edge Vector Points"
          value={metrics?.local_vector_count ?? 0}
          icon={<Layers className="w-4 h-4" />}
          subtitle={`Mutable: ${metrics?.edge_mutable_points ?? 0} | Imm: ${metrics?.edge_immutable_points ?? 0}`}
        />
        <MetricCard
          title="Embedded Chunks"
          value={metrics?.embedded_chunks ?? 0}
          icon={<Database className="w-4 h-4" />}
          subtitle={`Unembedded: ${metrics?.unembedded_chunks ?? 0}`}
          trend={metrics?.unembedded_chunks === 0 ? '✓ Fully Embedded' : `${metrics?.unembedded_chunks} pending`}
          trendColor={metrics?.unembedded_chunks === 0 ? 'emerald' : 'amber'}
        />
        <MetricCard
          title="Pending Sync Items"
          value={metrics?.pending_sync ?? 0}
          icon={<RefreshCw className="w-4 h-4" />}
          subtitle={`Failed retries: ${metrics?.failed_sync ?? 0}`}
          trendColor={metrics?.pending_sync === 0 ? 'emerald' : 'sky'}
        />
        <MetricCard
          title="Open Conflicts"
          value={metrics?.open_conflicts ?? 0}
          icon={<GitCompare className="w-4 h-4" />}
          subtitle="Divergent revisions requiring review"
          trend={metrics?.open_conflicts === 0 ? 'Zero conflicts' : 'Attention needed'}
          trendColor={metrics?.open_conflicts === 0 ? 'emerald' : 'amber'}
        />
      </div>

      {/* Sub-grid: Storage & Sync Status */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Qdrant Edge Architecture Card */}
        <div className="p-5 rounded-xl bg-industrial-900/80 border border-white/10 space-y-4">
          <div className="flex items-center justify-between border-b border-white/10 pb-3">
            <div className="flex items-center gap-2">
              <Cpu className="w-4 h-4 text-emerald-400" />
              <h2 className="text-sm font-semibold text-slate-100">Qdrant Edge Engine</h2>
            </div>
            <StatusBadge
              status={metrics?.edge_shard_available ? 'available' : 'unavailable'}
              label={metrics?.edge_shard_available ? 'Ready' : 'Offline'}
              size="sm"
            />
          </div>

          <div className="space-y-2.5 font-mono text-xs">
            <div className="flex justify-between py-1 border-b border-white/5">
              <span className="text-slate-400">Mutable Shard (Local Writes):</span>
              <span className="text-slate-200 font-bold">{metrics?.edge_mutable_points} points</span>
            </div>
            <div className="flex justify-between py-1 border-b border-white/5">
              <span className="text-slate-400">Immutable Shard (Server Sync):</span>
              <span className="text-slate-200 font-bold">{metrics?.edge_immutable_points} points</span>
            </div>
            <div className="flex justify-between py-1 border-b border-white/5">
              <span className="text-slate-400">Storage Path:</span>
              <span className="text-slate-400 truncate max-w-[170px]" title={metrics?.edge_storage_path || ''}>
                {metrics?.edge_storage_path || 'data/qdrant_edge'}
              </span>
            </div>
            <div className="flex justify-between py-1">
              <span className="text-slate-400">Last Disk Flush:</span>
              <span className="text-slate-300">
                {metrics?.edge_last_flush ? new Date(metrics.edge_last_flush).toLocaleTimeString() : 'Never'}
              </span>
            </div>
          </div>
        </div>

        {/* Knowledge & Document Vault Card */}
        <div className="p-5 rounded-xl bg-industrial-900/80 border border-white/10 space-y-4">
          <div className="flex items-center justify-between border-b border-white/10 pb-3">
            <div className="flex items-center gap-2">
              <HardDrive className="w-4 h-4 text-sky-400" />
              <h2 className="text-sm font-semibold text-slate-100">Vault & Ingestion</h2>
            </div>
            <Link to="/documents" className="text-xs text-sky-400 hover:text-sky-300 flex items-center gap-1">
              View All <ArrowRight className="w-3 h-3" />
            </Link>
          </div>

          <div className="space-y-2.5 font-mono text-xs">
            <div className="flex justify-between py-1 border-b border-white/5">
              <span className="text-slate-400">Total Documents:</span>
              <span className="text-slate-200 font-bold">{metrics?.total_documents}</span>
            </div>
            <div className="flex justify-between py-1 border-b border-white/5">
              <span className="text-slate-400">Processed Successfully:</span>
              <span className="text-emerald-400 font-bold">{metrics?.processed_documents}</span>
            </div>
            <div className="flex justify-between py-1 border-b border-white/5">
              <span className="text-slate-400">Processing Failures:</span>
              <span className={metrics?.failed_documents ? 'text-rose-400 font-bold' : 'text-slate-400'}>
                {metrics?.failed_documents}
              </span>
            </div>
            <div className="flex justify-between py-1">
              <span className="text-slate-400">Disk Footprint:</span>
              <span className="text-slate-300">{formatBytes(metrics?.storage_usage_bytes)}</span>
            </div>
          </div>
        </div>

        {/* Sync & Connectivity Telemetry */}
        <div className="p-5 rounded-xl bg-industrial-900/80 border border-white/10 space-y-4">
          <div className="flex items-center justify-between border-b border-white/10 pb-3">
            <div className="flex items-center gap-2">
              <Clock className="w-4 h-4 text-amber-400" />
              <h2 className="text-sm font-semibold text-slate-100">Cloud Sync Status</h2>
            </div>
            <Link to="/sync" className="text-xs text-amber-400 hover:text-amber-300 flex items-center gap-1">
              Center <ArrowRight className="w-3 h-3" />
            </Link>
          </div>

          <div className="space-y-2.5 font-mono text-xs">
            <div className="flex justify-between py-1 border-b border-white/5">
              <span className="text-slate-400">Cloud Target:</span>
              <span className="text-slate-300">Qdrant Server</span>
            </div>
            <div className="flex justify-between py-1 border-b border-white/5">
              <span className="text-slate-400">Remote Reachability:</span>
              <StatusBadge
                status={connectivity?.dependencies?.qdrant_server?.status || 'offline'}
                size="sm"
              />
            </div>
            <div className="flex justify-between py-1 border-b border-white/5">
              <span className="text-slate-400">Last Successful Sync:</span>
              <span className="text-slate-300">
                {metrics?.last_successful_sync ? new Date(metrics.last_successful_sync).toLocaleString() : 'Pending initial sync'}
              </span>
            </div>
            <div className="flex justify-between py-1">
              <span className="text-slate-400">Queue Backlog:</span>
              <span className="text-sky-400 font-bold">{metrics?.pending_sync} tasks</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
