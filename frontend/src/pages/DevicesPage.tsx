import React from 'react'
import { useQuery } from '@tanstack/react-query'
import { HardDrive, RefreshCw, MapPin, Cpu } from 'lucide-react'
import { api } from '../services/api'
import { StatusBadge } from '../components/common/StatusBadge'
import { LoadingState } from '../components/common/LoadingState'
import { EmptyState } from '../components/common/EmptyState'
import { ErrorState } from '../components/common/ErrorState'
import { formatTime } from '../utils/date'

export const DevicesPage: React.FC = () => {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['devices'],
    queryFn: api.listDevices,
    refetchInterval: 15000,
  })

  const { data: metrics } = useQuery({
    queryKey: ['dashboardMetrics'],
    queryFn: api.getDashboardMetrics,
  })

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-100 tracking-tight">Connected Nodes & Devices</h1>
          <p className="text-xs text-slate-400 mt-0.5">
            Registered industrial edge nodes, site locations, and synchronization heartbeats.
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

      {(() => {
        const deviceList = data ? (data.devices || (data as any).items || []) : []
        if (isLoading) {
          return <LoadingState title="Loading Device Fleet..." />
        }
        if (error) {
          return <ErrorState message={error instanceof Error ? error.message : 'Failed to query devices'} onRetry={() => refetch()} />
        }
        if (deviceList.length === 0) {
          return (
            <EmptyState
              icon={<HardDrive className="w-8 h-8 text-slate-500" />}
              title="No Registered Devices"
              description="Local edge node will register automatically upon startup."
            />
          )
        }
        return (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {deviceList.map((device: any) => {
              const isCurrent = device.id === metrics?.current_device_id
            return (
              <div
                key={device.id}
                className={`p-5 rounded-xl border backdrop-blur-md transition-all space-y-4 ${
                  isCurrent
                    ? 'bg-industrial-900 border-sky-500/40 shadow-lg shadow-sky-500/5'
                    : 'bg-industrial-900/60 border-white/10'
                }`}
              >
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-2.5">
                    <div className="p-2 rounded-lg bg-white/5 text-sky-400 border border-white/5">
                      <Cpu className="w-4 h-4" />
                    </div>
                    <div>
                      <h3 className="text-sm font-semibold text-slate-100">{device.name}</h3>
                      <span className="text-[10px] font-mono text-slate-500 flex items-center gap-1">
                        <MapPin className="w-3 h-3" /> {device.site}
                      </span>
                    </div>
                  </div>
                  <div className="flex items-center gap-1.5">
                    {isCurrent && (
                      <span className="px-1.5 py-0.5 rounded text-[10px] font-mono font-bold bg-sky-500/20 text-sky-300 border border-sky-500/40">
                        THIS NODE
                      </span>
                    )}
                    <StatusBadge status={device.status} size="sm" />
                  </div>
                </div>

                <div className="space-y-1.5 text-xs font-mono text-slate-400 pt-2 border-t border-white/5">
                  <div className="flex justify-between">
                    <span className="text-slate-500">Device ID:</span>
                    <span className="text-slate-300 truncate max-w-[170px]" title={device.id}>
                      {device.id}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-500">Software:</span>
                    <span className="text-slate-300">{device.software_version || 'v1.0.0'}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-500">Last Seen:</span>
                    <span className="text-slate-300">
                      {formatTime(device.last_heartbeat_at, 'Online')}
                    </span>
                  </div>
                </div>
              </div>
            )
          })}
          </div>
        )
      })()}
    </div>
  )
}
