"""
EDGEWISE AI — Phase 8 Conflict Resolution Integration & Unit Tests

Mandatory Test Scenarios:
- Test A: Keep Local
- Test B: Keep Cloud
- Test C: Merge
- Test D: Manual
- Test E: Concurrent Resolution (Optimistic Concurrency Control)
- Test F: Crash / Transaction Safety
- Test G: RAG Traceability
- Test H: API Endpoints & Side-by-Side Diff Presentation
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.database import get_db
from app.main import app
from app.models.database import AuditEvent, Base, Conflict, MemoryRecord, SyncItem
from app.services.conflict.constants import (
    ConflictAuditEvent,
    ConflictConcurrencyError,
    ConflictResolutionType,
    ConflictState,
    ConflictStateError,
    ConflictValidationError,
)
from app.services.conflict.diff import DiffEngine
from app.services.conflict.service import ConflictService
from app.services.edge_memory import generate_point_id_from_chunk_id, get_edge_memory_service
from app.services.edge_memory.unified_search import LocalMemorySearch
from app.services.embeddings import get_embedding_service
from app.services.local_write.service import LocalWriteService
from app.services.synchronization.constants import SyncState

settings = get_settings()


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# =============================================================================
# Isolated Test Fixtures
# =============================================================================

@pytest.fixture
async def phase8_db(tmp_path: Path) -> AsyncGenerator[AsyncSession, None]:
    """Isolated SQLite database for Phase 8 conflict tests."""
    db_file = tmp_path / f"test_p8_{uuid.uuid4().hex[:8]}.db"
    db_url = f"sqlite+aiosqlite:///{db_file.as_posix()}"
    engine = create_async_engine(db_url, echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_maker() as session:
        yield session

    await engine.dispose()


@pytest.fixture
async def sample_conflict(phase8_db: AsyncSession) -> tuple[MemoryRecord, Conflict]:
    """Creates a local MemoryRecord and an associated open Conflict."""
    write_svc = LocalWriteService(phase8_db)
    record = await write_svc.create_memory_record(
        content="Reactor Coolant Flow: Normal 1200 kg/s, Max 1400 kg/s",
        record_type="observation",
        sensitivity="internal",
    )
    await phase8_db.commit()

    cloud_text = "Reactor Coolant Flow: Normal 1250 kg/s, Max 1500 kg/s (updated by cloud control)"
    conflict = Conflict(
        record_type=record.record_type,
        record_id=record.id,
        local_revision=1,
        local_content_hash=record.content_hash,
        local_updated_at=datetime.now(timezone.utc),
        local_content_preview=record.content,
        local_device_id=settings.device_id,
        cloud_revision=2,
        cloud_content_hash=_sha256(cloud_text),
        cloud_updated_at=datetime.now(timezone.utc),
        cloud_content_preview=cloud_text,
        cloud_device_id="central-cloud-node-01",
        status=ConflictState.OPEN.value,
        version=1,
    )
    phase8_db.add(conflict)
    await phase8_db.commit()
    await phase8_db.refresh(record)
    await phase8_db.refresh(conflict)

    return record, conflict


# =============================================================================
# Mandatory Test A: Keep Local
# =============================================================================

class TestMandatoryKeepLocal:
    @pytest.mark.asyncio
    async def test_resolve_keep_local(
        self,
        phase8_db: AsyncSession,
        sample_conflict: tuple[MemoryRecord, Conflict],
    ):
        record, conflict = sample_conflict
        service = ConflictService(phase8_db)

        # 2. Resolve keep_local
        resolved = await service.resolve_keep_local(
            conflict_id=conflict.id,
            resolved_by="lead-engineer",
            notes="Local calibration verified by on-site sensor test",
        )
        await phase8_db.commit()

        # 3. Verify conflict is RESOLVED
        assert resolved.status == ConflictState.RESOLVED.value
        assert resolved.resolution == ConflictResolutionType.KEEP_LOCAL.value
        assert resolved.resolved_by == "lead-engineer"
        assert resolved.resolved_at is not None

        # 4. Verify local selected version persists and monotonic revision assigned
        await phase8_db.refresh(record)
        assert record.content == conflict.local_content_preview
        assert record.revision == max(1, conflict.cloud_revision) + 1  # 2 + 1 = 3
        assert record.sync_status == "pending"

        # 5. Verify follow-up SyncItem exists for remote synchronization
        stmt = select(SyncItem).where(
            SyncItem.record_id == record.id,
            SyncItem.revision == record.revision,
        )
        res = await phase8_db.execute(stmt)
        sync_item = res.scalar_one()
        assert sync_item.operation == "upsert"
        assert sync_item.status == SyncState.PENDING.value

        # 6. Verify original cloud version is preserved in conflict history
        meta = json.loads(resolved.resolution_metadata_json)
        assert meta["preserved_cloud_hash"] == conflict.cloud_content_hash
        assert meta["preserved_cloud_revision"] == 2
        assert conflict.cloud_content_preview is not None

        # 7. Verify audit event
        stmt_audit = select(AuditEvent).where(AuditEvent.entity_id == conflict.id)
        res_audit = await phase8_db.execute(stmt_audit)
        events = res_audit.scalars().all()
        event_types = [e.event_type for e in events]
        assert ConflictAuditEvent.CONFLICT_KEEP_LOCAL.value in event_types
        assert ConflictAuditEvent.CONFLICT_RESOLVED.value in event_types


# =============================================================================
# Mandatory Test B: Keep Cloud
# =============================================================================

class TestMandatoryKeepCloud:
    @pytest.mark.asyncio
    async def test_resolve_keep_cloud(
        self,
        phase8_db: AsyncSession,
        sample_conflict: tuple[MemoryRecord, Conflict],
    ):
        record, conflict = sample_conflict
        service = ConflictService(phase8_db)

        # 2. Resolve keep_cloud
        resolved = await service.resolve_keep_cloud(
            conflict_id=conflict.id,
            resolved_by="operations-lead",
            notes="Adopting cloud central telemetry specifications",
        )
        await phase8_db.commit()

        # 3. Verify local content becomes cloud version
        await phase8_db.refresh(record)
        assert record.content == conflict.cloud_content_preview
        assert record.content_hash == conflict.cloud_content_hash
        assert record.revision == max(1, conflict.cloud_revision) + 1
        assert record.sync_status == SyncState.SYNCED.value

        # 4. Verify Edge vector updated
        edge_svc = get_edge_memory_service()
        pt_id = generate_point_id_from_chunk_id(record.id)
        records = edge_svc.retrieve_points([pt_id], shard_type="mutable")
        assert len(records) == 1
        assert "1250 kg/s" in records[0].payload["text"]

        # 5. Verify search reflects the new cloud content
        searcher = LocalMemorySearch()
        search_res = searcher.search("1250 kg/s", limit=50)
        assert search_res.total_results >= 1
        assert any(record.id in str(r.payload) for r in search_res.results)

        # 6. Verify audit event
        stmt_audit = select(AuditEvent).where(AuditEvent.entity_id == conflict.id)
        res_audit = await phase8_db.execute(stmt_audit)
        events = res_audit.scalars().all()
        event_types = [e.event_type for e in events]
        assert ConflictAuditEvent.CONFLICT_KEEP_CLOUD.value in event_types
        assert ConflictAuditEvent.CONFLICT_RESOLVED.value in event_types


# =============================================================================
# Mandatory Test C: Merge
# =============================================================================

class TestMandatoryMerge:
    @pytest.mark.asyncio
    async def test_resolve_merge(
        self,
        phase8_db: AsyncSession,
        sample_conflict: tuple[MemoryRecord, Conflict],
    ):
        record, conflict = sample_conflict
        service = ConflictService(phase8_db)

        merged_content = (
            "Reactor Coolant Flow Agreement: Local baseline 1200 kg/s, "
            "Cloud ceiling 1500 kg/s, Emergency trip at 1600 kg/s"
        )

        # 2. Provide merged content
        resolved = await service.resolve_merge(
            conflict_id=conflict.id,
            merged_content=merged_content,
            resolved_by="plant-director",
            notes="Synthesized consensus configuration between edge and central",
        )
        await phase8_db.commit()

        # 3 & 4. Verify new revision and new hash
        await phase8_db.refresh(record)
        assert record.content == merged_content
        expected_hash = _sha256(merged_content)
        assert record.content_hash == expected_hash
        assert record.revision == max(1, conflict.cloud_revision) + 1  # 3

        # 5. Verify both original versions remain recorded in conflict history
        assert conflict.local_content_preview is not None
        assert conflict.cloud_content_preview is not None
        meta = json.loads(resolved.resolution_metadata_json)
        assert meta["result_content_hash"] == expected_hash
        assert meta["original_local_hash"] == conflict.local_content_hash
        assert meta["original_cloud_hash"] == conflict.cloud_content_hash

        # 6. Verify SyncItem created for remote upload
        stmt = select(SyncItem).where(
            SyncItem.record_id == record.id,
            SyncItem.revision == record.revision,
        )
        res = await phase8_db.execute(stmt)
        sync_item = res.scalar_one()
        assert sync_item.status == SyncState.PENDING.value

        # 7. Verify audit events
        stmt_audit = select(AuditEvent).where(AuditEvent.entity_id == conflict.id)
        res_audit = await phase8_db.execute(stmt_audit)
        events = res_audit.scalars().all()
        event_types = [e.event_type for e in events]
        assert ConflictAuditEvent.CONFLICT_MERGED.value in event_types
        assert ConflictAuditEvent.CONFLICT_RESOLVED.value in event_types


# =============================================================================
# Mandatory Test D: Manual
# =============================================================================

class TestMandatoryManual:
    @pytest.mark.asyncio
    async def test_resolve_manual(
        self,
        phase8_db: AsyncSession,
        sample_conflict: tuple[MemoryRecord, Conflict],
    ):
        record, conflict = sample_conflict
        service = ConflictService(phase8_db)

        manual_content = "MANUAL OVERRIDE: Emergency sensor calibration set to 1225 kg/s by Field Officer 7"

        # 2 & 3. Submit manual final content and verify update
        resolved = await service.resolve_manual(
            conflict_id=conflict.id,
            manual_content=manual_content,
            resolved_by="field-officer-7",
            notes="Physical inspection override",
        )
        await phase8_db.commit()

        # 4. Verify conflict resolved
        assert resolved.status == ConflictState.RESOLVED.value
        assert resolved.resolution == ConflictResolutionType.MANUAL.value

        await phase8_db.refresh(record)
        assert record.content == manual_content
        assert record.content_hash == _sha256(manual_content)
        assert record.revision == 3

        # Verify Edge vector matches manual content
        edge_svc = get_edge_memory_service()
        pt_id = generate_point_id_from_chunk_id(record.id)
        records = edge_svc.retrieve_points([pt_id], shard_type="mutable")
        assert len(records) == 1
        assert "MANUAL OVERRIDE" in records[0].payload["text"]


# =============================================================================
# Mandatory Test E: Concurrent Resolution (Optimistic Concurrency Control)
# =============================================================================

class TestMandatoryConcurrentResolution:
    @pytest.mark.asyncio
    async def test_concurrent_resolution_rejected(
        self,
        phase8_db: AsyncSession,
        sample_conflict: tuple[MemoryRecord, Conflict],
    ):
        record, conflict = sample_conflict
        service = ConflictService(phase8_db)

        # 1. Both Client A and Client B read conflict at version 1
        assert conflict.version == 1

        # 2. Client A claims and resolves successfully with expected_version=1
        await service.claim_conflict(conflict.id, claimed_by="client-A", expected_version=1)
        # version is now 2
        await service.resolve_keep_local(conflict.id, resolved_by="client-A", expected_version=2)
        await phase8_db.commit()

        # 3 & 4. Client B attempts to resolve with stale expected_version=1
        with pytest.raises(ConflictConcurrencyError) as exc_info:
            await service.resolve_keep_cloud(
                conflict.id,
                resolved_by="client-B",
                expected_version=1,  # Stale version!
            )
        assert "modified concurrently" in str(exc_info.value)

        # 5. Verify no data is lost and conflict remains Client A's resolution
        await phase8_db.refresh(conflict)
        assert conflict.status == ConflictState.RESOLVED.value
        assert conflict.resolution == ConflictResolutionType.KEEP_LOCAL.value
        assert conflict.resolved_by == "client-A"


# =============================================================================
# Mandatory Test F: Crash / Transaction Safety
# =============================================================================

class TestMandatoryCrashTransactionSafety:
    @pytest.mark.asyncio
    async def test_transaction_rollback_preserves_consistency(
        self,
        phase8_db: AsyncSession,
        sample_conflict: tuple[MemoryRecord, Conflict],
    ):
        record, conflict = sample_conflict
        service = ConflictService(phase8_db)

        orig_record_rev = record.revision
        orig_record_content = record.content

        # Simulate exception during resolution after partial state mutation
        try:
            async with phase8_db.begin_nested():
                # Attempt manual resolution with invalid empty content
                await service.resolve_manual(
                    conflict_id=conflict.id,
                    manual_content="   ",  # Invalid empty content
                    resolved_by="tester",
                )
        except ConflictValidationError:
            await phase8_db.rollback()

        # Verify database consistency: conflict remains OPEN, record untouched
        await phase8_db.refresh(conflict)
        await phase8_db.refresh(record)

        assert conflict.status == ConflictState.OPEN.value
        assert conflict.resolution is None
        assert record.revision == orig_record_rev
        assert record.content == orig_record_content


# =============================================================================
# Mandatory Test G: RAG Traceability
# =============================================================================

class TestMandatoryRAGTraceability:
    @pytest.mark.asyncio
    async def test_rag_retrieval_returns_current_version_only(
        self,
        phase8_db: AsyncSession,
        sample_conflict: tuple[MemoryRecord, Conflict],
    ):
        record, conflict = sample_conflict
        service = ConflictService(phase8_db)

        # 1. Resolve conflict via MERGE to introduce specific unique term
        unique_spec = f"Delta-Coolant-Trip-Protocol-{uuid.uuid4().hex[:6]}"
        merged_text = f"Standard Operating Procedure: {unique_spec} establishes 1475 kg/s limits."
        await service.resolve_merge(
            conflict_id=conflict.id,
            merged_content=merged_text,
            resolved_by="rag-validator",
        )
        await phase8_db.commit()

        # 2. Query Unified Local Search
        searcher = LocalMemorySearch()
        res = searcher.search(unique_spec, limit=50)

        # 3. Verify retrieval finds current resolved version with intact citation mapping
        assert res.total_results >= 1
        matching_hits = [r for r in res.results if r.payload.get("record_id") == record.id]
        assert len(matching_hits) > 0
        hit = matching_hits[0]
        assert hit.payload["record_id"] == record.id
        assert hit.payload["revision"] == 3
        assert unique_spec in hit.payload["text"]


# =============================================================================
# API Endpoints & Diff Engine Presentation Tests
# =============================================================================

class TestConflictAPIE2E:
    @pytest.mark.asyncio
    async def test_diff_engine_computation(self):
        local_text = "Line 1: baseline\nLine 2: local value 50\nLine 3: common end"
        cloud_text = "Line 1: baseline\nLine 2: cloud value 75\nLine 3: common end"

        diff = DiffEngine.compute_diff(local_text, cloud_text)
        assert diff.additions_count >= 1
        assert diff.deletions_count >= 1
        assert diff.unchanged_count >= 2
        assert diff.is_identical is False

    @pytest.mark.asyncio
    async def test_api_conflict_lifecycle(
        self,
        phase8_db: AsyncSession,
        sample_conflict: tuple[MemoryRecord, Conflict],
    ):
        record, conflict = sample_conflict

        # Override dependency for FastAPI app
        async def override_get_db():
            yield phase8_db

        app.dependency_overrides[get_db] = override_get_db
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            # 1. GET /api/conflicts
            res_list = await ac.get("/api/conflicts?status=open")
            assert res_list.status_code == 200
            data_list = res_list.json()
            assert data_list["total"] >= 1
            assert data_list["open_count"] >= 1

            # 2. GET /api/conflicts/{id} (includes diff)
            res_detail = await ac.get(f"/api/conflicts/{conflict.id}")
            assert res_detail.status_code == 200
            data_detail = res_detail.json()
            assert "conflict" in data_detail
            assert "lines" in data_detail
            assert len(data_detail["lines"]) > 0
            assert "metadata_diffs" in data_detail

            # 3. POST /api/conflicts/{id}/suggest-merge
            res_sugg = await ac.post(f"/api/conflicts/{conflict.id}/suggest-merge")
            assert res_sugg.status_code == 200
            data_sugg = res_sugg.json()
            assert data_sugg["label"] == "AI suggested merge"
            assert data_sugg["requires_user_approval"] is True

            # 4. POST /api/conflicts/{id}/claim
            res_claim = await ac.post(
                f"/api/conflicts/{conflict.id}/claim",
                json={"claimed_by": "api-reviewer", "expected_version": 1},
            )
            assert res_claim.status_code == 200
            assert res_claim.json()["status"] == ConflictState.IN_REVIEW.value
            assert res_claim.json()["version"] == 2

            # 5. POST /api/conflicts/{id}/resolve (keep_local)
            res_resolve = await ac.post(
                f"/api/conflicts/{conflict.id}/resolve",
                json={
                    "resolution": "keep_local",
                    "resolved_by": "api-reviewer",
                    "notes": "API test resolution",
                    "expected_version": 2,
                },
            )
            assert res_resolve.status_code == 200
            assert res_resolve.json()["status"] == ConflictState.RESOLVED.value
            assert res_resolve.json()["resolution"] == ConflictResolutionType.KEEP_LOCAL.value

        app.dependency_overrides.clear()
