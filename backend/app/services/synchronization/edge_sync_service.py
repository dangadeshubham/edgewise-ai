"""EDGEWISE AI — Edge ↔ Cloud Synchronization Coordinator (Phase 7)

Implements bidirectional Edge ↔ Cloud synchronization:
1. Edge → Cloud: Batch uploads pending local knowledge to Qdrant Server.
2. Synchronization Barrier: Thread-safe locking preventing concurrent mutations
   during immutable shard reconstruction.
3. Cloud → Edge: Ingestion of server points into local immutable shard.
4. Mutable Shard Cleanup: Deletes from mutable shard only points safely represented
   and verified in the immutable shard.
5. Conflict Detection: Reconciles cloud points with local state, recording Conflict models.
6. Structured Audit Events: Emits SYNC_STARTED, SYNC_UPLOAD_SUCCESS, SYNC_COMPLETED, etc.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import time
import uuid
from dataclasses import dataclass
from typing import Any, Optional

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.database import Conflict, MemoryRecord, SyncItem
from app.repositories.audit import AuditRepository
from app.repositories.sync import ConflictRepository, SyncRepository
from app.services.edge_memory import generate_point_id_from_chunk_id, get_edge_memory_service
from app.services.synchronization.backend import SyncResult
from app.services.synchronization.constants import (
    SyncErrorCategory,
    SyncOperation,
    SyncState,
)
from app.services.synchronization.engine import SyncEngine
from app.services.synchronization.qdrant_backend import QdrantServerSyncBackend
from app.services.synchronization.queue_service import SyncQueueService

settings = get_settings()
logger = structlog.get_logger("edgewise.sync.edge_service")

# Global barrier lock preventing interleaved immutable shard modifications
_SYNC_BARRIER_LOCK = asyncio.Lock()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class EdgeSyncResult:
    """Comprehensive summary of a bidirectional Edge ↔ Cloud synchronization cycle."""
    started: bool
    uploaded: int
    deleted: int
    failed: int
    conflicts: int
    snapshot_applied: bool
    duration_ms: float
    message: str
    server_points_count: int = 0
    barrier_state: str = "NORMAL"


class EdgeCloudSyncService:
    """
    Coordinates bidirectional Edge ↔ Cloud synchronization using Qdrant Server
    and the native embedded Qdrant Edge mutable/immutable architecture.
    """

    def __init__(
        self,
        session: AsyncSession,
        qdrant_backend: Optional[QdrantServerSyncBackend] = None,
    ) -> None:
        self.session = session
        self.backend = qdrant_backend or QdrantServerSyncBackend()
        self.queue_service = SyncQueueService(session)
        self.audit_repo = AuditRepository(session)
        self.sync_repo = SyncRepository(session)
        self.conflict_repo = ConflictRepository(session)
        self.edge_service = get_edge_memory_service()

    async def run_full_sync(
        self,
        batch_size: Optional[int] = None,
        apply_cloud_to_edge: bool = True,
    ) -> EdgeSyncResult:
        """
        Execute full bidirectional synchronization cycle:
        1. Check Qdrant Server availability
        2. Edge → Cloud drain: upload all eligible pending SyncItems
        3. Enter Synchronization Barrier
        4. Cloud → Edge refresh: fetch server state, detect conflicts, populate immutable shard
        5. Mutable Shard Cleanup: purge only verified synced points
        6. Release Barrier & log audit events
        """
        start_time = time.perf_counter()
        sync_run_id = str(uuid.uuid4())

        # 1. Health check
        is_cloud_alive = await self.backend.health_check()
        if not is_cloud_alive:
            duration = (time.perf_counter() - start_time) * 1000
            msg = "Synchronization aborted: Qdrant Server is unavailable/offline."
            logger.warning("sync_aborted_server_unavailable", sync_run_id=sync_run_id)
            return EdgeSyncResult(
                started=False,
                uploaded=0,
                deleted=0,
                failed=0,
                conflicts=0,
                snapshot_applied=False,
                duration_ms=round(duration, 2),
                message=msg,
                barrier_state="ABORTED",
            )

        # Audit: SYNC_STARTED
        start_time_iso = datetime.now(timezone.utc).isoformat()
        await self.audit_repo.log_event(
            event_type="SYNC_STARTED",
            description=f"Bidirectional Edge ↔ Cloud sync initiated (Run ID: {sync_run_id})",
            entity_type="sync_run",
            entity_id=sync_run_id,
            details={"device_id": settings.device_id, "server_url": self.backend.server_url, "start_time": start_time_iso},
            severity="info",
            operation_id=sync_run_id,
            device_id=settings.device_id,
        )

        uploaded = 0
        deleted = 0
        failed = 0
        conflicts = 0
        snapshot_applied = False
        server_points_count = 0

        # Acquire Synchronization Barrier Lock
        async with _SYNC_BARRIER_LOCK:
            barrier_state = "PREPARE_SYNC"
            logger.info("sync_barrier_acquired", sync_run_id=sync_run_id)

            # =================================================================
            # Phase 7A: Edge → Cloud Upload (Drain Pending Queue)
            # =================================================================
            barrier_state = "DRAIN_LOCAL_UPLOADS"
            limit = batch_size or settings.sync_batch_size

            engine = SyncEngine(self.session, backend=self.backend)
            batch_result = await engine.run_batch(batch_size=limit)

            uploaded = batch_result.items_succeeded
            failed = batch_result.items_failed
            conflicts += batch_result.conflicts_detected

            # Audit upload results
            if uploaded > 0:
                await self.audit_repo.log_event(
                    event_type="SYNC_UPLOAD_SUCCESS",
                    description=f"Successfully uploaded {uploaded} items to Qdrant Server",
                    entity_type="sync_run",
                    entity_id=sync_run_id,
                    details={"count": uploaded, "duration_ms": batch_result.duration_ms},
                    severity="info",
                    device_id=settings.device_id,
                )

            if failed > 0:
                await self.audit_repo.log_event(
                    event_type="SYNC_UPLOAD_FAILED",
                    description=f"{failed} items failed remote Qdrant upload",
                    entity_type="sync_run",
                    entity_id=sync_run_id,
                    details={"count": failed},
                    severity="warning",
                    device_id=settings.device_id,
                )

            # =================================================================
            # Phase 7B: Cloud → Edge Refresh & Conflict Detection
            # =================================================================
            if apply_cloud_to_edge and is_cloud_alive:
                barrier_state = "OBTAIN_SERVER_DATA"
                try:
                    server_records = await self.backend.fetch_server_points(limit=500)
                    server_points_count = len(server_records)

                    barrier_state = "APPLY_IMMUTABLE"
                    await self.audit_repo.log_event(
                        event_type="SYNC_SNAPSHOT_STARTED",
                        description=f"Cloud → Edge synchronization: ingesting {server_points_count} points into immutable shard",
                        entity_type="sync_run",
                        entity_id=sync_run_id,
                        details={"server_points_count": server_points_count},
                        severity="info",
                        device_id=settings.device_id,
                    )

                    # Initialize or clear local immutable shard
                    self.edge_service.init_immutable_shard()

                    verified_points: set[str] = set()

                    for rec in server_records:
                        point_id = str(rec.id)
                        payload = rec.payload or {}
                        vector = rec.vector

                        # Extract dense vector
                        dense_vec: list[float] = []
                        if isinstance(vector, list):
                            dense_vec = vector
                        elif isinstance(vector, dict) and "dense" in vector:
                            dense_vec = vector["dense"]

                        if not dense_vec or len(dense_vec) != settings.edge_vector_dimension:
                            continue

                        text_val = payload.get("text") or payload.get("content") or ""

                        # Ingest into immutable shard
                        try:
                            self.edge_service.upsert_chunk(
                                point_id=point_id,
                                dense_vector=dense_vec,
                                text=text_val,
                                payload=payload,
                                shard_type="immutable",
                            )
                            verified_points.add(point_id)
                        except Exception as e:
                            logger.warning("immutable_ingest_failed", point_id=point_id, error=str(e))

                        # Conflict and change detection against local SQLite
                        detected_conflict = await self._detect_and_reconcile_record(payload)
                        if detected_conflict:
                            conflicts += 1

                    self.edge_service.flush("immutable")

                    barrier_state = "VERIFY_IMMUTABLE"
                    if self.edge_service.is_healthy("immutable"):
                        snapshot_applied = True
                        await self.audit_repo.log_event(
                            event_type="SYNC_SNAPSHOT_COMPLETED",
                            description=f"Immutable shard verified with {len(verified_points)} active points",
                            entity_type="sync_run",
                            entity_id=sync_run_id,
                            details={"points_ingested": len(verified_points)},
                            severity="info",
                            device_id=settings.device_id,
                        )

                        # =========================================================
                        # Phase 7C: Mutable Shard Cleanup (Safe Data Loss Prevention)
                        # =========================================================
                        if settings.sync_cleanup_mutable_after_refresh and verified_points:
                            await self._cleanup_mutable_shard(verified_points)

                except Exception as exc:
                    logger.error("cloud_to_edge_sync_failed", error=str(exc), exc_info=True)

            barrier_state = "NORMAL"

        total_duration = (time.perf_counter() - start_time) * 1000
        remote_time_ms = batch_result.duration_ms if 'batch_result' in locals() else 0.0
        queue_time_ms = max(0.0, total_duration - remote_time_ms)

        msg = (
            f"Edge ↔ Cloud synchronization complete: {uploaded} uploaded to cloud, "
            f"{failed} failed, {conflicts} conflicts detected. "
            f"Immutable shard updated ({server_points_count} points)."
        )

        from app.core.metrics import get_metrics_registry
        metrics = get_metrics_registry()
        metrics.inc_sync_run("completed" if failed == 0 else "partial")
        if uploaded > 0:
            metrics.inc_sync_record("upload", "success")
        if failed > 0:
            metrics.inc_sync_record("upload", "failed")

        await self.audit_repo.log_event(
            event_type="SYNC_COMPLETED",
            description=msg,
            entity_type="sync_run",
            entity_id=sync_run_id,
            details={
                "sync_run_id": sync_run_id,
                "start_time": start_time_iso,
                "end_time": datetime.now(timezone.utc).isoformat(),
                "duration_ms": round(total_duration, 2),
                "queue_time_ms": round(queue_time_ms, 2),
                "remote_operation_time_ms": round(remote_time_ms, 2),
                "total_sync_run_time_ms": round(total_duration, 2),
                "records_attempted": uploaded + failed + deleted,
                "uploaded": uploaded,
                "deleted": deleted,
                "failed": failed,
                "conflicts": conflicts,
                "snapshot_status": "applied" if snapshot_applied else "unchanged",
                "snapshot_applied": snapshot_applied,
            },
            severity="info",
            operation_id=sync_run_id,
            device_id=settings.device_id,
        )

        await self.session.commit()

        return EdgeSyncResult(
            started=True,
            uploaded=uploaded,
            deleted=deleted,
            failed=failed,
            conflicts=conflicts,
            snapshot_applied=snapshot_applied,
            duration_ms=round(total_duration, 2),
            message=msg,
            server_points_count=server_points_count,
            barrier_state=barrier_state,
        )

    # =========================================================================
    # Conflict Detection & Reconciliation
    # =========================================================================

    async def _detect_and_reconcile_record(self, cloud_payload: dict[str, Any]) -> bool:
        """
        Reconcile a cloud point payload with local SQLite MemoryRecord:
        - NO_CHANGE: revision and hash match
        - LOCAL_NEWER: local revision > cloud revision
        - REMOTE_NEWER: cloud revision > local revision (update local record)
        - CONFLICT: independent edits with differing content hashes
        """
        record_id = cloud_payload.get("record_id")
        if not record_id:
            return False

        cloud_rev = int(cloud_payload.get("revision", 1))
        cloud_device = cloud_payload.get("origin_device") or cloud_payload.get("device_id") or "remote"
        cloud_text = cloud_payload.get("text") or cloud_payload.get("content") or ""
        cloud_hash = cloud_payload.get("content_hash")
        if not cloud_hash:
            import hashlib
            cloud_hash = hashlib.sha256(cloud_text.encode("utf-8")).hexdigest()

        stmt = select(MemoryRecord).where(MemoryRecord.id == record_id)
        res = await self.session.execute(stmt)
        local_rec = res.scalar_one_or_none()

        if local_rec is None:
            # Cloud has a record we don't have locally -> ingest into SQLite
            new_rec = MemoryRecord(
                id=record_id,
                device_id=cloud_device,
                content=cloud_text,
                content_hash=cloud_hash,
                record_type=cloud_payload.get("record_type", "note"),
                sensitivity=cloud_payload.get("sensitivity", "internal"),
                sync_status="synced",
                version=1,
                revision=cloud_rev,
                origin_device=cloud_device,
                last_synced_revision=cloud_rev,
                created_at=utcnow(),
                updated_at=utcnow(),
            )
            self.session.add(new_rec)
            return False

        # Compare hashes and revisions
        local_rev = local_rec.revision or 1
        local_hash = local_rec.content_hash

        if local_hash == cloud_hash:
            # NO_CHANGE: identical content
            if local_rec.sync_status != "synced":
                local_rec.sync_status = "synced"
                local_rec.last_synced_revision = cloud_rev
            return False

        # Hashes differ
        if local_rec.sync_status == "synced" and cloud_rev > local_rev:
            # REMOTE_NEWER: local had no pending changes, safely advance local
            local_rec.content = cloud_text
            local_rec.content_hash = cloud_hash
            local_rec.revision = cloud_rev
            local_rec.last_synced_revision = cloud_rev
            local_rec.updated_at = utcnow()
            logger.info("remote_newer_applied", record_id=record_id, new_revision=cloud_rev)
            return False

        if local_rev > cloud_rev:
            # LOCAL_NEWER: local has edits awaiting push
            return False

        # Both modified independently -> CONFLICT!
        conflict_id = str(uuid.uuid4())
        conflict = Conflict(
            id=conflict_id,
            record_type=local_rec.record_type,
            record_id=record_id,
            local_revision=local_rev,
            local_content_hash=local_hash,
            local_updated_at=local_rec.updated_at or utcnow(),
            local_content_preview=local_rec.content[:200] if local_rec.content else None,
            local_device_id=settings.device_id,
            cloud_revision=cloud_rev,
            cloud_content_hash=cloud_hash,
            cloud_updated_at=utcnow(),
            cloud_content_preview=cloud_text[:200] if cloud_text else None,
            cloud_device_id=cloud_device,
            status="open",
            created_at=utcnow(),
        )
        self.session.add(conflict)

        # Mark local record as conflict
        local_rec.sync_status = "conflict"

        await self.audit_repo.log_event(
            event_type="SYNC_CONFLICT_DETECTED",
            description=f"Conflict detected on record '{record_id}' (local rev {local_rev} vs cloud rev {cloud_rev})",
            entity_type="conflict",
            entity_id=conflict_id,
            details={
                "record_id": record_id,
                "local_revision": local_rev,
                "cloud_revision": cloud_rev,
                "local_hash": local_hash,
                "cloud_hash": cloud_hash,
            },
            severity="warning",
            device_id=settings.device_id,
        )

        logger.warning(
            "sync_conflict_detected_and_persisted",
            conflict_id=conflict_id,
            record_id=record_id,
            local_rev=local_rev,
            cloud_rev=cloud_rev,
        )
        return True

    # =========================================================================
    # Mutable Shard Cleanup (Safe Data Loss Prevention)
    # =========================================================================

    async def _cleanup_mutable_shard(self, verified_immutable_points: set[str]) -> None:
        """
        Safely remove duplicate points from the mutable shard only after:
        1. The point successfully synced to Qdrant Server.
        2. The point is verified present in the newly refreshed immutable shard.
        3. The local MemoryRecord is marked 'synced'.
        """
        # Find local records marked 'synced'
        stmt = select(MemoryRecord.id).where(MemoryRecord.sync_status == "synced")
        res = await self.session.execute(stmt)
        synced_record_ids = set(res.scalars().all())

        points_to_remove: list[str] = []
        for rec_id in synced_record_ids:
            pt_id = generate_point_id_from_chunk_id(rec_id)
            if pt_id in verified_immutable_points:
                points_to_remove.append(pt_id)

        if points_to_remove:
            try:
                self.edge_service.delete_points(points_to_remove, shard_type="mutable")
                self.edge_service.flush("mutable")
                logger.info(
                    "mutable_shard_cleaned_up",
                    count=len(points_to_remove),
                    note="Removed duplicate points verified in immutable shard",
                )
            except Exception as e:
                logger.warning("mutable_shard_cleanup_failed", error=str(e))
