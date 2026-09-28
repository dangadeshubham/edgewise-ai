"""
EDGEWISE AI — Audit Repository

Persistence and indexed query interface for the immutable audit trail.
Enforces strict append-only constraints.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional, Sequence, Tuple

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import normalize_event_type
from app.core.errors import EdgewiseStorageError
from app.models.database import AuditEvent
from app.repositories.base import BaseRepository


class AuditRepository(BaseRepository[AuditEvent]):
    """Repository handling database operations for Audit events."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(AuditEvent, session)

    async def log_event(
        self,
        event_type: str,
        description: str,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
        severity: str = "info",
        request_id: Optional[str] = None,
        operation_id: Optional[str] = None,
        device_id: Optional[str] = None,
    ) -> AuditEvent:
        """Create and persist an immutable audit event."""
        details_str = json.dumps(details) if details else None
        event = AuditEvent(
            event_type=event_type,
            description=description,
            entity_type=entity_type,
            entity_id=entity_id,
            details_json=details_str,
            severity=severity.lower(),
            request_id=request_id,
            operation_id=operation_id,
            device_id=device_id,
            created_at=datetime.now(timezone.utc),
        )
        return await self.create(event)

    async def list_by_entity(
        self, entity_type: str, entity_id: str, limit: int = 50
    ) -> Sequence[AuditEvent]:
        """Fetch audit trail for a specific entity."""
        result = await self.session.execute(
            select(AuditEvent)
            .where(
                AuditEvent.entity_type == entity_type,
                AuditEvent.entity_id == entity_id,
            )
            .order_by(AuditEvent.created_at.desc())
            .limit(limit)
        )
        return result.scalars().all()

    async def query_events(
        self,
        event_type: Optional[str] = None,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        device_id: Optional[str] = None,
        severity: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Tuple[Sequence[AuditEvent], int]:
        """
        Indexed, paginated query across audit events with multi-attribute filtering.
        Avoids loading entire dataset into memory.
        """
        filters = []

        if event_type:
            cleaned = event_type.strip()
            norm = normalize_event_type(cleaned)
            # Match either the exact stored string or canonical normalized form or lowercase
            filters.append(
                or_(
                    AuditEvent.event_type == cleaned,
                    AuditEvent.event_type == norm,
                    AuditEvent.event_type == cleaned.lower(),
                    AuditEvent.event_type == cleaned.upper(),
                )
            )

        if entity_type:
            filters.append(AuditEvent.entity_type == entity_type.strip().lower())

        if entity_id:
            filters.append(AuditEvent.entity_id == entity_id.strip())

        if device_id:
            filters.append(AuditEvent.device_id == device_id.strip())

        if severity:
            filters.append(AuditEvent.severity == severity.strip().lower())

        if start_date:
            filters.append(AuditEvent.created_at >= start_date)

        if end_date:
            filters.append(AuditEvent.created_at <= end_date)

        # Count total matches
        count_stmt = select(func.count(AuditEvent.id))
        if filters:
            count_stmt = count_stmt.where(*filters)
        total_res = await self.session.execute(count_stmt)
        total = total_res.scalar() or 0

        # Fetch paginated slice
        stmt = select(AuditEvent)
        if filters:
            stmt = stmt.where(*filters)
        stmt = (
            stmt.order_by(AuditEvent.created_at.desc())
            .offset((max(1, page) - 1) * page_size)
            .limit(page_size)
        )
        items_res = await self.session.execute(stmt)
        items = items_res.scalars().all()

        return items, total

    async def update(self, *args: Any, **kwargs: Any) -> Any:
        """Prevent updates to immutable audit records."""
        raise EdgewiseStorageError("Audit records are append-only and cannot be updated.")

    async def delete(self, *args: Any, **kwargs: Any) -> Any:
        """Prevent deletion of immutable audit records."""
        raise EdgewiseStorageError("Audit records are append-only and cannot be deleted.")
