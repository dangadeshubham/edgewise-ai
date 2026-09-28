"""
EDGEWISE AI — Memory API (Phase 5)

Browse and manage memory records using the LocalWriteService.
All writes go through the 5-step local write path:
validate → SQLite → Qdrant Edge → sync metadata → audit.
"""

from __future__ import annotations

import json
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.models.database import MemoryRecord
from app.schemas.api import (
    MemoryListResponse,
    MemoryRecordCreate,
    MemoryRecordResponse,
    SuccessResponse,
)
from app.services.local_write import LocalWriteService

logger = structlog.get_logger("edgewise.api.memory")
settings = get_settings()
router = APIRouter()


def _record_to_response(record: MemoryRecord) -> MemoryRecordResponse:
    """Convert DB model to response schema."""
    metadata = None
    if record.metadata_json:
        try:
            metadata = json.loads(record.metadata_json)
        except (json.JSONDecodeError, TypeError):
            metadata = None

    return MemoryRecordResponse(
        id=record.id,
        device_id=record.device_id,
        source_id=record.source_id,
        document_id=record.document_id,
        content=record.content,
        content_hash=record.content_hash,
        record_type=record.record_type,
        sensitivity=record.sensitivity,
        sync_status=record.sync_status,
        version=record.version,
        revision=record.revision,
        origin_device=record.origin_device,
        metadata=metadata,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


@router.get("", response_model=MemoryListResponse)
async def list_memory_records(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    record_type: Optional[str] = None,
    sync_status: Optional[str] = None,
    sensitivity: Optional[str] = None,
    device_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """List memory records with filtering."""
    query = select(MemoryRecord).where(MemoryRecord.deleted_at.is_(None))

    if record_type:
        query = query.where(MemoryRecord.record_type == record_type)
    if sync_status:
        query = query.where(MemoryRecord.sync_status == sync_status)
    if sensitivity:
        query = query.where(MemoryRecord.sensitivity == sensitivity)
    if device_id:
        query = query.where(MemoryRecord.device_id == device_id)

    # Count
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Paginate
    offset = (page - 1) * page_size
    query = query.order_by(MemoryRecord.created_at.desc()).offset(offset).limit(page_size)
    result = await db.execute(query)
    records = result.scalars().all()

    total_pages = max(1, (total + page_size - 1) // page_size)

    return MemoryListResponse(
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        items=[_record_to_response(r) for r in records],
    )


@router.get("/{record_id}", response_model=MemoryRecordResponse)
async def get_memory_record(record_id: str, db: AsyncSession = Depends(get_db)):
    """Get a single memory record."""
    result = await db.execute(
        select(MemoryRecord).where(
            MemoryRecord.id == record_id,
            MemoryRecord.deleted_at.is_(None),
        )
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Memory record '{record_id}' not found.",
        )
    return _record_to_response(record)


@router.post("", response_model=MemoryRecordResponse, status_code=201)
async def create_memory_record(
    request: MemoryRecordCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new memory record using the LocalWriteService.
    Full 5-step write path: validate → SQLite → Qdrant Edge → sync metadata → audit.
    """
    try:
        write_service = LocalWriteService(db)
        record = await write_service.create_memory_record(
            content=request.content,
            record_type=request.record_type,
            sensitivity=request.sensitivity,
            metadata=request.metadata,
        )
        await db.commit()
        return _record_to_response(record)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )
    except Exception as exc:
        logger.error("memory_record_create_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create memory record: {type(exc).__name__}",
        )


@router.delete("/{record_id}", response_model=SuccessResponse)
async def delete_memory_record(record_id: str, db: AsyncSession = Depends(get_db)):
    """Soft-delete a memory record using the LocalWriteService."""
    result = await db.execute(
        select(MemoryRecord).where(
            MemoryRecord.id == record_id,
            MemoryRecord.deleted_at.is_(None),
        )
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Memory record '{record_id}' not found.",
        )

    try:
        write_service = LocalWriteService(db)
        await write_service.delete_memory_record(record)
        await db.commit()
        return SuccessResponse(message=f"Memory record '{record_id}' deleted.")
    except Exception as exc:
        logger.error("memory_record_delete_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete memory record: {type(exc).__name__}",
        )
