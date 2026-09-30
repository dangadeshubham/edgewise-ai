import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { StatusBadge } from '../components/common/StatusBadge'
import { MetricCard } from '../components/common/MetricCard'
import { ConfirmDialog } from '../components/common/ConfirmDialog'
import { SearchBar } from '../components/common/SearchBar'
import { FilterBar } from '../components/common/FilterBar'
import { Pagination } from '../components/common/Pagination'
import { Database } from 'lucide-react'

describe('Unit Components Suite', () => {
  describe('StatusBadge', () => {
    it('renders positive/available badge correctly', () => {
      render(<StatusBadge status="available" />)
      expect(screen.getByText('available')).toBeInTheDocument()
    })

    it('renders degraded badge correctly with custom label', () => {
      render(<StatusBadge status="degraded" label="DEGRADED SYNC" />)
      expect(screen.getByText('DEGRADED SYNC')).toBeInTheDocument()
    })

    it('renders offline/conflict states properly', () => {
      const { rerender } = render(<StatusBadge status="offline" />)
      expect(screen.getByText('offline')).toBeInTheDocument()

      rerender(<StatusBadge status="conflict" />)
      expect(screen.getByText('conflict')).toBeInTheDocument()
    })
  })

  describe('MetricCard', () => {
    it('renders label, formatted value, and subtitle', () => {
      render(
        <MetricCard
          title="Edge Mutable Points"
          value={1420}
          subtitle="Qdrant Local Store"
          icon={<Database data-testid="metric-icon" />}
        />
      )
      expect(screen.getByText('Edge Mutable Points')).toBeInTheDocument()
      expect(screen.getByText('1,420')).toBeInTheDocument()
      expect(screen.getByText('Qdrant Local Store')).toBeInTheDocument()
      expect(screen.getByTestId('metric-icon')).toBeInTheDocument()
    })

    it('renders loading state when isLoading is true', () => {
      const { container } = render(
        <MetricCard title="Pending Sync" value={0} isLoading={true} />
      )
      expect(container.querySelector('.animate-pulse')).toBeInTheDocument()
    })
  })

  describe('ConfirmDialog', () => {
    it('renders modal with title, message, and details', () => {
      const onConfirm = vi.fn()
      const onCancel = vi.fn()

      render(
        <ConfirmDialog
          isOpen={true}
          title="Confirm Resolution"
          message="Are you sure you want to commit this resolution?"
          details="Target record: mem-rec-001"
          onConfirm={onConfirm}
          onCancel={onCancel}
        />
      )

      expect(screen.getByText('Confirm Resolution')).toBeInTheDocument()
      expect(screen.getByText('Are you sure you want to commit this resolution?')).toBeInTheDocument()
      expect(screen.getByText('Target record: mem-rec-001')).toBeInTheDocument()

      fireEvent.click(screen.getByRole('button', { name: /confirm action/i }))
      expect(onConfirm).toHaveBeenCalledTimes(1)

      fireEvent.click(screen.getByRole('button', { name: /cancel/i }))
      expect(onCancel).toHaveBeenCalledTimes(1)
    })

    it('does not render when isOpen is false', () => {
      render(
        <ConfirmDialog
          isOpen={false}
          title="Hidden"
          message="Should not show"
          onConfirm={() => {}}
          onCancel={() => {}}
        />
      )
      expect(screen.queryByText('Hidden')).not.toBeInTheDocument()
    })
  })

  describe('SearchBar', () => {
    it('calls onChange with search text', () => {
      const onChange = vi.fn()
      render(<SearchBar value="" onChange={onChange} debounceMs={0} placeholder="Search memory records..." />)

      const input = screen.getByPlaceholderText('Search memory records...')
      fireEvent.change(input, { target: { value: 'calibrations' } })
      expect(onChange).toHaveBeenCalledWith('calibrations')
    })

    it('renders clear button and clears search', () => {
      const onClear = vi.fn()
      render(<SearchBar value="active-query" onChange={() => {}} onClear={onClear} />)

      const clearBtn = screen.getByRole('button', { name: /clear search/i })
      fireEvent.click(clearBtn)
      expect(onClear).toHaveBeenCalledTimes(1)
    })
  })

  describe('FilterBar', () => {
    it('renders filter pills and highlights active filter', () => {
      const onSelect = vi.fn()
      const options = [
        { label: 'All', value: '', count: 12 },
        { label: 'Open', value: 'detected', count: 3 },
        { label: 'Resolved', value: 'resolved', count: 9 },
      ]

      render(<FilterBar options={options} activeValue="" onSelect={onSelect} />)

      expect(screen.getByText('All')).toBeInTheDocument()
      expect(screen.getByText('Open')).toBeInTheDocument()
      expect(screen.getByText('3')).toBeInTheDocument()

      fireEvent.click(screen.getByText('Open'))
      expect(onSelect).toHaveBeenCalledWith('detected')
    })
  })

  describe('Pagination', () => {
    it('disables previous button on page 1', () => {
      render(<Pagination currentPage={1} totalPages={4} totalItems={36} onPageChange={() => {}} />)

      const prevBtn = screen.getByRole('button', { name: /previous page/i })
      expect(prevBtn).toBeDisabled()

      const nextBtn = screen.getByRole('button', { name: /next page/i })
      expect(nextBtn).not.toBeDisabled()
    })

    it('triggers onPageChange when clicking next button', () => {
      const onPageChange = vi.fn()
      render(<Pagination currentPage={2} totalPages={5} totalItems={50} onPageChange={onPageChange} />)

      fireEvent.click(screen.getByRole('button', { name: /next page/i }))
      expect(onPageChange).toHaveBeenCalledWith(3)

      fireEvent.click(screen.getByRole('button', { name: /previous page/i }))
      expect(onPageChange).toHaveBeenCalledWith(1)
    })
  })

  describe('Safe Date Formatting (Task H)', () => {
    it('never renders "Invalid Date" for null, undefined, or malformed inputs', async () => {
      const { formatTime, formatDate, formatDateTime } = await import('../utils/date')

      expect(formatTime(null)).toBe('--')
      expect(formatTime(undefined)).toBe('--')
      expect(formatTime('not-a-date')).toBe('--')
      expect(formatTime('')).toBe('--')

      expect(formatDate(null)).toBe('--')
      expect(formatDate(undefined)).toBe('--')
      expect(formatDate('garbage-date')).toBe('--')

      expect(formatDateTime(null)).toBe('--')
      expect(formatDateTime(undefined)).toBe('--')
      expect(formatDateTime('invalid-iso-string')).toBe('--')

      // Valid ISO date formatting
      const iso = '2026-09-30T10:00:00Z'
      expect(formatTime(iso)).not.toBe('Invalid Date')
      expect(formatDate(iso)).not.toBe('Invalid Date')
      expect(formatDateTime(iso)).not.toBe('Invalid Date')
    })
  })
})
