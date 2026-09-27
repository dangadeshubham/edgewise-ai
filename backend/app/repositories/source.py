"""
EDGEWISE AI — Source Repository

Data access for ingestion sources.
"""

from __future__ import annotations

from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import Source
from app.repositories.base import BaseRepository


class SourceRepository(BaseRepository[Source]):
    """Repository handling database operations for Source models."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Source, session)

    async def get_by_name(self, name: str) -> Optional[Source]:
        """Find a source by its name."""
        result = await self.session.execute(
            select(Source).where(Source.name == name)
        )
        return result.scalar_one_or_none()

    async def list_by_type(self, source_type: str) -> Sequence[Source]:
        """List all sources of a given type."""
        result = await self.session.execute(
            select(Source).where(Source.source_type == source_type).order_by(Source.name)
        )
        return result.scalars().all()
