"""
EDGEWISE AI — Sync Repository

Data access for sync items and conflicts.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import Conflict, SyncItem
from app.repositories.base import BaseRepository


class SyncRepository(BaseRepository[SyncItem]):
    """Repository handling database operations for Sync items."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(SyncItem, session)

    async def count_by_status(self, status: str) -> int:
        """Count sync items by status."""
        result = await self.session.execute(
            select(func.count(SyncItem.id)).where(SyncItem.status == status)
        )
        return result.scalar() or 0

    async def get_last_successful_sync_time(self) -> Optional[datetime]:
        """Get timestamp of most recently completed sync item."""
        result = await self.session.execute(
            select(func.max(SyncItem.completed_at)).where(SyncItem.status == "synced")
        )
        return result.scalar()


class ConflictRepository(BaseRepository[Conflict]):
    """Repository handling database operations for Conflict models."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Conflict, session)

    async def count_open(self) -> int:
        """Count open unresolved conflicts."""
        result = await self.session.execute(
            select(func.count(Conflict.id)).where(Conflict.status == "open")
        )
        return result.scalar() or 0
