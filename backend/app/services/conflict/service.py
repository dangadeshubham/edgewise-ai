"""
EDGEWISE AI — Conflict Resolution Service (Phase 8)

Handles:
- Conflict lifecycle management (OPEN -> IN_REVIEW -> RESOLVED / DISMISSED)
- Side-by-side diff generation and comparison
- Optimistic locking for concurrent resolution protection
- Explicit resolution actions: KEEP_LOCAL, KEEP_CLOUD, MERGE, MANUAL
- Monotonic revision rules: max(local_rev, cloud_rev) + 1
- Local Edge memory vector updates (preventing stale vector retrieval)
- Follow-up durable sync queue scheduling (SyncItem)
- Comprehensive audit event logging
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Optional, Sequence

import structlog
from sqlalchemy import desc, asc, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.database import Conflict, MemoryRecord
from app.repositories.audit import AuditRepository
from app.services.conflict.constants import (
    ConflictAuditEvent,
    ConflictConcurrencyError,
    ConflictNotFoundError,
    ConflictResolutionType,
    ConflictState,
    ConflictStateError,
    ConflictValidationError,
)
from app.services.conflict.diff import ConflictDiffResult, DiffEngine
from app.services.edge_memory.service import EdgeMemoryService, get_edge_memory_service
from app.services.embeddings.service import EmbeddingService, get_embedding_service
from app.services.synchronization.constants import SyncOperation, SyncState
from app.services.synchronization.queue_service import SyncQueueService

logger = structlog.get_logger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _compute_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ConflictService:
    """Manages conflict review, comparison, resolution, and edge vector updates."""

    def __init__(
        self,
        session: AsyncSession,
        edge_service: Optional[EdgeMemoryService] = None,
        embedding_service: Optional[EmbeddingService] = None,
    ) -> None:
        self.session = session
        self.edge_service = edge_service or get_edge_memory_service()
        self.embedding_service = embedding_service or get_embedding_service()
        self.audit_repo = AuditRepository(session)
        self.queue_service = SyncQueueService(session)

    # -------------------------------------------------------------------------
    # Retrieval & Listing
    # -------------------------------------------------------------------------

    async def list_conflicts(
        self,
        status: Optional[str] = None,
        device_id: Optional[str] = None,
        entity_type: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        sort_by: str = "newest",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[Sequence[Conflict], int]:
        """
        List conflicts with real query filters and pagination.
        sort_by: 'newest' (created_at DESC), 'oldest_unresolved' (created_at ASC)
        """
        stmt = select(Conflict)

        if status:
            stmt = stmt.where(Conflict.status == status)
        if device_id:
            stmt = stmt.where(
                (Conflict.local_device_id == device_id) | (Conflict.cloud_device_id == device_id)
            )
        if entity_type:
            stmt = stmt.where(Conflict.record_type == entity_type)
        if date_from:
            stmt = stmt.where(Conflict.created_at >= date_from)
        if date_to:
            stmt = stmt.where(Conflict.created_at <= date_to)

        # Count query
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_res = await self.session.execute(count_stmt)
        total_count = total_res.scalar_one()

        # Sorting
        if sort_by == "oldest_unresolved":
            stmt = stmt.order_by(asc(Conflict.created_at))
        else:
            stmt = stmt.order_by(desc(Conflict.created_at))

        stmt = stmt.limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        items = result.scalars().all()

        return items, total_count

    async def get_conflict(self, conflict_id: str) -> Conflict:
        """Fetch conflict by ID, raising ConflictNotFoundError if missing."""
        stmt = select(Conflict).where(Conflict.id == conflict_id)
        result = await self.session.execute(stmt)
        conflict = result.scalar_one_or_none()
        if conflict is None:
            raise ConflictNotFoundError(f"Conflict '{conflict_id}' not found.")
        return conflict

    async def get_conflict_with_diff(self, conflict_id: str) -> tuple[Conflict, ConflictDiffResult]:
        """Fetch conflict and compute side-by-side diff."""
        conflict = await self.get_conflict(conflict_id)

        local_meta = {
            "revision": conflict.local_revision,
            "content_hash": conflict.local_content_hash,
            "device_id": conflict.local_device_id,
            "updated_at": conflict.local_updated_at.isoformat() if conflict.local_updated_at else "",
        }
        cloud_meta = {
            "revision": conflict.cloud_revision,
            "content_hash": conflict.cloud_content_hash,
            "device_id": conflict.cloud_device_id,
            "updated_at": conflict.cloud_updated_at.isoformat() if conflict.cloud_updated_at else "",
        }

        diff = DiffEngine.compute_diff(
            local_content=conflict.local_content_preview or "",
            cloud_content=conflict.cloud_content_preview or "",
            local_meta=local_meta,
            cloud_meta=cloud_meta,
        )
        return conflict, diff

    # -------------------------------------------------------------------------
    # Lifecycle: Claim
    # -------------------------------------------------------------------------

    async def claim_conflict(
        self,
        conflict_id: str,
        claimed_by: str,
        expected_version: Optional[int] = None,
    ) -> Conflict:
        """
        Transition conflict from OPEN to IN_REVIEW.
        Enforces optimistic concurrency locking.
        """
        conflict = await self.get_conflict(conflict_id)

        if expected_version is not None and conflict.version != expected_version:
            raise ConflictConcurrencyError(
                f"Conflict '{conflict_id}' was modified concurrently (current version {conflict.version} != expected {expected_version})."
            )

        if conflict.status in (ConflictState.RESOLVED.value, ConflictState.DISMISSED.value):
            raise ConflictStateError(
                f"Cannot claim conflict '{conflict_id}' in terminal state '{conflict.status}'."
            )

        conflict.status = ConflictState.IN_REVIEW.value
        conflict.version = (conflict.version or 1) + 1

        await self.audit_repo.log_event(
            event_type=ConflictAuditEvent.CONFLICT_CLAIMED.value,
            description=f"Conflict '{conflict_id}' claimed by '{claimed_by}' for review.",
            entity_type="conflict",
            entity_id=conflict_id,
            details={
                "conflict_id": conflict_id,
                "record_id": conflict.record_id,
                "claimed_by": claimed_by,
                "new_version": conflict.version,
            },
            severity="info",
            device_id=settings.device_id,
        )

        await self.session.flush()
        return conflict

    # -------------------------------------------------------------------------
    # Resolution: KEEP_LOCAL
    # -------------------------------------------------------------------------

    async def resolve_keep_local(
        self,
        conflict_id: str,
        resolved_by: str,
        notes: Optional[str] = None,
        expected_version: Optional[int] = None,
    ) -> Conflict:
        """
        Resolves conflict by preserving the local content and assigning a monotonic revision.
        Creates a follow-up SyncItem for Qdrant Server synchronization.
        """
        conflict = await self._validate_and_prepare_resolution(conflict_id, expected_version)
        record = await self._get_memory_record(conflict.record_id)

        # Monotonic revision assignment: max(local_rev, cloud_rev) + 1
        new_rev = max(record.revision, conflict.cloud_revision) + 1

        record.revision = new_rev
        record.sync_status = "pending"
        record.updated_at = _utc_now()

        # Enqueue follow-up synchronization so Qdrant Server receives the authoritative winner
        await self.queue_service.enqueue(
            record_type=record.record_type,
            record_id=record.id,
            operation=SyncOperation.UPSERT,
            payload={
                "content": record.content,
                "revision": new_rev,
                "content_hash": record.content_hash,
                "resolution": "keep_local",
            },
            revision=new_rev,
            content_hash=record.content_hash,
        )

        # Update conflict record
        conflict.status = ConflictState.RESOLVED.value
        conflict.resolution = ConflictResolutionType.KEEP_LOCAL.value
        conflict.resolved_by = resolved_by
        conflict.resolved_at = _utc_now()
        conflict.resolution_notes = notes
        conflict.resolution_metadata_json = json.dumps({
            "selected_version": "local",
            "assigned_revision": new_rev,
            "preserved_cloud_hash": conflict.cloud_content_hash,
            "preserved_cloud_revision": conflict.cloud_revision,
        })
        conflict.version = (conflict.version or 1) + 1

        # Audit events
        await self._log_resolution_events(
            conflict=conflict,
            event_type=ConflictAuditEvent.CONFLICT_KEEP_LOCAL.value,
            resolved_by=resolved_by,
            new_rev=new_rev,
            notes=notes,
        )

        await self.session.flush()
        logger.info(
            "conflict_resolved_keep_local",
            conflict_id=conflict_id,
            record_id=record.id,
            assigned_revision=new_rev,
        )
        return conflict

    # -------------------------------------------------------------------------
    # Resolution: KEEP_CLOUD
    # -------------------------------------------------------------------------

    async def resolve_keep_cloud(
        self,
        conflict_id: str,
        resolved_by: str,
        notes: Optional[str] = None,
        expected_version: Optional[int] = None,
    ) -> Conflict:
        """
        Resolves conflict by adopting the cloud content.
        Updates SQLite record and local Edge memory embedding so stale data is replaced immediately.
        """
        conflict = await self._validate_and_prepare_resolution(conflict_id, expected_version)
        record = await self._get_memory_record(conflict.record_id)

        # Cloud version data
        cloud_content = conflict.cloud_content_preview or ""
        cloud_hash = conflict.cloud_content_hash or _compute_sha256(cloud_content)
        new_rev = max(record.revision, conflict.cloud_revision) + 1

        # 1. Update SQLite record
        record.content = cloud_content
        record.content_hash = cloud_hash
        record.revision = new_rev
        record.sync_status = SyncState.SYNCED.value  # Cloud already has this content
        record.origin_device = conflict.cloud_device_id
        record.updated_at = _utc_now()

        # 2. Update local Edge memory vector representation immediately
        try:
            self._update_edge_memory_vector(
                record_id=record.id,
                content=cloud_content,
                revision=new_rev,
                content_hash=cloud_hash,
                origin_device=conflict.cloud_device_id or "cloud",
                record_type=record.record_type,
                sensitivity=record.sensitivity,
            )
        except Exception as exc:
            logger.warning("failed_to_update_edge_vector_on_keep_cloud", error=str(exc))

        # 3. Update conflict record
        conflict.status = ConflictState.RESOLVED.value
        conflict.resolution = ConflictResolutionType.KEEP_CLOUD.value
        conflict.resolved_by = resolved_by
        conflict.resolved_at = _utc_now()
        conflict.resolution_notes = notes
        conflict.resolution_metadata_json = json.dumps({
            "selected_version": "cloud",
            "assigned_revision": new_rev,
            "superseded_local_hash": conflict.local_content_hash,
            "superseded_local_revision": conflict.local_revision,
        })
        conflict.version = (conflict.version or 1) + 1

        # Audit events
        await self._log_resolution_events(
            conflict=conflict,
            event_type=ConflictAuditEvent.CONFLICT_KEEP_CLOUD.value,
            resolved_by=resolved_by,
            new_rev=new_rev,
            notes=notes,
        )

        await self.session.flush()
        logger.info(
            "conflict_resolved_keep_cloud",
            conflict_id=conflict_id,
            record_id=record.id,
            assigned_revision=new_rev,
        )
        return conflict

    # -------------------------------------------------------------------------
    # Resolution: MERGE
    # -------------------------------------------------------------------------

    async def resolve_merge(
        self,
        conflict_id: str,
        merged_content: str,
        resolved_by: str,
        notes: Optional[str] = None,
        expected_version: Optional[int] = None,
    ) -> Conflict:
        """
        Resolves conflict by applying user-approved merged content.
        Validates content, calculates SHA-256, assigns monotonic revision,
        updates Edge vector, and enqueues durable sync for cloud upload.
        """
        return await self._apply_custom_content_resolution(
            conflict_id=conflict_id,
            content=merged_content,
            resolution_type=ConflictResolutionType.MERGE.value,
            audit_event_type=ConflictAuditEvent.CONFLICT_MERGED.value,
            resolved_by=resolved_by,
            notes=notes,
            expected_version=expected_version,
        )

    # -------------------------------------------------------------------------
    # Resolution: MANUAL
    # -------------------------------------------------------------------------

    async def resolve_manual(
        self,
        conflict_id: str,
        manual_content: str,
        resolved_by: str,
        notes: Optional[str] = None,
        expected_version: Optional[int] = None,
    ) -> Conflict:
        """
        Resolves conflict with manually entered content from the user.
        Validates content, calculates SHA-256, assigns monotonic revision,
        updates Edge vector, and enqueues durable sync for cloud upload.
        """
        return await self._apply_custom_content_resolution(
            conflict_id=conflict_id,
            content=manual_content,
            resolution_type=ConflictResolutionType.MANUAL.value,
            audit_event_type=ConflictAuditEvent.CONFLICT_MANUAL.value,
            resolved_by=resolved_by,
            notes=notes,
            expected_version=expected_version,
        )

    # -------------------------------------------------------------------------
    # Lifecycle: Dismiss
    # -------------------------------------------------------------------------

    async def dismiss_conflict(
        self,
        conflict_id: str,
        dismissed_by: str,
        reason: Optional[str] = None,
        expected_version: Optional[int] = None,
    ) -> Conflict:
        """
        Dismisses a conflict without altering the local record or remote state.
        Preserves complete history for administrative audit.
        """
        conflict = await self.get_conflict(conflict_id)

        if conflict.status in (ConflictState.RESOLVED.value, ConflictState.DISMISSED.value):
            raise ConflictStateError(
                f"Cannot dismiss conflict '{conflict_id}' already in state '{conflict.status}'."
            )

        if expected_version is not None and conflict.version != expected_version:
            raise ConflictConcurrencyError(
                f"Conflict '{conflict_id}' was modified concurrently (current version {conflict.version} != expected {expected_version})."
            )

        conflict.status = ConflictState.DISMISSED.value
        conflict.resolved_by = dismissed_by
        conflict.resolved_at = _utc_now()
        conflict.resolution_notes = reason
        conflict.version = (conflict.version or 1) + 1

        await self.audit_repo.log_event(
            event_type=ConflictAuditEvent.CONFLICT_DISMISSED.value,
            description=f"Conflict '{conflict_id}' was dismissed by '{dismissed_by}'.",
            entity_type="conflict",
            entity_id=conflict_id,
            details={
                "conflict_id": conflict_id,
                "record_id": conflict.record_id,
                "dismissed_by": dismissed_by,
                "reason": reason,
            },
            severity="info",
            device_id=settings.device_id,
        )

        await self.session.flush()
        return conflict

    # -------------------------------------------------------------------------
    # AI Merge Suggestion (Strictly Non-Autonomous)
    # -------------------------------------------------------------------------

    async def generate_suggested_merge(self, conflict_id: str) -> dict[str, Any]:
        """
        Generates a non-autonomous, human-review-only merge suggestion.
        NEVER automatically published or committed to database.
        """
        conflict = await self.get_conflict(conflict_id)

        local_lines = (conflict.local_content_preview or "").splitlines()
        cloud_lines = (conflict.cloud_content_preview or "").splitlines()

        # Heuristic 3-way line union preserving distinct non-duplicate information
        merged_set: list[str] = []
        for line in local_lines:
            merged_set.append(line)
        for line in cloud_lines:
            if line not in merged_set:
                merged_set.append(line)

        suggested_text = "\n".join(merged_set)

        return {
            "conflict_id": conflict_id,
            "label": "AI suggested merge",
            "source": "deterministic_line_union",
            "requires_user_approval": True,
            "suggested_content": suggested_text,
            "note": "This is an unapproved suggestion. Review and modify before saving.",
        }

    # -------------------------------------------------------------------------
    # Internal Helpers
    # -------------------------------------------------------------------------

    async def _validate_and_prepare_resolution(
        self,
        conflict_id: str,
        expected_version: Optional[int],
    ) -> Conflict:
        """Validate that conflict is actionable and optimistic lock holds."""
        conflict = await self.get_conflict(conflict_id)

        if expected_version is not None and conflict.version != expected_version:
            raise ConflictConcurrencyError(
                f"Conflict '{conflict_id}' was modified concurrently (current version {conflict.version} != expected {expected_version})."
            )

        if conflict.status in (ConflictState.RESOLVED.value, ConflictState.DISMISSED.value):
            raise ConflictStateError(
                f"Conflict '{conflict_id}' is already {conflict.status}."
            )

        return conflict

    async def _get_memory_record(self, record_id: str) -> MemoryRecord:
        """Fetch MemoryRecord or raise ValidationError."""
        stmt = select(MemoryRecord).where(MemoryRecord.id == record_id)
        result = await self.session.execute(stmt)
        record = result.scalar_one_or_none()
        if record is None:
            raise ConflictValidationError(f"Underlying MemoryRecord '{record_id}' not found.")
        return record

    async def _apply_custom_content_resolution(
        self,
        conflict_id: str,
        content: str,
        resolution_type: str,
        audit_event_type: str,
        resolved_by: str,
        notes: Optional[str],
        expected_version: Optional[int],
    ) -> Conflict:
        """Shared logic for MERGE and MANUAL resolutions."""
        if not content or not content.strip():
            raise ConflictValidationError("Resolution content cannot be empty.")
        if len(content) > 1_000_000:
            raise ConflictValidationError("Resolution content exceeds 1MB limit.")

        conflict = await self._validate_and_prepare_resolution(conflict_id, expected_version)
        record = await self._get_memory_record(conflict.record_id)

        new_hash = _compute_sha256(content)
        new_rev = max(record.revision, conflict.cloud_revision) + 1

        # 1. Update SQLite record
        record.content = content
        record.content_hash = new_hash
        record.revision = new_rev
        record.sync_status = "pending"
        record.updated_at = _utc_now()

        # 2. Update local Edge memory vector representation immediately
        try:
            self._update_edge_memory_vector(
                record_id=record.id,
                content=content,
                revision=new_rev,
                content_hash=new_hash,
                origin_device=settings.device_id,
                record_type=record.record_type,
                sensitivity=record.sensitivity,
            )
        except Exception as exc:
            logger.warning("failed_to_update_edge_vector_on_merge", error=str(exc))

        # 3. Enqueue follow-up SyncItem for remote Qdrant Server update
        await self.queue_service.enqueue(
            record_type=record.record_type,
            record_id=record.id,
            operation=SyncOperation.UPSERT,
            payload={
                "content": content,
                "revision": new_rev,
                "content_hash": new_hash,
                "resolution": resolution_type,
            },
            revision=new_rev,
            content_hash=new_hash,
        )

        # 4. Update conflict record
        conflict.status = ConflictState.RESOLVED.value
        conflict.resolution = resolution_type
        conflict.resolved_by = resolved_by
        conflict.resolved_at = _utc_now()
        conflict.resolution_notes = notes
        conflict.resolution_metadata_json = json.dumps({
            "selected_version": resolution_type,
            "assigned_revision": new_rev,
            "result_content_hash": new_hash,
            "original_local_hash": conflict.local_content_hash,
            "original_cloud_hash": conflict.cloud_content_hash,
        })
        conflict.version = (conflict.version or 1) + 1

        # 5. Audit events
        await self._log_resolution_events(
            conflict=conflict,
            event_type=audit_event_type,
            resolved_by=resolved_by,
            new_rev=new_rev,
            notes=notes,
        )

        await self.session.flush()
        logger.info(
            "conflict_resolved_custom_content",
            conflict_id=conflict_id,
            record_id=record.id,
            resolution_type=resolution_type,
            assigned_revision=new_rev,
        )
        return conflict

    def _update_edge_memory_vector(
        self,
        record_id: str,
        content: str,
        revision: int,
        content_hash: str,
        origin_device: str,
        record_type: str,
        sensitivity: str,
    ) -> None:
        """Regenerates embedding and replaces vector in Edge mutable shard."""
        from app.services.synchronization.qdrant_backend import generate_point_id_from_chunk_id

        point_id = generate_point_id_from_chunk_id(record_id)
        dense_vec = self.embedding_service.embed_text(content)

        payload = {
            "record_id": record_id,
            "memory_record_id": record_id,
            "record_type": record_type,
            "sensitivity": sensitivity,
            "revision": revision,
            "content_hash": content_hash,
            "origin_device": origin_device,
            "text": content,
            "updated_at": _utc_now().isoformat(),
        }

        self.edge_service.upsert_chunk(
            point_id=point_id,
            dense_vector=dense_vec,
            text=content,
            payload=payload,
            shard_type="mutable",
        )
        self.edge_service.flush("mutable")

    async def _log_resolution_events(
        self,
        conflict: Conflict,
        event_type: str,
        resolved_by: str,
        new_rev: int,
        notes: Optional[str],
    ) -> None:
        """Records specific resolution event and universal CONFLICT_RESOLVED event."""
        details = {
            "conflict_id": conflict.id,
            "record_id": conflict.record_id,
            "resolution": conflict.resolution,
            "resolved_by": resolved_by,
            "assigned_revision": new_rev,
            "notes": notes,
        }

        # Specific event (e.g. CONFLICT_KEEP_LOCAL, CONFLICT_MERGED)
        await self.audit_repo.log_event(
            event_type=event_type,
            description=f"Conflict '{conflict.id}' resolved via {conflict.resolution} by '{resolved_by}'.",
            entity_type="conflict",
            entity_id=conflict.id,
            details=details,
            severity="info",
            device_id=settings.device_id,
        )

        # Universal CONFLICT_RESOLVED event
        await self.audit_repo.log_event(
            event_type=ConflictAuditEvent.CONFLICT_RESOLVED.value,
            description=f"Conflict '{conflict.id}' marked RESOLVED.",
            entity_type="conflict",
            entity_id=conflict.id,
            details=details,
            severity="info",
            device_id=settings.device_id,
        )
