"""AI Copilot API — RAG-powered question answering."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.api import CopilotQueryRequest, CopilotQueryResponse

router = APIRouter()


@router.post("/query", response_model=CopilotQueryResponse)
async def copilot_query(request: CopilotQueryRequest, db: AsyncSession = Depends(get_db)):
    """Ask a question and receive a grounded answer with source citations."""
    # Implemented in Phase 4
    raise HTTPException(status_code=501, detail="AI Copilot not yet implemented")
