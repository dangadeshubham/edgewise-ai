"""
EDGEWISE AI — Pydantic Request/Response Schemas

API contracts for all endpoints. Every response shape is defined here,
ensuring consistent typing and validation across the system.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


# =============================================================================
# Common
# =============================================================================

class PaginationParams(BaseModel):
    page: int = Field(1, ge=1)
    page_size: int = Field(50, ge=1, le=200)


class PaginatedResponse(BaseModel):
    total: int
    page: int
    page_size: int
    total_pages: int
    items: list[Any]


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
    request_id: Optional[str] = None


class SuccessResponse(BaseModel):
    message: str
    data: Optional[Any] = None


# =============================================================================
# Health
# =============================================================================

class ComponentHealth(BaseModel):
    name: str
    status: str  # healthy, unhealthy, degraded, unknown
    latency_ms: Optional[float] = None
    message: Optional[str] = None


class HealthResponse(BaseModel):
    status: str  # healthy, degraded, unhealthy
    version: str
    device_id: str
    uptime_seconds: float
    components: list[ComponentHealth]
    timestamp: datetime


class ReadinessResponse(BaseModel):
    ready: bool
    checks: dict[str, bool]


class LivenessResponse(BaseModel):
    alive: bool


# =============================================================================
# Connectivity
# =============================================================================

class ConnectivityResponse(BaseModel):
    state: str  # online, offline, degraded, syncing
    internet_available: bool
    qdrant_cloud_available: bool
    ollama_available: bool
    local_database_available: bool
    edge_shard_available: bool
    last_check: Optional[datetime] = None


# =============================================================================
# Documents
# =============================================================================

class DocumentUploadResponse(BaseModel):
    id: str
    filename: str
    mime_type: str
    file_size: int
    content_hash: str
    processing_status: str
    message: str
    is_duplicate: bool = False
    version: int = 1


class DocumentResponse(BaseModel):
    id: str
    device_id: str
    source_id: Optional[str] = None
    filename: str
    original_filename: str
    mime_type: str
    file_size: int
    content_hash: str
    title: Optional[str] = None
    description: Optional[str] = None
    document_type: Optional[str] = None
    processing_status: str
    processing_error: Optional[str] = None
    sensitivity: str
    sync_status: str
    version: int
    revision: int
    origin_device: Optional[str] = None
    chunk_count: int
    created_at: datetime
    updated_at: datetime
    indexed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class DocumentVersionResponse(BaseModel):
    id: str
    document_id: str
    version: int
    content_hash: str
    file_size: int
    change_summary: Optional[str] = None
    created_by_device: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class DocumentListResponse(PaginatedResponse):
    items: list[DocumentResponse]


# =============================================================================
# Search
# =============================================================================

class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    limit: int = Field(10, ge=1, le=100)
    source_filter: Optional[list[str]] = None
    device_filter: Optional[list[str]] = None
    document_type_filter: Optional[list[str]] = None
    sensitivity_filter: Optional[list[str]] = None
    min_score: Optional[float] = Field(None, ge=0.0, le=1.0)


class SearchResultItem(BaseModel):
    id: str
    content: str
    score: float
    document_id: Optional[str] = None
    document_title: Optional[str] = None
    filename: Optional[str] = None
    source_name: Optional[str] = None
    document_type: Optional[str] = None
    device_id: Optional[str] = None
    chunk_index: Optional[int] = None
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    metadata: Optional[dict[str, Any]] = None


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResultItem]
    total_results: int
    retrieval_latency_ms: float
    search_type: str = "semantic"  # semantic, hybrid, keyword


# =============================================================================
# AI Copilot
# =============================================================================

class CopilotQueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)
    conversation_id: Optional[str] = None
    max_sources: int = Field(5, ge=1, le=20)


class SourceCitation(BaseModel):
    document_id: Optional[str] = None
    document_title: Optional[str] = None
    chunk_id: Optional[str] = None
    filename: Optional[str] = None
    source_name: Optional[str] = None
    content_preview: str
    relevance_score: float
    chunk_index: Optional[int] = None
    page_start: Optional[int] = None
    page_end: Optional[int] = None


class EvidenceInfo(BaseModel):
    """Real evidence metrics — no fake confidence percentages."""
    chunk_count: int
    source_count: int
    top_retrieval_score: float
    retrieval_threshold_applied: Optional[float] = None


class CopilotQueryResponse(BaseModel):
    conversation_id: str
    answer: str
    sources: list[SourceCitation]
    evidence: EvidenceInfo
    retrieval_latency_ms: float
    generation_latency_ms: float
    total_latency_ms: float
    embedding_latency_ms: float
    offline_mode: bool
    model_used: Optional[str] = None
    insufficient_evidence: bool = False


# =============================================================================
# Memory
# =============================================================================

class MemoryRecordCreate(BaseModel):
    content: str = Field(..., min_length=1)
    record_type: str = Field("note", pattern="^(chunk|note|observation|record)$")
    sensitivity: str = Field("internal")
    metadata: Optional[dict[str, Any]] = None


class MemoryRecordResponse(BaseModel):
    id: str
    device_id: str
    source_id: Optional[str] = None
    document_id: Optional[str] = None
    content: str
    content_hash: str
    record_type: str
    sensitivity: str
    sync_status: str
    version: int
    revision: int
    origin_device: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MemoryListResponse(PaginatedResponse):
    items: list[MemoryRecordResponse]


# =============================================================================
# Synchronization
# =============================================================================

class SyncStatusResponse(BaseModel):
    state: str  # idle, syncing, error
    queue_size: int
    pending_count: int
    processing_count: int
    synced_count: int
    failed_count: int
    conflict_count: int
    last_sync: Optional[datetime] = None
    next_retry: Optional[datetime] = None
    current_device_id: str


class SyncRunResponse(BaseModel):
    message: str
    items_processed: int
    items_succeeded: int
    items_failed: int
    conflicts_detected: int
    duration_ms: float


class SyncHistoryItem(BaseModel):
    id: str
    record_type: str
    record_id: str
    operation: str
    status: str
    retry_count: int
    last_error: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class SyncHistoryResponse(PaginatedResponse):
    items: list[SyncHistoryItem]


class SyncQueueItem(BaseModel):
    id: str
    record_type: str
    record_id: str
    operation: str
    status: str
    priority: int
    retry_count: int
    next_retry_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class SyncQueueResponse(PaginatedResponse):
    items: list[SyncQueueItem]


# =============================================================================
# Conflicts
# =============================================================================

class ConflictResponse(BaseModel):
    id: str
    record_type: str
    record_id: str
    local_revision: int
    local_content_hash: str
    local_updated_at: datetime
    local_content_preview: Optional[str] = None
    local_device_id: str
    cloud_revision: int
    cloud_content_hash: str
    cloud_updated_at: datetime
    cloud_content_preview: Optional[str] = None
    cloud_device_id: Optional[str] = None
    status: str
    resolution: Optional[str] = None
    resolved_by: Optional[str] = None
    resolved_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ConflictResolveRequest(BaseModel):
    resolution: str = Field(
        ...,
        pattern="^(keep_local|keep_cloud|merge|manual)$"
    )
    resolution_notes: Optional[str] = None
    merged_content: Optional[str] = None  # Required if resolution is "merge" or "manual"


class ConflictListResponse(PaginatedResponse):
    items: list[ConflictResponse]


# =============================================================================
# Devices
# =============================================================================

class DeviceCreate(BaseModel):
    id: Optional[str] = Field(None, description="Device UUID. Automatically generated if omitted.")
    name: str = Field(..., min_length=1, max_length=255, description="Device display name")
    site: str = Field(..., min_length=1, max_length=255, description="Site location")
    status: str = Field("active", pattern="^(active|inactive|offline|degraded)$")
    software_version: Optional[str] = Field(None, max_length=64)

    @field_validator("id")
    @classmethod
    def validate_uuid(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            import uuid
            try:
                parsed = uuid.UUID(v)
                return str(parsed)
            except (ValueError, AttributeError):
                raise ValueError("id must be a valid UUID string")
        return v


class DeviceResponse(BaseModel):
    id: str
    name: str
    site: str
    status: str
    software_version: Optional[str] = None
    last_seen: Optional[datetime] = None
    last_sync: Optional[datetime] = None
    pending_changes: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DeviceListResponse(BaseModel):
    devices: list[DeviceResponse]


# =============================================================================
# Activity
# =============================================================================

class ActivityEvent(BaseModel):
    id: str
    device_id: Optional[str] = None
    event_type: str
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    description: str
    severity: str
    details: Optional[dict[str, Any]] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ActivityListResponse(PaginatedResponse):
    items: list[ActivityEvent]


# =============================================================================
# Dashboard
# =============================================================================

class DashboardMetrics(BaseModel):
    connectivity_state: str
    local_memory_records: int
    local_vector_count: int
    cloud_record_count: Optional[int] = None
    pending_sync: int
    failed_sync: int
    open_conflicts: int
    last_successful_sync: Optional[datetime] = None
    current_device_id: str
    current_device_name: str
    current_device_site: str
    total_documents: int
    processed_documents: int
    failed_documents: int
    storage_usage_bytes: Optional[int] = None
    edge_mutable_points: int = 0
    edge_immutable_points: int = 0
    embedded_chunks: int = 0
    unembedded_chunks: int = 0
    edge_storage_path: Optional[str] = None
    edge_shard_available: bool = True
    edge_last_flush: Optional[datetime] = None
