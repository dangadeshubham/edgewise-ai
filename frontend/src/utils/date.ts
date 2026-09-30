/**
 * Safe date and time formatting utilities.
 * Guarantees that "Invalid Date" is never rendered anywhere in the application.
 */

export function isValidDate(d: any): boolean {
  if (!d) return false
  const parsed = new Date(d)
  return !isNaN(parsed.getTime())
}

export function formatTime(value?: string | number | Date | null, fallback = '--'): string {
  if (!value) return fallback
  const d = new Date(value)
  if (isNaN(d.getTime())) return fallback
  return d.toLocaleTimeString()
}

export function formatDate(value?: string | number | Date | null, fallback = '--'): string {
  if (!value) return fallback
  const d = new Date(value)
  if (isNaN(d.getTime())) return fallback
  return d.toLocaleDateString()
}

export function formatDateTime(value?: string | number | Date | null, fallback = '--'): string {
  if (!value) return fallback
  const d = new Date(value)
  if (isNaN(d.getTime())) return fallback
  return d.toLocaleString()
}
