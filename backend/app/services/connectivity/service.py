"""
EDGEWISE AI — Connectivity Service

Manages and reports connectivity state for all external dependencies.
Distinguishes between different failure modes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import httpx

from app.core.config import ConnectivityState, get_settings
from app.schemas.api import ConnectivityResponse

settings = get_settings()


class ConnectivityService:
    """Checks and reports connectivity to external services."""

    def __init__(self):
        self._last_check: Optional[datetime] = None

    async def get_connectivity_status(self) -> ConnectivityResponse:
        """Check all external dependencies and return aggregate status."""
        internet = await self._check_internet()
        qdrant_cloud = await self._check_qdrant_cloud()
        ollama = await self._check_ollama()
        local_db = await self._check_local_database()
        edge_shard = await self._check_edge_shard()

        self._last_check = datetime.now(timezone.utc)

        # Determine overall state
        if not local_db or not edge_shard:
            state = ConnectivityState.OFFLINE
        elif not internet:
            state = ConnectivityState.OFFLINE
        elif not qdrant_cloud or not ollama:
            state = ConnectivityState.DEGRADED
        else:
            state = ConnectivityState.ONLINE

        return ConnectivityResponse(
            state=state.value,
            internet_available=internet,
            qdrant_cloud_available=qdrant_cloud,
            ollama_available=ollama,
            local_database_available=local_db,
            edge_shard_available=edge_shard,
            last_check=self._last_check,
        )

    async def _check_internet(self) -> bool:
        """Check basic internet connectivity."""
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get("https://httpbin.org/status/200")
                return resp.status_code == 200
        except Exception:
            return False

    async def _check_qdrant_cloud(self) -> bool:
        """Check if Qdrant Server/Cloud is reachable."""
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                headers = {}
                if settings.qdrant_api_key:
                    headers["api-key"] = settings.qdrant_api_key
                resp = await client.get(
                    f"{settings.qdrant_server_url}/healthz",
                    headers=headers,
                )
                return resp.status_code == 200
        except Exception:
            return False

    async def _check_ollama(self) -> bool:
        """Check if Ollama is reachable."""
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"{settings.ollama_base_url}/api/tags")
                return resp.status_code == 200
        except Exception:
            return False

    async def _check_local_database(self) -> bool:
        """Check if SQLite is accessible."""
        try:
            from app.core.database import async_session_factory
            from sqlalchemy import text
            async with async_session_factory() as session:
                await session.execute(text("SELECT 1"))
                return True
        except Exception:
            return False

    async def _check_edge_shard(self) -> bool:
        """Check if Edge shard is loaded, accessible, and queryable."""
        try:
            from app.services.edge_memory import get_edge_memory_service
            edge = get_edge_memory_service()
            return edge.is_healthy("mutable")
        except Exception:
            return False
