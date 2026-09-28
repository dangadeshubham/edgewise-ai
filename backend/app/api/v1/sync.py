"""EDGEWISE AI — Synchronization API (Phase 6 Durable Queue)

Endpoints:
  GET  /api/sync/status   — Queue size, pending/processing/failed counts, retry stats
  GET  /api/sync/queue    — Inspect queue items with status filter & pagination
  GET  /api/sync/history  — Inspect historical sync attempts with duration & error categories
  POST /api/sync/run      — Run local queue processing lifecycle (LocalNoopSyncBackend in Phase 6)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.schemas.api import (
    SyncHistoryItem,
    SyncHistoryResponse,
    SyncQueueItem,
    SyncQueueResponse,
    SyncRunResponse,
    SyncStatusResponse,
)
from app.services.edge_memory import get_edge_memory_service
from app.services.synchronization.edge_sync_service import EdgeCloudSyncService
from app.services.synchronization.qdrant_backend import QdrantServerSyncBackend
from app.services.synchronization.queue_service import SyncQueueService

settings = get_settings()
router = APIRouter()


@router.get("/status", response_model=SyncStatusResponse)
async def get_sync_status(
    db: AsyncSession = Depends(get_db),
) -> SyncStatusResponse:
    """
    Get current synchronization status and real queue metrics calculated from SQLite,
    plus true Qdrant Server remote connectivity status.
    Zero fabricated numbers.
    """
    queue_service = SyncQueueService(db)
    stats = await queue_service.get_queue_statistics()

    # Real Qdrant Server probe
    backend = QdrantServerSyncBackend()
    cloud_available = await backend.health_check()

    # Real Edge Shard point counts
    edge_service = get_edge_memory_service()
    immutable_points = edge_service.count_points("immutable") if edge_service.has_immutable_shard() else 0

    return SyncStatusResponse(
        state=stats["state"],
        queue_size=stats["queue_size"],
        pending_count=stats["pending_count"],
        processing_count=stats["processing_count"],
        synced_count=stats["synced_count"],
        failed_count=stats["failed_count"],
        conflict_count=stats["conflict_count"],
        last_sync=stats["latest_successful_sync"],
        next_retry=stats["next_retry_at"],
        current_device_id=stats["current_device_id"],
        ready_pending_count=stats["ready_pending_count"],
        cancelled_count=stats["cancelled_count"],
        retrying_count=stats["retrying_count"],
        oldest_pending_at=stats["oldest_pending_at"],
        latest_successful_sync=stats["latest_successful_sync"],
        total_attempts=stats["total_attempts"],
        average_attempt_duration_ms=stats["average_attempt_duration_ms"],
        cloud_available=cloud_available,
        qdrant_server_url=settings.qdrant_server_url,
        qdrant_collection=settings.qdrant_collection_name,
        snapshot_state="ready" if edge_service.is_healthy("immutable") else "unpopulated",
        immutable_shard_points=immutable_points,
        uploaded_count=stats["synced_count"],
    )


@router.post("/run", response_model=SyncRunResponse)
async def run_sync(
    batch_size: int = Query(default=20, ge=1, le=100, description="Max items to process in this run"),
    apply_cloud_to_edge: bool = Query(default=True, description="Refresh local immutable shard from cloud after upload"),
    db: AsyncSession = Depends(get_db),
) -> SyncRunResponse:
    """
    Execute real bidirectional Edge ↔ Cloud synchronization:
    - Verifies Qdrant Server availability
    - Uploads pending local items (Edge → Cloud)
    - Reconciles cloud points and detects conflicts
    - Refreshes local immutable shard (Cloud → Edge)
    - Cleans up duplicate mutable vectors safely
    """
    sync_service = EdgeCloudSyncService(db)
    result = await sync_service.run_full_sync(
        batch_size=batch_size,
        apply_cloud_to_edge=apply_cloud_to_edge,
    )
    total_processed = result.uploaded + result.deleted + result.failed
    return SyncRunResponse(
        message=result.message,
        items_processed=total_processed,
        items_succeeded=result.uploaded + result.deleted,
        items_failed=result.failed,
        conflicts_detected=result.conflicts,
        duration_ms=result.duration_ms,
        started=result.started,
        uploaded=result.uploaded,
        deleted=result.deleted,
        failed=result.failed,
        conflicts=result.conflicts,
        snapshot_applied=result.snapshot_applied,
        server_points_count=result.server_points_count,
    )


@router.get("/queue", response_model=SyncQueueResponse)
async def get_sync_queue(
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=50, ge=1, le=100, description="Items per page"),
    status: str | None = Query(default=None, description="Filter by status (pending, processing, synced, failed, conflict, cancelled)"),
    db: AsyncSession = Depends(get_db),
) -> SyncQueueResponse:
    """
    Get paginated items in the durable synchronization queue.
    """
    import math

    queue_service = SyncQueueService(db)
    items, total = await queue_service.get_queue_items(page=page, page_size=page_size, status=status)
    queue_items = [SyncQueueItem.model_validate(item) for item in items]
    total_pages = math.ceil(total / page_size) if total > 0 else 0
    return SyncQueueResponse(
        items=queue_items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/history", response_model=SyncHistoryResponse)
async def get_sync_history(
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=50, ge=1, le=100, description="Items per page"),
    status: str | None = Query(default=None, description="Filter by status (success, failed, conflict)"),
    db: AsyncSession = Depends(get_db),
) -> SyncHistoryResponse:
    """
    Get paginated synchronization attempt history directly from SQLite sync_attempts table.
    """
    import math

    queue_service = SyncQueueService(db)
    attempts, total = await queue_service.get_history_items(page=page, page_size=page_size, status=status)
    history_items = [SyncHistoryItem.model_validate(attempt) for attempt in attempts]
    total_pages = math.ceil(total / page_size) if total > 0 else 0
    return SyncHistoryResponse(
        items=history_items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )
