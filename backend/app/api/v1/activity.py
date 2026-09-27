"""Activity API — Audit event timeline."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.api import ActivityListResponse

router = APIRouter()


@router.get("", response_model=ActivityListResponse)
async def list_activity(
    page: int = 1,
    page_size: int = 50,
    event_type: str | None = None,
    entity_type: str | None = None,
    severity: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Get activity timeline with optional filtering."""
    raise HTTPException(status_code=501, detail="Not yet implemented")
