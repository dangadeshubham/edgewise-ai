"""Dashboard API — Aggregated system metrics."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.api import DashboardMetrics

router = APIRouter()


@router.get("/metrics", response_model=DashboardMetrics)
async def get_dashboard_metrics(db: AsyncSession = Depends(get_db)):
    """Get live aggregated dashboard metrics from real system state."""
    raise HTTPException(status_code=501, detail="Not yet implemented")
