import React, { useState, useEffect } from 'react'
import { Search, X } from 'lucide-react'

interface SearchBarProps {
  value: string
  onChange: (value: string) => void
  onClear?: () => void
  placeholder?: string
  debounceMs?: number
  className?: string
}

export const SearchBar: React.FC<SearchBarProps> = ({
  value,
  onChange,
  onClear,
  placeholder = 'Search records by content or identifier...',
  debounceMs = 300,
  className = '',
}) => {
  const [internalVal, setInternalVal] = useState(value)

  useEffect(() => {
    setInternalVal(value)
  }, [value])

  useEffect(() => {
    if (debounceMs === 0) {
      if (internalVal !== value) {
        onChange(internalVal)
      }
      return
    }

    const handler = setTimeout(() => {
      if (internalVal !== value) {
        onChange(internalVal)
      }
    }, debounceMs)

    return () => clearTimeout(handler)
  }, [internalVal, debounceMs, onChange, value])

  const handleClear = () => {
    setInternalVal('')
    onChange('')
    if (onClear) onClear()
  }

  return (
    <div className={`relative flex items-center ${className}`}>
      <Search className="absolute left-3 w-4 h-4 text-slate-500 pointer-events-none" />
      <input
        type="text"
        value={internalVal}
        onChange={(e) => {
          setInternalVal(e.target.value)
          if (debounceMs === 0) {
            onChange(e.target.value)
          }
        }}
        placeholder={placeholder}
        className="w-full bg-industrial-900 border border-white/10 rounded-lg pl-9 pr-8 py-2 text-xs font-mono text-slate-100 placeholder:text-slate-500 focus:outline-none focus:border-sky-500/50 transition-colors"
      />
      {internalVal && (
        <button
          type="button"
          aria-label="Clear search"
          onClick={handleClear}
          className="absolute right-2.5 text-slate-500 hover:text-slate-300 transition-colors"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      )}
    </div>
  )
}
