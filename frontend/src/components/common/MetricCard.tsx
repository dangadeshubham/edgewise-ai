import React from 'react'

interface MetricCardProps {
  title: string
  value: string | number
  icon?: React.ReactNode
  subtitle?: string
  trend?: string
  trendColor?: 'emerald' | 'amber' | 'rose' | 'sky' | 'slate'
  isLoading?: boolean
  className?: string
}

export const MetricCard: React.FC<MetricCardProps> = ({
  title,
  value,
  icon,
  subtitle,
  trend,
  trendColor = 'slate',
  isLoading = false,
  className = '',
}) => {
  const trendColorClasses = {
    emerald: 'text-emerald-400',
    amber: 'text-amber-400',
    rose: 'text-rose-400',
    sky: 'text-sky-400',
    slate: 'text-slate-400',
  }[trendColor]

  if (isLoading) {
    return (
      <div
        className={`bg-industrial-900/80 border border-white/10 rounded-xl p-4 flex flex-col justify-between animate-pulse ${className}`}
      >
        <div className="flex items-start justify-between">
          <div className="h-4 bg-white/10 rounded w-24 mb-2" />
          <div className="w-8 h-8 rounded-lg bg-white/5" />
        </div>
        <div className="mt-3">
          <div className="h-8 bg-white/10 rounded w-16 mb-2" />
          <div className="h-3 bg-white/5 rounded w-32" />
        </div>
      </div>
    )
  }

  const formattedValue = typeof value === 'number' ? value.toLocaleString() : value

  return (
    <div
      className={`bg-industrial-900/80 border border-white/10 rounded-xl p-4 flex flex-col justify-between hover:border-sky-500/30 transition-colors shadow-lg backdrop-blur-md ${className}`}
    >
      <div className="flex items-start justify-between">
        <span className="text-xs font-medium text-slate-400 uppercase tracking-wider">
          {title}
        </span>
        {icon && (
          <div className="p-2 rounded-lg bg-white/5 text-sky-400 border border-white/5">
            {icon}
          </div>
        )}
      </div>
      <div className="mt-3">
        <div className="text-2xl font-bold font-mono text-slate-100 tracking-tight">
          {formattedValue}
        </div>
        {(subtitle || trend) && (
          <div className="flex items-center gap-2 mt-1 text-xs">
            {trend && <span className={`font-mono font-medium ${trendColorClasses}`}>{trend}</span>}
            {subtitle && <span className="text-slate-500 truncate">{subtitle}</span>}
          </div>
        )}
      </div>
    </div>
  )
}
