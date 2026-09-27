"""Conflicts API — View and resolve synchronization conflicts."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.api import (
    ConflictListResponse,
    ConflictResolveRequest,
    ConflictResponse,
    SuccessResponse,
)

router = APIRouter()


@router.get("", response_model=ConflictListResponse)
async def list_conflicts(
    page: int = 1,
    page_size: int = 50,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """List all conflicts with optional status filter."""
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.get("/{conflict_id}", response_model=ConflictResponse)
async def get_conflict(conflict_id: str, db: AsyncSession = Depends(get_db)):
    """Get details of a specific conflict."""
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.post("/{conflict_id}/resolve", response_model=SuccessResponse)
async def resolve_conflict(
    conflict_id: str,
    request: ConflictResolveRequest,
    db: AsyncSession = Depends(get_db),
):
    """Resolve a conflict with a chosen strategy."""
    # Implemented in Phase 8
    raise HTTPException(status_code=501, detail="Conflict resolution not yet implemented")
