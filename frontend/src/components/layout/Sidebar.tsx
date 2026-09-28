import React from 'react'
import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard,
  Bot,
  Database,
  FileText,
  RefreshCw,
  GitCompare,
  HardDrive,
  Activity,
  Settings,
} from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../../services/api'

interface SidebarProps {
  isOpen: boolean
  onClose?: () => void
}

export const Sidebar: React.FC<SidebarProps> = ({ isOpen, onClose }) => {
  // Query live metrics to show badges for open conflicts and pending sync
  const { data: metrics } = useQuery({
    queryKey: ['dashboardMetrics'],
    queryFn: api.getDashboardMetrics,
    refetchInterval: 10000,
  })

  const navItems = [
    { to: '/', label: 'Operations Dashboard', icon: <LayoutDashboard className="w-4 h-4" /> },
    { to: '/copilot', label: 'AI Copilot', icon: <Bot className="w-4 h-4" /> },
    { to: '/memory', label: 'Memory Explorer', icon: <Database className="w-4 h-4" /> },
    { to: '/documents', label: 'Document Vault', icon: <FileText className="w-4 h-4" /> },
    {
      to: '/sync',
      label: 'Synchronization',
      icon: <RefreshCw className="w-4 h-4" />,
      badge: metrics?.pending_sync && metrics.pending_sync > 0 ? metrics.pending_sync : undefined,
      badgeColor: 'sky',
    },
    {
      to: '/conflicts',
      label: 'Conflict Review',
      icon: <GitCompare className="w-4 h-4" />,
      badge: metrics?.open_conflicts && metrics.open_conflicts > 0 ? metrics.open_conflicts : undefined,
      badgeColor: 'amber',
    },
    { to: '/devices', label: 'Connected Devices', icon: <HardDrive className="w-4 h-4" /> },
    { to: '/activity', label: 'Audit Activity', icon: <Activity className="w-4 h-4" /> },
    { to: '/settings', label: 'Node Settings', icon: <Settings className="w-4 h-4" /> },
  ]

  return (
    <>
      {/* Mobile Backdrop */}
      {isOpen && (
        <div
          className="fixed inset-0 bg-black/60 backdrop-blur-sm z-30 lg:hidden"
          onClick={onClose}
        />
      )}

      <aside
        className={`fixed top-0 left-0 bottom-0 z-40 w-64 bg-industrial-900 border-r border-white/10 flex flex-col transition-transform duration-200 ease-in-out lg:translate-x-0 ${
          isOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        {/* Brand Header */}
        <div className="h-16 flex items-center gap-3 px-6 border-b border-white/10 bg-industrial-950/60">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-tr from-sky-500 to-emerald-400 flex items-center justify-center shadow-lg shadow-sky-500/20">
            <span className="font-mono font-black text-sm text-slate-950">EW</span>
          </div>
          <div>
            <div className="flex items-center gap-1.5 font-bold tracking-tight text-slate-100 text-sm">
              EDGEWISE<span className="text-sky-400 font-mono">.AI</span>
            </div>
            <div className="text-[10px] text-slate-500 font-mono tracking-wider">
              OPERATIONS PLATFORM
            </div>
          </div>
        </div>

        {/* Navigation Items */}
        <nav className="flex-1 overflow-y-auto px-3 py-4 space-y-1">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'}
              onClick={onClose}
              className={({ isActive }) =>
                `flex items-center justify-between px-3 py-2.5 rounded-lg text-xs font-medium tracking-wide transition-all ${
                  isActive
                    ? 'bg-sky-500/15 text-sky-300 font-semibold border border-sky-500/30 shadow-sm'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-white/5 border border-transparent'
                }`
              }
            >
              <div className="flex items-center gap-3">
                <span className="text-current opacity-80">{item.icon}</span>
                <span>{item.label}</span>
              </div>
              {item.badge !== undefined && (
                <span
                  className={`px-1.5 py-0.5 rounded text-[10px] font-mono font-bold ${
                    item.badgeColor === 'amber'
                      ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40'
                      : 'bg-sky-500/20 text-sky-300 border border-sky-500/40'
                  }`}
                >
                  {item.badge}
                </span>
              )}
            </NavLink>
          ))}
        </nav>

        {/* Node Storage Info / Footer */}
        <div className="p-4 border-t border-white/10 bg-industrial-950/40 text-xs font-mono">
          <div className="flex items-center justify-between text-slate-400 mb-1">
            <span className="text-[10px] text-slate-500 uppercase">Local Memory</span>
            <span className="text-slate-300 text-[10px]">
              {metrics?.edge_mutable_points ?? 0} pts
            </span>
          </div>
          <div className="w-full bg-industrial-800 rounded-full h-1.5 overflow-hidden">
            <div
              className="bg-emerald-500 h-full rounded-full transition-all duration-500"
              style={{
                width: `${Math.min(100, Math.max(10, ((metrics?.embedded_chunks || 1) / Math.max(1, (metrics?.embedded_chunks || 1) + (metrics?.unembedded_chunks || 0))) * 100))}%`,
              }}
            />
          </div>
          <div className="flex items-center justify-between text-[10px] text-slate-500 mt-2">
            <span>Offline Resilience</span>
            <span className="text-emerald-400 font-bold">ACTIVE</span>
          </div>
        </div>
      </aside>
    </>
  )
}
