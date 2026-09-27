"""
EDGEWISE AI — Audit Repository

Persistence for immutable audit trail events.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
            severity=severity,
            request_id=request_id,
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
