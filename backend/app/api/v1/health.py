"""
EDGEWISE AI — Health & System Endpoints

Top-level system observability endpoints:
  GET /health
  GET /health/ready
  GET /health/live
  GET /system/connectivity
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.api import (
    ConnectivityResponse,
    HealthResponse,
    LivenessResponse,
    ReadinessResponse,
)
from app.services.connectivity.service import ConnectivityService
from app.services.health.service import HealthService

router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check(db: AsyncSession = Depends(get_db)) -> HealthResponse:
    """Comprehensive health check probing all real system dependencies."""
    service = HealthService()
    return await service.check_health(db)


@router.get("/health/ready", response_model=ReadinessResponse, tags=["Health"])
async def readiness_check(
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> ReadinessResponse:
    """Kubernetes-style readiness probe. Returns 503 if dependencies are unready."""
    service = HealthService()
    result = await service.check_readiness(db)
    if not result.ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return result


@router.get("/health/live", response_model=LivenessResponse, tags=["Health"])
async def liveness_check() -> LivenessResponse:
    """Kubernetes-style liveness probe. Always returns alive if process is running."""
    return LivenessResponse(alive=True)


@router.get("/system/connectivity", response_model=ConnectivityResponse, tags=["System"])
async def connectivity_status() -> ConnectivityResponse:
    """Get detailed connectivity state for all external dependencies."""
    service = ConnectivityService()
    return await service.get_connectivity_status()
