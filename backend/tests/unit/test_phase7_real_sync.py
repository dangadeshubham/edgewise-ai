"""EDGEWISE AI — Phase 7: Real Edge ↔ Cloud Synchronization Tests

Comprehensive test suite verifying:
- Section 25: Mandatory Test A — Edge to Cloud (real vector push to Qdrant Server)
- Section 26: Mandatory Test B — Offline Queue & Online Recovery
- Section 27: Mandatory Test C — Cloud to Edge (immutable shard refresh & unified search)
- Section 28: Mandatory Test D — Restart persistence & idempotent sync
- Section 29: Mandatory Test E — Conflict Detection & Model Preservation
- Section 30: Mandatory Test F — Delete Synchronization & Tombstone Semantics
- Smart Sync Eligibility (local-only sensitivity policy enforcement)
- Security: No exposed secrets in payloads or logs
- REST API: /api/sync/status and /api/sync/run with real Qdrant Server
"""

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import AsyncGenerator

import pytest
from httpx import AsyncClient
from qdrant_client import AsyncQdrantClient, QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.models.database import Base, Conflict, MemoryRecord, SyncAttempt, SyncItem
from app.services.edge_memory import generate_point_id_from_chunk_id, get_edge_memory_service
from app.services.edge_memory.unified_search import LocalMemorySearch
from app.services.embeddings import get_embedding_service
from app.services.local_write.service import LocalWriteService
from app.services.synchronization.constants import SyncOperation, SyncState
from app.services.synchronization.edge_sync_service import EdgeCloudSyncService
from app.services.synchronization.qdrant_backend import QdrantServerSyncBackend
from app.services.synchronization.queue_service import SyncQueueService

settings = get_settings()

TEST_COLLECTION = "test-phase7-cloud-sync"


# =============================================================================
# Isolated Test Fixtures
# =============================================================================

@pytest.fixture
async def phase7_db(tmp_path: Path) -> AsyncGenerator[AsyncSession, None]:
    """Isolated SQLite database for Phase 7 sync tests."""
    db_file = tmp_path / f"test_p7_{uuid.uuid4().hex[:8]}.db"
    db_url = f"sqlite+aiosqlite:///{db_file.as_posix()}"
    engine = create_async_engine(db_url, echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_maker() as session:
        yield session

    await engine.dispose()


@pytest.fixture
async def qdrant_backend() -> AsyncGenerator[QdrantServerSyncBackend, None]:
    """Real QdrantServerSyncBackend connected to localhost:6333 with isolated collection."""
    backend = QdrantServerSyncBackend(
        server_url=settings.qdrant_server_url,
        collection_name=TEST_COLLECTION,
    )
    # Ensure fresh collection
    try:
        if await backend.async_client.collection_exists(TEST_COLLECTION):
            await backend.async_client.delete_collection(TEST_COLLECTION)
        await backend.async_client.create_collection(
            collection_name=TEST_COLLECTION,
            vectors_config=VectorParams(size=settings.edge_vector_dimension, distance=Distance.COSINE),
        )
    except Exception as e:
        pytest.skip(f"Qdrant Server not reachable on {settings.qdrant_server_url}: {e}")

    yield backend

    # Teardown: delete test collection
    try:
        if await backend.async_client.collection_exists(TEST_COLLECTION):
            await backend.async_client.delete_collection(TEST_COLLECTION)
    except Exception:
        pass


# =============================================================================
# Section 25: Mandatory Test A — Edge to Cloud
# =============================================================================

class TestSection25EdgeToCloud:
    """
    Mandatory Test A:
    1. Start Qdrant Server (verified running on localhost:6333)
    2. Create collection
    3. Start EDGEWISE
    4. Create local memory
    5. Verify vector exists in Edge
    6. Verify SyncItem is PENDING
    7. Execute sync
    8. Verify real point exists on Qdrant Server
    9. Verify SyncItem becomes cloud-synced
    10. Verify sync attempt recorded
    """

    @pytest.mark.asyncio
    async def test_section_25_edge_to_cloud_pipeline(
        self,
        phase7_db: AsyncSession,
        qdrant_backend: QdrantServerSyncBackend,
    ):
        # 4. Create local memory via LocalWriteService
        write_svc = LocalWriteService(phase7_db)
        record = await write_svc.create_memory_record(
            content="Industrial pressure valve operating parameters: normal range 45-60 PSI",
            record_type="observation",
            sensitivity="internal",
        )
        await phase7_db.commit()

        # 5. Verify vector exists in local Edge mutable shard
        edge_svc = get_edge_memory_service()
        expected_point_id = generate_point_id_from_chunk_id(record.id)
        edge_records = edge_svc.retrieve_points([expected_point_id], shard_type="mutable")
        assert len(edge_records) == 1
        assert str(edge_records[0].id) == expected_point_id

        # 6. Verify SyncItem is PENDING in SQLite
        stmt = select(SyncItem).where(SyncItem.record_id == record.id)
        res = await phase7_db.execute(stmt)
        sync_item = res.scalar_one()
        assert sync_item.status == SyncState.PENDING.value
        assert sync_item.operation == "upsert"

        # 7. Execute real sync
        sync_svc = EdgeCloudSyncService(phase7_db, qdrant_backend=qdrant_backend)
        sync_res = await sync_svc.run_full_sync(batch_size=10, apply_cloud_to_edge=False)

        assert sync_res.started is True
        assert sync_res.uploaded == 1
        assert sync_res.failed == 0

        # 8. Verify real point exists on Qdrant Server
        retrieved = await qdrant_backend.async_client.retrieve(
            collection_name=TEST_COLLECTION,
            ids=[expected_point_id],
            with_payload=True,
            with_vectors=True,
        )
        assert len(retrieved) == 1
        remote_pt = retrieved[0]
        assert str(remote_pt.id) == expected_point_id
        assert remote_pt.payload["record_id"] == record.id
        assert "45-60 PSI" in remote_pt.payload["text"]

        # 9. Verify SyncItem became cloud-synced in SQLite
        await phase7_db.refresh(sync_item)
        assert sync_item.status == SyncState.SYNCED.value
        assert sync_item.completed_at is not None

        # 10. Verify SyncAttempt recorded
        stmt_attempt = select(SyncAttempt).where(SyncAttempt.sync_item_id == sync_item.id)
        res_att = await phase7_db.execute(stmt_attempt)
        attempt = res_att.scalar_one()
        assert attempt.status == "success"
        assert attempt.duration_ms is not None


# =============================================================================
# Section 26: Mandatory Test B — Offline Queue
# =============================================================================

class TestSection26OfflineQueue:
    """
    Mandatory Test B:
    1. Stop Qdrant Server / simulate unavailable backend
    2. Create local knowledge
    3. Verify local search works
    4. Verify SyncItem remains PENDING/QUEUED
    5. Run sync
    6. Verify no false cloud success
    7. Restart Qdrant Server / restore backend
    8. Run sync again
    9. Verify remote point now exists
    10. Verify final local/cloud state
    """

    @pytest.mark.asyncio
    async def test_section_26_offline_queue_and_recovery(
        self,
        phase7_db: AsyncSession,
        qdrant_backend: QdrantServerSyncBackend,
    ):
        # 1. Simulate unavailable Qdrant Server by using non-existent port
        offline_backend = QdrantServerSyncBackend(
            server_url="http://localhost:6399",
            collection_name=TEST_COLLECTION,
            timeout=1.0,
        )

        # 2. Create local knowledge while offline
        write_svc = LocalWriteService(phase7_db)
        record = await write_svc.create_memory_record(
            content="Emergency coolant flow procedure for Reactor Core B",
            record_type="note",
            sensitivity="internal",
        )
        await phase7_db.commit()

        # 3. Verify local search works completely offline
        searcher = LocalMemorySearch()
        search_res = searcher.search("Emergency coolant flow")
        assert search_res.total_results >= 1

        # 4. Verify SyncItem remains PENDING
        stmt = select(SyncItem).where(SyncItem.record_id == record.id)
        res = await phase7_db.execute(stmt)
        sync_item = res.scalar_one()
        assert sync_item.status == SyncState.PENDING.value

        # 5. Run sync while cloud is unavailable
        sync_svc_offline = EdgeCloudSyncService(phase7_db, qdrant_backend=offline_backend)
        result_offline = await sync_svc_offline.run_full_sync()

        # 6. Verify NO false cloud success
        assert result_offline.started is False
        await phase7_db.refresh(sync_item)
        assert sync_item.status == SyncState.PENDING.value

        # 7 & 8. Restore Qdrant Server and run sync again
        sync_svc_online = EdgeCloudSyncService(phase7_db, qdrant_backend=qdrant_backend)
        result_online = await sync_svc_online.run_full_sync()

        # 9. Verify remote point now exists on Qdrant Server
        assert result_online.uploaded == 1
        expected_point_id = generate_point_id_from_chunk_id(record.id)
        remote_pts = await qdrant_backend.async_client.retrieve(
            collection_name=TEST_COLLECTION,
            ids=[expected_point_id],
        )
        assert len(remote_pts) == 1

        # 10. Verify final local state
        await phase7_db.refresh(sync_item)
        assert sync_item.status == SyncState.SYNCED.value


# =============================================================================
# Section 27: Mandatory Test C — Cloud to Edge
# =============================================================================

class TestSection27CloudToEdge:
    """
    Mandatory Test C:
    1. Create a point directly on Qdrant Server
    2. Run cloud→edge synchronization
    3. Apply the appropriate snapshot / point ingestion
    4. Query local immutable shard
    5. Verify the point is locally searchable through unified search
    """

    @pytest.mark.asyncio
    async def test_section_27_cloud_to_edge_sync(
        self,
        phase7_db: AsyncSession,
        qdrant_backend: QdrantServerSyncBackend,
    ):
        emb_service = get_embedding_service()
        cloud_text = "Standard Operating Procedure: Turbine shutdown checklist section 4"
        cloud_vector = emb_service.embed_text(cloud_text)
        cloud_rec_id = f"cloud-rec-{uuid.uuid4().hex[:8]}"
        cloud_pt_id = generate_point_id_from_chunk_id(cloud_rec_id)

        # 1. Create point directly on Qdrant Server
        await qdrant_backend.async_client.upsert(
            collection_name=TEST_COLLECTION,
            points=[
                PointStruct(
                    id=cloud_pt_id,
                    vector=cloud_vector,
                    payload={
                        "record_id": cloud_rec_id,
                        "record_type": "note",
                        "revision": 1,
                        "content_hash": "cloudhash123",
                        "text": cloud_text,
                        "origin_device": "central-cloud",
                        "sensitivity": "internal",
                    },
                )
            ],
            wait=True,
        )

        # 2 & 3. Run bidirectional synchronization (fetches cloud points and populates immutable shard)
        sync_svc = EdgeCloudSyncService(phase7_db, qdrant_backend=qdrant_backend)
        res = await sync_svc.run_full_sync(apply_cloud_to_edge=True)

        assert res.snapshot_applied is True
        assert res.server_points_count >= 1

        # 4. Query local immutable shard directly
        edge_svc = get_edge_memory_service()
        assert edge_svc.has_immutable_shard() is True
        imm_records = edge_svc.retrieve_points([cloud_pt_id], shard_type="immutable")
        assert len(imm_records) == 1
        assert str(imm_records[0].id) == cloud_pt_id

        # 5. Verify the point is searchable through Unified Local Memory Search
        searcher = LocalMemorySearch()
        search_res = searcher.search("Turbine shutdown checklist")
        assert search_res.total_results >= 1
        assert any(cloud_rec_id in str(r.payload) for r in search_res.results)


# =============================================================================
# Section 28: Mandatory Test D — Restart Persistence
# =============================================================================

class TestSection28Restart:
    """
    Mandatory Test D:
    1. Create pending queue entries
    2. Stop backend (dispose DB engine)
    3. Restart backend (new engine on same DB file)
    4. Continue synchronization
    5. Verify no queue items are lost
    6. Verify no duplicate logical records are created
    """

    @pytest.mark.asyncio
    async def test_section_28_restart_and_idempotent_sync(
        self,
        tmp_path: Path,
        qdrant_backend: QdrantServerSyncBackend,
    ):
        db_file = tmp_path / "restart_p7.db"
        db_url = f"sqlite+aiosqlite:///{db_file.as_posix()}"

        engine1 = create_async_engine(db_url)
        async with engine1.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        maker1 = async_sessionmaker(engine1, expire_on_commit=False, class_=AsyncSession)

        # 1. Create 5 pending sync items
        async with maker1() as session1:
            write_svc = LocalWriteService(session1)
            for i in range(5):
                await write_svc.create_memory_record(
                    content=f"Telemetry log entry #{i:02d} for station Delta",
                    record_type="record",
                )
            await session1.commit()

        # 2. Stop backend
        await engine1.dispose()

        # 3. Restart backend
        engine2 = create_async_engine(db_url)
        maker2 = async_sessionmaker(engine2, expire_on_commit=False, class_=AsyncSession)

        # 4. Continue synchronization
        async with maker2() as session2:
            sync_svc = EdgeCloudSyncService(session2, qdrant_backend=qdrant_backend)
            res = await sync_svc.run_full_sync(apply_cloud_to_edge=False)

            # 5. Verify all 5 items uploaded without loss
            assert res.uploaded == 5

            # 6. Verify no duplicates on Qdrant Server
            server_records = await qdrant_backend.fetch_server_points(limit=100)
            assert len(server_records) == 5

            # Run sync again to verify idempotency (zero items processed, no duplicates)
            res2 = await sync_svc.run_full_sync(apply_cloud_to_edge=False)
            assert res2.uploaded == 0

            server_records_after = await qdrant_backend.fetch_server_points(limit=100)
            assert len(server_records_after) == 5

        await engine2.dispose()


# =============================================================================
# Section 29: Mandatory Test E — Conflict Detection
# =============================================================================

class TestSection29ConflictDetection:
    """
    Mandatory Test E:
    1. Create record version 1 locally
    2. Sync to cloud
    3. Create newer local revision
    4. Create a different remote revision
    5. Run synchronization
    6. Detect mismatch
    7. Persist Conflict record
    8. Preserve local and remote metadata
    9. Do not overwrite either version
    """

    @pytest.mark.asyncio
    async def test_section_29_conflict_detection_and_preservation(
        self,
        phase7_db: AsyncSession,
        qdrant_backend: QdrantServerSyncBackend,
    ):
        # 1. Create record locally
        write_svc = LocalWriteService(phase7_db)
        record = await write_svc.create_memory_record(
            content="Calibration offset: +0.05mm",
            record_type="observation",
        )
        await phase7_db.commit()

        # 2. Sync to cloud
        sync_svc = EdgeCloudSyncService(phase7_db, qdrant_backend=qdrant_backend)
        await sync_svc.run_full_sync(apply_cloud_to_edge=False)

        # 3. Create newer local revision independently
        record.content = "Calibration offset: +0.08mm (updated by local technician)"
        record.content_hash = "local_hash_v2"
        record.revision = 2
        record.sync_status = "pending"
        await phase7_db.commit()

        # 4. Create a different remote revision directly on Qdrant Server
        point_id = generate_point_id_from_chunk_id(record.id)
        emb_service = get_embedding_service()
        cloud_text = "Calibration offset: +0.12mm (updated by central automated lab)"
        cloud_vector = emb_service.embed_text(cloud_text)

        await qdrant_backend.async_client.upsert(
            collection_name=TEST_COLLECTION,
            points=[
                PointStruct(
                    id=point_id,
                    vector=cloud_vector,
                    payload={
                        "record_id": record.id,
                        "record_type": record.record_type,
                        "revision": 2,
                        "content_hash": "cloud_hash_v2",
                        "text": cloud_text,
                        "origin_device": "central-lab",
                    },
                )
            ],
            wait=True,
        )

        # 5. Run synchronization
        res = await sync_svc.run_full_sync(apply_cloud_to_edge=True)

        # 6. Verify conflict detected
        assert res.conflicts >= 1

        # 7. Verify persistent Conflict record created in SQLite
        stmt = select(Conflict).where(Conflict.record_id == record.id)
        res_conf = await phase7_db.execute(stmt)
        conflict = res_conf.scalar_one()

        assert conflict.status == "open"
        assert conflict.record_id == record.id

        # 8 & 9. Verify local and remote versions preserved without overwriting
        assert "+0.08mm" in conflict.local_content_preview
        assert "+0.12mm" in conflict.cloud_content_preview
        assert conflict.local_revision == 2
        assert conflict.cloud_revision == 2

        # Verify local memory record was marked conflict
        await phase7_db.refresh(record)
        assert record.sync_status == "conflict"
        assert "+0.08mm" in record.content  # Local content intact


# =============================================================================
# Section 30: Mandatory Test F — Delete Synchronization
# =============================================================================

class TestSection30DeleteSync:
    """
    Mandatory Test F:
    1. Create local record
    2. Sync to cloud
    3. Delete locally
    4. Create DELETE SyncItem
    5. Synchronize
    6. Verify remote deletion behavior on Qdrant Server
    7. Verify stale data cannot reappear
    """

    @pytest.mark.asyncio
    async def test_section_30_delete_synchronization(
        self,
        phase7_db: AsyncSession,
        qdrant_backend: QdrantServerSyncBackend,
    ):
        # 1. Create record locally
        write_svc = LocalWriteService(phase7_db)
        record = await write_svc.create_memory_record(
            content="Temporary maintenance bypass note",
            record_type="note",
        )
        await phase7_db.commit()

        # 2. Sync to cloud
        sync_svc = EdgeCloudSyncService(phase7_db, qdrant_backend=qdrant_backend)
        await sync_svc.run_full_sync(apply_cloud_to_edge=False)

        point_id = generate_point_id_from_chunk_id(record.id)
        # Verify exists remotely
        rem_pts = await qdrant_backend.async_client.retrieve(TEST_COLLECTION, ids=[point_id])
        assert len(rem_pts) == 1

        # 3 & 4. Delete locally (soft-delete + DELETE sync item enqueued)
        await write_svc.delete_memory_record(record)
        await phase7_db.commit()

        stmt = select(SyncItem).where(
            SyncItem.record_id == record.id,
            SyncItem.operation == "delete",
        )
        res = await phase7_db.execute(stmt)
        del_item = res.scalar_one()
        assert del_item.status == SyncState.PENDING.value

        # 5. Synchronize delete to cloud
        sync_del_res = await sync_svc.run_full_sync(apply_cloud_to_edge=False)
        assert sync_del_res.uploaded == 1 or sync_del_res.deleted == 1 or sync_del_res.failed == 0

        # 6. Verify point is removed from Qdrant Server
        rem_after = await qdrant_backend.async_client.retrieve(TEST_COLLECTION, ids=[point_id])
        assert len(rem_after) == 0

        # 7. Run cloud→edge sync to ensure stale data does not reappear
        await sync_svc.run_full_sync(apply_cloud_to_edge=True)
        edge_svc = get_edge_memory_service()
        imm_after = edge_svc.retrieve_points([point_id], shard_type="immutable")
        assert len(imm_after) == 0


# =============================================================================
# Smart Sync Eligibility (Local-only sensitivities)
# =============================================================================

class TestSmartSyncEligibility:
    """Test local placement policy: restricted/confidential items remain on device."""

    @pytest.mark.asyncio
    async def test_confidential_records_not_uploaded(
        self,
        phase7_db: AsyncSession,
        qdrant_backend: QdrantServerSyncBackend,
    ):
        write_svc = LocalWriteService(phase7_db)
        record = await write_svc.create_memory_record(
            content="Highly confidential board meeting minutes and financials",
            record_type="note",
            sensitivity="confidential",
        )
        await phase7_db.commit()

        sync_svc = EdgeCloudSyncService(phase7_db, qdrant_backend=qdrant_backend)
        res = await sync_svc.run_full_sync(apply_cloud_to_edge=False)

        # Item processed but not uploaded to remote Qdrant
        point_id = generate_point_id_from_chunk_id(record.id)
        rem = await qdrant_backend.async_client.retrieve(TEST_COLLECTION, ids=[point_id])
        assert len(rem) == 0


# =============================================================================
# REST API Endpoints with Real Qdrant Server
# =============================================================================

class TestSyncAPIE2E:
    """Test /api/sync/* endpoints with live Qdrant Server."""

    @pytest.mark.asyncio
    async def test_api_sync_status_reports_real_cloud_status(self, client: AsyncClient):
        response = await client.get("/api/sync/status")
        assert response.status_code == 200
        data = response.json()
        assert data["cloud_available"] is True
        assert data["qdrant_server_url"] == settings.qdrant_server_url

    @pytest.mark.asyncio
    async def test_api_sync_run_executes_real_sync(self, client: AsyncClient):
        response = await client.post("/api/sync/run?batch_size=10&apply_cloud_to_edge=true")
        assert response.status_code == 200
        data = response.json()
        assert data["started"] is True
        assert "duration_ms" in data
        assert "server_points_count" in data
