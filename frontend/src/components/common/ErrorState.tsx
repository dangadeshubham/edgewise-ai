import React from 'react'
import { AlertTriangle, RefreshCw } from 'lucide-react'

interface ErrorStateProps {
  title?: string
  message: string
  onRetry?: () => void
  className?: string
}

export const ErrorState: React.FC<ErrorStateProps> = ({
  title = 'Operation Error',
  message,
  onRetry,
  className = '',
}) => {
  return (
    <div
      className={`p-6 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-200 flex flex-col gap-3 ${className}`}
    >
      <div className="flex items-center gap-2">
        <AlertTriangle className="w-5 h-5 text-rose-400 shrink-0" />
        <h3 className="text-sm font-semibold text-rose-100">{title}</h3>
      </div>
      <p className="text-xs text-rose-300 font-mono leading-relaxed break-words">{message}</p>
      {onRetry && (
        <div>
          <button
            onClick={onRetry}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-rose-500/20 hover:bg-rose-500/30 border border-rose-500/40 text-xs font-medium text-rose-100 transition-colors"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            Retry Query
          </button>
        </div>
      )}
    </div>
  )
}
