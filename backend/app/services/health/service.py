"""
EDGEWISE AI — Health Service

Comprehensive inspection of real system dependencies:
- SQLite database
- Qdrant Server / Cloud
- Ollama Local LLM
- Edge Shard storage
- Internet connectivity

Dependencies are actually probed over network/disk/DB.
No component is marked healthy just because configuration exists.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
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
    """Checks real health of application dependencies."""

    def __init__(self, http_timeout: float = 2.0) -> None:
        self.http_timeout = http_timeout

    async def check_health(self, db: AsyncSession) -> HealthResponse:
        """Run comprehensive health checks on all dependencies."""
        components: list[ComponentHealth] = []

        # 1. Database check
        db_health = await self._check_database(db)
        components.append(db_health)

        # 2. Qdrant Server / Cloud
        qdrant_health = await self._check_qdrant()
        components.append(qdrant_health)

        # 3. Ollama LLM
        ollama_health = await self._check_ollama()
        components.append(ollama_health)

        # 4. Edge Shard storage
        edge_health = await self._check_edge_shard()
        components.append(edge_health)

        # 5. Internet connectivity
        internet_health = await self._check_internet()
        components.append(internet_health)

        # Determine overall status
        if db_health.status != "healthy":
            overall_status = "unhealthy"
        elif any(c.status != "healthy" for c in components):
            overall_status = "degraded"
        else:
            overall_status = "healthy"

        from app.main import APP_START_TIME
        uptime = time.time() - APP_START_TIME if APP_START_TIME > 0 else 0.0

        return HealthResponse(
            status=overall_status,
            version="0.1.0",
            device_id=settings.device_id,
            uptime_seconds=round(uptime, 1),
            components=components,
            timestamp=datetime.now(timezone.utc),
        )

    async def check_readiness(self, db: AsyncSession) -> ReadinessResponse:
        """
        Kubernetes readiness probe.
        Verifies core operational readiness (database reachable and operational).
        """
        checks: dict[str, bool] = {}
        try:
            await db.execute(text("SELECT 1"))
            checks["database"] = True
        except Exception:
            checks["database"] = False

        ready = all(checks.values()) and len(checks) > 0
        return ReadinessResponse(ready=ready, checks=checks)

    async def _check_database(self, db: AsyncSession) -> ComponentHealth:
        """Actually execute a query against SQLite."""
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
                message=f"Database unavailable: {type(e).__name__}",
            )

    async def _check_qdrant(self) -> ComponentHealth:
        """Actually check Qdrant HTTP health endpoint."""
        start = time.perf_counter()
        headers = {}
        if settings.qdrant_api_key:
            headers["api-key"] = settings.qdrant_api_key
        try:
            async with httpx.AsyncClient(timeout=self.http_timeout) as client:
                resp = await client.get(
                    f"{settings.qdrant_server_url}/healthz",
                    headers=headers,
                )
                latency = (time.perf_counter() - start) * 1000
                if resp.status_code == 200:
                    return ComponentHealth(
                        name="qdrant",
                        status="healthy",
                        latency_ms=round(latency, 2),
                        message="Qdrant responding",
                    )
                return ComponentHealth(
                    name="qdrant",
                    status="unhealthy",
                    latency_ms=round(latency, 2),
                    message=f"Qdrant returned HTTP {resp.status_code}",
                )
        except Exception:
            latency = (time.perf_counter() - start) * 1000
            return ComponentHealth(
                name="qdrant",
                status="unhealthy",
                latency_ms=round(latency, 2),
                message="Qdrant unavailable: connection failed",
            )

    async def _check_ollama(self) -> ComponentHealth:
        """Actually check Ollama API endpoint."""
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self.http_timeout) as client:
                resp = await client.get(f"{settings.ollama_base_url}/api/tags")
                latency = (time.perf_counter() - start) * 1000
                if resp.status_code == 200:
                    return ComponentHealth(
                        name="ollama",
                        status="healthy",
                        latency_ms=round(latency, 2),
                        message="Ollama responding",
                    )
                return ComponentHealth(
                    name="ollama",
                    status="unhealthy",
                    latency_ms=round(latency, 2),
                    message=f"Ollama returned HTTP {resp.status_code}",
                )
        except Exception:
            latency = (time.perf_counter() - start) * 1000
            return ComponentHealth(
                name="ollama",
                status="unhealthy",
                latency_ms=round(latency, 2),
                message="Ollama unavailable: connection failed",
            )

    async def _check_edge_shard(self) -> ComponentHealth:
        """Check Edge shard storage directory."""
        start = time.perf_counter()
        try:
            mutable_dir = Path(settings.edge_mutable_shard_path)
            if mutable_dir.exists():
                latency = (time.perf_counter() - start) * 1000
                return ComponentHealth(
                    name="edge",
                    status="healthy",
                    latency_ms=round(latency, 2),
                    message="Edge storage path accessible",
                )
            latency = (time.perf_counter() - start) * 1000
            return ComponentHealth(
                name="edge",
                status="unhealthy",
                latency_ms=round(latency, 2),
                message="Edge unavailable: mutable shard directory does not exist",
            )
        except Exception as e:
            latency = (time.perf_counter() - start) * 1000
            return ComponentHealth(
                name="edge",
                status="unhealthy",
                latency_ms=round(latency, 2),
                message=f"Edge unavailable: {type(e).__name__}",
            )

    async def _check_internet(self) -> ComponentHealth:
        """Actually probe internet connectivity via public probe."""
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self.http_timeout) as client:
                resp = await client.get("https://httpbin.org/status/200")
                latency = (time.perf_counter() - start) * 1000
                if resp.status_code == 200:
                    return ComponentHealth(
                        name="internet",
                        status="healthy",
                        latency_ms=round(latency, 2),
                        message="Internet reachable",
                    )
                return ComponentHealth(
                    name="internet",
                    status="unhealthy",
                    latency_ms=round(latency, 2),
                    message=f"Internet probe returned HTTP {resp.status_code}",
                )
        except Exception:
            latency = (time.perf_counter() - start) * 1000
            return ComponentHealth(
                name="internet",
                status="unhealthy",
                latency_ms=round(latency, 2),
                message="Internet unavailable: offline",
            )
