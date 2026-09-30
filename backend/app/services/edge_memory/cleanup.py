"""
EDGEWISE AI — Vector Shard Integrity and Orphan Cleanup Service

Safely audits and reconciles vector points in local Qdrant Edge shards
against authoritative SQLite records (DocumentChunks and MemoryRecords).
Never blindly deletes data: verifies exact relational references before pruning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.database import Document, DocumentChunk, MemoryRecord
from app.services.edge_memory.point_id import generate_point_id_from_chunk_id
from app.services.edge_memory.service import EdgeMemoryService, get_edge_memory_service

logger = structlog.get_logger("edgewise.vector_cleanup")


@dataclass
class CleanupReport:
    total_scanned: int = 0
    valid_retained: int = 0
    orphans_identified: int = 0
    orphans_deleted: int = 0
    dry_run: bool = True
    orphan_categories: Dict[str, int] = field(default_factory=dict)
    remaining_mutable_points: int = 0
    remaining_immutable_points: int = 0
    details: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_scanned": self.total_scanned,
            "valid_retained": self.valid_retained,
            "orphans_identified": self.orphans_identified,
            "orphans_deleted": self.orphans_deleted,
            "dry_run": self.dry_run,
            "orphan_categories": self.orphan_categories,
            "remaining_mutable_points": self.remaining_mutable_points,
            "remaining_immutable_points": self.remaining_immutable_points,
            "details": self.details[:50],  # cap details for response payload
        }


class VectorCleanupService:
    """Safe reconciliation and pruning service for Qdrant Edge shards."""

    def __init__(
        self,
        db: AsyncSession,
        edge_service: Optional[EdgeMemoryService] = None,
    ) -> None:
        self.db = db
        self.edge_service = edge_service or get_edge_memory_service()

    async def get_valid_identifiers(self) -> tuple[Set[str], Set[str], Set[str]]:
        """
        Query all authoritative, active identifiers from SQLite.
        Returns (valid_chunk_vector_ids, valid_chunk_ids, valid_memory_record_ids).
        """
        # 1. Active Document Chunks
        chunk_stmt = (
            select(DocumentChunk)
            .join(Document, DocumentChunk.document_id == Document.id)
            .where(Document.deleted_at.is_(None))
        )
        chunk_res = await self.db.execute(chunk_stmt)
        active_chunks = chunk_res.scalars().all()

        valid_chunk_vector_ids = {
            c.vector_point_id for c in active_chunks if c.vector_point_id
        }
        valid_chunk_ids = {str(c.id) for c in active_chunks}

        # 2. Active Memory Records
        mem_stmt = select(MemoryRecord).where(MemoryRecord.deleted_at.is_(None))
        mem_res = await self.db.execute(mem_stmt)
        active_mems = mem_res.scalars().all()

        valid_mem_ids: Set[str] = set()
        for m in active_mems:
            valid_mem_ids.add(str(m.id))
            try:
                derived = generate_point_id_from_chunk_id(m.id)
                valid_mem_ids.add(derived)
            except Exception:
                pass

        return valid_chunk_vector_ids, valid_chunk_ids, valid_mem_ids

    async def reconcile_and_cleanup(
        self,
        dry_run: bool = True,
        shard_type: str = "mutable",
    ) -> CleanupReport:
        """
        Scan specified Qdrant shard, identify orphaned vectors, and safely delete them if dry_run=False.
        """
        valid_vector_ids, valid_chunk_ids, valid_mem_ids = await self.get_valid_identifiers()

        report = CleanupReport(dry_run=dry_run)
        orphans_to_delete: List[str] = []

        # Scroll all points in target shard
        offset: Optional[str | int] = None
        scanned_points = []
        while True:
            pts, next_offset = self.edge_service.scroll_points(
                shard_type=shard_type,
                limit=100,
                offset=offset,
                with_payload=True,
                with_vector=False,
            )
            scanned_points.extend(pts)
            if not next_offset or len(pts) == 0:
                break
            offset = next_offset

        report.total_scanned = len(scanned_points)

        for pt in scanned_points:
            pid = str(pt.id)
            pl = pt.payload or {}

            # Check point validity against authoritative SQLite references
            is_valid_chunk = (
                pid in valid_vector_ids
                or pid in valid_chunk_ids
                or pl.get("chunk_id") in valid_chunk_ids
                or pl.get("vector_point_id") in valid_vector_ids
            )
            is_valid_mem = (
                pid in valid_mem_ids
                or pl.get("memory_record_id") in valid_mem_ids
                or pl.get("record_id") in valid_mem_ids
            )

            if is_valid_chunk or is_valid_mem:
                report.valid_retained += 1
                continue

            # Identify orphan reason / category
            rec_type = pl.get("record_type", "unknown")
            text_snippet = pl.get("text", "")
            if "scale 500" in text_snippet or "scale 1000" in text_snippet:
                cat = "benchmark_telemetry"
            elif "test" in text_snippet.lower():
                cat = "unit_test_artifact"
            elif pl.get("document_id"):
                cat = "stale_deleted_document"
            else:
                cat = f"orphan_{rec_type}"

            report.orphan_categories[cat] = report.orphan_categories.get(cat, 0) + 1
            report.orphans_identified += 1
            orphans_to_delete.append(pid)
            if len(report.details) < 50:
                report.details.append(f"Orphan {pid} ({cat}): '{text_snippet[:40]}'")

        # Execute safe deletion if not dry run
        if not dry_run and orphans_to_delete:
            batch_size = 100
            for i in range(0, len(orphans_to_delete), batch_size):
                batch = orphans_to_delete[i : i + batch_size]
                self.edge_service.delete_points(batch, shard_type=shard_type)

            self.edge_service.flush(shard_type)
            report.orphans_deleted = len(orphans_to_delete)

            # Audit logging
            try:
                from app.repositories.audit import AuditRepository
                audit_repo = AuditRepository(self.db)
                await audit_repo.log_event(
                    event_type="VECTOR_SHARD_ORPHANS_PURGED",
                    description=f"Safely purged {report.orphans_deleted} orphaned vectors from {shard_type} shard. Retained {report.valid_retained} valid vectors.",
                    entity_type="qdrant_edge",
                    entity_id=shard_type,
                    details=report.orphan_categories,
                    severity="info",
                )
                await self.db.commit()
            except Exception as e:
                logger.warning("audit_log_failed_for_vector_cleanup", error=str(e))

            logger.info(
                "vector_cleanup_completed",
                shard=shard_type,
                deleted=report.orphans_deleted,
                retained=report.valid_retained,
            )

        report.remaining_mutable_points = self.edge_service.count_points("mutable")
        report.remaining_immutable_points = (
            self.edge_service.count_points("immutable")
            if self.edge_service.has_immutable_shard()
            else 0
        )
        return report
