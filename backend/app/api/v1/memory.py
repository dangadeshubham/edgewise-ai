"""Memory API — Browse and manage memory records."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.api import (
    MemoryListResponse,
    MemoryRecordCreate,
    MemoryRecordResponse,
    SuccessResponse,
)

router = APIRouter()


@router.get("", response_model=MemoryListResponse)
async def list_memory_records(
    page: int = 1,
    page_size: int = 50,
    record_type: str | None = None,
    sync_status: str | None = None,
    sensitivity: str | None = None,
    device_id: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """List memory records with filtering."""
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.get("/{record_id}", response_model=MemoryRecordResponse)
async def get_memory_record(record_id: str, db: AsyncSession = Depends(get_db)):
    """Get a single memory record."""
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.post("", response_model=MemoryRecordResponse, status_code=201)
async def create_memory_record(request: MemoryRecordCreate, db: AsyncSession = Depends(get_db)):
    """Create a new memory record (e.g., technician note)."""
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.delete("/{record_id}", response_model=SuccessResponse)
async def delete_memory_record(record_id: str, db: AsyncSession = Depends(get_db)):
    """Soft-delete a memory record."""
    raise HTTPException(status_code=501, detail="Not yet implemented")
