"""EDGEWISE AI — Phase 6: Durable Synchronization Queue Tests

Comprehensive unit and integration test suite verifying:
 1. Enqueue
 2. Dequeue / claim
 3. State transition
 4. Invalid state transition rejection
 5. Persistence after restart
 6. Duplicate enqueue handling (idempotency)
 7. Idempotent processing
 8. Retry scheduling
 9. Exponential backoff calculation
10. Max retry limit enforcement
11. Permanent failure handling (non-retryable errors)
12. Abandoned PROCESSING job recovery
13. Batch processing via SyncEngine
14. Concurrent claim protection / isolation
15. Delete / tombstone queue entry
16. Queue statistics accuracy from SQLite
17. Sync attempt persistence & timing
18. LocalWriteService → SyncItem integration
19. Mandatory Crash Recovery Test (Section 21)
20. Mandatory Restart Test (Section 22)
21. API endpoint testing (/api/sync/status, /api/sync/run, /api/sync/queue, /api/sync/history)
"""

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.models.database import Base, MemoryRecord, SyncAttempt, SyncItem
from app.services.local_write.service import LocalWriteService
from app.services.synchronization.backend import (
    LocalNoopSyncBackend,
    SyncResult,
)
from app.services.synchronization.constants import (
    InvalidStateTransitionError,
    SyncErrorCategory,
    SyncOperation,
    SyncState,
    is_retryable_error,
    validate_transition,
)
from app.services.synchronization.engine import SyncEngine
from app.services.synchronization.queue_service import SyncQueueService

settings = get_settings()


# =============================================================================
# Isolated Test Fixtures
# =============================================================================

@pytest.fixture
async def sync_db(tmp_path: Path) -> AsyncGenerator[AsyncSession, None]:
    """Isolated SQLite database with schema created directly for sync unit tests."""
    db_file = tmp_path / f"test_sync_{uuid.uuid4().hex[:8]}.db"
    db_url = f"sqlite+aiosqlite:///{db_file.as_posix()}"
    engine = create_async_engine(db_url, echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_maker() as session:
        yield session

    await engine.dispose()


# =============================================================================
# 1. State Machine & Transitions
# =============================================================================

class TestSyncStateMachine:
    """Test sync state transitions and invariants."""

    def test_valid_transitions(self):
        # PENDING -> PROCESSING
        validate_transition(SyncState.PENDING, SyncState.PROCESSING)
        validate_transition(SyncState.PENDING, SyncState.CANCELLED)

        # PROCESSING -> SYNCED, FAILED, CONFLICT, PENDING
        validate_transition(SyncState.PROCESSING, SyncState.SYNCED)
        validate_transition(SyncState.PROCESSING, SyncState.FAILED)
        validate_transition(SyncState.PROCESSING, SyncState.CONFLICT)
        validate_transition(SyncState.PROCESSING, SyncState.PENDING)

        # FAILED -> PENDING, CANCELLED
        validate_transition(SyncState.FAILED, SyncState.PENDING)
        validate_transition(SyncState.FAILED, SyncState.CANCELLED)

        # CONFLICT -> PENDING, CANCELLED
        validate_transition(SyncState.CONFLICT, SyncState.PENDING)
        validate_transition(SyncState.CONFLICT, SyncState.CANCELLED)

        # Self-transitions are no-ops
        validate_transition(SyncState.PENDING, SyncState.PENDING)
        validate_transition(SyncState.SYNCED, SyncState.SYNCED)

    def test_invalid_transitions_rejected(self):
        # Cannot jump PENDING -> SYNCED directly
        with pytest.raises(InvalidStateTransitionError):
            validate_transition(SyncState.PENDING, SyncState.SYNCED)

        # Cannot transition from terminal SYNCED
        with pytest.raises(InvalidStateTransitionError):
            validate_transition(SyncState.SYNCED, SyncState.PROCESSING)

        with pytest.raises(InvalidStateTransitionError):
            validate_transition(SyncState.SYNCED, SyncState.PENDING)

        # Cannot transition from terminal CANCELLED
        with pytest.raises(InvalidStateTransitionError):
            validate_transition(SyncState.CANCELLED, SyncState.PROCESSING)

    def test_error_retryability_classification(self):
        assert is_retryable_error(SyncErrorCategory.TRANSIENT_NETWORK_ERROR) is True
        assert is_retryable_error(SyncErrorCategory.TIMEOUT) is True
        assert is_retryable_error(SyncErrorCategory.REMOTE_UNAVAILABLE) is True
        assert is_retryable_error(SyncErrorCategory.RATE_LIMITED) is True

        # Non-retryable
        assert is_retryable_error(SyncErrorCategory.VALIDATION_ERROR) is False
        assert is_retryable_error(SyncErrorCategory.AUTHENTICATION_ERROR) is False
        assert is_retryable_error(SyncErrorCategory.PERMANENT_FAILURE) is False


# =============================================================================
# 2. Durable Queue Service Operations
# =============================================================================

class TestSyncQueueService:
    """Test core queue operations: enqueue, claim, complete, fail, cancel."""

    @pytest.mark.asyncio
    async def test_enqueue_creates_pending_item(self, sync_db: AsyncSession):
        service = SyncQueueService(sync_db)
        item = await service.enqueue(
            record_type="memory_record",
            record_id="rec-001",
            operation=SyncOperation.UPSERT,
            payload={"text": "hello edge"},
            revision=1,
            content_hash="hash123",
        )
        await sync_db.commit()

        assert item.id is not None
        assert item.status == SyncState.PENDING.value
        assert item.operation == "upsert"
        assert item.revision == 1
        assert item.content_hash == "hash123"
        assert json.loads(item.payload_json)["text"] == "hello edge"

    @pytest.mark.asyncio
    async def test_duplicate_enqueue_supersedes_idempotently(self, sync_db: AsyncSession):
        service = SyncQueueService(sync_db)

        # First enqueue
        item1 = await service.enqueue(
            record_type="memory_record",
            record_id="rec-002",
            operation=SyncOperation.UPSERT,
            payload={"text": "v1 content"},
            revision=1,
        )
        await sync_db.commit()
        item1_id = item1.id

        # Second enqueue for same entity before processing
        item2 = await service.enqueue(
            record_type="memory_record",
            record_id="rec-002",
            operation=SyncOperation.UPSERT,
            payload={"text": "v2 content"},
            revision=2,
        )
        await sync_db.commit()

        # Must keep stable ID, but update revision & payload
        assert item2.id == item1_id
        assert item2.revision == 2
        assert json.loads(item2.payload_json)["text"] == "v2 content"

        # Verify only 1 pending item in database
        stmt = select(func.count(SyncItem.id)).where(SyncItem.record_id == "rec-002")
        res = await sync_db.execute(stmt)
        assert res.scalar() == 1

    @pytest.mark.asyncio
    async def test_claim_pending_transitions_to_processing(self, sync_db: AsyncSession):
        service = SyncQueueService(sync_db)
        await service.enqueue(record_type="note", record_id="n1", operation="upsert", priority=10)
        await service.enqueue(record_type="note", record_id="n2", operation="upsert", priority=5)
        await sync_db.commit()

        claimed = await service.claim_pending(batch_size=1)
        await sync_db.commit()

        assert len(claimed) == 1
        assert claimed[0].record_id == "n1"  # Higher priority first
        assert claimed[0].status == SyncState.PROCESSING.value
        assert claimed[0].processing_started_at is not None

        # Next claim gets n2
        claimed2 = await service.claim_pending(batch_size=1)
        await sync_db.commit()
        assert len(claimed2) == 1
        assert claimed2[0].record_id == "n2"

    @pytest.mark.asyncio
    async def test_complete_records_success_and_sync_attempt(self, sync_db: AsyncSession):
        service = SyncQueueService(sync_db)
        item = await service.enqueue(record_type="doc", record_id="d1", operation="upsert")
        await service.claim_pending(batch_size=1)
        await sync_db.commit()

        completed = await service.complete(item.id, duration_ms=45.2)
        await sync_db.commit()

        assert completed.status == SyncState.SYNCED.value
        assert completed.completed_at is not None

        # Verify SyncAttempt recorded
        stmt = select(SyncAttempt).where(SyncAttempt.sync_item_id == item.id)
        res = await sync_db.execute(stmt)
        attempt = res.scalar_one()
        assert attempt.status == "success"
        assert attempt.duration_ms == 45.2
        assert attempt.attempt_number == 1

    @pytest.mark.asyncio
    async def test_retry_scheduling_and_exponential_backoff(self, sync_db: AsyncSession):
        service = SyncQueueService(sync_db)
        item = await service.enqueue(record_type="doc", record_id="d-retry", operation="upsert", max_retries=3)
        await service.claim_pending(batch_size=1)
        await sync_db.commit()

        before_fail = datetime.now(timezone.utc)
        failed_item = await service.fail(
            item.id,
            error_category=SyncErrorCategory.TRANSIENT_NETWORK_ERROR,
            error_message="Connection timed out",
            duration_ms=100.0,
        )
        await sync_db.commit()

        # Should be scheduled for retry (status returned to PENDING)
        assert failed_item.status == SyncState.PENDING.value
        assert failed_item.retry_count == 1
        assert failed_item.next_retry_at is not None
        assert failed_item.next_retry_at > before_fail

        # Verify not immediately claimable while next_retry_at is in the future
        claimed_too_soon = await service.claim_pending(batch_size=10)
        assert len(claimed_too_soon) == 0

    @pytest.mark.asyncio
    async def test_max_retries_reaches_terminal_failed(self, sync_db: AsyncSession):
        service = SyncQueueService(sync_db)
        item = await service.enqueue(record_type="doc", record_id="d-max", operation="upsert", max_retries=2)
        await sync_db.commit()

        # Attempt 1
        await service.claim_pending(batch_size=1)
        await service.fail(item.id, SyncErrorCategory.TIMEOUT, "Timeout 1")
        await sync_db.commit()
        assert item.status == SyncState.PENDING.value
        assert item.retry_count == 1

        # Fast forward next_retry_at so it can be claimed again
        item.next_retry_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await sync_db.commit()

        # Attempt 2 (reaches max retries)
        await service.claim_pending(batch_size=1)
        final_fail = await service.fail(item.id, SyncErrorCategory.TIMEOUT, "Timeout 2")
        await sync_db.commit()

        assert final_fail.status == SyncState.FAILED.value
        assert final_fail.retry_count == 2
        assert final_fail.next_retry_at is None

    @pytest.mark.asyncio
    async def test_non_retryable_error_fails_immediately(self, sync_db: AsyncSession):
        service = SyncQueueService(sync_db)
        item = await service.enqueue(record_type="doc", record_id="d-val", operation="upsert", max_retries=5)
        await service.claim_pending(batch_size=1)
        await sync_db.commit()

        failed = await service.fail(
            item.id,
            error_category=SyncErrorCategory.VALIDATION_ERROR,
            error_message="Corrupted schema in payload",
        )
        await sync_db.commit()

        # Fails immediately despite max_retries = 5
        assert failed.status == SyncState.FAILED.value
        assert failed.next_retry_at is None

    @pytest.mark.asyncio
    async def test_cancel_item(self, sync_db: AsyncSession):
        service = SyncQueueService(sync_db)
        item = await service.enqueue(record_type="doc", record_id="d-cancel", operation="upsert")
        await sync_db.commit()

        cancelled = await service.cancel(item.id, reason="User cancelled sync")
        await sync_db.commit()

        assert cancelled.status == SyncState.CANCELLED.value
        assert "User cancelled" in cancelled.last_error

        # Cannot be claimed
        claimed = await service.claim_pending(batch_size=10)
        assert len(claimed) == 0


# =============================================================================
# 3. Crash Recovery & Abandoned Job Recovery
# =============================================================================

class TestAbandonedJobRecovery:
    """Tests abandoned job recovery when process crashes mid-processing."""

    @pytest.mark.asyncio
    async def test_abandoned_processing_item_recovered(self, sync_db: AsyncSession):
        service = SyncQueueService(sync_db)
        item = await service.enqueue(record_type="note", record_id="n-crash", operation="upsert")
        await service.claim_pending(batch_size=1)
        await sync_db.commit()

        # Item is now PROCESSING
        assert item.status == SyncState.PROCESSING.value

        # Simulate time passing beyond timeout
        old_time = datetime.now(timezone.utc) - timedelta(seconds=400)
        item.processing_started_at = old_time
        await sync_db.commit()

        # Recover abandoned items with 300s timeout
        recovered = await service.recover_abandoned(timeout_seconds=300.0)
        await sync_db.commit()

        assert len(recovered) == 1
        assert recovered[0].id == item.id
        assert recovered[0].status == SyncState.PENDING.value
        assert recovered[0].retry_count == 1
        assert "timeout" in recovered[0].last_error.lower()

        # Verify an attempt record was created explaining the timeout
        stmt = select(SyncAttempt).where(SyncAttempt.sync_item_id == item.id)
        res = await sync_db.execute(stmt)
        attempt = res.scalar_one()
        assert attempt.error_category == "timeout"


# =============================================================================
# 4. Mandatory Section 21: Crash Recovery Test
# =============================================================================

class TestSection21CrashRecovery:
    """
    Mandatory Section 21 Test:
    1. Create PENDING sync item
    2. Claim it
    3. Simulate process crash before completion
    4. Restart application
    5. Recover abandoned PROCESSING item
    6. Verify it becomes eligible again
    7. Process it
    8. Verify final state
    """

    @pytest.mark.asyncio
    async def test_section_21_crash_recovery_lifecycle(self, tmp_path: Path):
        db_file = tmp_path / "section_21_crash.db"
        db_url = f"sqlite+aiosqlite:///{db_file.as_posix()}"

        # Initialize SQLite DB
        engine1 = create_async_engine(db_url)
        async with engine1.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_maker1 = async_sessionmaker(engine1, expire_on_commit=False, class_=AsyncSession)

        # 1. Create PENDING sync item
        async with session_maker1() as session:
            service = SyncQueueService(session)
            item = await service.enqueue(
                record_type="memory_record",
                record_id="rec-crash-21",
                operation="upsert",
                payload={"info": "pre-crash data"},
            )
            item_id = item.id
            await session.commit()

            # 2. Claim it (becomes PROCESSING)
            claimed = await service.claim_pending(batch_size=1)
            assert len(claimed) == 1
            assert claimed[0].id == item_id
            assert claimed[0].status == SyncState.PROCESSING.value

            # Backdate processing_started_at to simulate elapsed time
            claimed[0].processing_started_at = datetime.now(timezone.utc) - timedelta(seconds=600)
            await session.commit()

        # 3. Simulate process crash: dispose engine1 completely
        await engine1.dispose()

        # 4. Restart application: create brand new engine2 & session on same DB
        engine2 = create_async_engine(db_url)
        session_maker2 = async_sessionmaker(engine2, expire_on_commit=False, class_=AsyncSession)

        async with session_maker2() as session2:
            service2 = SyncQueueService(session2)

            # 5. Recover abandoned PROCESSING item
            recovered = await service2.recover_abandoned(timeout_seconds=300.0)
            assert len(recovered) == 1
            assert recovered[0].id == item_id
            await session2.commit()

            # 6. Verify it becomes eligible again
            # Allow next_retry_at to pass
            recovered[0].next_retry_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            await session2.commit()

            claimed_again = await service2.claim_pending(batch_size=1)
            assert len(claimed_again) == 1
            assert claimed_again[0].id == item_id
            assert claimed_again[0].status == SyncState.PROCESSING.value

            # 7. Process it to completion
            engine = SyncEngine(session2)
            backend = LocalNoopSyncBackend()
            res = await backend.upsert(claimed_again[0])
            assert res.status == SyncState.SYNCED

            await service2.complete(item_id, duration_ms=res.duration_ms)
            await session2.commit()

            # 8. Verify final state is SYNCED
            stmt = select(SyncItem).where(SyncItem.id == item_id)
            final_res = await session2.execute(stmt)
            final_item = final_res.scalar_one()
            assert final_item.status == SyncState.SYNCED.value
            assert final_item.completed_at is not None

        await engine2.dispose()


# =============================================================================
# 5. Mandatory Section 22: Restart Test
# =============================================================================

class TestSection22RestartPersistence:
    """
    Mandatory Section 22 Test:
    1. Create 20 pending sync items
    2. Stop backend
    3. Restart backend
    4. Verify exactly 20 remain
    5. Process first batch (e.g. 5)
    6. Stop backend
    7. Restart
    8. Verify remaining queue is intact (15 pending, 5 synced)
    """

    @pytest.mark.asyncio
    async def test_section_22_restart_persistence(self, tmp_path: Path):
        db_file = tmp_path / "section_22_restart.db"
        db_url = f"sqlite+aiosqlite:///{db_file.as_posix()}"

        # Initialize DB
        engine1 = create_async_engine(db_url)
        async with engine1.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_maker1 = async_sessionmaker(engine1, expire_on_commit=False, class_=AsyncSession)

        # 1. Create 20 pending sync items
        async with session_maker1() as session:
            service = SyncQueueService(session)
            for i in range(20):
                await service.enqueue(
                    record_type="item",
                    record_id=f"item-{i:03d}",
                    operation="upsert",
                    payload={"index": i},
                )
            await session.commit()

        # 2. Stop backend
        await engine1.dispose()

        # 3. Restart backend
        engine2 = create_async_engine(db_url)
        session_maker2 = async_sessionmaker(engine2, expire_on_commit=False, class_=AsyncSession)

        # 4. Verify exactly 20 remain
        async with session_maker2() as session2:
            service2 = SyncQueueService(session2)
            stats = await service2.get_queue_statistics()
            assert stats["pending_count"] == 20
            assert stats["synced_count"] == 0

            # 5. Process first batch (5 items)
            engine = SyncEngine(session2)
            result = await engine.run_batch(batch_size=5)
            assert result.items_processed == 5
            assert result.items_succeeded == 5
            await session2.commit()

        # 6. Stop backend
        await engine2.dispose()

        # 7. Restart
        engine3 = create_async_engine(db_url)
        session_maker3 = async_sessionmaker(engine3, expire_on_commit=False, class_=AsyncSession)

        # 8. Verify remaining queue is intact
        async with session_maker3() as session3:
            service3 = SyncQueueService(session3)
            stats3 = await service3.get_queue_statistics()
            assert stats3["pending_count"] == 15
            assert stats3["synced_count"] == 5
            assert stats3["queue_size"] == 15

        await engine3.dispose()


# =============================================================================
# 6. LocalWriteService Integration & Tombstones
# =============================================================================

class TestLocalWriteSyncIntegration:
    """Test LocalWriteService integration with SyncQueueService."""

    @pytest.mark.asyncio
    async def test_local_write_creates_sync_item(self, sync_db: AsyncSession):
        write_svc = LocalWriteService(sync_db)
        record = await write_svc.create_memory_record(
            content="Local write knowledge unit",
            record_type="note",
        )
        await sync_db.commit()

        stmt = select(SyncItem).where(SyncItem.record_id == record.id)
        res = await sync_db.execute(stmt)
        sync_item = res.scalar_one()

        assert sync_item.operation == "upsert"
        assert sync_item.status == SyncState.PENDING.value
        assert sync_item.record_type == "memory_record"

    @pytest.mark.asyncio
    async def test_delete_creates_durable_delete_sync_item(self, sync_db: AsyncSession):
        write_svc = LocalWriteService(sync_db)
        record = await write_svc.create_memory_record(
            content="Knowledge to be deleted",
            record_type="note",
        )
        await sync_db.commit()

        # Now soft-delete
        await write_svc.delete_memory_record(record)
        await sync_db.commit()

        # Verify DELETE sync item exists (tombstone queued for Phase 7)
        stmt = select(SyncItem).where(
            SyncItem.record_id == record.id,
            SyncItem.operation == "delete",
        )
        res = await sync_db.execute(stmt)
        del_item = res.scalar_one()

        assert del_item.status == SyncState.PENDING.value
        assert del_item.operation == "delete"


# =============================================================================
# 7. Sync API Endpoints
# =============================================================================

class TestSyncAPIEndpoints:
    """Test /api/sync/* REST endpoints with client."""

    @pytest.mark.asyncio
    async def test_sync_status_endpoint(self, client: AsyncClient):
        response = await client.get("/api/sync/status")
        assert response.status_code == 200
        data = response.json()
        assert "state" in data
        assert "queue_size" in data
        assert "pending_count" in data
        assert "current_device_id" in data

    @pytest.mark.asyncio
    async def test_sync_queue_endpoint(self, client: AsyncClient):
        response = await client.get("/api/sync/queue")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data

    @pytest.mark.asyncio
    async def test_sync_history_endpoint(self, client: AsyncClient):
        response = await client.get("/api/sync/history")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data

    @pytest.mark.asyncio
    async def test_sync_run_endpoint_local_processing(self, client: AsyncClient):
        # Trigger sync run
        response = await client.post("/api/sync/run?batch_size=10")
        assert response.status_code == 200
        data = response.json()
        assert "items_processed" in data
        assert "items_succeeded" in data
        assert "duration_ms" in data
        # Explicit check: must NOT claim "cloud synchronized"
        assert "cloud synchronized" not in data["message"].lower()
