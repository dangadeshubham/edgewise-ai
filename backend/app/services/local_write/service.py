"""
EDGEWISE AI — Local Write Service (Phase 5)

Clean abstraction for any local knowledge write operation.
Every write must:
  1. Validate
  2. Persist to SQLite
  3. Write/update Qdrant Edge
  4. Create sync metadata (prepare Phase 6)
  5. Create audit event

Does NOT implement cloud synchronization (Phase 6+).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.database import AuditEvent, MemoryRecord, SyncItem
from app.repositories.audit import AuditRepository
from app.services.edge_memory import get_edge_memory_service, generate_point_id_from_chunk_id
from app.services.embeddings import get_embedding_service

settings = get_settings()
logger = structlog.get_logger("edgewise.local_write")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class LocalWriteService:
    """
    Orchestrates local write operations with consistency guarantees.

    All writes go through this service to ensure:
    - SQLite and Qdrant Edge are kept in sync
    - Sync metadata is created for future Phase 6
    - Audit trail is maintained
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.audit_repo = AuditRepository(session)

    async def create_memory_record(
        self,
        content: str,
        record_type: str = "note",
        sensitivity: str = "internal",
        metadata: Optional[dict[str, Any]] = None,
        source_id: Optional[str] = None,
        document_id: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> MemoryRecord:
        """
        Create a new local memory record with full write path:
        validate → SQLite → Qdrant Edge → sync metadata → audit.
        """
        # 1. Validate
        if not content or not content.strip():
            raise ValueError("Memory record content must not be empty")

        content = content.strip()
        if len(content) > 50000:
            raise ValueError("Memory record content exceeds maximum length (50000 chars)")

        valid_types = {"chunk", "note", "observation", "record"}
        if record_type not in valid_types:
            raise ValueError(f"record_type must be one of {valid_types}")

        # 2. Generate content hash
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

        # 3. Persist to SQLite
        record_id = str(uuid.uuid4())
        now = utcnow()

        record = MemoryRecord(
            id=record_id,
            device_id=settings.device_id,
            source_id=source_id,
            document_id=document_id,
            content=content,
            content_hash=content_hash,
            record_type=record_type,
            sensitivity=sensitivity,
            sync_status="pending",
            version=1,
            revision=1,
            origin_device=settings.device_id,
            metadata_json=json.dumps(metadata) if metadata else None,
            created_at=now,
            updated_at=now,
        )
        self.session.add(record)
        await self.session.flush()

        # 4. Write to Qdrant Edge
        try:
            embedding_service = get_embedding_service()
            edge_service = get_edge_memory_service()

            vectors = embedding_service.embed_texts([content])
            if vectors:
                point_id = generate_point_id_from_chunk_id(record_id)
                payload = {
                    "memory_record_id": record_id,
                    "device_id": settings.device_id,
                    "record_type": record_type,
                    "sensitivity": sensitivity,
                    "content_hash": content_hash,
                    "created_at": now.isoformat(),
                    "source_id": source_id,
                    "document_id": document_id,
                }
                edge_service.upsert_chunk(
                    point_id=point_id,
                    dense_vector=vectors[0],
                    text=content,
                    payload=payload,
                    shard_type="mutable",
                )
                edge_service.flush("mutable")

                record.vector_point_id = point_id

                logger.info(
                    "memory_record_embedded",
                    record_id=record_id,
                    point_id=point_id,
                )
        except Exception as e:
            logger.warning(
                "memory_record_embedding_failed",
                record_id=record_id,
                error=str(e),
            )
            # SQLite write succeeded, embedding failed — record is still valid
            # It can be re-embedded later

        # 5. Create sync metadata via SyncQueueService (Phase 6 Durable Queue)
        from app.services.synchronization.queue_service import SyncQueueService
        from app.services.synchronization.constants import SyncOperation

        queue_svc = SyncQueueService(self.session)
        sync_item = await queue_svc.enqueue(
            record_type="memory_record",
            record_id=record_id,
            operation=SyncOperation.UPSERT,
            payload={
                "content": content,
                "content_hash": content_hash,
                "record_type": record_type,
                "sensitivity": sensitivity,
                "metadata": metadata,
                "origin_device": settings.device_id,
                "version": 1,
                "revision": 1,
            },
            revision=1,
            content_hash=content_hash,
            device_id=settings.device_id,
        )

        # 6. Create audit event
        await self.audit_repo.log_event(
            event_type="memory_record_created",
            description=f"Memory record '{record_id}' ({record_type}) created locally.",
            entity_type="memory_record",
            entity_id=record_id,
            details={
                "record_type": record_type,
                "sensitivity": sensitivity,
                "content_length": len(content),
                "content_hash": content_hash,
                "has_vector": record.vector_point_id is not None,
            },
            severity="info",
            request_id=request_id,
            device_id=settings.device_id,
        )

        await self.session.flush()

        logger.info(
            "memory_record_created",
            record_id=record_id,
            record_type=record_type,
            content_length=len(content),
        )

        return record

    async def delete_memory_record(
        self,
        record: MemoryRecord,
        request_id: Optional[str] = None,
    ) -> None:
        """
        Soft-delete a memory record with full cleanup:
        mark deleted → remove from Edge → sync metadata → audit.
        """
        now = utcnow()
        record.deleted_at = now
        record.updated_at = now
        record.sync_status = "pending"

        # Remove from Qdrant Edge
        if record.vector_point_id:
            try:
                edge_service = get_edge_memory_service()
                edge_service.delete_points([record.vector_point_id], shard_type="mutable")
                edge_service.flush("mutable")
            except Exception as e:
                logger.warning(
                    "memory_record_edge_delete_failed",
                    record_id=record.id,
                    error=str(e),
                )

        # Create sync metadata for delete via SyncQueueService (Phase 6 Durable Queue)
        from app.services.synchronization.queue_service import SyncQueueService
        from app.services.synchronization.constants import SyncOperation

        queue_svc = SyncQueueService(self.session)
        sync_item = await queue_svc.enqueue(
            record_type="memory_record",
            record_id=record.id,
            operation=SyncOperation.DELETE,
            payload={
                "record_id": record.id,
                "deleted_at": now.isoformat(),
                "origin_device": settings.device_id,
            },
            revision=(record.revision or 1) + 1,
            content_hash=record.content_hash,
            device_id=settings.device_id,
        )

        # Audit
        await self.audit_repo.log_event(
            event_type="memory_record_deleted",
            description=f"Memory record '{record.id}' soft-deleted.",
            entity_type="memory_record",
            entity_id=record.id,
            severity="warning",
            request_id=request_id,
            device_id=settings.device_id,
        )

        await self.session.flush()
