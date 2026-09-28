import React from 'react'

export interface FilterOption {
  id?: string
  value?: string
  label: string
  count?: number
}

interface FilterBarProps {
  options: FilterOption[]
  selectedId?: string
  activeValue?: string
  onSelect: (idOrValue: string) => void
  className?: string
}

export const FilterBar: React.FC<FilterBarProps> = ({
  options,
  selectedId,
  activeValue,
  onSelect,
  className = '',
}) => {
  const currentActive = selectedId ?? activeValue ?? ''

  return (
    <div className={`flex items-center gap-1.5 overflow-x-auto py-1 ${className}`}>
      {options.map((opt) => {
        const key = opt.id ?? opt.value ?? ''
        const isActive = key === currentActive
        return (
          <button
            key={key || opt.label}
            type="button"
            onClick={() => onSelect(key)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium tracking-wide flex items-center gap-2 whitespace-nowrap transition-colors border ${
              isActive
                ? 'bg-sky-500/15 border-sky-500 text-sky-300 font-semibold shadow-sm'
                : 'bg-industrial-900/60 border-white/5 text-slate-400 hover:text-slate-200 hover:border-white/15'
            }`}
          >
            <span>{opt.label}</span>
            {opt.count !== undefined && (
              <span
                className={`px-1.5 py-0.2 rounded-md font-mono text-[10px] ${
                  isActive
                    ? 'bg-sky-500/30 text-sky-200'
                    : 'bg-white/5 text-slate-500'
                }`}
              >
                {opt.count}
              </span>
            )}
          </button>
        )
      })}
    </div>
  )
}
