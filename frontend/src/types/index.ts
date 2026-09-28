/**
 * EDGEWISE AI — Frontend TypeScript Type Definitions
 * Matched strictly to backend FastAPI schemas in backend/app/schemas/api.py
 */

// =============================================================================
// Connectivity & Health
// =============================================================================

export interface DependencyStatus {
  status: 'available' | 'unavailable' | 'degraded' | 'unknown'
  message?: string | null
  latency_ms?: number | null
  last_check?: string | null
}

export interface ConnectivityDependencies {
  sqlite: DependencyStatus
  qdrant_edge: DependencyStatus
  ollama: DependencyStatus
  internet: DependencyStatus
  qdrant_server: DependencyStatus
}

export interface ConnectivityStatusResponse {
  state: 'online' | 'offline' | 'degraded' | 'sync_pending' | 'syncing'
  device_id: string
  timestamp: string
  dependencies: ConnectivityDependencies
  consecutive_failures: Record<string, number>
  last_state_change: string
}

export interface ComprehensiveHealthResponse {
  status: string
  app_mode: string
  timestamp: string
  dependencies: Record<string, DependencyStatus>
}

// =============================================================================
// Dashboard
// =============================================================================

export interface DashboardMetrics {
  connectivity_state: string
  local_memory_records: number
  local_vector_count: number
  cloud_record_count?: number | null
  pending_sync: number
  failed_sync: number
  open_conflicts: number
  last_successful_sync?: string | null
  current_device_id: string
  current_device_name: string
  current_device_site: string
  total_documents: number
  processed_documents: number
  failed_documents: number
  storage_usage_bytes?: number | null
  edge_mutable_points: number
  edge_immutable_points: number
  embedded_chunks: number
  unembedded_chunks: number
  edge_storage_path?: string | null
  edge_shard_available: boolean
  edge_last_flush?: string | null
}

// =============================================================================
// Copilot & Retrieval
// =============================================================================

export interface SourceCitation {
  document_id?: string | null
  document_title?: string | null
  chunk_id?: string | null
  filename?: string | null
  source_name?: string | null
  content_preview: string
  relevance_score: number
  chunk_index?: number | null
  page_start?: number | null
  page_end?: number | null
}

export interface EvidenceInfo {
  chunk_count: number
  source_count: number
  top_retrieval_score: number
  retrieval_threshold_applied?: number | null
}

export interface CopilotQueryRequest {
  question: string
  conversation_id?: string | null
  max_sources?: number
}

export interface CopilotQueryResponse {
  conversation_id: string
  answer: string
  sources: SourceCitation[]
  evidence: EvidenceInfo
  retrieval_latency_ms: number
  generation_latency_ms: number
  total_latency_ms: number
  embedding_latency_ms: number
  offline_mode: boolean
  model_used?: string | null
  insufficient_evidence: boolean
}

export interface ConversationSummary {
  id: string
  device_id: string
  title: string
  message_count: number
  created_at: string
  updated_at: string
}

export interface ConversationMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  sources?: SourceCitation[] | null
  created_at: string
}

export interface ConversationDetail {
  conversation: ConversationSummary
  messages: ConversationMessage[]
}

// =============================================================================
// Documents
// =============================================================================

export interface DocumentResponse {
  id: string
  device_id: string
  source_id?: string | null
  title: string
  filename: string
  file_type: string
  file_size_bytes: number
  content_hash: string
  status: 'pending' | 'processing' | 'processed' | 'failed'
  version: number
  revision: number
  chunk_count: number
  created_at: string
  updated_at: string
  error_message?: string | null
}

export interface DocumentChunkResponse {
  id: string
  document_id: string
  chunk_index: number
  content_preview: string
  char_count: number
  page_start?: number | null
  page_end?: number | null
  content_hash: string
  vector_point_id?: string | null
  has_embedding: boolean
}

export interface DocumentDetailResponse {
  document: DocumentResponse
  chunks: DocumentChunkResponse[]
}

export interface DocumentListResponse {
  items: DocumentResponse[]
  total: number
  page: number
  page_size: number
  pages: number
}

// =============================================================================
// Memory Records
// =============================================================================

export interface MemoryRecordResponse {
  id: string
  device_id: string
  source_id?: string | null
  document_id?: string | null
  chunk_id?: string | null
  content: string
  content_hash: string
  record_type: string
  vector_point_id?: string | null
  sensitivity: string
  sync_status: string
  version: number
  revision: number
  origin_device?: string | null
  last_synced_revision?: number | null
  metadata_json?: string | null
  created_at: string
  updated_at: string
}

export interface MemoryListResponse {
  items: MemoryRecordResponse[]
  total: number
  page: number
  page_size: number
  pages: number
}

// =============================================================================
// Synchronization (Phase 6 & 7)
// =============================================================================

export interface SyncStatusResponse {
  status: string
  queue_size: number
  pending_count: number
  processing_count: number
  failed_count: number
  dead_letter_count: number
  open_conflicts_count: number
  last_sync_time?: string | null
  last_sync_duration_ms?: number | null
  last_error?: string | null
  active_processing_count: number
  avg_attempt_count: number
  cloud_available: boolean
  cloud_url?: string | null
  cloud_collection?: string | null
  last_cloud_sync_time?: string | null
  snapshot_status?: string | null
}

export interface SyncQueueItem {
  id: string
  record_type: string
  record_id: string
  operation: string
  status: string
  priority: number
  retry_count: number
  max_retries: number
  revision?: number | null
  content_hash?: string | null
  created_at: string
  scheduled_at?: string | null
  processing_started_at?: string | null
  completed_at?: string | null
  last_error_category?: string | null
  last_error_message?: string | null
}

export interface SyncQueueResponse {
  items: SyncQueueItem[]
  total: number
  page: number
  page_size: number
  pages: number
}

export interface SyncHistoryItem {
  id: string
  sync_item_id: string
  record_type?: string | null
  record_id?: string | null
  operation?: string | null
  attempt_number: number
  status: string
  started_at?: string | null
  completed_at?: string | null
  duration_ms?: number | null
  error_category?: string | null
  error_message?: string | null
  attempted_at: string
}

export interface SyncHistoryResponse {
  items: SyncHistoryItem[]
  total: number
  page: number
  page_size: number
  pages: number
}

export interface SyncRunResponse {
  started: boolean
  processed_count: number
  success_count: number
  failed_count: number
  retry_scheduled_count: number
  uploaded?: number
  deleted?: number
  conflicts?: number
  snapshot_applied?: boolean
  server_points_count?: number
  duration_ms: number
  message?: string
}

// =============================================================================
// Conflicts (Phase 8)
// =============================================================================

export interface ConflictResponse {
  id: string
  record_type: string
  record_id: string
  local_revision: number
  local_content_hash: string
  local_updated_at: string
  local_content_preview?: string | null
  local_device_id: string
  cloud_revision: number
  cloud_content_hash: string
  cloud_updated_at: string
  cloud_content_preview?: string | null
  cloud_device_id?: string | null
  status: 'open' | 'in_review' | 'resolved' | 'dismissed'
  resolution?: 'keep_local' | 'keep_cloud' | 'merge' | 'manual' | null
  resolved_by?: string | null
  resolved_at?: string | null
  resolution_notes?: string | null
  resolution_metadata_json?: string | null
  version: number
  created_at: string
}

export interface ConflictListResponse {
  items: ConflictResponse[]
  total: number
  open_count: number
  in_review_count: number
  resolved_count: number
  dismissed_count: number
}

export interface ConflictDiffLine {
  line_number_local?: number | null
  line_number_cloud?: number | null
  line_type: 'added' | 'removed' | 'unchanged' | 'modified'
  content: string
}

export interface ConflictFieldDiff {
  field_name: string
  local_value: any
  cloud_value: any
  is_different: boolean
}

export interface ConflictDiffDetailResponse {
  conflict: ConflictResponse
  lines: ConflictDiffLine[]
  metadata_diffs: ConflictFieldDiff[]
  json_field_diffs?: ConflictFieldDiff[] | null
  additions_count: number
  deletions_count: number
  unchanged_count: number
  is_identical: boolean
}

export interface ConflictResolveRequest {
  resolution: 'keep_local' | 'keep_cloud' | 'merge' | 'manual'
  merged_content?: string | null
  manual_content?: string | null
  resolved_by?: string
  notes?: string | null
  expected_version?: number | null
}

export interface ConflictSuggestMergeResponse {
  conflict_id: string
  label: string
  source: string
  requires_user_approval: boolean
  suggested_content: string
  note: string
}

// =============================================================================
// Devices & Activity
// =============================================================================

export interface DeviceResponse {
  id: string
  name: string
  site: string
  status: string
  software_version?: string | null
  ip_address?: string | null
  last_heartbeat_at?: string | null
  last_sync_at?: string | null
  created_at: string
}

export interface DeviceListResponse {
  devices: DeviceResponse[]
}

export interface ActivityEvent {
  id: string
  device_id?: string | null
  event_type: string
  entity_type?: string | null
  entity_id?: string | null
  description: string
  severity: string
  details?: Record<string, any> | null
  created_at: string
}

export interface ActivityListResponse {
  items: ActivityEvent[]
  total: number
  page: number
  page_size: number
  pages: number
}
