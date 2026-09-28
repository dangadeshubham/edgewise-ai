import React, { useState } from 'react'
import { Menu, ShieldCheck, Wifi, WifiOff } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../../services/api'
import { StatusBadge } from '../common/StatusBadge'
import { SystemStatusModal } from './SystemStatusModal'

interface TopNavigationProps {
  onToggleSidebar: () => void
}

export const TopNavigation: React.FC<TopNavigationProps> = ({ onToggleSidebar }) => {
  const [isStatusModalOpen, setIsStatusModalOpen] = useState(false)

  // Polling connectivity state every 15 seconds (real telemetry)
  const { data: connectivity } = useQuery({
    queryKey: ['connectivity'],
    queryFn: api.getConnectivity,
    refetchInterval: 15000,
  })

  // Polling dashboard metrics for device identity
  const { data: metrics } = useQuery({
    queryKey: ['dashboardMetrics'],
    queryFn: api.getDashboardMetrics,
    refetchInterval: 30000,
  })

  const currentState = connectivity?.state || 'offline'

  return (
    <>
      <header className="h-16 bg-industrial-900/90 backdrop-blur-md border-b border-white/10 px-6 flex items-center justify-between sticky top-0 z-30">
        <div className="flex items-center gap-3">
          <button
            onClick={onToggleSidebar}
            className="p-2 rounded-lg text-slate-400 hover:text-slate-100 hover:bg-white/5 lg:hidden transition-colors"
          >
            <Menu className="w-5 h-5" />
          </button>
          <div className="hidden sm:flex items-center gap-2 font-mono text-xs text-slate-400">
            <span className="text-slate-500">Node:</span>
            <span className="text-slate-200 font-semibold">
              {metrics?.current_device_name || 'Edge Node 001'}
            </span>
            <span className="text-slate-600">/</span>
            <span className="text-slate-400">{metrics?.current_device_site || 'Facility A'}</span>
          </div>
        </div>

        <div className="flex items-center gap-3">
          {/* Global System Connectivity Pill */}
          <button
            onClick={() => setIsStatusModalOpen(true)}
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-industrial-950/80 border border-white/10 hover:border-sky-500/40 transition-colors shadow-sm"
            title="Click to view detailed dependency telemetry"
          >
            {currentState === 'online' ? (
              <Wifi className="w-3.5 h-3.5 text-emerald-400" />
            ) : (
              <WifiOff className="w-3.5 h-3.5 text-rose-400" />
            )}
            <StatusBadge status={currentState} size="sm" />
          </button>

          {/* Device ID Badge */}
          <div className="hidden md:flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-white/5 border border-white/5 font-mono text-xs text-slate-400">
            <ShieldCheck className="w-3.5 h-3.5 text-sky-400" />
            <span className="truncate max-w-[120px]">
              {metrics?.current_device_id || 'edge-001'}
            </span>
          </div>
        </div>
      </header>

      {/* Dependency Status Inspector Modal */}
      <SystemStatusModal
        isOpen={isStatusModalOpen}
        onClose={() => setIsStatusModalOpen(false)}
        connectivity={connectivity}
      />
    </>
  )
}
