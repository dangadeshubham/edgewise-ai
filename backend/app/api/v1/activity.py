"""
EDGEWISE AI — Activity & Audit Telemetry API

Serves indexed, queryable operational audit event records with pagination
and multi-field filtering.
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.repositories.audit import AuditRepository
from app.schemas.api import ActivityEventResponse, ActivityListResponse

router = APIRouter()


@router.get("", response_model=ActivityListResponse)
async def list_activity(
    page: int = Query(1, ge=1, description="Page index"),
    page_size: int = Query(50, ge=1, le=200, description="Page size limit"),
    event_type: Optional[str] = Query(None, description="Event type filter"),
    entity_type: Optional[str] = Query(None, description="Entity type filter"),
    entity_id: Optional[str] = Query(None, description="Entity ID filter"),
    device_id: Optional[str] = Query(None, description="Device filter"),
    severity: Optional[str] = Query(None, description="Severity filter (info, warning, error, critical)"),
    start_date: Optional[datetime] = Query(None, description="Inclusive start datetime"),
    end_date: Optional[datetime] = Query(None, description="Inclusive end datetime"),
    db: AsyncSession = Depends(get_db),
) -> ActivityListResponse:
    """Get activity timeline with indexed filtering and cursor pagination."""
    repo = AuditRepository(db)
    items, total = await repo.query_events(
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        device_id=device_id,
        severity=severity,
        start_date=start_date,
        end_date=end_date,
        page=page,
        page_size=page_size,
    )

    event_responses = []
    for item in items:
        details = None
        if item.details_json:
            try:
                details = json.loads(item.details_json)
            except Exception:
                details = {"raw": item.details_json}

        event_responses.append(
            ActivityEventResponse(
                id=item.id,
                device_id=item.device_id,
                event_type=item.event_type,
                entity_type=item.entity_type,
                entity_id=item.entity_id,
                description=item.description,
                severity=item.severity or "info",
                details=details,
                operation_id=item.operation_id,
                request_id=item.request_id,
                created_at=item.created_at,
            )
        )

    pages = math.ceil(total / page_size) if total > 0 else 1
    return ActivityListResponse(
        items=event_responses,
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )
