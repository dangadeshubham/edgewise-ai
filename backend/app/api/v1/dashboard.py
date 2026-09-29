"""
EDGEWISE AI — Dashboard API

Live aggregated system metrics computed directly from real persisted application state.
No simulated success or hardcoded metrics.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.repositories.document import DocumentRepository
from app.repositories.memory import MemoryRecordRepository
from app.repositories.sync import ConflictRepository, SyncRepository
from app.schemas.api import DashboardMetrics
from app.services.connectivity.service import ConnectivityService

router = APIRouter()
settings = get_settings()


@router.get("/metrics", response_model=DashboardMetrics)
async def get_dashboard_metrics(
    db: AsyncSession = Depends(get_db),
) -> DashboardMetrics:
    """Get live aggregated dashboard metrics computed strictly from persisted state."""
    # 1. Real connectivity state
    conn_service = ConnectivityService()
    conn_status = await conn_service.get_connectivity_status()

    # 2. Database repositories
    doc_repo = DocumentRepository(db)
    memory_repo = MemoryRecordRepository(db)
    sync_repo = SyncRepository(db)
    conflict_repo = ConflictRepository(db)

    # 3. Query actual database counts
    total_docs = await doc_repo.count_active()
    processed_docs = await doc_repo.count_by_status("completed")
    failed_docs = await doc_repo.count_by_status("failed")
    storage_bytes = await doc_repo.get_storage_bytes()

    memory_count = await memory_repo.count_active()

    # Edge Memory Real Metrics
    from app.services.edge_memory import get_edge_memory_service
    edge_service = get_edge_memory_service()
    mutable_points = edge_service.count_points("mutable")
    immutable_points = edge_service.count_points("immutable") if edge_service.has_immutable_shard() else 0
    edge_available = edge_service.is_healthy("mutable")
    last_flush = edge_service.last_flush_time

    # Query embedded vs unembedded chunks from persisted DB records
    from sqlalchemy import func, select
    from app.models.database import DocumentChunk
    vector_res = await db.execute(
        select(func.count(DocumentChunk.id)).where(DocumentChunk.is_embedded.is_(True))
    )
    embedded_chunks = vector_res.scalar() or 0

    unembedded_res = await db.execute(
        select(func.count(DocumentChunk.id)).where(DocumentChunk.is_embedded.is_(False))
    )
    unembedded_chunks = unembedded_res.scalar() or 0

    # Query synced cloud records from persisted DB state
    from app.models.database import MemoryRecord
    cloud_res = await db.execute(
        select(func.count(MemoryRecord.id)).where(
            MemoryRecord.sync_status == "synced",
            MemoryRecord.deleted_at.is_(None),
        )
    )
    cloud_records = cloud_res.scalar() or 0

    pending_sync = await sync_repo.count_by_status("pending")
    failed_sync = await sync_repo.count_by_status("failed")
    last_sync = await sync_repo.get_last_successful_sync_time()
    open_conflicts = await conflict_repo.count_open()

    conn_state = conn_status.get("state") if isinstance(conn_status, dict) else getattr(conn_status, "state", "unknown")
    return DashboardMetrics(
        connectivity_state=conn_state,
        local_memory_records=memory_count,
        local_vector_count=embedded_chunks,
        cloud_record_count=cloud_records,
        pending_sync=pending_sync,
        failed_sync=failed_sync,
        open_conflicts=open_conflicts,
        last_successful_sync=last_sync,
        current_device_id=settings.device_id,
        current_device_name=settings.device_name,
        current_device_site=settings.device_site,
        total_documents=total_docs,
        processed_documents=processed_docs,
        failed_documents=failed_docs,
        storage_usage_bytes=storage_bytes,
        edge_mutable_points=mutable_points,
        edge_immutable_points=immutable_points,
        embedded_chunks=embedded_chunks,
        unembedded_chunks=unembedded_chunks,
        edge_storage_path="data/qdrant_edge/mutable",
        edge_shard_available=edge_available,
        edge_last_flush=last_flush,
    )
