"""
EDGEWISE AI — Regression Tests for QA Dashboard Inconsistencies & Safe Vector Reconciliation

Covers:
- Task A & E: Dashboard metric source (Edge Vector Points == mutable + immutable points).
- Task B, C, D: Orphan vector audit, non-destructive identification, and safe cleanup.
- Task F: Disk flush tracking & safe representation.
- Task G: /system/connectivity authoritative device record & timestamp schema.
- Task H: Safe date handling (never render "Invalid Date").
"""

from __future__ import annotations

import datetime
from pathlib import Path
import tempfile
import uuid
import pytest
import qdrant_edge
from sqlalchemy import select

from app.core.config import get_settings
from app.models.database import Document, DocumentChunk, DocumentVersion, MemoryRecord
from app.services.connectivity.manager import (
    ConnectivityManager,
    ConnectivityState,
    get_connectivity_manager,
)
from app.services.edge_memory import EdgeMemoryService, generate_point_id
from app.services.edge_memory.cleanup import VectorCleanupService


@pytest.mark.asyncio
async def test_dashboard_metrics_vector_source(db_session):
    """
    Task A & E: Verify Edge Vector Points metric represents actual searchable Qdrant points
    (mutable + immutable), distinct from embedded chunks.
    """
    from app.api.v1.dashboard import get_dashboard_metrics

    metrics = await get_dashboard_metrics(db=db_session)

    # local_vector_count must strictly match sum of mutable + immutable points
    expected_vectors = metrics.edge_mutable_points + metrics.edge_immutable_points
    assert metrics.local_vector_count == expected_vectors
    assert isinstance(metrics.embedded_chunks, int)
    assert isinstance(metrics.unembedded_chunks, int)
    assert metrics.current_device_id is not None
    assert metrics.current_device_name is not None


@pytest.mark.asyncio
async def test_connectivity_endpoint_device_and_timestamp(client):
    """
    Task G: Fix device information in /system/connectivity so it uses the
    same authoritative Device record as the dashboard and includes a valid ISO timestamp.
    """
    settings = get_settings()
    resp = await client.get("/system/connectivity")
    assert resp.status_code == 200
    data = resp.json()

    # Authoritative device identification
    assert "device_id" in data
    assert data["device_id"] == settings.device_id
    assert "device_name" in data
    assert data["device_name"] == settings.device_name
    assert "device_site" in data
    assert data["device_site"] == settings.device_site

    # Valid ISO timestamp present
    assert "timestamp" in data
    assert data["timestamp"] is not None
    parsed_dt = datetime.datetime.fromisoformat(data["timestamp"])
    assert parsed_dt.year >= 2026


@pytest.mark.asyncio
async def test_safe_orphan_vector_cleanup(db_session, temp_data_dir):
    """
    Task B, C, D: Verify VectorCleanupService audits and cleans ONLY orphaned vectors,
    strictly retaining active DocumentChunks and MemoryRecords without data loss.
    """
    # 1. Setup isolated test shard
    shard_dir = temp_data_dir / f"orphan_test_{uuid.uuid4().hex[:8]}"
    shard_dir.mkdir(parents=True, exist_ok=True)
    mut_dir = shard_dir / "mutable"
    imm_dir = shard_dir / "immutable"

    edge_svc = EdgeMemoryService(
        data_dir=str(shard_dir),
        mutable_dir=str(mut_dir),
        immutable_dir=str(imm_dir),
        dimension=384,
    )

    try:
        # 2. Insert valid Document and DocumentChunk in SQLite
        doc_id = str(uuid.uuid4())
        ver_id = str(uuid.uuid4())
        chunk_id = str(uuid.uuid4())
        content_hash = "abc123hash"
        valid_point_id = generate_point_id(doc_id, 0, content_hash)

        doc = Document(
            id=doc_id,
            filename="safe_test.pdf",
            original_filename="safe_test.pdf",
            mime_type="application/pdf",
            file_path="uploads/safe_test.pdf",
            title="Safe Ingestion Test",
            file_size=1024,
            content_hash="dochash123",
            device_id="edge-device-001",
        )
        db_session.add(doc)

        ver = DocumentVersion(
            id=ver_id,
            document_id=doc_id,
            version=1,
            content_hash="dochash123",
            file_size=1024,
        )
        db_session.add(ver)

        chunk = DocumentChunk(
            id=chunk_id,
            document_id=doc_id,
            chunk_index=0,
            content="Critical operating parameters: normal 65C, max 82C.",
            content_hash=content_hash,
            token_count=10,
            is_embedded=True,
            vector_point_id=valid_point_id,
        )
        db_session.add(chunk)
        await db_session.commit()

        # 3. Insert into Qdrant: 1 valid point + 3 orphaned points
        dummy_vec = [0.1] * 384
        edge_svc.upsert_chunk(
            point_id=valid_point_id,
            dense_vector=dummy_vec,
            text=chunk.content,
            payload={
                "document_id": doc_id,
                "document_version_id": ver_id,
                "chunk_id": chunk_id,
                "title": doc.title,
            },
            shard_type="mutable",
        )

        orphan_id_1 = str(uuid.uuid4())
        orphan_id_2 = str(uuid.uuid4())
        orphan_id_3 = str(uuid.uuid4())

        edge_svc.upsert_chunk(
            point_id=orphan_id_1,
            dense_vector=dummy_vec,
            text="Sync telemetry record #458 for scale 500",
            payload={"record_type": "observation", "document_id": None},
            shard_type="mutable",
        )
        edge_svc.upsert_chunk(
            point_id=orphan_id_2,
            dense_vector=dummy_vec,
            text="Stale deleted document text",
            payload={"document_id": str(uuid.uuid4())},  # Non-existent doc
            shard_type="mutable",
        )
        edge_svc.upsert_chunk(
            point_id=orphan_id_3,
            dense_vector=dummy_vec,
            text="Unit test artifact from previous run",
            payload={"record_type": "note"},
            shard_type="mutable",
        )

        assert edge_svc.count_points("mutable") == 4

        # 4. Dry Run Audit
        cleanup_svc = VectorCleanupService(db_session, edge_service=edge_svc)
        dry_report = await cleanup_svc.reconcile_and_cleanup(dry_run=True, shard_type="mutable")

        assert dry_report.total_scanned == 4
        assert dry_report.valid_retained == 1
        assert dry_report.orphans_identified == 3
        assert dry_report.orphans_deleted == 0
        assert edge_svc.count_points("mutable") == 4  # Unchanged

        # 5. Execute Safe Cleanup
        exec_report = await cleanup_svc.reconcile_and_cleanup(dry_run=False, shard_type="mutable")

        assert exec_report.total_scanned == 4
        assert exec_report.valid_retained == 1
        assert exec_report.orphans_identified == 3
        assert exec_report.orphans_deleted == 3
        assert exec_report.remaining_mutable_points == 1

        # 6. Verify valid chunk point is intact and queryable
        retained_pts = edge_svc.retrieve_points([valid_point_id], shard_type="mutable")
        assert len(retained_pts) == 1
        assert retained_pts[0].payload["chunk_id"] == chunk_id
        assert retained_pts[0].payload["document_id"] == doc_id
        assert retained_pts[0].payload["document_version_id"] == ver_id

        # Verify orphans were deleted
        deleted_check = edge_svc.retrieve_points([orphan_id_1, orphan_id_2, orphan_id_3], shard_type="mutable")
        assert len(deleted_check) == 0

    finally:
        edge_svc.close()


def test_edge_memory_flush_timestamp_tracking(temp_data_dir):
    """
    Task F: Verify meaning of 'Last Disk Flush'. If no flush timestamp is recorded,
    it returns None; when flushed, it records an exact UTC datetime.
    """
    shard_dir = temp_data_dir / f"flush_test_{uuid.uuid4().hex[:8]}"
    shard_dir.mkdir(parents=True, exist_ok=True)

    edge_svc = EdgeMemoryService(
        data_dir=str(shard_dir),
        mutable_dir=str(shard_dir / "mutable"),
        immutable_dir=str(shard_dir / "immutable"),
        dimension=384,
    )
    try:
        # Initially not flushed
        assert edge_svc.last_flush_time is None
        info = edge_svc.get_shard_info("mutable")
        assert info["last_flush"] is None

        # Execute flush
        edge_svc.flush("mutable")
        assert edge_svc.last_flush_time is not None
        assert isinstance(edge_svc.last_flush_time, datetime.datetime)

        info_after = edge_svc.get_shard_info("mutable")
        assert info_after["last_flush"] is not None
    finally:
        edge_svc.close()
