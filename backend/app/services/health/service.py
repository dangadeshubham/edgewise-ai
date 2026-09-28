"""
EDGEWISE AI — Health Service (Phase 5)

Comprehensive inspection of real system dependencies:
- SQLite database
- Qdrant Server / Cloud
- Ollama Local LLM
- Edge Shard storage
- Internet connectivity
- Embedding model

Dependencies are actually probed over network/disk/DB.
No component is marked healthy just because configuration exists.

Phase 5 addition: integrates with ConnectivityManager for state machine,
and reflects accurate offline-first status.
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
from app.services.connectivity.manager import (
    ConnectivityManager,
    DependencyName,
    DependencyStatus,
    get_connectivity_manager,
)

settings = get_settings()


class HealthService:
    """Checks real health of application dependencies."""

    def __init__(self, http_timeout: float = 2.0) -> None:
        self.http_timeout = http_timeout
        self.connectivity = get_connectivity_manager()

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

        # 4. Edge Shard storage & querying
        edge_health = await self._check_edge_shard()
        components.append(edge_health)

        # 5. Embedding Model service & dimension
        emb_health = await self._check_embedding()
        components.append(emb_health)

        # 6. Internet connectivity
        internet_health = await self._check_internet()
        components.append(internet_health)

        # Determine overall status using offline-first logic:
        # - If SQLite is down → unhealthy (critical)
        # - If Edge is down → degraded (local search impaired)
        # - If internet/Qdrant Server/Ollama down → degraded (but local can work)
        # - All up → healthy
        if db_health.status != "healthy":
            overall_status = "unhealthy"
        elif edge_health.status != "healthy":
            overall_status = "degraded"
        elif any(c.status != "healthy" for c in components):
            overall_status = "degraded"
        else:
            overall_status = "healthy"

        from app.main import APP_START_TIME
        uptime = time.time() - APP_START_TIME if APP_START_TIME > 0 else 0.0

        # Add connectivity manager summary
        conn_state = self.connectivity.state.value
        app_mode = self.connectivity.application_mode

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
        Verifies core operational readiness:
        - SQLite database operational
        - Qdrant Edge shard loaded and queryable
        - Embedding service available with valid dimension

        Note: Internet/Qdrant Server/Ollama are NOT required for readiness.
        The application is offline-first and ready without cloud dependencies.
        """
        checks: dict[str, bool] = {}
        try:
            await db.execute(text("SELECT 1"))
            checks["database"] = True
        except Exception:
            checks["database"] = False

        try:
            from app.services.edge_memory import get_edge_memory_service
            edge = get_edge_memory_service()
            checks["edge_shard"] = edge.is_healthy("mutable")
        except Exception:
            checks["edge_shard"] = False

        try:
            from app.services.embeddings import get_embedding_service
            emb = get_embedding_service()
            checks["embedding"] = emb.is_healthy()
        except Exception:
            checks["embedding"] = False

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
                message=f"DATABASE_UNAVAILABLE: {type(e).__name__}",
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
                        name="qdrant_server",
                        status="healthy",
                        latency_ms=round(latency, 2),
                        message="Qdrant Server responding",
                    )
                return ComponentHealth(
                    name="qdrant_server",
                    status="unhealthy",
                    latency_ms=round(latency, 2),
                    message=f"Qdrant Server returned HTTP {resp.status_code}",
                )
        except Exception:
            latency = (time.perf_counter() - start) * 1000
            return ComponentHealth(
                name="qdrant_server",
                status="unhealthy",
                latency_ms=round(latency, 2),
                message="Qdrant Server unavailable: not required for offline operation",
            )

    async def _check_ollama(self) -> ComponentHealth:
        """Actually check Ollama API endpoint AND configured model availability."""
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self.http_timeout) as client:
                resp = await client.get(f"{settings.ollama_base_url}/api/tags")
                latency = (time.perf_counter() - start) * 1000
                if resp.status_code != 200:
                    return ComponentHealth(
                        name="ollama",
                        status="unhealthy",
                        latency_ms=round(latency, 2),
                        message=f"Ollama returned HTTP {resp.status_code}",
                    )

                # Check model availability
                data = resp.json()
                available_models = [m["name"] for m in data.get("models", [])]
                model_found = any(
                    m == settings.ollama_model
                    or m.startswith(settings.ollama_model.split(":")[0] + ":")
                    for m in available_models
                )

                if not model_found:
                    return ComponentHealth(
                        name="ollama",
                        status="degraded",
                        latency_ms=round(latency, 2),
                        message=f"OLLAMA_AVAILABLE but OLLAMA_MODEL_UNAVAILABLE: '{settings.ollama_model}' not in {available_models}",
                    )

                return ComponentHealth(
                    name="ollama",
                    status="healthy",
                    latency_ms=round(latency, 2),
                    message=f"OLLAMA_AVAILABLE, OLLAMA_MODEL_AVAILABLE: {settings.ollama_model}",
                )
        except Exception:
            latency = (time.perf_counter() - start) * 1000
            return ComponentHealth(
                name="ollama",
                status="unhealthy",
                latency_ms=round(latency, 2),
                message="OLLAMA_UNAVAILABLE: connection failed",
            )

    async def _check_edge_shard(self) -> ComponentHealth:
        """Inspect actual Edge shard: exists, loaded, queryable."""
        start = time.perf_counter()
        try:
            from app.services.edge_memory import get_edge_memory_service
            edge = get_edge_memory_service()
            if not edge.mutable_dir.exists():
                latency = (time.perf_counter() - start) * 1000
                return ComponentHealth(
                    name="qdrant_edge",
                    status="unhealthy",
                    latency_ms=round(latency, 2),
                    message="EDGE_UNAVAILABLE: mutable shard directory does not exist",
                )
            info = edge.get_shard_info("mutable")
            if info.get("status") != "ready":
                latency = (time.perf_counter() - start) * 1000
                return ComponentHealth(
                    name="qdrant_edge",
                    status="unhealthy",
                    latency_ms=round(latency, 2),
                    message=f"EDGE_UNAVAILABLE: shard status {info.get('status')}",
                )
            latency = (time.perf_counter() - start) * 1000
            return ComponentHealth(
                name="qdrant_edge",
                status="healthy",
                latency_ms=round(latency, 2),
                message=f"Edge shard ready ({info.get('points_count', 0)} points)",
            )
        except Exception as e:
            latency = (time.perf_counter() - start) * 1000
            return ComponentHealth(
                name="qdrant_edge",
                status="unhealthy",
                latency_ms=round(latency, 2),
                message=f"EDGE_UNAVAILABLE: {type(e).__name__}",
            )

    async def _check_embedding(self) -> ComponentHealth:
        """Inspect embedding service: model loaded and dimension valid."""
        start = time.perf_counter()
        try:
            from app.services.embeddings import get_embedding_service
            emb = get_embedding_service()
            if not emb.is_healthy():
                latency = (time.perf_counter() - start) * 1000
                return ComponentHealth(
                    name="embedding",
                    status="unhealthy",
                    latency_ms=round(latency, 2),
                    message="EMBEDDING_UNAVAILABLE: probe validation failed",
                )
            if emb.dimension != settings.edge_vector_dimension:
                latency = (time.perf_counter() - start) * 1000
                return ComponentHealth(
                    name="embedding",
                    status="unhealthy",
                    latency_ms=round(latency, 2),
                    message=f"EMBEDDING_UNAVAILABLE: dimension mismatch ({emb.dimension} != {settings.edge_vector_dimension})",
                )
            latency = (time.perf_counter() - start) * 1000
            return ComponentHealth(
                name="embedding",
                status="healthy",
                latency_ms=round(latency, 2),
                message=f"Embedding model ready (dim={emb.dimension})",
            )
        except Exception as e:
            latency = (time.perf_counter() - start) * 1000
            return ComponentHealth(
                name="embedding",
                status="unhealthy",
                latency_ms=round(latency, 2),
                message=f"EMBEDDING_UNAVAILABLE: {type(e).__name__}",
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
                message="Internet unavailable: offline (local AI operational)",
            )
