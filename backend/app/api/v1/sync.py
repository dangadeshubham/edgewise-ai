"""Synchronization API — Queue status, trigger sync, history."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.api import (
    SyncHistoryResponse,
    SyncQueueResponse,
    SyncRunResponse,
    SyncStatusResponse,
)

router = APIRouter()


@router.get("/status", response_model=SyncStatusResponse)
async def get_sync_status(db: AsyncSession = Depends(get_db)):
    """Get current synchronization status and queue metrics."""
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.post("/run", response_model=SyncRunResponse)
async def run_sync(db: AsyncSession = Depends(get_db)):
    """Manually trigger synchronization of pending items."""
    # Implemented in Phase 6-7
    raise HTTPException(status_code=501, detail="Synchronization not yet implemented")


@router.get("/history", response_model=SyncHistoryResponse)
async def get_sync_history(
    page: int = 1,
    page_size: int = 50,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Get synchronization attempt history."""
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.get("/queue", response_model=SyncQueueResponse)
async def get_sync_queue(
    page: int = 1,
    page_size: int = 50,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Get current items in the sync queue."""
    raise HTTPException(status_code=501, detail="Not yet implemented")
