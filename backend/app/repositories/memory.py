"""
EDGEWISE AI — Memory Record Repository

Data access for local memory records.
"""

from __future__ import annotations

from typing import Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import MemoryRecord
from app.repositories.base import BaseRepository


class MemoryRecordRepository(BaseRepository[MemoryRecord]):
    """Repository handling database operations for MemoryRecord models."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(MemoryRecord, session)

    async def get_by_content_hash(self, content_hash: str) -> Optional[MemoryRecord]:
        """Find a memory record by content hash."""
        result = await self.session.execute(
            select(MemoryRecord).where(
                MemoryRecord.content_hash == content_hash,
                MemoryRecord.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def list_active(
        self,
        skip: int = 0,
        limit: int = 50,
        record_type: Optional[str] = None,
    ) -> Sequence[MemoryRecord]:
        """List active memory records."""
        query = select(MemoryRecord).where(MemoryRecord.deleted_at.is_(None))
        if record_type:
            query = query.where(MemoryRecord.record_type == record_type)
        query = query.order_by(MemoryRecord.created_at.desc()).offset(skip).limit(limit)
        result = await self.session.execute(query)
        return result.scalars().all()

    async def count_active(self) -> int:
        """Count active memory records."""
        result = await self.session.execute(
            select(func.count(MemoryRecord.id)).where(MemoryRecord.deleted_at.is_(None))
        )
        return result.scalar() or 0
