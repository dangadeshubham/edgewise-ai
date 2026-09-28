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

from app.core.database import get_db
from app.schemas.api import (
    SyncHistoryItem,
    SyncHistoryResponse,
    SyncQueueItem,
    SyncQueueResponse,
    SyncRunResponse,
    SyncStatusResponse,
)
from app.services.synchronization.engine import SyncEngine
from app.services.synchronization.queue_service import SyncQueueService

router = APIRouter()


@router.get("/status", response_model=SyncStatusResponse)
async def get_sync_status(
    db: AsyncSession = Depends(get_db),
) -> SyncStatusResponse:
    """
    Get current synchronization status and real queue metrics calculated from SQLite.
    Zero fabricated numbers.
    """
    queue_service = SyncQueueService(db)
    stats = await queue_service.get_queue_statistics()
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
    )


@router.post("/run", response_model=SyncRunResponse)
async def run_sync(
    batch_size: int = Query(default=20, ge=1, le=100, description="Max items to process in this run"),
    db: AsyncSession = Depends(get_db),
) -> SyncRunResponse:
    """
    Execute local queue-processing lifecycle over eligible pending items.

    NOTE (Phase 6):
    This endpoint executes the local queue lifecycle using the LocalNoopSyncBackend.
    It does NOT connect to or synchronize with Qdrant Server (Phase 7).
    Data remains durable in local SQLite.
    """
    engine = SyncEngine(db)
    result = await engine.run_batch(batch_size=batch_size)
    return SyncRunResponse(
        message=result.message,
        items_processed=result.items_processed,
        items_succeeded=result.items_succeeded,
        items_failed=result.items_failed,
        conflicts_detected=result.conflicts_detected,
        duration_ms=result.duration_ms,
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
