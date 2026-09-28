"""
EDGEWISE AI — Health & System Endpoints (Phase 5)

Top-level system observability endpoints:
  GET /health          — comprehensive health with per-dependency status
  GET /health/ready    — Kubernetes readiness probe
  GET /health/live     — Kubernetes liveness probe
  GET /system/connectivity — detailed connectivity state for all dependencies
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
from app.services.connectivity.manager import get_connectivity_manager
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


@router.get("/system/connectivity", tags=["System"])
async def connectivity_status():
    """
    Get detailed connectivity state for all external dependencies.
    Returns independent per-dependency status (not simple booleans).

    Example response:
    {
      "state": "offline",
      "application_mode": "offline",
      "internet": "unavailable",
      "qdrant_edge": "available",
      "ollama": "available",
      "qdrant_server": "unavailable",
      "sqlite": "available",
      "dependencies": { ... },
      "recent_events": [ ... ]
    }
    """
    service = ConnectivityService()
    return await service.get_connectivity_status()
