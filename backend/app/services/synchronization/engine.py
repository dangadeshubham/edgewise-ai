"""EDGEWISE AI — Sync Engine Execution Coordinator (Phase 6)

Coordinates the queue claim-process-record lifecycle:
1. Claims a batch of eligible PENDING items.
2. Dispatches each item to the configured SyncBackend (LocalNoopSyncBackend in Phase 6).
3. Transitions item states and records SyncAttempt telemetry.
4. Ensures crash-resilient exception handling so no item is stranded in PROCESSING.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.services.synchronization.backend import (
    LocalNoopSyncBackend,
    SyncBackend,
    SyncResult,
)
from app.services.synchronization.constants import (
    SyncErrorCategory,
    SyncOperation,
    SyncState,
)
from app.services.synchronization.queue_service import SyncQueueService

settings = get_settings()
logger = structlog.get_logger("edgewise.sync.engine")


@dataclass
class SyncRunResult:
    """Summary of a sync queue execution batch."""
    message: str
    items_processed: int
    items_succeeded: int
    items_failed: int
    conflicts_detected: int
    duration_ms: float


class SyncEngine:
    """
    Executes the sync queue worker loop over a batch of items.
    Phase 6 uses the LocalNoopSyncBackend to verify queue durability
    without uploading to any external Qdrant server.
    """

    def __init__(
        self,
        session: AsyncSession,
        backend: Optional[SyncBackend] = None,
    ) -> None:
        self.session = session
        self.queue_service = SyncQueueService(session)
        self.backend = backend or LocalNoopSyncBackend()

    async def run_batch(
        self,
        batch_size: Optional[int] = None,
        worker_id: Optional[str] = None,
    ) -> SyncRunResult:
        """
        Claim and execute a batch of pending items.
        """
        batch_start = time.perf_counter()
        limit = batch_size or settings.sync_batch_size

        # 1. Claim eligible pending items atomically
        claimed = await self.queue_service.claim_pending(batch_size=limit, worker_id=worker_id)

        items_processed = len(claimed)
        items_succeeded = 0
        items_failed = 0
        conflicts_detected = 0

        for item in claimed:
            try:
                op_str = (item.operation or "upsert").lower()

                # Dispatch to sync backend
                if op_str == SyncOperation.DELETE.value:
                    result: SyncResult = await self.backend.delete(item)
                else:
                    result = await self.backend.upsert(item)

                # Transition item state based on backend outcome
                if result.status == SyncState.SYNCED:
                    await self.queue_service.complete(item.id, duration_ms=result.duration_ms)
                    items_succeeded += 1
                elif result.status == SyncState.CONFLICT:
                    await self.queue_service.mark_conflict(
                        item.id,
                        error_message=result.error_message or "Conflict with remote revision",
                        duration_ms=result.duration_ms,
                    )
                    conflicts_detected += 1
                else:
                    cat = result.error_category or SyncErrorCategory.PERMANENT_FAILURE
                    msg = result.error_message or "Sync operation failed"
                    await self.queue_service.fail(item.id, cat, msg, duration_ms=result.duration_ms)
                    items_failed += 1

            except Exception as exc:
                # Catch-all: prevent any item from remaining stuck in PROCESSING
                logger.error(
                    "sync_execution_unhandled_exception",
                    sync_item_id=item.id,
                    error=str(exc),
                    exc_info=True,
                )
                try:
                    await self.queue_service.fail(
                        item.id,
                        SyncErrorCategory.PERMANENT_FAILURE,
                        f"Unhandled worker exception: {exc}",
                        duration_ms=0.0,
                    )
                except Exception:
                    pass
                items_failed += 1

        total_duration = (time.perf_counter() - batch_start) * 1000

        # Phase 6 phrasing: explicitly states local queue processing, NOT cloud sync
        if items_processed == 0:
            msg = "No pending items in queue to process."
        else:
            msg = (
                f"Processed {items_processed} items locally: "
                f"{items_succeeded} succeeded, {items_failed} failed, {conflicts_detected} conflicts. "
                "(Queued locally — Awaiting Phase 7 Qdrant Server synchronization)"
            )

        return SyncRunResult(
            message=msg,
            items_processed=items_processed,
            items_succeeded=items_succeeded,
            items_failed=items_failed,
            conflicts_detected=conflicts_detected,
            duration_ms=round(total_duration, 2),
        )
