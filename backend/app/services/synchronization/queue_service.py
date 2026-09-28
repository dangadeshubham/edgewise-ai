"""EDGEWISE AI — Durable Sync Queue Service (Phase 6)

Core SQLite-backed synchronization queue service providing:
- Atomic, race-free claiming of pending work
- Strict state machine transitions
- Restart resilience & crash recovery
- Configurable exponential backoff retry scheduling
- Real SQLite metrics & audit trail logging
- Idempotent enqueue & payload validation
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Sequence

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.database import AuditEvent, MemoryRecord, SyncAttempt, SyncItem
from app.services.synchronization.constants import (
    NON_RETRYABLE_ERROR_CATEGORIES,
    SyncErrorCategory,
    SyncOperation,
    SyncState,
    is_retryable_error,
    validate_transition,
)

settings = get_settings()
logger = structlog.get_logger("edgewise.sync.queue")


def utcnow() -> datetime:
    """Return timezone-aware current UTC datetime."""
    return datetime.now(timezone.utc)


class SyncQueueService:
    """
    Durable, restart-safe synchronization queue backed by SQLite.
    All state modifications strictly follow the SyncState state machine.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # =========================================================================
    # 1. Enqueue (Idempotent)
    # =========================================================================

    async def enqueue(
        self,
        record_type: str,
        record_id: str,
        operation: SyncOperation | str,
        payload: Optional[dict[str, Any] | str] = None,
        revision: int = 1,
        content_hash: Optional[str] = None,
        priority: int = 0,
        max_retries: Optional[int] = None,
        device_id: Optional[str] = None,
    ) -> SyncItem:
        """
        Enqueue a sync item with idempotency guarantees.

        If a pending item for the same (record_type, record_id) already exists:
        - It is superseded with the newest payload, revision, and operation.
        - The stable sync item ID is preserved.
        - Prevents duplicate uncontrolled pending rows in the queue.
        """
        if isinstance(operation, SyncOperation):
            op_str = operation.value
        else:
            op_str = str(operation).lower()

        if op_str not in {SyncOperation.UPSERT.value, SyncOperation.DELETE.value}:
            raise ValueError(f"Invalid sync operation: {operation}")

        # Security: validate and normalize payload_json
        payload_str: Optional[str] = None
        if payload is not None:
            if isinstance(payload, dict):
                # Ensure no sensitive credentials leaked
                sanitized = {k: v for k, v in payload.items() if not k.lower().endswith(("_key", "_secret", "_token", "_password"))}
                payload_str = json.dumps(sanitized)
            elif isinstance(payload, str):
                try:
                    parsed = json.loads(payload)
                    if isinstance(parsed, dict):
                        sanitized = {k: v for k, v in parsed.items() if not k.lower().endswith(("_key", "_secret", "_token", "_password"))}
                        payload_str = json.dumps(sanitized)
                    else:
                        payload_str = payload
                except Exception as e:
                    raise ValueError(f"Invalid payload JSON: {e}")

        now = utcnow()
        dev_id = device_id or settings.device_id
        retries_limit = max_retries if max_retries is not None else settings.sync_max_retries

        # Check for existing PENDING item for this record
        stmt = select(SyncItem).where(
            SyncItem.record_type == record_type,
            SyncItem.record_id == record_id,
            SyncItem.status == SyncState.PENDING.value,
        )
        result = await self.session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing is not None:
            # Supersede existing pending item idempotently
            existing.operation = op_str
            existing.payload_json = payload_str
            existing.revision = max(existing.revision or 1, revision)
            existing.content_hash = content_hash or existing.content_hash
            existing.priority = max(existing.priority or 0, priority)
            existing.next_retry_at = None  # Reset retry timer on update
            existing.updated_at = now
            await self.session.flush()

            logger.info(
                "sync_item_superseded",
                sync_item_id=existing.id,
                record_id=record_id,
                operation=op_str,
                revision=existing.revision,
            )
            return existing

        # Create new SyncItem
        item_id = str(uuid.uuid4())
        item = SyncItem(
            id=item_id,
            record_type=record_type,
            record_id=record_id,
            operation=op_str,
            device_id=dev_id,
            status=SyncState.PENDING.value,
            priority=priority,
            retry_count=0,
            max_retries=retries_limit,
            next_retry_at=None,
            last_error=None,
            payload_json=payload_str,
            revision=revision,
            content_hash=content_hash,
            created_at=now,
            updated_at=now,
        )
        self.session.add(item)
        await self.session.flush()

        logger.info(
            "sync_item_enqueued",
            sync_item_id=item_id,
            record_id=record_id,
            operation=op_str,
            revision=revision,
        )
        return item

    # =========================================================================
    # 2. Claiming Work
    # =========================================================================

    async def claim_pending(
        self,
        batch_size: Optional[int] = None,
        worker_id: Optional[str] = None,
    ) -> list[SyncItem]:
        """
        Atomically claim eligible pending items for processing.

        Eligible items:
        - status == PENDING
        - next_retry_at IS NULL or next_retry_at <= now()
        Ordered by priority DESC, created_at ASC.
        Transitions claimed items from PENDING to PROCESSING.
        """
        limit = batch_size or settings.sync_batch_size
        now = utcnow()

        stmt = (
            select(SyncItem)
            .where(
                SyncItem.status == SyncState.PENDING.value,
                (SyncItem.next_retry_at.is_(None)) | (SyncItem.next_retry_at <= now),
            )
            .order_by(SyncItem.priority.desc(), SyncItem.created_at.asc())
            .limit(limit)
        )

        result = await self.session.execute(stmt)
        items = list(result.scalars().all())

        if not items:
            return []

        claimed: list[SyncItem] = []
        for item in items:
            # Enforce state machine transition
            validate_transition(item.status, SyncState.PROCESSING, item.id)
            item.status = SyncState.PROCESSING.value
            item.processing_started_at = now
            item.updated_at = now
            claimed.append(item)

        await self.session.flush()

        logger.info(
            "sync_items_claimed",
            count=len(claimed),
            worker_id=worker_id,
            item_ids=[i.id for i in claimed],
        )
        return claimed

    # =========================================================================
    # 3. Complete Item (Success)
    # =========================================================================

    async def complete(
        self,
        sync_item_id: str,
        duration_ms: Optional[float] = None,
    ) -> SyncItem:
        """
        Mark a sync item as SYNCED and record a successful attempt.
        Updates linked MemoryRecord sync_status if applicable.
        """
        item = await self._get_item(sync_item_id)
        validate_transition(item.status, SyncState.SYNCED, item.id)

        now = utcnow()
        item.status = SyncState.SYNCED.value
        item.completed_at = now
        item.updated_at = now
        item.processing_started_at = None

        attempt_num = (item.retry_count or 0) + 1

        attempt = SyncAttempt(
            id=str(uuid.uuid4()),
            sync_item_id=item.id,
            attempt_number=attempt_num,
            status="success",
            started_at=item.processing_started_at or now,
            completed_at=now,
            duration_ms=duration_ms,
            error_category=None,
            error_message=None,
            attempted_at=now,
        )
        self.session.add(attempt)

        # Update associated MemoryRecord if present
        if item.record_type == "memory_record":
            await self.session.execute(
                update(MemoryRecord)
                .where(MemoryRecord.id == item.record_id)
                .values(
                    sync_status="synced",
                    last_synced_revision=item.revision,
                    updated_at=now,
                )
            )

        await self.session.flush()

        logger.info(
            "sync_item_completed",
            sync_item_id=item.id,
            record_id=item.record_id,
            duration_ms=duration_ms,
        )
        return item

    # =========================================================================
    # 4. Fail Item (Retry Policy / Exponential Backoff)
    # =========================================================================

    async def fail(
        self,
        sync_item_id: str,
        error_category: SyncErrorCategory | str,
        error_message: str,
        duration_ms: Optional[float] = None,
    ) -> SyncItem:
        """
        Handle item processing failure with exponential backoff retry scheduling.

        - If error is non-retryable OR max_retries reached: transitions to FAILED.
        - If error is retryable and retries remain: transitions PROCESSING → FAILED → PENDING
          with computed next_retry_at exponential backoff timestamp.
        """
        item = await self._get_item(sync_item_id)
        cat_str = error_category.value if isinstance(error_category, SyncErrorCategory) else str(error_category)
        now = utcnow()

        current_retries = item.retry_count or 0
        new_retries = current_retries + 1
        max_allowed = item.max_retries if item.max_retries is not None else settings.sync_max_retries

        retryable = is_retryable_error(cat_str) and (new_retries < max_allowed)

        # Validate transition from PROCESSING to FAILED
        validate_transition(item.status, SyncState.FAILED, item.id)

        safe_err = error_message[:1000] if error_message else "Unknown error"
        item.last_error = f"[{cat_str}] {safe_err}"
        item.retry_count = new_retries
        item.updated_at = now
        item.processing_started_at = None

        if retryable:
            # Transition FAILED → PENDING for scheduled retry
            validate_transition(SyncState.FAILED, SyncState.PENDING, item.id)
            item.status = SyncState.PENDING.value

            # Exponential backoff formula: base * 2^(retries - 1)
            backoff = min(
                settings.sync_max_backoff_seconds,
                settings.sync_base_backoff_seconds * (2 ** max(0, new_retries - 1)),
            )
            item.next_retry_at = now + timedelta(seconds=backoff)

            logger.warning(
                "sync_item_retry_scheduled",
                sync_item_id=item.id,
                retry_count=new_retries,
                max_retries=max_allowed,
                backoff_seconds=backoff,
                next_retry_at=item.next_retry_at.isoformat(),
                error_category=cat_str,
            )
        else:
            # Terminal failure
            item.status = SyncState.FAILED.value
            item.next_retry_at = None

            logger.error(
                "sync_item_permanently_failed",
                sync_item_id=item.id,
                retry_count=new_retries,
                max_retries=max_allowed,
                error_category=cat_str,
                error_message=safe_err,
            )

        # Record attempt
        attempt = SyncAttempt(
            id=str(uuid.uuid4()),
            sync_item_id=item.id,
            attempt_number=new_retries,
            status="failed",
            started_at=now - timedelta(milliseconds=duration_ms or 0),
            completed_at=now,
            duration_ms=duration_ms,
            error_category=cat_str,
            error_message=safe_err,
            attempted_at=now,
        )
        self.session.add(attempt)
        await self.session.flush()

        return item

    # =========================================================================
    # 5. Mark Conflict
    # =========================================================================

    async def mark_conflict(
        self,
        sync_item_id: str,
        error_message: str = "Conflict detected with remote state",
        duration_ms: Optional[float] = None,
    ) -> SyncItem:
        """Mark a sync item as CONFLICT."""
        item = await self._get_item(sync_item_id)
        validate_transition(item.status, SyncState.CONFLICT, item.id)

        now = utcnow()
        item.status = SyncState.CONFLICT.value
        item.last_error = f"[conflict] {error_message}"
        item.updated_at = now
        item.processing_started_at = None

        attempt = SyncAttempt(
            id=str(uuid.uuid4()),
            sync_item_id=item.id,
            attempt_number=(item.retry_count or 0) + 1,
            status="conflict",
            started_at=now,
            completed_at=now,
            duration_ms=duration_ms,
            error_category=SyncErrorCategory.CONFLICT.value,
            error_message=error_message,
            attempted_at=now,
        )
        self.session.add(attempt)
        await self.session.flush()

        logger.warning(
            "sync_item_conflict_recorded",
            sync_item_id=item.id,
            record_id=item.record_id,
        )
        return item

    # =========================================================================
    # 6. Cancel Item
    # =========================================================================

    async def cancel(
        self,
        sync_item_id: str,
        reason: Optional[str] = None,
    ) -> SyncItem:
        """Cancel a pending, failed, or conflicted sync item."""
        item = await self._get_item(sync_item_id)
        validate_transition(item.status, SyncState.CANCELLED, item.id)

        now = utcnow()
        item.status = SyncState.CANCELLED.value
        if reason:
            item.last_error = f"Cancelled: {reason}"
        item.updated_at = now
        item.processing_started_at = None
        await self.session.flush()

        logger.info("sync_item_cancelled", sync_item_id=item.id, reason=reason)
        return item

    # =========================================================================
    # 7. Abandoned Job Recovery (Crash Safety)
    # =========================================================================

    async def recover_abandoned(
        self,
        timeout_seconds: Optional[float] = None,
    ) -> list[SyncItem]:
        """
        Recover items stuck in PROCESSING state due to worker or backend crash.

        Identifies PROCESSING items where processing_started_at is older than timeout.
        Returns eligible items back to PENDING (or marks FAILED if retry limit reached).
        """
        timeout = timeout_seconds if timeout_seconds is not None else settings.sync_processing_timeout_seconds
        cutoff = utcnow() - timedelta(seconds=timeout)

        stmt = select(SyncItem).where(
            SyncItem.status == SyncState.PROCESSING.value,
            (SyncItem.processing_started_at.is_(None)) | (SyncItem.processing_started_at <= cutoff),
        )
        result = await self.session.execute(stmt)
        abandoned_items = list(result.scalars().all())

        if not abandoned_items:
            return []

        recovered: list[SyncItem] = []
        now = utcnow()

        for item in abandoned_items:
            current_retries = item.retry_count or 0
            new_retries = current_retries + 1
            max_allowed = item.max_retries if item.max_retries is not None else settings.sync_max_retries

            # Record attempt for the abandoned job
            attempt = SyncAttempt(
                id=str(uuid.uuid4()),
                sync_item_id=item.id,
                attempt_number=new_retries,
                status="failed",
                started_at=item.processing_started_at or now,
                completed_at=now,
                error_category=SyncErrorCategory.TIMEOUT.value,
                error_message=f"Abandoned job recovered after crash/timeout ({timeout}s)",
                attempted_at=now,
            )
            self.session.add(attempt)

            if new_retries < max_allowed:
                validate_transition(item.status, SyncState.PENDING, item.id)
                item.status = SyncState.PENDING.value
                item.retry_count = new_retries
                item.last_error = f"[timeout] Process crashed during execution; returned to queue (attempt {new_retries}/{max_allowed})"
                item.processing_started_at = None
                item.updated_at = now
                # Small backoff before immediate re-claim
                item.next_retry_at = now + timedelta(seconds=settings.sync_base_backoff_seconds)
            else:
                validate_transition(item.status, SyncState.FAILED, item.id)
                item.status = SyncState.FAILED.value
                item.retry_count = new_retries
                item.last_error = f"[timeout] Process crashed during execution; max retries reached ({max_allowed})"
                item.processing_started_at = None
                item.next_retry_at = None
                item.updated_at = now

            recovered.append(item)

        await self.session.flush()

        logger.warning(
            "abandoned_sync_items_recovered",
            count=len(recovered),
            item_ids=[i.id for i in recovered],
        )
        return recovered

    # =========================================================================
    # 8. Queue Metrics & Observability
    # =========================================================================

    async def get_queue_statistics(self) -> dict[str, Any]:
        """
        Compute real queue metrics directly from SQLite.
        Zero fabricated data.
        """
        now = utcnow()

        # Counts by status
        counts_res = await self.session.execute(
            select(SyncItem.status, func.count(SyncItem.id)).group_by(SyncItem.status)
        )
        status_counts = dict(counts_res.all())

        pending_total = status_counts.get(SyncState.PENDING.value, 0)
        processing_count = status_counts.get(SyncState.PROCESSING.value, 0)
        synced_count = status_counts.get(SyncState.SYNCED.value, 0)
        failed_count = status_counts.get(SyncState.FAILED.value, 0)
        conflict_count = status_counts.get(SyncState.CONFLICT.value, 0)
        cancelled_count = status_counts.get(SyncState.CANCELLED.value, 0)

        # Retrying count: pending items where next_retry_at > now
        retrying_res = await self.session.execute(
            select(func.count(SyncItem.id)).where(
                SyncItem.status == SyncState.PENDING.value,
                SyncItem.next_retry_at > now,
            )
        )
        retrying_count = retrying_res.scalar() or 0

        # Ready pending (eligible for immediate claim)
        ready_pending = pending_total - retrying_count

        # Oldest pending creation timestamp
        oldest_pending_res = await self.session.execute(
            select(func.min(SyncItem.created_at)).where(
                SyncItem.status == SyncState.PENDING.value
            )
        )
        oldest_pending_at = oldest_pending_res.scalar()

        # Latest successful sync completed timestamp
        latest_sync_res = await self.session.execute(
            select(func.max(SyncItem.completed_at)).where(
                SyncItem.status == SyncState.SYNCED.value
            )
        )
        latest_successful_sync = latest_sync_res.scalar()

        # Next upcoming retry timestamp
        next_retry_res = await self.session.execute(
            select(func.min(SyncItem.next_retry_at)).where(
                SyncItem.status == SyncState.PENDING.value,
                SyncItem.next_retry_at > now,
            )
        )
        next_retry_at = next_retry_res.scalar()

        # Sync attempt statistics
        attempt_stats = await self.session.execute(
            select(
                func.count(SyncAttempt.id),
                func.avg(SyncAttempt.duration_ms),
            ).where(SyncAttempt.duration_ms.isnot(None))
        )
        total_attempts, avg_duration = attempt_stats.one()

        avg_duration_rounded = round(avg_duration, 2) if avg_duration is not None else None

        # Queue state derivation
        if processing_count > 0:
            queue_state = "syncing"
        elif failed_count > 0 or conflict_count > 0:
            queue_state = "error"
        else:
            queue_state = "idle"

        return {
            "state": queue_state,
            "queue_size": pending_total + processing_count,
            "pending_count": pending_total,
            "ready_pending_count": ready_pending,
            "processing_count": processing_count,
            "synced_count": synced_count,
            "failed_count": failed_count,
            "conflict_count": conflict_count,
            "cancelled_count": cancelled_count,
            "retrying_count": retrying_count,
            "oldest_pending_at": oldest_pending_at.isoformat() if oldest_pending_at else None,
            "latest_successful_sync": latest_successful_sync.isoformat() if latest_successful_sync else None,
            "next_retry_at": next_retry_at.isoformat() if next_retry_at else None,
            "total_attempts": total_attempts or 0,
            "average_attempt_duration_ms": avg_duration_rounded,
            "current_device_id": settings.device_id,
        }

    # =========================================================================
    # 9. List Items (Queue & History Queries)
    # =========================================================================

    async def get_queue_items(
        self,
        page: int = 1,
        page_size: int = 50,
        status: Optional[str] = None,
    ) -> tuple[list[SyncItem], int]:
        """Paginated retrieval of sync items in the queue."""
        offset = (page - 1) * page_size
        query = select(SyncItem)
        count_query = select(func.count(SyncItem.id))

        if status:
            query = query.where(SyncItem.status == status.lower())
            count_query = count_query.where(SyncItem.status == status.lower())

        query = query.order_by(SyncItem.created_at.desc()).offset(offset).limit(page_size)

        total_res = await self.session.execute(count_query)
        total = total_res.scalar() or 0

        items_res = await self.session.execute(query)
        items = list(items_res.scalars().all())

        return items, total

    async def get_history_items(
        self,
        page: int = 1,
        page_size: int = 50,
        status: Optional[str] = None,
    ) -> tuple[list[SyncAttempt], int]:
        """Paginated retrieval of sync attempts."""
        offset = (page - 1) * page_size
        query = select(SyncAttempt)
        count_query = select(func.count(SyncAttempt.id))

        if status:
            query = query.where(SyncAttempt.status == status.lower())
            count_query = count_query.where(SyncAttempt.status == status.lower())

        query = query.order_by(SyncAttempt.attempted_at.desc()).offset(offset).limit(page_size)

        total_res = await self.session.execute(count_query)
        total = total_res.scalar() or 0

        items_res = await self.session.execute(query)
        items = list(items_res.scalars().all())

        return items, total

    # =========================================================================
    # Internal Helpers
    # =========================================================================

    async def _get_item(self, sync_item_id: str) -> SyncItem:
        """Fetch a sync item by ID or raise ValueError."""
        stmt = select(SyncItem).where(SyncItem.id == sync_item_id)
        result = await self.session.execute(stmt)
        item = result.scalar_one_or_none()
        if item is None:
            raise ValueError(f"Sync item not found: {sync_item_id}")
        return item
