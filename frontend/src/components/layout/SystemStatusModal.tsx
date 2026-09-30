import React from 'react'
import { X, CheckCircle2, AlertTriangle, XCircle, HelpCircle } from 'lucide-react'
import type { ConnectivityStatusResponse } from '../../types'
import { formatTime } from '../../utils/date'

interface SystemStatusModalProps {
  isOpen: boolean
  onClose: () => void
  connectivity?: ConnectivityStatusResponse | null
}

export const SystemStatusModal: React.FC<SystemStatusModalProps> = ({
  isOpen,
  onClose,
  connectivity,
}) => {
  if (!isOpen) return null

  const getStatusIcon = (status?: string) => {
    switch (status) {
      case 'available':
        return <CheckCircle2 className="w-4 h-4 text-emerald-400" />
      case 'degraded':
        return <AlertTriangle className="w-4 h-4 text-amber-400" />
      case 'unavailable':
        return <XCircle className="w-4 h-4 text-rose-400" />
      default:
        return <HelpCircle className="w-4 h-4 text-slate-500" />
    }
  }

  const getStatusTextClass = (status?: string) => {
    switch (status) {
      case 'available':
        return 'text-emerald-400'
      case 'degraded':
        return 'text-amber-400'
      case 'unavailable':
        return 'text-rose-400'
      default:
        return 'text-slate-500'
    }
  }

  const deps = connectivity?.dependencies

  const items = [
    { key: 'sqlite', name: 'SQLite Knowledge Database', info: deps?.sqlite, desc: 'Local durable relational and queue storage' },
    { key: 'qdrant_edge', name: 'Qdrant Edge Vector Shards', info: deps?.qdrant_edge, desc: 'Local mutable and immutable embedded vector indexes' },
    { key: 'ollama', name: 'Ollama Local LLM', info: deps?.ollama, desc: 'Local grounded inference engine for Copilot RAG' },
    { key: 'internet', name: 'Wide Area Network (Internet)', info: deps?.internet, desc: 'External IP routing and DNS resolution' },
    { key: 'qdrant_server', name: 'Central Qdrant Server', info: deps?.qdrant_server, desc: 'Remote enterprise vector cluster for sync' },
  ]

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="fixed inset-0 bg-black/80 backdrop-blur-sm" onClick={onClose} />
      <div className="relative bg-industrial-900 border border-white/10 rounded-xl max-w-lg w-full p-6 shadow-2xl z-10">
        <div className="flex items-center justify-between border-b border-white/10 pb-4">
          <div>
            <h3 className="text-base font-semibold text-slate-100 flex items-center gap-2">
              System Dependencies
              <span className="font-mono text-xs text-sky-400 px-2 py-0.5 rounded bg-sky-500/10 border border-sky-500/20 uppercase">
                {connectivity?.state || 'OFFLINE'}
              </span>
            </h3>
            <p className="text-xs text-slate-400 mt-0.5">
              Real telemetry from <code className="text-slate-300">/system/connectivity</code>
            </p>
          </div>
          <button
            onClick={onClose}
            className="text-slate-500 hover:text-slate-300 transition-colors p-1"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="mt-4 space-y-3">
          {items.map((item) => (
            <div
              key={item.key}
              className="p-3 rounded-lg bg-black/40 border border-white/5 flex items-start justify-between gap-3"
            >
              <div className="flex items-start gap-3">
                <div className="mt-0.5">{getStatusIcon(item.info?.status)}</div>
                <div>
                  <div className="text-xs font-semibold text-slate-200">{item.name}</div>
                  <div className="text-[11px] text-slate-400">{item.desc}</div>
                  {item.info?.message && (
                    <div className="text-[10px] font-mono text-rose-300 mt-1">
                      {item.info.message}
                    </div>
                  )}
                </div>
              </div>
              <div className="text-right shrink-0">
                <span
                  className={`text-xs font-mono font-bold uppercase ${getStatusTextClass(
                    item.info?.status
                  )}`}
                >
                  {item.info?.status || 'UNKNOWN'}
                </span>
                {item.info?.latency_ms !== null && item.info?.latency_ms !== undefined && (
                  <div className="text-[10px] font-mono text-slate-500">
                    {item.info.latency_ms.toFixed(1)} ms
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>

        <div className="mt-6 pt-3 border-t border-white/10 flex items-center justify-between text-xs text-slate-500 font-mono">
          <span>Device ID: {connectivity?.device_id || 'unknown'}</span>
          <span>{formatTime(connectivity?.timestamp)}</span>
        </div>
      </div>
    </div>
  )
}
