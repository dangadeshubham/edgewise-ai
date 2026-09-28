/**
 * EDGEWISE AI — API Client Service
 * Strictly consumes real FastAPI endpoints without data fabrication.
 */

import type {
  ActivityListResponse,
  ComprehensiveHealthResponse,
  ConflictDiffDetailResponse,
  ConflictListResponse,
  ConflictResolveRequest,
  ConflictResponse,
  ConflictSuggestMergeResponse,
  ConnectivityStatusResponse,
  ConversationDetail,
  ConversationSummary,
  CopilotQueryRequest,
  CopilotQueryResponse,
  DashboardMetrics,
  DeviceListResponse,
  DeviceResponse,
  DocumentDetailResponse,
  DocumentListResponse,
  DocumentResponse,
  MemoryListResponse,
  MemoryRecordResponse,
  SyncHistoryResponse,
  SyncQueueResponse,
  SyncRunResponse,
  SyncStatusResponse,
} from '../types'

const BASE_URL = ''

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let errorDetail = `HTTP ${res.status}: ${res.statusText}`
    try {
      const body = await res.json()
      if (body.detail) {
        errorDetail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
      } else if (body.error) {
        errorDetail = body.error
      }
    } catch {
      // Body not JSON
    }
    throw new Error(errorDetail)
  }
  return res.json() as Promise<T>
}

export const api = {
  // --- Connectivity & Health ---
  async getConnectivity(): Promise<ConnectivityStatusResponse> {
    const res = await fetch(`${BASE_URL}/system/connectivity`)
    return handleResponse<ConnectivityStatusResponse>(res)
  },

  async getHealth(): Promise<ComprehensiveHealthResponse> {
    const res = await fetch(`${BASE_URL}/health`)
    return handleResponse<ComprehensiveHealthResponse>(res)
  },

  // --- Dashboard ---
  async getDashboardMetrics(): Promise<DashboardMetrics> {
    const res = await fetch(`${BASE_URL}/api/dashboard/metrics`)
    return handleResponse<DashboardMetrics>(res)
  },

  // --- AI Copilot ---
  async queryCopilot(payload: CopilotQueryRequest, signal?: AbortSignal): Promise<CopilotQueryResponse> {
    const res = await fetch(`${BASE_URL}/api/copilot/query`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal,
    })
    return handleResponse<CopilotQueryResponse>(res)
  },

  async listConversations(limit: number = 20): Promise<ConversationSummary[]> {
    const res = await fetch(`${BASE_URL}/api/copilot/conversations?limit=${limit}`)
    return handleResponse<ConversationSummary[]>(res)
  },

  async getConversation(id: string): Promise<ConversationDetail> {
    const res = await fetch(`${BASE_URL}/api/copilot/conversations/${id}`)
    return handleResponse<ConversationDetail>(res)
  },

  // --- Documents ---
  async listDocuments(page: number = 1, pageSize: number = 20, status?: string): Promise<DocumentListResponse> {
    let url = `${BASE_URL}/api/documents?page=${page}&page_size=${pageSize}`
    if (status) url += `&status=${encodeURIComponent(status)}`
    const res = await fetch(url)
    return handleResponse<DocumentListResponse>(res)
  },

  async getDocument(id: string): Promise<DocumentDetailResponse> {
    const res = await fetch(`${BASE_URL}/api/documents/${id}`)
    return handleResponse<DocumentDetailResponse>(res)
  },

  async uploadDocument(file: File, title?: string, sourceId?: string): Promise<DocumentResponse> {
    const formData = new FormData()
    formData.append('file', file)
    if (title) formData.append('title', title)
    if (sourceId) formData.append('source_id', sourceId)

    const res = await fetch(`${BASE_URL}/api/documents/upload`, {
      method: 'POST',
      body: formData,
    })
    return handleResponse<DocumentResponse>(res)
  },

  async reindexDocument(id: string): Promise<{ success: boolean; message: string }> {
    const res = await fetch(`${BASE_URL}/api/documents/${id}/reindex`, {
      method: 'POST',
    })
    return handleResponse<{ success: boolean; message: string }>(res)
  },

  async deleteDocument(id: string): Promise<{ success: boolean; message: string }> {
    const res = await fetch(`${BASE_URL}/api/documents/${id}`, {
      method: 'DELETE',
    })
    return handleResponse<{ success: boolean; message: string }>(res)
  },

  // --- Memory ---
  async listMemory(page: number = 1, pageSize: number = 20, query?: string, sensitivity?: string, syncStatus?: string): Promise<MemoryListResponse> {
    let url = `${BASE_URL}/api/memory?page=${page}&page_size=${pageSize}`
    if (query) url += `&query=${encodeURIComponent(query)}`
    if (sensitivity) url += `&sensitivity=${encodeURIComponent(sensitivity)}`
    if (syncStatus) url += `&sync_status=${encodeURIComponent(syncStatus)}`
    const res = await fetch(url)
    return handleResponse<MemoryListResponse>(res)
  },

  async getMemoryRecord(id: string): Promise<MemoryRecordResponse> {
    const res = await fetch(`${BASE_URL}/api/memory/${id}`)
    return handleResponse<MemoryRecordResponse>(res)
  },

  // --- Synchronization (Phases 6 & 7) ---
  async getSyncStatus(): Promise<SyncStatusResponse> {
    const res = await fetch(`${BASE_URL}/api/sync/status`)
    return handleResponse<SyncStatusResponse>(res)
  },

  async getSyncQueue(page: number = 1, pageSize: number = 20, status?: string): Promise<SyncQueueResponse> {
    let url = `${BASE_URL}/api/sync/queue?page=${page}&page_size=${pageSize}`
    if (status) url += `&status=${encodeURIComponent(status)}`
    const res = await fetch(url)
    return handleResponse<SyncQueueResponse>(res)
  },

  async getSyncHistory(page: number = 1, pageSize: number = 20): Promise<SyncHistoryResponse> {
    const res = await fetch(`${BASE_URL}/api/sync/history?page=${page}&page_size=${pageSize}`)
    return handleResponse<SyncHistoryResponse>(res)
  },

  async runSync(batchSize: number = 20, applyCloudToEdge: boolean = true): Promise<SyncRunResponse> {
    const res = await fetch(`${BASE_URL}/api/sync/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ batch_size: batchSize, apply_cloud_to_edge: applyCloudToEdge }),
    })
    return handleResponse<SyncRunResponse>(res)
  },

  // --- Conflicts (Phase 8) ---
  async listConflicts(status?: string, sortBy: string = 'newest', limit: number = 50, offset: number = 0): Promise<ConflictListResponse> {
    let url = `${BASE_URL}/api/conflicts?sort_by=${sortBy}&limit=${limit}&offset=${offset}`
    if (status) url += `&status=${encodeURIComponent(status)}`
    const res = await fetch(url)
    return handleResponse<ConflictListResponse>(res)
  },

  async getConflict(id: string): Promise<ConflictDiffDetailResponse> {
    const res = await fetch(`${BASE_URL}/api/conflicts/${id}`)
    return handleResponse<ConflictDiffDetailResponse>(res)
  },

  async claimConflict(id: string, claimedBy: string = 'operator', expectedVersion?: number): Promise<ConflictResponse> {
    const res = await fetch(`${BASE_URL}/api/conflicts/${id}/claim`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ claimed_by: claimedBy, expected_version: expectedVersion }),
    })
    return handleResponse<ConflictResponse>(res)
  },

  async resolveConflict(id: string, payload: ConflictResolveRequest): Promise<ConflictResponse> {
    const res = await fetch(`${BASE_URL}/api/conflicts/${id}/resolve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    return handleResponse<ConflictResponse>(res)
  },

  async dismissConflict(id: string, dismissedBy: string = 'operator', reason?: string, expectedVersion?: number): Promise<ConflictResponse> {
    const res = await fetch(`${BASE_URL}/api/conflicts/${id}/dismiss`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dismissed_by: dismissedBy, reason, expected_version: expectedVersion }),
    })
    return handleResponse<ConflictResponse>(res)
  },

  async suggestMerge(id: string): Promise<ConflictSuggestMergeResponse> {
    const res = await fetch(`${BASE_URL}/api/conflicts/${id}/suggest-merge`, {
      method: 'POST',
    })
    return handleResponse<ConflictSuggestMergeResponse>(res)
  },

  // --- Devices ---
  async listDevices(): Promise<DeviceListResponse> {
    const res = await fetch(`${BASE_URL}/api/devices`)
    return handleResponse<DeviceListResponse>(res)
  },

  async getDevice(id: string): Promise<DeviceResponse> {
    const res = await fetch(`${BASE_URL}/api/devices/${id}`)
    return handleResponse<DeviceResponse>(res)
  },

  // --- Activity ---
  async listActivity(page: number = 1, pageSize: number = 25, entityType?: string): Promise<ActivityListResponse> {
    let url = `${BASE_URL}/api/activity?page=${page}&page_size=${pageSize}`
    if (entityType) url += `&entity_type=${encodeURIComponent(entityType)}`
    const res = await fetch(url)
    return handleResponse<ActivityListResponse>(res)
  },
}
