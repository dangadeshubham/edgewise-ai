"""Search API — Semantic and hybrid search."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.api import SearchRequest, SearchResponse

router = APIRouter()


@router.post("", response_model=SearchResponse)
async def search(request: SearchRequest, db: AsyncSession = Depends(get_db)):
    """Perform semantic search across local vector memory."""
    # Implemented in Phase 3
    raise HTTPException(status_code=501, detail="Search not yet implemented")
