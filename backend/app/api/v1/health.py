"""
EDGEWISE AI — Health & System Endpoints

These are top-level routes (not under /api) as per convention:
  GET /health
  GET /health/ready
  GET /health/live
  GET /system/connectivity
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.api import (
    ConnectivityResponse,
    HealthResponse,
    LivenessResponse,
    ReadinessResponse,
)

router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check(db: AsyncSession = Depends(get_db)):
    """Comprehensive health check of all system components."""
    # Implemented in Phase 1
    from app.services.health.service import HealthService
    service = HealthService()
    return await service.check_health(db)


@router.get("/health/ready", response_model=ReadinessResponse, tags=["Health"])
async def readiness_check(db: AsyncSession = Depends(get_db)):
    """Kubernetes-style readiness probe."""
    from app.services.health.service import HealthService
    service = HealthService()
    return await service.check_readiness(db)


@router.get("/health/live", response_model=LivenessResponse, tags=["Health"])
async def liveness_check():
    """Kubernetes-style liveness probe. Always returns alive if process is running."""
    return LivenessResponse(alive=True)


@router.get("/system/connectivity", response_model=ConnectivityResponse, tags=["System"])
async def connectivity_status():
    """Get detailed connectivity state for all external dependencies."""
    from app.services.connectivity.service import ConnectivityService
    service = ConnectivityService()
    return await service.get_connectivity_status()
