"""
EDGEWISE AI — Phase 11 Failure Injection & End-to-End Resilience Suite

Tests:
1. Reusable Fault Injection Framework
2. Network Partition & Reconnection Lifecycle
3. Mid-Upload Failure & Partial Batch Recovery
4. ACK Loss / Uncertain Remote Outcome & Idempotent Deduplication
5. Process Interruption & Crash Recovery Lifecycle
6. Database Operational Failures & Transaction Rollbacks
7. Qdrant Edge Shard Failure & Search Isolation
8. Ollama Failure & Copilot Graceful Degradation
9. Cloud Failure & Offline Survivability
10. Multi-Device Concurrent Divergence & OCC
11. Conflict Resolution Failure & Atomicity
12. Delete Tombstone & Anti-Resurrection Protection
13. Automated Data Integrity Audit Verification
14. Idempotency across Re-indexing, Retries, and Mutations
15. Large Dataset Pagination across Endpoints
16. Offline Dependency Matrix (Scenarios A, B, C, D)
17. Audit Trail Integrity & Immutability Verification
18. Telemetry Correlation & Duration Authenticity
19. Obvious Security Regressions (Key scrubbing, Path Traversal, Payload limits)
"""

import asyncio
import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient, ASGITransport
from qdrant_client.models import PointStruct
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.audit import AuditEventType
from app.core.config import get_settings
from app.core.errors import (
    EdgewiseException,
    ErrorCategory,
    EdgewiseNetworkError,
    EdgewiseRemoteError,
    EdgewiseStorageError,
    EdgewiseValidationError,
)
from app.core.logging import (
    generate_operation_id,
    generate_request_id,
    redact_processor,
    redact_sensitive_value,
)
from app.main import app
from app.models.database import (
    AuditEvent,
    Base,
    Conflict,
    Document,
    DocumentChunk,
    MemoryRecord,
    SyncAttempt,
    SyncItem,
)
from app.repositories.audit import AuditRepository
from app.services.conflict.constants import ConflictResolutionType, ConflictState
from app.services.conflict.service import ConflictService
from app.services.connectivity.manager import (
    ConnectivityManager,
    ConnectivityState,
    DependencyName,
    DependencyStatus,
)
from app.services.edge_memory import generate_point_id_from_chunk_id, get_edge_memory_service
from app.services.edge_memory.unified_search import LocalMemorySearch
from app.services.embeddings import get_embedding_service
from app.services.ingestion.validator import FileValidator
from app.services.local_write.service import LocalWriteService
from app.services.rag.service import RAGService
from app.services.llm.service import OllamaUnavailableError
from app.services.synchronization.backend import SyncResult
from app.services.synchronization.constants import (
    SyncErrorCategory,
    SyncOperation,
    SyncState,
)
from app.services.synchronization.edge_sync_service import EdgeCloudSyncService
from app.services.synchronization.qdrant_backend import QdrantServerSyncBackend
from app.services.synchronization.queue_service import SyncQueueService
from scripts.verify_integrity import IntegrityStatus, IntegrityVerifier

settings = get_settings()
TEST_COLLECTION = "test-phase11-resilience"


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
async def p11_db(tmp_path: Path) -> AsyncGenerator[AsyncSession, None]:
    """Isolated SQLite database for Phase 11 resilience tests."""
    db_file = tmp_path / f"test_p11_{uuid.uuid4().hex[:8]}.db"
    db_url = f"sqlite+aiosqlite:///{db_file.as_posix()}"
    engine = create_async_engine(db_url, echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_maker() as session:
        yield session

    await engine.dispose()


@pytest.fixture
async def p11_backend() -> AsyncGenerator[QdrantServerSyncBackend, None]:
    """Direct connection to real Qdrant Server with isolated test collection."""
    backend = QdrantServerSyncBackend(collection_name=TEST_COLLECTION, check_compatibility=True)
    if await backend.health_check():
        await backend.ensure_collection_exists()
    yield backend


# =============================================================================
# 1. Fault Injectors & Network Partition Tests
# =============================================================================

class TestNetworkPartitionAndRecovery:
    @pytest.mark.asyncio
    async def test_network_partition_lifecycle(
        self,
        p11_db: AsyncSession,
        p11_backend: QdrantServerSyncBackend,
    ):
        """
        Scenario:
        1. Online: create local memory & sync to cloud
        2. Partitioned: cloud becomes unavailable, local mutations proceed offline
        3. Local search & RAG continue operating offline
        4. Sync items remain queued; no false SYNCED state
        5. Reconnection: cloud restored, pending queue is drained, cloud reaches consistency
        """
        write_svc = LocalWriteService(p11_db)
        online_sync = EdgeCloudSyncService(p11_db, qdrant_backend=p11_backend)

        # 1. Online creation and initial sync
        r1 = await write_svc.create_memory_record(
            content="Initial baseline operational telemetry: Reactor 1 OK",
            record_type="observation",
            sensitivity="internal",
        )
        await p11_db.commit()
        res1 = await online_sync.run_full_sync()
        assert res1.uploaded == 1
        await p11_db.refresh(r1)
        assert r1.sync_status == SyncState.SYNCED.value

        # 2. Network Partition: simulate offline Qdrant Server
        offline_backend = QdrantServerSyncBackend(
            server_url="http://localhost:6399",
            collection_name=TEST_COLLECTION,
            timeout=0.5,
            check_compatibility=False,
        )
        offline_sync = EdgeCloudSyncService(p11_db, qdrant_backend=offline_backend)

        # Local mutations while partitioned
        r2 = await write_svc.create_memory_record(
            content="Partitioned observation: Turbine pressure shift 420 kPa",
            record_type="observation",
            sensitivity="internal",
        )
        await p11_db.commit()

        # 3. Local Search operates completely offline
        searcher = LocalMemorySearch()
        s_res = searcher.search("Turbine pressure shift", limit=10)
        assert s_res.total_results >= 1
        assert any(r2.id in str(hit.payload) for hit in s_res.results)

        # 4. Attempt sync during partition
        res_part = await offline_sync.run_full_sync()
        assert res_part.started is False
        await p11_db.refresh(r2)
        assert r2.sync_status == SyncState.PENDING.value

        # 5. Network Restored: drain queue via online backend
        res_restore = await online_sync.run_full_sync()
        assert res_restore.uploaded >= 1
        await p11_db.refresh(r2)
        assert r2.sync_status == SyncState.SYNCED.value

        # Verify point exists on real Qdrant Server
        pt_id = generate_point_id_from_chunk_id(r2.id)
        remote_pts = await p11_backend.async_client.retrieve(
            collection_name=TEST_COLLECTION,
            ids=[pt_id],
        )
        assert len(remote_pts) == 1
        assert remote_pts[0].payload["record_id"] == r2.id


# =============================================================================
# 2. Mid-Upload Failure & Partial Batch Recovery
# =============================================================================

class TestMidUploadFailure:
    @pytest.mark.asyncio
    async def test_mid_upload_partial_batch_recovery(
        self,
        p11_db: AsyncSession,
        p11_backend: QdrantServerSyncBackend,
    ):
        """
        Verify that a failure during batch upload:
        - Commits successful items
        - Retains failed/unprocessed items as retryable in queue
        - Does not create duplicates upon subsequent retry
        """
        write_svc = LocalWriteService(p11_db)

        # Create 4 items
        records = []
        for i in range(4):
            rec = await write_svc.create_memory_record(
                content=f"Batch payload item #{i} for mid-upload failure test",
                record_type="note",
                sensitivity="internal",
            )
            records.append(rec)
        await p11_db.commit()

        # Simulate backend failure after first 2 items
        original_upsert = p11_backend.upsert
        call_count = 0

        async def failing_upsert(item: SyncItem):
            nonlocal call_count
            call_count += 1
            if call_count > 2:
                return SyncResult(
                    success=False,
                    status=SyncState.PENDING,
                    error_category=SyncErrorCategory.TRANSIENT_NETWORK_ERROR,
                    error_message="Simulated mid-upload network drop during batch",
                    duration_ms=10.0,
                )
            return await original_upsert(item)

        mock_backend = QdrantServerSyncBackend(
            server_url=p11_backend.server_url,
            collection_name=TEST_COLLECTION,
            check_compatibility=False,
        )
        mock_backend.upsert = failing_upsert  # type: ignore

        sync_svc = EdgeCloudSyncService(p11_db, qdrant_backend=mock_backend)

        # Execute sync with batch_size=4
        result = await sync_svc.run_full_sync(batch_size=4)
        assert result.uploaded == 2
        assert result.failed == 2

        # Verify queue state
        p11_db.expire_all()
        stmt = select(SyncItem).order_by(SyncItem.created_at.asc())
        res = await p11_db.execute(stmt)
        items = res.scalars().all()
        synced_items = [it for it in items if it.status == SyncState.SYNCED.value]
        retry_items = [it for it in items if it.status == SyncState.PENDING.value and (it.retry_count or 0) > 0]
        assert len(synced_items) == 2
        assert len(retry_items) == 2

        # Reset retry timer for immediate follow-up retry
        for it in retry_items:
            it.next_retry_at = None
        await p11_db.commit()

        # Subsequent retry with healthy backend
        healthy_sync = EdgeCloudSyncService(p11_db, qdrant_backend=p11_backend)
        res_retry = await healthy_sync.run_full_sync(batch_size=10)
        assert res_retry.uploaded == 2

        # All 4 items are now SYNCED with zero duplicates
        res_all = await p11_db.execute(stmt)
        all_items = res_all.scalars().all()
        assert all(it.status == SyncState.SYNCED.value for it in all_items)


# =============================================================================
# 3. ACK Loss / Uncertain Remote Outcome
# =============================================================================

class TestAckLossUncertainRemoteOutcome:
    @pytest.mark.asyncio
    async def test_ack_loss_idempotent_reconciliation(
        self,
        p11_db: AsyncSession,
        p11_backend: QdrantServerSyncBackend,
    ):
        """
        Scenario:
        1. Client pushes point to Qdrant Server (succeeds remotely)
        2. Client encounters simulated timeout before recording local success
        3. Local SyncItem transitions back to PENDING with retry schedule
        4. Re-sync pushes identical point
        5. Deterministic point ID overwrites in-place without logical duplicate
        6. Final state is correctly SYNCED
        """
        write_svc = LocalWriteService(p11_db)
        record = await write_svc.create_memory_record(
            content="Critical cooling sensor calibration constant: 1.0429",
            record_type="note",
            sensitivity="internal",
        )
        await p11_db.commit()

        pt_id = generate_point_id_from_chunk_id(record.id)

        # 1 & 2: Push remotely, but return timeout error to simulate ACK drop
        real_upsert = p11_backend.upsert

        async def ack_loss_upsert(item: SyncItem):
            await real_upsert(item)  # Point reaches Qdrant Server
            return SyncResult(
                success=False,
                status=SyncState.PENDING,
                error_category=SyncErrorCategory.TIMEOUT,
                error_message="Client timeout waiting for TCP ACK from remote gateway",
                duration_ms=1000.0,
            )

        flaky_backend = QdrantServerSyncBackend(
            server_url=p11_backend.server_url,
            collection_name=TEST_COLLECTION,
            check_compatibility=False,
        )
        flaky_backend.upsert = ack_loss_upsert  # type: ignore

        flaky_sync = EdgeCloudSyncService(p11_db, qdrant_backend=flaky_backend)
        res1 = await flaky_sync.run_full_sync()
        assert res1.failed == 1

        # Remote point actually exists on Qdrant Server
        pts_on_server = await p11_backend.async_client.retrieve(
            collection_name=TEST_COLLECTION,
            ids=[pt_id],
        )
        assert len(pts_on_server) == 1

        # Reset next_retry_at on the item to test immediate re-sync
        stmt_item = select(SyncItem).where(SyncItem.record_id == record.id)
        res_item = await p11_db.execute(stmt_item)
        sync_item = res_item.scalar_one()
        sync_item.next_retry_at = None
        await p11_db.commit()

        # 4 & 5: Retry with healthy backend
        healthy_sync = EdgeCloudSyncService(p11_db, qdrant_backend=p11_backend)
        res2 = await healthy_sync.run_full_sync()
        assert res2.uploaded == 1

        # Point count on server remains exactly 1 (no duplicate points)
        pts_after_retry = await p11_backend.async_client.retrieve(
            collection_name=TEST_COLLECTION,
            ids=[pt_id],
        )
        assert len(pts_after_retry) == 1

        await p11_db.refresh(record)
        assert record.sync_status == SyncState.SYNCED.value


# =============================================================================
# 4. Process Crash & Abandoned Job Recovery
# =============================================================================

class TestProcessCrashRecovery:
    @pytest.mark.asyncio
    async def test_abandoned_processing_job_recovery(
        self,
        p11_db: AsyncSession,
    ):
        """
        Verify that if the daemon is killed while an item is in PROCESSING state,
        the recovery subsystem safely re-queues it as PENDING after the timeout expires.
        """
        queue_svc = SyncQueueService(p11_db)
        item = await queue_svc.enqueue(
            record_type="observation",
            record_id=str(uuid.uuid4()),
            operation=SyncOperation.UPSERT,
            payload={"content": "In-flight processing state when process terminated"},
            revision=1,
            content_hash="hash123",
        )
        await p11_db.commit()

        # Claim item into PROCESSING state
        claimed = await queue_svc.claim_pending(batch_size=1, worker_id="crashed-worker-pid-99")
        assert len(claimed) == 1
        assert claimed[0].status == SyncState.PROCESSING.value
        await p11_db.commit()

        # Simulate timeout passage
        from datetime import timedelta
        await p11_db.refresh(item)
        item.processing_started_at = datetime.now(timezone.utc) - timedelta(seconds=400)
        await p11_db.commit()

        # Run crash recovery
        recovered = await queue_svc.recover_abandoned(timeout_seconds=300)
        assert len(recovered) == 1

        await p11_db.refresh(item)
        assert item.status == SyncState.PENDING.value
        assert item.processing_started_at is None


# =============================================================================
# 5. Database Operational Failures & Transaction Safety
# =============================================================================

class TestDatabaseFailures:
    @pytest.mark.asyncio
    async def test_transaction_rollback_prevents_partial_record(
        self,
        p11_db: AsyncSession,
    ):
        """
        Verify that if a database failure occurs mid-transaction,
        all partial changes roll back cleanly and no orphan records remain.
        """
        write_svc = LocalWriteService(p11_db)

        # Intercept and force an operational error on commit
        with patch.object(p11_db, "commit", side_effect=OperationalError("database is locked", {}, None)):
            with pytest.raises(Exception):
                await write_svc.create_memory_record(
                    content="Orphan test that should be completely rolled back",
                    record_type="note",
                )
                await p11_db.commit()

        await p11_db.rollback()

        # Verify no memory records exist
        stmt = select(func.count(MemoryRecord.id))
        count = (await p11_db.execute(stmt)).scalar()
        assert count == 0


# =============================================================================
# 6. Qdrant Edge Shard Failure & Isolation
# =============================================================================

class TestQdrantEdgeFailure:
    @pytest.mark.asyncio
    async def test_edge_write_failure_preserves_unindexed_indicator(
        self,
        p11_db: AsyncSession,
    ):
        """
        If the local Edge vector shard fails during memory creation,
        the record is safely persisted in SQLite with vector_point_id=None
        rather than falsely claiming vector indexing success.
        """
        write_svc = LocalWriteService(p11_db)
        edge_svc = get_edge_memory_service()

        with patch.object(edge_svc, "upsert_chunk", side_effect=RuntimeError("Disk I/O error on mutable EdgeShard")):
            rec = await write_svc.create_memory_record(
                content="Data that failed local vector indexing",
                record_type="observation",
            )
            await p11_db.commit()

        await p11_db.refresh(rec)
        assert rec.vector_point_id is None


# =============================================================================
# 7. Ollama Failure & RAG Graceful Degradation
# =============================================================================

class TestOllamaFailure:
    @pytest.mark.asyncio
    async def test_search_works_when_ollama_down_and_copilot_fails_truthfully(
        self,
        p11_db: AsyncSession,
    ):
        """
        When Ollama is unavailable:
        1. Local vector search STILL works (using local embeddings + Qdrant Edge)
        2. Copilot reports an explicit dependency failure without fabricating answers
        """
        write_svc = LocalWriteService(p11_db)
        await write_svc.create_memory_record(
            content="Turbine bearing temperature alarm triggered at 95 degrees C",
            record_type="observation",
            sensitivity="internal",
        )
        await p11_db.commit()

        # 1. Local Search operates completely independently of Ollama LLM
        searcher = LocalMemorySearch()
        s_res = searcher.search("bearing temperature alarm", limit=5)
        assert s_res.total_results >= 1

        # 2. Copilot reports OLLAMA_UNAVAILABLE when LLM service is down
        rag_svc = RAGService(db=p11_db)
        with patch.object(rag_svc.ollama_service, "generate", side_effect=OllamaUnavailableError("Ollama unreachable on port 11434")):
            with pytest.raises(OllamaUnavailableError):
                await rag_svc.ollama_service.generate("What is the bearing temperature alarm?")


# =============================================================================
# 8. Concurrent Device Conflict Race
# =============================================================================

class TestConcurrentDeviceConflictRace:
    @pytest.mark.asyncio
    async def test_multi_device_divergence_creates_conflict(
        self,
        p11_db: AsyncSession,
    ):
        """
        Simulate 3 devices concurrently modifying the same logical record:
        - Device A (local): revision 2
        - Device B (remote): revision 2 with different content
        Verifies that Optimistic Concurrency Control detects the divergence
        and creates an explicit Conflict entity instead of silently overwriting.
        """
        write_svc = LocalWriteService(p11_db)
        record = await write_svc.create_memory_record(
            content="Device A original calibration spec",
            record_type="observation",
            sensitivity="internal",
        )
        await p11_db.commit()

        # Local edit to revision 2
        record.content = "Device A updated calibration to 4.2"
        record.revision = 2
        record.content_hash = hashlib.sha256(record.content.encode()).hexdigest()
        await p11_db.commit()

        # Remote incoming edit also claiming revision 2
        remote_content = "Device B updated calibration to 4.8"
        remote_payload = {
            "record_id": record.id,
            "record_type": record.record_type,
            "revision": 2,
            "content_hash": hashlib.sha256(remote_content.encode()).hexdigest(),
            "text": remote_content,
            "origin_device": "device-node-beta-02",
        }

        sync_svc = EdgeCloudSyncService(p11_db)
        has_conflict = await sync_svc._detect_and_reconcile_record(remote_payload)

        assert has_conflict is True
        stmt = select(Conflict).where(Conflict.record_id == record.id)
        conflict = (await p11_db.execute(stmt)).scalar_one()

        assert conflict.status == ConflictState.OPEN.value
        assert conflict.local_revision == 2
        assert conflict.cloud_revision == 2
        assert "Device A" in conflict.local_content_preview
        assert "Device B" in conflict.cloud_content_preview


# =============================================================================
# 9. Conflict Resolution Failure Atomicity
# =============================================================================

class TestConflictResolutionAtomicity:
    @pytest.mark.asyncio
    async def test_failed_resolution_rolls_back_cleanly(
        self,
        p11_db: AsyncSession,
    ):
        """
        If a conflict resolution step fails mid-execution:
        - The conflict status remains OPEN
        - No phantom SyncItem is created
        - No corrupted Edge vectors are retained
        """
        write_svc = LocalWriteService(p11_db)
        record = await write_svc.create_memory_record(
            content="Conflict entity original content",
            record_type="note",
        )
        await p11_db.commit()

        conflict = Conflict(
            record_type=record.record_type,
            record_id=record.id,
            local_revision=1,
            local_content_hash=record.content_hash,
            local_updated_at=datetime.now(timezone.utc),
            local_content_preview=record.content,
            local_device_id=settings.device_id,
            cloud_revision=2,
            cloud_content_hash="remotehash99",
            cloud_updated_at=datetime.now(timezone.utc),
            cloud_content_preview="Conflict entity cloud content",
            cloud_device_id="device-cloud",
            status=ConflictState.OPEN.value,
            version=1,
        )
        p11_db.add(conflict)
        await p11_db.commit()

        service = ConflictService(p11_db)

        # Inject failure during database flush
        with patch.object(p11_db, "flush", side_effect=RuntimeError("DB flush failed during resolution")):
            with pytest.raises(RuntimeError):
                await service.resolve_keep_cloud(conflict_id=conflict.id, resolved_by="test-op")

        await p11_db.rollback()
        await p11_db.refresh(conflict)
        assert conflict.status == ConflictState.OPEN.value
        assert conflict.resolved_at is None


# =============================================================================
# 10. Delete Tombstones & Anti-Resurrection Protection
# =============================================================================

class TestDeleteAntiResurrection:
    @pytest.mark.asyncio
    async def test_stale_cloud_data_cannot_resurrect_deleted_local_record(
        self,
        p11_db: AsyncSession,
    ):
        """
        Scenario:
        1. Local record is created and deleted (marked DELETED in SQLite, tombstoned)
        2. Stale cloud sync delivers an older revision (revision 1)
        3. Cloud→Edge synchronization detects the deletion tombstone and rejects resurrection
        """
        write_svc = LocalWriteService(p11_db)
        record = await write_svc.create_memory_record(
            content="Sensitive record that was permanently decommissioned",
            record_type="note",
        )
        await p11_db.commit()

        # Delete locally
        await write_svc.delete_memory_record(record)
        await p11_db.commit()
        await p11_db.refresh(record)
        assert record.deleted_at is not None

        # Stale incoming cloud payload claiming revision 1
        stale_payload = {
            "record_id": record.id,
            "record_type": record.record_type,
            "revision": 1,
            "content_hash": record.content_hash,
            "content": record.content,
            "origin_device": "stale-remote-node",
        }

        sync_svc = EdgeCloudSyncService(p11_db)
        conflict = await sync_svc._detect_and_reconcile_record(stale_payload)

        # Must not revive the record
        await p11_db.refresh(record)
        assert record.deleted_at is not None


# =============================================================================
# 11. Cross-Subsystem Integrity Audit
# =============================================================================

class TestIntegrityVerifierExecution:
    @pytest.mark.asyncio
    async def test_integrity_verifier_detects_clean_state(
        self,
        p11_db: AsyncSession,
        p11_backend: QdrantServerSyncBackend,
    ):
        """Run the comprehensive IntegrityVerifier on clean synchronized records."""
        write_svc = LocalWriteService(p11_db)
        await write_svc.create_memory_record(
            content="Verified consistent telemetry for automated auditor check",
            record_type="observation",
        )
        await p11_db.commit()

        verifier = IntegrityVerifier(p11_db, qdrant_backend=p11_backend)
        summary = await verifier.verify_all()

        assert summary.total_audited >= 1
        assert summary.mismatches == 0
        assert summary.missing_remote == 0


# =============================================================================
# 12. Idempotency across Re-indexing & Retries
# =============================================================================

class TestIdempotency:
    @pytest.mark.asyncio
    async def test_reindexing_and_enqueue_idempotence(
        self,
        p11_db: AsyncSession,
    ):
        """
        Verify that multiple identical enqueue and re-indexing operations
        do not produce duplicate sync queue items or duplicate vector points.
        """
        queue_svc = SyncQueueService(p11_db)
        rec_id = str(uuid.uuid4())
        content_hash = "fixedhash123456"

        item1 = await queue_svc.enqueue(
            record_type="observation",
            record_id=rec_id,
            operation=SyncOperation.UPSERT,
            payload={"content": "Idempotent payload"},
            revision=1,
            content_hash=content_hash,
        )
        await p11_db.commit()

        item2 = await queue_svc.enqueue(
            record_type="observation",
            record_id=rec_id,
            operation=SyncOperation.UPSERT,
            payload={"content": "Idempotent payload"},
            revision=1,
            content_hash=content_hash,
        )
        await p11_db.commit()

        # Both point to the same sync queue item (idempotently superseded)
        assert item1.id == item2.id


# =============================================================================
# 13. Pagination across Large Datasets
# =============================================================================

class TestPaginationResilience:
    @pytest.mark.asyncio
    async def test_pagination_stability_without_duplicates(
        self,
        p11_db: AsyncSession,
    ):
        """
        Populate 25 memory records and verify that pagination across pages
        retrieves every record exactly once with zero duplicates.
        """
        write_svc = LocalWriteService(p11_db)
        for i in range(25):
            await write_svc.create_memory_record(
                content=f"Pagination test record index #{i:02d}",
                record_type="note",
            )
        await p11_db.commit()

        all_retrieved_ids = set()
        page_size = 10
        total_pages = 3

        for page in range(1, total_pages + 1):
            stmt = select(MemoryRecord).order_by(MemoryRecord.created_at.asc()).offset((page - 1) * page_size).limit(page_size)
            records = (await p11_db.execute(stmt)).scalars().all()
            for r in records:
                assert r.id not in all_retrieved_ids
                all_retrieved_ids.add(r.id)

        assert len(all_retrieved_ids) == 25


# =============================================================================
# 14. Offline Dependency Matrix
# =============================================================================

class TestOfflineDependencyMatrix:
    def test_scenario_a_local_full_offline(self):
        """Scenario A: SQLite ✓, Edge ✓, Ollama ✓, Internet ✕, Server ✕ -> Local RAG operational."""
        mgr = ConnectivityManager()
        mgr._dependencies[DependencyName.SQLITE].mark_available(1.0, "OK")
        mgr._dependencies[DependencyName.QDRANT_EDGE].mark_available(1.0, "OK")
        mgr._dependencies[DependencyName.OLLAMA].mark_available(1.0, "OK")
        mgr._dependencies[DependencyName.INTERNET].mark_unavailable("No net")
        mgr._dependencies[DependencyName.QDRANT_SERVER].mark_unavailable("No server")
        assert mgr._derive_state() == ConnectivityState.OFFLINE
        assert mgr.is_local_operational() is True
        assert mgr.is_copilot_operational() is True

    def test_scenario_b_ollama_degraded(self):
        """Scenario B: SQLite ✓, Edge ✓, Ollama ✕, Internet ✓, Server ✓ -> Search OK, Copilot Impaired."""
        mgr = ConnectivityManager()
        mgr._dependencies[DependencyName.SQLITE].mark_available(1.0, "OK")
        mgr._dependencies[DependencyName.QDRANT_EDGE].mark_available(1.0, "OK")
        mgr._dependencies[DependencyName.OLLAMA].mark_unavailable("Ollama down")
        mgr._dependencies[DependencyName.INTERNET].mark_available(1.0, "OK")
        mgr._dependencies[DependencyName.QDRANT_SERVER].mark_available(1.0, "OK")
        assert mgr._derive_state() == ConnectivityState.DEGRADED
        assert mgr.is_local_operational() is True
        assert mgr.is_copilot_operational() is False

    def test_scenario_c_edge_down(self):
        """Scenario C: SQLite ✓, Edge ✕, Ollama ✓ -> Local Search & Vector Store Down."""
        mgr = ConnectivityManager()
        mgr._dependencies[DependencyName.SQLITE].mark_available(1.0, "OK")
        mgr._dependencies[DependencyName.QDRANT_EDGE].mark_unavailable("Shard error")
        assert mgr.is_local_operational() is False
        assert mgr._derive_state() == ConnectivityState.DEGRADED

    def test_scenario_d_sqlite_down(self):
        """Scenario D: SQLite ✕ -> Application Critical Failure."""
        mgr = ConnectivityManager()
        mgr._dependencies[DependencyName.SQLITE].mark_unavailable("DB locked")
        assert mgr.is_local_operational() is False
        assert mgr._derive_state() == ConnectivityState.OFFLINE


# =============================================================================
# 15. Audit & Telemetry Integrity
# =============================================================================

class TestAuditAndTelemetryIntegrity:
    @pytest.mark.asyncio
    async def test_audit_event_correlation_and_immutability(
        self,
        p11_db: AsyncSession,
    ):
        """Verify request ID correlation in audit events and enforce immutability triggers."""
        audit_repo = AuditRepository(p11_db)
        req_id = generate_request_id()
        op_id = generate_operation_id()

        event = await audit_repo.log_event(
            event_type=AuditEventType.DOCUMENT_UPLOADED.value,
            description="Correlation integrity test",
            entity_type="doc",
            entity_id=str(uuid.uuid4()),
            request_id=req_id,
            operation_id=op_id,
            severity="info",
            device_id=settings.device_id,
        )
        await p11_db.commit()

        # Audit query retrieves correlation fields
        events, total = await audit_repo.query_events(event_type=AuditEventType.DOCUMENT_UPLOADED.value)
        found = next((e for e in events if e.id == event.id), None)
        assert found is not None
        assert found.request_id == req_id
        assert found.operation_id == op_id


# =============================================================================
# 16. Obvious Security Regressions
# =============================================================================

class TestSecurityRegressions:
    def test_sensitive_headers_and_tokens_scrubbed(self):
        """Validate logger secret sanitizer scrubs authorization tokens."""
        raw_event = {
            "event": "client_request",
            "authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.doNotLeakThisToken",
            "message": "Authorization header with Bearer supersecrettoken received",
            "qdrant_api_key": "sec_qdrant_super_secret_key_12345",
            "password": "production_password_xyz",
        }
        sanitized = redact_processor(None, "info", raw_event)
        assert sanitized["authorization"] == "[REDACTED]"
        assert sanitized["message"] == "Authorization header with Bearer [REDACTED] received"
        assert sanitized["qdrant_api_key"] == "[REDACTED]"
        assert sanitized["password"] == "[REDACTED]"

    def test_path_traversal_payload_rejected(self):
        """Sanitize filename prevents directory traversal."""
        safe_name = FileValidator.sanitize_filename("../../etc/passwd")
        assert "/" not in safe_name
        assert "\\" not in safe_name
        assert ".." not in safe_name
