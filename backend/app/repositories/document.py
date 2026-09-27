"""
EDGEWISE AI — Document Repository

Data access for documents, versions, and chunks.
"""

from __future__ import annotations

from typing import Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import Document, DocumentChunk, DocumentVersion
from app.repositories.base import BaseRepository


class DocumentRepository(BaseRepository[Document]):
    """Repository handling database operations for Document models."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Document, session)

    async def get_by_content_hash(self, content_hash: str) -> Optional[Document]:
        """Find a document by content hash (deduplication)."""
        result = await self.session.execute(
            select(Document).where(
                Document.content_hash == content_hash,
                Document.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def list_active(
        self,
        skip: int = 0,
        limit: int = 50,
        source_id: Optional[str] = None,
        document_type: Optional[str] = None,
    ) -> Sequence[Document]:
        """List active (non-deleted) documents."""
        query = select(Document).where(Document.deleted_at.is_(None))
        if source_id:
            query = query.where(Document.source_id == source_id)
        if document_type:
            query = query.where(Document.document_type == document_type)
        query = query.order_by(Document.created_at.desc()).offset(skip).limit(limit)
        result = await self.session.execute(query)
        return result.scalars().all()

    async def count_active(self) -> int:
        """Count active documents."""
        result = await self.session.execute(
            select(func.count(Document.id)).where(Document.deleted_at.is_(None))
        )
        return result.scalar() or 0

    async def count_by_status(self, processing_status: str) -> int:
        """Count documents with specific processing status."""
        result = await self.session.execute(
            select(func.count(Document.id)).where(
                Document.deleted_at.is_(None),
                Document.processing_status == processing_status,
            )
        )
        return result.scalar() or 0

    async def get_storage_bytes(self) -> int:
        """Calculate total storage size in bytes of active documents."""
        result = await self.session.execute(
            select(func.coalesce(func.sum(Document.file_size), 0)).where(
                Document.deleted_at.is_(None)
            )
        )
        return int(result.scalar() or 0)
