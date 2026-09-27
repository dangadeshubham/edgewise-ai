"""
EDGEWISE AI — Health Service

Checks the health of all system components:
- SQLite database
- Qdrant Edge shard
- Qdrant Server/Cloud
- Ollama LLM
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.schemas.api import (
    ComponentHealth,
    HealthResponse,
    ReadinessResponse,
)

settings = get_settings()


class HealthService:
    """Checks health of all application dependencies."""

    async def check_health(self, db: AsyncSession) -> HealthResponse:
        """Run comprehensive health check on all components."""
        components: list[ComponentHealth] = []
        overall_status = "healthy"

        # Check SQLite
        db_health = await self._check_database(db)
        components.append(db_health)
        if db_health.status != "healthy":
            overall_status = "degraded"

        # Other component checks will be added in later phases
        # (Edge shard, Qdrant server, Ollama)

        from app.main import APP_START_TIME
        uptime = time.time() - APP_START_TIME if APP_START_TIME > 0 else 0

        return HealthResponse(
            status=overall_status,
            version="0.1.0",
            device_id=settings.device_id,
            uptime_seconds=uptime,
            components=components,
            timestamp=datetime.now(timezone.utc),
        )

    async def check_readiness(self, db: AsyncSession) -> ReadinessResponse:
        """Check if application is ready to serve requests."""
        checks = {}

        # Database check
        try:
            await db.execute(text("SELECT 1"))
            checks["database"] = True
        except Exception:
            checks["database"] = False

        ready = all(checks.values())
        return ReadinessResponse(ready=ready, checks=checks)

    async def _check_database(self, db: AsyncSession) -> ComponentHealth:
        """Check SQLite connectivity and response time."""
        start = time.perf_counter()
        try:
            await db.execute(text("SELECT 1"))
            latency = (time.perf_counter() - start) * 1000
            return ComponentHealth(
                name="sqlite",
                status="healthy",
                latency_ms=round(latency, 2),
                message="Database responding",
            )
        except Exception as e:
            latency = (time.perf_counter() - start) * 1000
            return ComponentHealth(
                name="sqlite",
                status="unhealthy",
                latency_ms=round(latency, 2),
                message=f"Database error: {type(e).__name__}",
            )
