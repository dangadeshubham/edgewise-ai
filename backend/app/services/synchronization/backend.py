"""EDGEWISE AI — Sync Backend Abstraction & Local No-op Implementation (Phase 6)

Phase 6 implements the durable local synchronization subsystem ONLY.
Remote Qdrant Server synchronization remains Phase 7.

LocalNoopSyncBackend:
- Executes the local queue processing lifecycle.
- Validates data payload integrity.
- Does NOT contact Qdrant Server.
- Does NOT claim data was uploaded to cloud.
- Supports deterministic simulation for unit and integration testing.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional

import structlog

from app.models.database import SyncItem
from app.services.synchronization.constants import (
    SyncErrorCategory,
    SyncState,
)

logger = structlog.get_logger("edgewise.sync.backend")


@dataclass
class SyncResult:
    """Outcome of a sync operation attempt."""
    success: bool
    status: SyncState
    error_category: Optional[SyncErrorCategory] = None
    error_message: Optional[str] = None
    duration_ms: float = 0.0
    remote_version: Optional[int] = None
    details: Optional[dict[str, Any]] = None


class SyncBackend(ABC):
    """Abstract interface for synchronization backends (Local No-op vs Cloud Qdrant)."""

    @abstractmethod
    async def upsert(self, item: SyncItem) -> SyncResult:
        """Execute an upsert operation on the backend."""
        ...

    @abstractmethod
    async def delete(self, item: SyncItem) -> SyncResult:
        """Execute a delete operation on the backend."""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Check whether the backend is available for syncing."""
        ...


class LocalNoopSyncBackend(SyncBackend):
    """
    Phase 6 Local No-op Sync Backend.

    Validates item payload structure and processes the queue item locally
    without contacting any remote server or cloud Qdrant.
    Configurable hooks allow deterministic error/conflict simulation during tests.
    """

    def __init__(
        self,
        simulated_error: Optional[tuple[SyncErrorCategory, str]] = None,
        simulate_conflict: bool = False,
        healthy: bool = True,
    ) -> None:
        self.simulated_error = simulated_error
        self.simulate_conflict = simulate_conflict
        self._healthy = healthy

    def set_simulated_error(self, category: SyncErrorCategory, message: str) -> None:
        """Configure the backend to fail with a specific category."""
        self.simulated_error = (category, message)

    def set_simulate_conflict(self, enabled: bool = True) -> None:
        """Configure the backend to trigger a conflict."""
        self.simulate_conflict = enabled

    def clear_simulations(self) -> None:
        """Reset all simulated behaviors."""
        self.simulated_error = None
        self.simulate_conflict = False
        self._healthy = True

    async def health_check(self) -> bool:
        """Return backend health status."""
        return self._healthy

    async def upsert(self, item: SyncItem) -> SyncResult:
        """
        Locally process an upsert sync item.
        Validates payload and returns SyncResult.
        """
        start = time.perf_counter()

        if not self._healthy:
            duration = (time.perf_counter() - start) * 1000
            return SyncResult(
                success=False,
                status=SyncState.FAILED,
                error_category=SyncErrorCategory.REMOTE_UNAVAILABLE,
                error_message="Sync backend is offline/unhealthy",
                duration_ms=round(duration, 2),
            )

        if self.simulated_error:
            cat, msg = self.simulated_error
            duration = (time.perf_counter() - start) * 1000
            return SyncResult(
                success=False,
                status=SyncState.FAILED,
                error_category=cat,
                error_message=msg,
                duration_ms=round(duration, 2),
            )

        if self.simulate_conflict:
            duration = (time.perf_counter() - start) * 1000
            return SyncResult(
                success=False,
                status=SyncState.CONFLICT,
                error_category=SyncErrorCategory.CONFLICT,
                error_message=f"Conflict detected for record {item.record_id}",
                duration_ms=round(duration, 2),
            )

        # Basic security and payload validation
        if item.payload_json:
            import json
            try:
                parsed = json.loads(item.payload_json)
                if not isinstance(parsed, dict):
                    duration = (time.perf_counter() - start) * 1000
                    return SyncResult(
                        success=False,
                        status=SyncState.FAILED,
                        error_category=SyncErrorCategory.VALIDATION_ERROR,
                        error_message="Sync payload must be a JSON object",
                        duration_ms=round(duration, 2),
                    )
            except Exception as e:
                duration = (time.perf_counter() - start) * 1000
                return SyncResult(
                    success=False,
                    status=SyncState.FAILED,
                    error_category=SyncErrorCategory.VALIDATION_ERROR,
                    error_message=f"Corrupt payload JSON: {e}",
                    duration_ms=round(duration, 2),
                )

        duration = (time.perf_counter() - start) * 1000
        logger.info(
            "local_noop_sync_upsert",
            sync_item_id=item.id,
            record_id=item.record_id,
            record_type=item.record_type,
            note="Processed locally via LocalNoopSyncBackend (Awaiting Phase 7 Qdrant Server)",
        )

        return SyncResult(
            success=True,
            status=SyncState.SYNCED,
            duration_ms=round(duration, 2),
            details={"mode": "local_noop", "cloud_synchronized": False},
        )

    async def delete(self, item: SyncItem) -> SyncResult:
        """
        Locally process a delete sync item.
        """
        start = time.perf_counter()

        if not self._healthy:
            duration = (time.perf_counter() - start) * 1000
            return SyncResult(
                success=False,
                status=SyncState.FAILED,
                error_category=SyncErrorCategory.REMOTE_UNAVAILABLE,
                error_message="Sync backend is offline/unhealthy",
                duration_ms=round(duration, 2),
            )

        if self.simulated_error:
            cat, msg = self.simulated_error
            duration = (time.perf_counter() - start) * 1000
            return SyncResult(
                success=False,
                status=SyncState.FAILED,
                error_category=cat,
                error_message=msg,
                duration_ms=round(duration, 2),
            )

        duration = (time.perf_counter() - start) * 1000
        logger.info(
            "local_noop_sync_delete",
            sync_item_id=item.id,
            record_id=item.record_id,
            record_type=item.record_type,
            note="Delete processed locally via LocalNoopSyncBackend",
        )

        return SyncResult(
            success=True,
            status=SyncState.SYNCED,
            duration_ms=round(duration, 2),
            details={"mode": "local_noop", "operation": "delete"},
        )
