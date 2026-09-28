"""
EDGEWISE AI — Connectivity Service (Phase 5)

Refactored to use the ConnectivityManager state machine.
Provides the API-facing connectivity status with accurate per-dependency state.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import structlog

from app.core.config import get_settings
from app.services.connectivity.manager import (
    ConnectivityManager,
    ConnectivityState,
    DependencyName,
    DependencyStatus,
    get_connectivity_manager,
)

settings = get_settings()
logger = structlog.get_logger("edgewise.connectivity")


class ConnectivityService:
    """
    Checks and reports connectivity to all dependencies.
    Delegates to ConnectivityManager for actual probing and state derivation.
    """

    def __init__(self) -> None:
        self.manager: ConnectivityManager = get_connectivity_manager()

    async def get_connectivity_status(self) -> dict[str, Any]:
        """Check all external dependencies and return accurate aggregate status."""
        await self.manager.check_all()
        return self.manager.get_status()

    async def check_local_dependencies(self) -> dict[str, Any]:
        """Check only local dependencies for fast health checks."""
        await self.manager.check_local_only()
        return {
            "state": self.manager.state.value,
            "application_mode": self.manager.application_mode,
            "sqlite": self.manager.get_dependency_status(DependencyName.SQLITE).status.value,
            "qdrant_edge": self.manager.get_dependency_status(DependencyName.QDRANT_EDGE).status.value,
            "ollama": self.manager.get_dependency_status(DependencyName.OLLAMA).status.value,
            "local_operational": self.manager.is_local_operational(),
            "copilot_operational": self.manager.is_copilot_operational(),
        }

    def get_cached_status(self) -> dict[str, Any]:
        """Return cached status without re-probing (for high-frequency callers)."""
        return self.manager.get_status()

    def is_local_operational(self) -> bool:
        """Quick check if local stack is operational."""
        return self.manager.is_local_operational()

    def is_copilot_operational(self) -> bool:
        """Quick check if Copilot can execute."""
        return self.manager.is_copilot_operational()
