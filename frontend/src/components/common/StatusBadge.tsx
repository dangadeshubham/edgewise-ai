import React from 'react'

interface StatusBadgeProps {
  status: string
  label?: string
  className?: string
  size?: 'sm' | 'md'
}

export const StatusBadge: React.FC<StatusBadgeProps> = ({
  status,
  label,
  className = '',
  size = 'md',
}) => {
  const norm = (status || '').toLowerCase()
  const display = label || norm.replace(/_/g, ' ')

  let colorClasses = 'bg-slate-800 text-slate-300 border-slate-700'

  if (['online', 'available', 'synced', 'processed', 'resolved', 'success'].includes(norm)) {
    colorClasses = 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
  } else if (['degraded', 'sync_pending', 'pending', 'in_review', 'open', 'processing'].includes(norm)) {
    colorClasses = 'bg-amber-500/10 text-amber-400 border-amber-500/30'
  } else if (['offline', 'unavailable', 'failed', 'conflict', 'dead_letter'].includes(norm)) {
    colorClasses = 'bg-rose-500/10 text-rose-400 border-rose-500/30'
  } else if (['syncing', 'uploading'].includes(norm)) {
    colorClasses = 'bg-sky-500/10 text-sky-400 border-sky-500/30'
  } else if (['dismissed', 'unknown'].includes(norm)) {
    colorClasses = 'bg-slate-700/30 text-slate-400 border-slate-600/30'
  }

  const sizeClasses = size === 'sm' ? 'px-2 py-0.5 text-xs' : 'px-2.5 py-1 text-xs'

  return (
    <span
      className={`inline-flex items-center gap-1.5 font-mono uppercase tracking-wider font-semibold border rounded-md ${sizeClasses} ${colorClasses} ${className}`}
    >
      <span className="w-1.5 h-1.5 rounded-full bg-current" />
      {display}
    </span>
  )
}
