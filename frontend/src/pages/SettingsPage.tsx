import React from 'react'
import { useQuery } from '@tanstack/react-query'
import { Shield, HardDrive, Cpu, Layers, Lock } from 'lucide-react'
import { api } from '../services/api'
import { StatusBadge } from '../components/common/StatusBadge'

export const SettingsPage: React.FC = () => {
  const { data: metrics } = useQuery({
    queryKey: ['dashboardMetrics'],
    queryFn: api.getDashboardMetrics,
  })

  const { data: connectivity } = useQuery({
    queryKey: ['connectivity'],
    queryFn: api.getConnectivity,
  })

  const { data: health } = useQuery({
    queryKey: ['health'],
    queryFn: api.getHealth,
  })

  return (
    <div className="space-y-6 max-w-4xl">
      {/* Header */}
      <div>
        <h1 className="text-xl font-bold text-slate-100 tracking-tight">System Configuration & Node Diagnostics</h1>
        <p className="text-xs text-slate-400 mt-0.5">
          Local node specifications, runtime environment, vector index paths, and security policies.
        </p>
      </div>

      {/* Security Assurance Banner */}
      <div className="p-4 rounded-xl bg-industrial-900/60 border border-white/10 flex items-start gap-3 text-xs font-mono text-slate-300">
        <Lock className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
        <div>
          <span className="font-bold text-slate-200">Security & Secret Isolation:</span>
          <p className="text-slate-400 mt-0.5 leading-relaxed">
            API keys, remote bearer tokens, and cryptographic secrets are kept strictly server-side in memory and environment variables. No secrets are exposed to browser clients or logs.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Node Identity Card */}
        <div className="p-5 rounded-xl bg-industrial-900/80 border border-white/10 space-y-3 font-mono text-xs">
          <div className="flex items-center gap-2 border-b border-white/10 pb-2 text-slate-200 font-bold">
            <Cpu className="w-4 h-4 text-sky-400" />
            <span>Node Identity</span>
          </div>
          <div className="space-y-2">
            <div className="flex justify-between">
              <span className="text-slate-500">Device ID:</span>
              <span className="text-slate-300 font-bold">{metrics?.current_device_id || 'edge-001'}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Name:</span>
              <span className="text-slate-300">{metrics?.current_device_name || 'Edge Node 001'}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Assigned Facility / Site:</span>
              <span className="text-slate-300">{metrics?.current_device_site || 'Facility A'}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Application Mode:</span>
              <span className="text-emerald-400 font-bold uppercase">{health?.app_mode || 'OFFLINE_FIRST'}</span>
            </div>
          </div>
        </div>

        {/* Vector Architecture & Storage Card */}
        <div className="p-5 rounded-xl bg-industrial-900/80 border border-white/10 space-y-3 font-mono text-xs">
          <div className="flex items-center gap-2 border-b border-white/10 pb-2 text-slate-200 font-bold">
            <Layers className="w-4 h-4 text-emerald-400" />
            <span>Qdrant Edge Vector Storage</span>
          </div>
          <div className="space-y-2">
            <div className="flex justify-between">
              <span className="text-slate-500">Embedding Model:</span>
              <span className="text-slate-300">all-MiniLM-L6-v2 (384-dim)</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Mutable Shard Points:</span>
              <span className="text-slate-300">{metrics?.edge_mutable_points ?? 0}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Immutable Shard Points:</span>
              <span className="text-slate-300">{metrics?.edge_immutable_points ?? 0}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Storage Root:</span>
              <span className="text-slate-400">{metrics?.edge_storage_path || 'data/qdrant_edge'}</span>
            </div>
          </div>
        </div>

        {/* AI & Local Copilot Configuration */}
        <div className="p-5 rounded-xl bg-industrial-900/80 border border-white/10 space-y-3 font-mono text-xs">
          <div className="flex items-center gap-2 border-b border-white/10 pb-2 text-slate-200 font-bold">
            <Shield className="w-4 h-4 text-purple-400" />
            <span>Local AI Model Engine</span>
          </div>
          <div className="space-y-2">
            <div className="flex justify-between">
              <span className="text-slate-500">LLM Provider:</span>
              <span className="text-slate-300">Ollama (Local daemon)</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Ollama Health:</span>
              <StatusBadge status={connectivity?.dependencies?.ollama?.status || 'offline'} size="sm" />
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Retrieval Grounding:</span>
              <span className="text-emerald-400 font-bold">STRICT (Zero Hallucination Guard)</span>
            </div>
          </div>
        </div>

        {/* Cloud Synchronization Policy */}
        <div className="p-5 rounded-xl bg-industrial-900/80 border border-white/10 space-y-3 font-mono text-xs">
          <div className="flex items-center gap-2 border-b border-white/10 pb-2 text-slate-200 font-bold">
            <HardDrive className="w-4 h-4 text-amber-400" />
            <span>Cloud Sync Policy</span>
          </div>
          <div className="space-y-2">
            <div className="flex justify-between">
              <span className="text-slate-500">Batch Processing Size:</span>
              <span className="text-slate-300">20 records / batch</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Retry Policy:</span>
              <span className="text-slate-300">Exponential Backoff (Max 5 attempts)</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Conflict Quarantine:</span>
              <span className="text-slate-300">Strict Non-Overwriting Boundary</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
