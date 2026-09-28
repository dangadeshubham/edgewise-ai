import React from 'react'
import { Loader2 } from 'lucide-react'

interface LoadingStateProps {
  title?: string
  message?: string
  className?: string
}

export const LoadingState: React.FC<LoadingStateProps> = ({
  title = 'Loading Operations Data...',
  message = 'Querying local SQLite and Qdrant Edge state.',
  className = '',
}) => {
  return (
    <div
      className={`flex flex-col items-center justify-center p-12 text-center rounded-xl bg-industrial-900/50 border border-white/5 ${className}`}
    >
      <Loader2 className="w-8 h-8 text-sky-400 animate-spin mb-3" />
      <h3 className="text-sm font-semibold text-slate-200">{title}</h3>
      <p className="text-xs text-slate-500 mt-1 max-w-sm">{message}</p>
    </div>
  )
}
