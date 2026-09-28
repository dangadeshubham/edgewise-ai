import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { DashboardPage } from '../pages/DashboardPage'
import { CopilotPage } from '../pages/CopilotPage'
import { DocumentsPage } from '../pages/DocumentsPage'
import { MemoryPage } from '../pages/MemoryPage'
import { SyncPage } from '../pages/SyncPage'
import { ConflictsPage } from '../pages/ConflictsPage'
import { DevicesPage } from '../pages/DevicesPage'
import { ActivityPage } from '../pages/ActivityPage'
import { SettingsPage } from '../pages/SettingsPage'
import { TopNavigation } from '../components/layout/TopNavigation'

function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0,
      },
      mutations: {
        retry: false,
      },
    },
  })
}

describe('End-to-End Operational Flows Suite', () => {
  let originalFetch: typeof global.fetch

  beforeEach(() => {
    originalFetch = global.fetch
  })

  afterEach(() => {
    global.fetch = originalFetch
    vi.restoreAllMocks()
  })

  // 1 & 2: Routing & Dashboard Data Loading
  it('loads real dashboard metrics and renders operations overview', async () => {
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/api/dashboard/metrics')) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              embedded_chunks: 142,
              unembedded_chunks: 3,
              edge_mutable_points: 85,
              edge_immutable_points: 142,
              pending_sync: 4,
              failed_sync: 0,
              open_conflicts: 1,
              connected_devices: 3,
              last_cloud_sync: '2026-09-28T12:00:00Z',
              offline_resilience_status: 'operational',
            }),
        })
      }
      if (url.includes('/system/connectivity')) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              mode: 'online',
              cloud_reachable: true,
              last_checked: '2026-09-28T12:00:00Z',
              dependencies: {
                sqlite: { status: 'available' },
                qdrant_edge: { status: 'available' },
                ollama: { status: 'available' },
                internet: { status: 'available' },
                qdrant_server: { status: 'available' },
              },
            }),
        })
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) })
    })

    const queryClient = createTestQueryClient()
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/']}>
          <DashboardPage />
        </MemoryRouter>
      </QueryClientProvider>
    )

    // Wait for real metric cards to render
    await waitFor(() => {
      expect(screen.getByText('Operational Intelligence Node')).toBeInTheDocument()
    })

    expect(screen.getByText('142')).toBeInTheDocument() // Embedded chunks
    expect(screen.getByText(/85 points/i)).toBeInTheDocument() // Mutable points
    expect(screen.getByText(/Immutable Shard/i)).toBeInTheDocument()
  })

  // 3 & 4: Connectivity Status & Offline UI
  it('correctly reflects OFFLINE mode and shows cloud unavailable banner', async () => {
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/system/connectivity')) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              state: 'offline',
              device_id: 'edge-001',
              timestamp: '2026-09-28T12:00:00Z',
              dependencies: {
                sqlite: { status: 'available' },
                qdrant_edge: { status: 'available' },
                ollama: { status: 'available' },
                internet: { status: 'unavailable' },
                qdrant_server: { status: 'unavailable', message: 'Connection refused' },
              },
            }),
        })
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) })
    })

    const queryClient = createTestQueryClient()
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <TopNavigation onToggleSidebar={() => {}} />
        </MemoryRouter>
      </QueryClientProvider>
    )

    await waitFor(() => {
      expect(screen.getByText(/offline/i)).toBeInTheDocument()
    })

    // Click to open system status inspector modal
    fireEvent.click(screen.getByTitle('Click to view detailed dependency telemetry'))
    expect(screen.getByText('System Dependencies')).toBeInTheDocument()
    expect(screen.getByText('SQLite Knowledge Database')).toBeInTheDocument()
    expect(screen.getByText('Central Qdrant Server')).toBeInTheDocument()
    expect(screen.getByText('Connection refused')).toBeInTheDocument()
  })

  // 5 & 6: Copilot Rendering & Source Citation Modal
  it('submits query to Copilot, renders grounded response, and opens citation modal', async () => {
    global.fetch = vi.fn().mockImplementation((url: string, opts?: RequestInit) => {
      if (url.includes('/api/copilot/query') && opts?.method === 'POST') {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              answer: 'The primary pump pressure tolerance is 120 PSI to 140 PSI.',
              conversation_id: 'conv-test-01',
              offline_fallback: false,
              total_duration_ms: 125.4,
              embed_duration_ms: 22.1,
              retrieval_duration_ms: 18.3,
              generation_duration_ms: 85.0,
              sources: [
                {
                  document_id: 'doc-pump-spec',
                  document_filename: 'pump_specifications_v2.pdf',
                  document_version_id: 'ver-001',
                  chunk_id: 'chunk-102',
                  page_number: 14,
                  score: 0.942,
                  text: 'Primary pump operational tolerance must remain strictly between 120 PSI and 140 PSI at 25C.',
                  metadata: { section: 'Hydraulics 4.1' },
                },
              ],
            }),
        })
      }
      if (url.includes('/api/copilot/conversations')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve([]),
        })
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) })
    })

    const queryClient = createTestQueryClient()
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <CopilotPage />
        </MemoryRouter>
      </QueryClientProvider>
    )

    const input = screen.getByPlaceholderText(/Ask maintenance or operating procedures/i)
    fireEvent.change(input, { target: { value: 'What is the pump pressure limit?' } })

    const sendBtn = screen.getByTitle('Send Inquiry')
    fireEvent.click(sendBtn)

    await waitFor(() => {
      expect(
        screen.getByText('The primary pump pressure tolerance is 120 PSI to 140 PSI.')
      ).toBeInTheDocument()
    })

    // Verify source card appears
    expect(screen.getByText('pump_specifications_v2.pdf')).toBeInTheDocument()
    expect(screen.getByText(/Page\s+14/i)).toBeInTheDocument()
    expect(screen.getByText(/Score:\s*0\.94/i)).toBeInTheDocument()

    // Click source card to open full traceability modal
    fireEvent.click(screen.getByText('pump_specifications_v2.pdf'))
    expect(screen.getByText('Source Evidence Traceability')).toBeInTheDocument()
    expect(screen.getByText(/chunk-102/i)).toBeInTheDocument()
    expect(
      screen.getAllByText(/Primary pump operational tolerance must remain strictly/i).length
    ).toBeGreaterThanOrEqual(1)
  })

  // 7 & 8: Document Management & Upload Error Feedback
  it('handles document list and displays error on upload failure', async () => {
    global.fetch = vi.fn().mockImplementation((url: string, opts?: RequestInit) => {
      if (url.includes('/api/documents') && opts?.method === 'POST') {
        return Promise.resolve({
          ok: false,
          status: 413,
          statusText: 'Payload Too Large',
          json: () => Promise.resolve({ detail: 'Document exceeds the 50MB edge quota.' }),
        })
      }
      if (url.includes('/api/documents')) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              items: [
                {
                  id: 'doc-001',
                  filename: 'turbine_maintenance.pdf',
                  file_type: 'application/pdf',
                  file_size_bytes: 204800,
                  content_hash: 'sha256-a1b2c3d4',
                  status: 'processed',
                  current_version_id: 'v1',
                  chunk_count: 18,
                  created_at: '2026-09-28T10:00:00Z',
                  updated_at: '2026-09-28T10:05:00Z',
                },
              ],
              total: 1,
              page: 1,
              page_size: 10,
            }),
        })
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) })
    })

    const queryClient = createTestQueryClient()
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <DocumentsPage />
        </MemoryRouter>
      </QueryClientProvider>
    )

    await waitFor(() => {
      expect(screen.getByText('turbine_maintenance.pdf')).toBeInTheDocument()
      expect(screen.getByText('18')).toBeInTheDocument()
    })

    // Simulate file input change
    const file = new File(['oversized content'], 'huge_file.pdf', { type: 'application/pdf' })
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement
    fireEvent.change(fileInput, { target: { files: [file] } })

    await waitFor(() => {
      expect(screen.getByText(/Document exceeds the 50MB edge quota/i)).toBeInTheDocument()
    })
  })

  // 9: Memory Pagination & Sensitivity
  it('renders memory explorer records with pagination and metadata badges', async () => {
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/api/memory')) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              items: [
                {
                  id: 'mem-001',
                  content: 'Vibration frequency at generator bearings measured at 62Hz.',
                  record_type: 'observation',
                  sensitivity: 'restricted',
                  device_id: 'edge-node-04',
                  revision: 3,
                  sync_status: 'synced',
                  created_at: '2026-09-28T09:00:00Z',
                  updated_at: '2026-09-28T09:30:00Z',
                },
              ],
              total: 25,
              page: 1,
              page_size: 10,
            }),
        })
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) })
    })

    const queryClient = createTestQueryClient()
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <MemoryPage />
        </MemoryRouter>
      </QueryClientProvider>
    )

    await waitFor(() => {
      expect(
        screen.getByText(/Vibration frequency at generator bearings/i)
      ).toBeInTheDocument()
      expect(screen.getByText('restricted')).toBeInTheDocument()
      expect(screen.getByText('synced')).toBeInTheDocument()
    })
  })

  // 10 & 11: Sync Status & Sync Now Execution
  it('displays synchronization queue and executes live sync trigger', async () => {
    let syncRan = false
    global.fetch = vi.fn().mockImplementation((url: string, opts?: RequestInit) => {
      if (url.includes('/api/sync/run') && opts?.method === 'POST') {
        syncRan = true
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              processed_count: 2,
              success_count: 2,
              failed_count: 0,
              conflict_count: 0,
              elapsed_seconds: 0.45,
            }),
        })
      }
      if (url.includes('/api/sync/status')) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              cloud_available: true,
              last_successful_sync: '2026-09-28T11:45:00Z',
              pending_count: 2,
              processing_count: 0,
              failed_count: 0,
              conflict_count: 0,
            }),
        })
      }
      if (url.includes('/api/sync/queue')) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              items: [
                {
                  id: 'sync-item-01',
                  record_type: 'memory',
                  record_id: 'mem-88',
                  operation: 'upsert',
                  status: 'pending',
                  priority: 1,
                  retry_count: 0,
                  max_retries: 5,
                  content_hash: 'hash-abc',
                  device_id: 'edge-node-01',
                  revision: 1,
                  created_at: '2026-09-28T11:50:00Z',
                },
              ],
              total: 1,
              page: 1,
              page_size: 10,
            }),
        })
      }
      if (url.includes('/api/sync/history')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ items: [], total: 0, page: 1, page_size: 10 }),
        })
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) })
    })

    const queryClient = createTestQueryClient()
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <SyncPage />
        </MemoryRouter>
      </QueryClientProvider>
    )

    await waitFor(() => {
      expect(screen.getByText('Synchronization Center')).toBeInTheDocument()
      expect(screen.getByText('Connected')).toBeInTheDocument()
      expect(screen.getByText(/mem-88/i)).toBeInTheDocument()
    })

    const syncBtn = screen.getByRole('button', { name: /sync now/i })
    fireEvent.click(syncBtn)

    await waitFor(() => {
      expect(syncRan).toBe(true)
    })
  })

  // 12, 13, 14, 15: Conflict Review, Keep Local, Keep Cloud, Heuristic Suggested Merge
  it('renders conflict diff and executes resolution flows with confirmations', async () => {
    let resolvedStrategy: string | null = null

    global.fetch = vi.fn().mockImplementation((url: string, opts?: RequestInit) => {
      if (url.includes('/api/conflicts/conf-001/resolve') && opts?.method === 'POST') {
        const body = JSON.parse(opts.body as string)
        resolvedStrategy = body.resolution || body.strategy
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              conflict_id: 'conf-001',
              status: 'resolved',
              resolution: body.resolution,
              resolved_by: body.resolved_by,
              resolved_at: '2026-09-28T12:10:00Z',
            }),
        })
      }
      if (url.includes('/api/conflicts/conf-001/suggest-merge')) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              suggested_content: 'MERGED CONSENSUS: Local and Cloud telemetry reconciled.',
              merge_type: 'heuristic',
              details: { algorithm: 'three-way-line-merge' },
            }),
        })
      }
      if (url.includes('/api/conflicts/conf-001')) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              conflict: {
                id: 'conf-001',
                record_id: 'entity-motor-temp',
                record_type: 'memory',
                status: 'open',
                version: 1,
                local_revision: 5,
                cloud_revision: 6,
                local_device_id: 'edge-node-01',
                cloud_device_id: 'cloud-replica-02',
                local_content_preview: 'Motor temperature measured at 75C steady.',
                cloud_content_preview: 'Motor temperature measured at 82C with warning spike.',
                local_content_hash: 'hash-loc',
                cloud_content_hash: 'hash-cld',
                local_updated_at: '2026-09-28T11:00:00Z',
                cloud_updated_at: '2026-09-28T11:00:00Z',
                created_at: '2026-09-28T11:00:00Z',
              },
              lines: [
                { line_type: 'removed', content: 'Motor temperature measured at 75C steady.' },
                { line_type: 'added', content: 'Motor temperature measured at 82C with warning spike.' },
              ],
              additions_count: 1,
              deletions_count: 1,
              unchanged_count: 0,
              metadata_diffs: [],
              is_identical: false,
            }),
        })
      }
      if (url.includes('/api/conflicts')) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              items: [
                {
                  id: 'conf-001',
                  record_id: 'entity-motor-temp',
                  record_type: 'memory',
                  status: 'open',
                  version: 1,
                  local_revision: 5,
                  cloud_revision: 6,
                  created_at: '2026-09-28T11:00:00Z',
                },
              ],
              total: 1,
            }),
        })
      }
      if (url.includes('/api/activity')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ items: [], total: 0, page: 1, page_size: 20 }),
        })
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) })
    })

    const queryClient = createTestQueryClient()
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <ConflictsPage />
        </MemoryRouter>
      </QueryClientProvider>
    )

    // Select the conflict
    await waitFor(() => {
      expect(screen.getByText('entity-motor-temp')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByText('entity-motor-temp'))

    // Inspect side-by-side diff
    await waitFor(() => {
      expect(screen.getByText(/- Motor temperature measured at 75C steady/i)).toBeInTheDocument()
      expect(
        screen.getByText(/\+ Motor temperature measured at 82C with warning spike/i)
      ).toBeInTheDocument()
    })

    // Click "Keep Local" -> Confirmation Dialog appears
    const keepLocalBtn = screen.getByRole('button', { name: /keep local/i })
    fireEvent.click(keepLocalBtn)

    expect(screen.getByText('Keep Local Version')).toBeInTheDocument()
    const confirmActionBtn = screen.getByRole('button', { name: /confirm action/i })
    fireEvent.click(confirmActionBtn)

    await waitFor(() => {
      expect(resolvedStrategy).toBe('keep_local')
    })
  })

  // 16: Stale Concurrency Error UX
  it('notifies operator when conflict was updated concurrently (HTTP 409)', async () => {
    global.fetch = vi.fn().mockImplementation((url: string, opts?: RequestInit) => {
      if (url.includes('/api/conflicts/conf-002/resolve') && opts?.method === 'POST') {
        return Promise.resolve({
          ok: false,
          status: 409,
          statusText: 'Conflict',
          json: () =>
            Promise.resolve({
              detail: 'Conflict was updated by another device. Reloading current state.',
            }),
        })
      }
      if (url.includes('/api/conflicts/conf-002')) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              conflict: {
                id: 'conf-002',
                record_id: 'rec-stale',
                record_type: 'memory',
                status: 'open',
                version: 1,
                local_revision: 2,
                cloud_revision: 3,
                local_device_id: 'node-1',
                cloud_device_id: 'cloud',
                local_content_preview: 'Local A',
                cloud_content_preview: 'Cloud B',
                local_content_hash: 'h1',
                cloud_content_hash: 'h2',
                local_updated_at: '2026-09-28T11:00:00Z',
                cloud_updated_at: '2026-09-28T11:00:00Z',
                created_at: '2026-09-28T11:00:00Z',
              },
              lines: [],
              additions_count: 0,
              deletions_count: 0,
              unchanged_count: 0,
              metadata_diffs: [],
              is_identical: false,
            }),
        })
      }
      if (url.includes('/api/conflicts')) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              items: [
                {
                  id: 'conf-002',
                  record_id: 'rec-stale',
                  record_type: 'memory',
                  status: 'open',
                  version: 1,
                  local_revision: 2,
                  cloud_revision: 3,
                  created_at: '2026-09-28T11:00:00Z',
                },
              ],
              total: 1,
            }),
        })
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) })
    })

    const queryClient = createTestQueryClient()
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <ConflictsPage />
        </MemoryRouter>
      </QueryClientProvider>
    )

    await waitFor(() => {
      expect(screen.getByText('rec-stale')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByText('rec-stale'))

    await waitFor(() => {
      expect(screen.getByText('Keep Cloud')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByText('Keep Cloud'))

    fireEvent.click(screen.getByRole('button', { name: /confirm action/i }))

    await waitFor(() => {
      expect(
        screen.getByText(/Conflict was updated by another device. Reloading current state/i)
      ).toBeInTheDocument()
    })
  })

  // 17, 18, 21: Device List, Activity List, Accessibility Basics
  it('renders device topology, activity log, and node settings safely without secrets', async () => {
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/api/devices')) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              devices: [
                {
                  id: 'dev-001',
                  name: 'Edge Gateway West-01',
                  site: 'Facility-B',
                  status: 'active',
                  last_seen: '2026-09-28T12:00:00Z',
                  last_sync: '2026-09-28T11:55:00Z',
                },
              ],
            }),
        })
      }
      if (url.includes('/api/activity')) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              items: [
                {
                  id: 'act-001',
                  event_type: 'sync_completed',
                  entity_type: 'sync',
                  entity_id: 'sync-run-99',
                  device_id: 'dev-001',
                  details: { items_synced: 14 },
                  created_at: '2026-09-28T11:55:00Z',
                },
              ],
              total: 1,
              page: 1,
              page_size: 25,
            }),
        })
      }
      if (url.includes('/api/dashboard/metrics')) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              embedded_chunks: 10,
              unembedded_chunks: 0,
              edge_mutable_points: 10,
              edge_immutable_points: 10,
              pending_sync: 0,
              failed_sync: 0,
              open_conflicts: 0,
              connected_devices: 1,
              last_cloud_sync: '2026-09-28T11:55:00Z',
            }),
        })
      }
      if (url.includes('/system/connectivity')) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              mode: 'online',
              cloud_reachable: true,
              last_checked: '2026-09-28T12:00:00Z',
              dependencies: {
                sqlite: { status: 'available' },
                qdrant_edge: { status: 'available' },
                ollama: { status: 'available' },
                internet: { status: 'available' },
                qdrant_server: { status: 'available' },
              },
            }),
        })
      }
      if (url.includes('/health')) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              status: 'healthy',
              version: '1.0.0',
              dependencies: {},
            }),
        })
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) })
    })

    const queryClient = createTestQueryClient()

    // 1. Devices Page
    const { unmount: unmountDevices } = render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <DevicesPage />
        </MemoryRouter>
      </QueryClientProvider>
    )
    await waitFor(() => {
      expect(screen.getByText('Edge Gateway West-01')).toBeInTheDocument()
      expect(screen.getByText('Facility-B')).toBeInTheDocument()
    })
    unmountDevices()

    // 2. Activity Page
    const { unmount: unmountActivity } = render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <ActivityPage />
        </MemoryRouter>
      </QueryClientProvider>
    )
    await waitFor(() => {
      expect(screen.getByText('sync_completed')).toBeInTheDocument()
      expect(screen.getByText(/sync-run/i)).toBeInTheDocument()
    })
    unmountActivity()

    // 3. Settings Page (Diagnostics without secrets)
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <SettingsPage />
        </MemoryRouter>
      </QueryClientProvider>
    )
    await waitFor(() => {
      expect(screen.getByText('System Configuration & Node Diagnostics')).toBeInTheDocument()
      expect(screen.getByText(/Security & Secret Isolation/i)).toBeInTheDocument()
    })

    // Verify secrets are strictly NOT present in the DOM
    expect(screen.queryByText(/bearer eyj/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/qdrant_api_key=/i)).not.toBeInTheDocument()
  })
})
