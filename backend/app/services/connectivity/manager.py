"""
EDGEWISE AI — Connectivity Manager (Phase 5)

Real connectivity state machine that independently tracks each dependency:
- SQLite
- Qdrant Edge (local shard)
- Ollama (local LLM)
- Internet
- Qdrant Server (cloud)

States:
  ONLINE       — all dependencies available
  OFFLINE      — internet unavailable, local stack works
  DEGRADED     — some dependencies impaired
  SYNC_PENDING — local changes exist awaiting future sync
  SYNCING      — active synchronization (Phase 6+)

Key principle: "internet unavailable" ≠ "everything unavailable".
Local SQLite + Qdrant Edge + Ollama can operate without internet or Qdrant Server.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Optional

import httpx
import structlog

from app.core.config import get_settings

logger = structlog.get_logger("edgewise.connectivity")
settings = get_settings()


# =============================================================================
# Enums
# =============================================================================

class ConnectivityState(str, Enum):
    """Top-level application connectivity state."""
    ONLINE = "online"
    OFFLINE = "offline"
    DEGRADED = "degraded"
    SYNC_PENDING = "sync_pending"
    SYNCING = "syncing"


class DependencyStatus(str, Enum):
    """Individual dependency status."""
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


class DependencyName(str, Enum):
    """Named dependencies that are independently tracked."""
    SQLITE = "sqlite"
    QDRANT_EDGE = "qdrant_edge"
    OLLAMA = "ollama"
    INTERNET = "internet"
    QDRANT_SERVER = "qdrant_server"


class ConnectivityEventType(str, Enum):
    """Events recorded when dependency state changes."""
    DEVICE_ONLINE = "DEVICE_ONLINE"
    DEVICE_OFFLINE = "DEVICE_OFFLINE"
    DEPENDENCY_DEGRADED = "DEPENDENCY_DEGRADED"
    DEPENDENCY_RECOVERED = "DEPENDENCY_RECOVERED"
    STATE_CHANGED = "STATE_CHANGED"


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class DependencyState:
    """Tracks the state of a single dependency."""
    name: DependencyName
    status: DependencyStatus = DependencyStatus.UNKNOWN
    last_check: Optional[datetime] = None
    last_available: Optional[datetime] = None
    last_unavailable: Optional[datetime] = None
    latency_ms: Optional[float] = None
    message: Optional[str] = None
    consecutive_failures: int = 0
    consecutive_successes: int = 0

    def mark_available(self, latency_ms: float = 0.0, message: str = "") -> bool:
        """Mark dependency as available. Returns True if state changed."""
        changed = self.status != DependencyStatus.AVAILABLE
        self.status = DependencyStatus.AVAILABLE
        self.last_check = datetime.now(timezone.utc)
        self.last_available = self.last_check
        self.latency_ms = latency_ms
        self.message = message
        self.consecutive_failures = 0
        self.consecutive_successes += 1
        return changed

    def mark_unavailable(self, message: str = "") -> bool:
        """Mark dependency as unavailable. Returns True if state changed."""
        changed = self.status != DependencyStatus.UNAVAILABLE
        self.status = DependencyStatus.UNAVAILABLE
        self.last_check = datetime.now(timezone.utc)
        self.last_unavailable = self.last_check
        self.latency_ms = None
        self.message = message
        self.consecutive_successes = 0
        self.consecutive_failures += 1
        return changed

    def mark_degraded(self, latency_ms: float = 0.0, message: str = "") -> bool:
        """Mark dependency as degraded. Returns True if state changed."""
        changed = self.status != DependencyStatus.DEGRADED
        self.status = DependencyStatus.DEGRADED
        self.last_check = datetime.now(timezone.utc)
        self.latency_ms = latency_ms
        self.message = message
        return changed

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name.value,
            "status": self.status.value,
            "last_check": self.last_check.isoformat() if self.last_check else None,
            "last_available": self.last_available.isoformat() if self.last_available else None,
            "last_failure": self.last_unavailable.isoformat() if self.last_unavailable else None,
            "latency_ms": self.latency_ms,
            "message": self.message,
            "consecutive_failures": self.consecutive_failures,
        }


@dataclass
class ConnectivityEvent:
    """Immutable record of a connectivity state change."""
    event_type: ConnectivityEventType
    dependency: Optional[DependencyName]
    old_status: Optional[str]
    new_status: str
    message: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type.value,
            "dependency": self.dependency.value if self.dependency else None,
            "old_status": self.old_status,
            "new_status": self.new_status,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
        }


# =============================================================================
# Connectivity Manager (Singleton)
# =============================================================================

class ConnectivityManager:
    """
    Centralized connectivity state machine.

    Independently tracks each dependency and derives the top-level
    application connectivity state from the component states.

    Thread-safe via asyncio lock. Does not generate fake events.
    """

    def __init__(self) -> None:
        self._dependencies: dict[DependencyName, DependencyState] = {
            dep: DependencyState(name=dep) for dep in DependencyName
        }
        self._state: ConnectivityState = ConnectivityState.OFFLINE
        self._events: list[ConnectivityEvent] = []
        self._max_events: int = 500
        self._lock = asyncio.Lock()
        self._started_at: datetime = datetime.now(timezone.utc)
        self._last_full_check: Optional[datetime] = None
        self._event_listeners: list[Callable] = []

    # ---- Properties ----

    @property
    def state(self) -> ConnectivityState:
        return self._state

    @property
    def dependencies(self) -> dict[DependencyName, DependencyState]:
        return dict(self._dependencies)

    @property
    def events(self) -> list[ConnectivityEvent]:
        return list(self._events)

    @property
    def application_mode(self) -> str:
        """Human-readable application mode string."""
        if self._state == ConnectivityState.ONLINE:
            return "online"
        elif self._state in (ConnectivityState.OFFLINE, ConnectivityState.SYNC_PENDING):
            return "offline"
        elif self._state == ConnectivityState.DEGRADED:
            return "degraded"
        elif self._state == ConnectivityState.SYNCING:
            return "syncing"
        return "unknown"

    # ---- Core State Derivation ----

    def _derive_state(self) -> ConnectivityState:
        """
        Derive top-level state from individual dependency states.

        Rules:
        1. SQLite unavailable → OFFLINE (critical failure)
        2. Qdrant Edge unavailable → DEGRADED
        3. Internet unavailable, but local stack works → OFFLINE (but functional)
        4. Internet available, Qdrant Server unavailable → DEGRADED
        5. Ollama unavailable → DEGRADED (search still works)
        6. All local + remote available → ONLINE
        """
        sqlite = self._dependencies[DependencyName.SQLITE]
        edge = self._dependencies[DependencyName.QDRANT_EDGE]
        ollama = self._dependencies[DependencyName.OLLAMA]
        internet = self._dependencies[DependencyName.INTERNET]
        qdrant_server = self._dependencies[DependencyName.QDRANT_SERVER]

        # If SQLite is down, nothing works
        if sqlite.status == DependencyStatus.UNAVAILABLE:
            return ConnectivityState.OFFLINE

        # If Qdrant Edge is down, local semantic search is impaired
        if edge.status == DependencyStatus.UNAVAILABLE:
            return ConnectivityState.DEGRADED

        # If internet is unavailable, we're offline but local stack works
        if internet.status == DependencyStatus.UNAVAILABLE:
            return ConnectivityState.OFFLINE

        # If internet is available but Qdrant Server unreachable
        if qdrant_server.status == DependencyStatus.UNAVAILABLE:
            return ConnectivityState.DEGRADED

        # If Ollama is unavailable, Copilot is impaired but search works
        if ollama.status == DependencyStatus.UNAVAILABLE:
            return ConnectivityState.DEGRADED

        # All dependencies available
        return ConnectivityState.ONLINE

    # ---- Dependency Probes ----

    async def _probe_sqlite(self) -> None:
        """Actually execute a query against SQLite."""
        dep = self._dependencies[DependencyName.SQLITE]
        start = time.perf_counter()
        try:
            from app.core.database import async_session_factory
            from sqlalchemy import text
            async with async_session_factory() as session:
                await session.execute(text("SELECT 1"))
            latency = (time.perf_counter() - start) * 1000
            changed = dep.mark_available(latency, "Database responding")
            if changed:
                self._record_event(
                    ConnectivityEventType.DEPENDENCY_RECOVERED,
                    DependencyName.SQLITE,
                    DependencyStatus.UNAVAILABLE.value,
                    DependencyStatus.AVAILABLE.value,
                    "SQLite database recovered",
                )
        except Exception as e:
            changed = dep.mark_unavailable(f"DATABASE_UNAVAILABLE: {type(e).__name__}")
            if changed:
                self._record_event(
                    ConnectivityEventType.DEPENDENCY_DEGRADED,
                    DependencyName.SQLITE,
                    DependencyStatus.AVAILABLE.value,
                    DependencyStatus.UNAVAILABLE.value,
                    f"SQLite database unavailable: {type(e).__name__}",
                )

    async def _probe_qdrant_edge(self) -> None:
        """Check if Edge shard is loaded and queryable."""
        dep = self._dependencies[DependencyName.QDRANT_EDGE]
        start = time.perf_counter()
        try:
            from app.services.edge_memory import get_edge_memory_service
            edge = get_edge_memory_service()
            healthy = edge.is_healthy("mutable")
            latency = (time.perf_counter() - start) * 1000
            if healthy:
                info = edge.get_shard_info("mutable")
                changed = dep.mark_available(
                    latency,
                    f"Edge shard ready ({info.get('points_count', 0)} points)",
                )
                if changed:
                    self._record_event(
                        ConnectivityEventType.DEPENDENCY_RECOVERED,
                        DependencyName.QDRANT_EDGE,
                        DependencyStatus.UNAVAILABLE.value,
                        DependencyStatus.AVAILABLE.value,
                        "Qdrant Edge shard recovered",
                    )
            else:
                changed = dep.mark_unavailable("Edge shard not ready")
                if changed:
                    self._record_event(
                        ConnectivityEventType.DEPENDENCY_DEGRADED,
                        DependencyName.QDRANT_EDGE,
                        DependencyStatus.AVAILABLE.value,
                        DependencyStatus.UNAVAILABLE.value,
                        "Qdrant Edge shard not ready",
                    )
        except Exception as e:
            changed = dep.mark_unavailable(f"EDGE_UNAVAILABLE: {type(e).__name__}")
            if changed:
                self._record_event(
                    ConnectivityEventType.DEPENDENCY_DEGRADED,
                    DependencyName.QDRANT_EDGE,
                    DependencyStatus.AVAILABLE.value,
                    DependencyStatus.UNAVAILABLE.value,
                    f"Qdrant Edge unavailable: {type(e).__name__}",
                )

    async def _probe_ollama(self) -> None:
        """Check if Ollama API is reachable and model is available."""
        dep = self._dependencies[DependencyName.OLLAMA]
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{settings.ollama_base_url}/api/tags")
                latency = (time.perf_counter() - start) * 1000
                if resp.status_code != 200:
                    changed = dep.mark_unavailable(f"Ollama HTTP {resp.status_code}")
                    if changed:
                        self._record_event(
                            ConnectivityEventType.DEPENDENCY_DEGRADED,
                            DependencyName.OLLAMA,
                            DependencyStatus.AVAILABLE.value,
                            DependencyStatus.UNAVAILABLE.value,
                            f"Ollama returned HTTP {resp.status_code}",
                        )
                    return

                data = resp.json()
                available_models = [m["name"] for m in data.get("models", [])]
                model_found = any(
                    m == settings.ollama_model
                    or m.startswith(settings.ollama_model.split(":")[0] + ":")
                    for m in available_models
                )
                if model_found:
                    changed = dep.mark_available(latency, f"Ollama ready, model: {settings.ollama_model}")
                    if changed:
                        self._record_event(
                            ConnectivityEventType.DEPENDENCY_RECOVERED,
                            DependencyName.OLLAMA,
                            DependencyStatus.UNAVAILABLE.value,
                            DependencyStatus.AVAILABLE.value,
                            f"Ollama recovered with model {settings.ollama_model}",
                        )
                else:
                    changed = dep.mark_degraded(latency, f"Ollama available but model '{settings.ollama_model}' not found")
                    if changed:
                        self._record_event(
                            ConnectivityEventType.DEPENDENCY_DEGRADED,
                            DependencyName.OLLAMA,
                            DependencyStatus.AVAILABLE.value,
                            DependencyStatus.DEGRADED.value,
                            f"Ollama model '{settings.ollama_model}' not found in {available_models}",
                        )
        except Exception as e:
            changed = dep.mark_unavailable(f"OLLAMA_UNAVAILABLE: {type(e).__name__}")
            if changed:
                self._record_event(
                    ConnectivityEventType.DEPENDENCY_DEGRADED,
                    DependencyName.OLLAMA,
                    DependencyStatus.AVAILABLE.value,
                    DependencyStatus.UNAVAILABLE.value,
                    f"Ollama unavailable: {type(e).__name__}",
                )

    async def _probe_internet(self) -> None:
        """Check basic internet connectivity."""
        dep = self._dependencies[DependencyName.INTERNET]
        start = time.perf_counter()
        # Try multiple endpoints for reliability
        endpoints = [
            "https://httpbin.org/status/200",
            "https://www.google.com/generate_204",
        ]
        for url in endpoints:
            try:
                async with httpx.AsyncClient(timeout=3.0) as client:
                    resp = await client.get(url)
                    latency = (time.perf_counter() - start) * 1000
                    if resp.status_code in (200, 204):
                        changed = dep.mark_available(latency, "Internet reachable")
                        if changed:
                            self._record_event(
                                ConnectivityEventType.DEVICE_ONLINE,
                                DependencyName.INTERNET,
                                DependencyStatus.UNAVAILABLE.value,
                                DependencyStatus.AVAILABLE.value,
                                "Internet connectivity restored",
                            )
                        return
            except Exception:
                continue

        changed = dep.mark_unavailable("Internet unreachable")
        if changed:
            self._record_event(
                ConnectivityEventType.DEVICE_OFFLINE,
                DependencyName.INTERNET,
                DependencyStatus.AVAILABLE.value,
                DependencyStatus.UNAVAILABLE.value,
                "Internet connectivity lost",
            )

    async def _probe_qdrant_server(self) -> None:
        """Check if Qdrant Server/Cloud is reachable."""
        dep = self._dependencies[DependencyName.QDRANT_SERVER]
        start = time.perf_counter()
        try:
            headers = {}
            if settings.qdrant_api_key:
                headers["api-key"] = settings.qdrant_api_key
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(
                    f"{settings.qdrant_server_url}/healthz",
                    headers=headers,
                )
                latency = (time.perf_counter() - start) * 1000
                if resp.status_code == 200:
                    changed = dep.mark_available(latency, "Qdrant Server responding")
                    if changed:
                        self._record_event(
                            ConnectivityEventType.DEPENDENCY_RECOVERED,
                            DependencyName.QDRANT_SERVER,
                            DependencyStatus.UNAVAILABLE.value,
                            DependencyStatus.AVAILABLE.value,
                            "Qdrant Server recovered",
                        )
                else:
                    changed = dep.mark_unavailable(f"Qdrant Server HTTP {resp.status_code}")
                    if changed:
                        self._record_event(
                            ConnectivityEventType.DEPENDENCY_DEGRADED,
                            DependencyName.QDRANT_SERVER,
                            DependencyStatus.AVAILABLE.value,
                            DependencyStatus.UNAVAILABLE.value,
                            f"Qdrant Server returned HTTP {resp.status_code}",
                        )
        except Exception as e:
            changed = dep.mark_unavailable(f"QDRANT_SERVER_UNAVAILABLE: {type(e).__name__}")
            if changed:
                self._record_event(
                    ConnectivityEventType.DEPENDENCY_DEGRADED,
                    DependencyName.QDRANT_SERVER,
                    DependencyStatus.AVAILABLE.value,
                    DependencyStatus.UNAVAILABLE.value,
                    f"Qdrant Server unavailable: {type(e).__name__}",
                )

    # ---- Event Recording ----

    def _record_event(
        self,
        event_type: ConnectivityEventType,
        dependency: Optional[DependencyName],
        old_status: Optional[str],
        new_status: str,
        message: str,
    ) -> None:
        """Record a genuine connectivity state change event."""
        event = ConnectivityEvent(
            event_type=event_type,
            dependency=dependency,
            old_status=old_status,
            new_status=new_status,
            message=message,
        )
        self._events.append(event)
        # Cap event history
        if len(self._events) > self._max_events:
            self._events = self._events[-self._max_events:]

        # Notify registered listeners (e.g. audit persistence)
        for listener in self._event_listeners:
            try:
                listener(event)
            except Exception:
                pass

    # ---- Full Check ----

    async def check_all(self) -> ConnectivityState:
        """
        Probe all dependencies and derive connectivity state.
        Records events only for actual state changes.
        """
        async with self._lock:
            old_state = self._state

            # Probe all dependencies concurrently
            await asyncio.gather(
                self._probe_sqlite(),
                self._probe_qdrant_edge(),
                self._probe_ollama(),
                self._probe_internet(),
                self._probe_qdrant_server(),
                return_exceptions=True,
            )

            # Derive new state
            new_state = self._derive_state()

            # Record top-level state change if it happened
            if new_state != old_state:
                self._record_event(
                    ConnectivityEventType.STATE_CHANGED,
                    None,
                    old_state.value,
                    new_state.value,
                    f"Application state changed: {old_state.value} → {new_state.value}",
                )
                logger.info(
                    "connectivity_state_changed",
                    old_state=old_state.value,
                    new_state=new_state.value,
                )

            self._state = new_state
            self._last_full_check = datetime.now(timezone.utc)
            return new_state

    # ---- Selective Checks ----

    async def check_local_only(self) -> None:
        """Check only local dependencies (SQLite, Qdrant Edge, Ollama)."""
        async with self._lock:
            old_state = self._state
            await asyncio.gather(
                self._probe_sqlite(),
                self._probe_qdrant_edge(),
                self._probe_ollama(),
                return_exceptions=True,
            )
            new_state = self._derive_state()
            if new_state != old_state:
                self._record_event(
                    ConnectivityEventType.STATE_CHANGED,
                    None,
                    old_state.value,
                    new_state.value,
                    f"Local check: state changed {old_state.value} → {new_state.value}",
                )
            self._state = new_state

    # ---- Status Export ----

    def get_status(self) -> dict[str, Any]:
        """Get full connectivity status for API responses."""
        now_iso = (self._last_full_check or datetime.now(timezone.utc)).isoformat()
        return {
            "state": self._state.value,
            "application_mode": self.application_mode,
            "device_id": settings.device_id,
            "device_name": settings.device_name,
            "device_site": settings.device_site,
            "timestamp": now_iso,
            "internet": self._dependencies[DependencyName.INTERNET].status.value,
            "qdrant_edge": self._dependencies[DependencyName.QDRANT_EDGE].status.value,
            "ollama": self._dependencies[DependencyName.OLLAMA].status.value,
            "qdrant_server": self._dependencies[DependencyName.QDRANT_SERVER].status.value,
            "sqlite": self._dependencies[DependencyName.SQLITE].status.value,
            "dependencies": {
                dep.value: self._dependencies[dep].to_dict()
                for dep in DependencyName
            },
            "last_check": self._last_full_check.isoformat() if self._last_full_check else None,
            "recent_events": [e.to_dict() for e in self._events[-20:]],
            # Backwards compatibility fields matching ConnectivityResponse schema
            "local_database_available": self._dependencies[DependencyName.SQLITE].status == DependencyStatus.AVAILABLE,
            "internet_available": self._dependencies[DependencyName.INTERNET].status == DependencyStatus.AVAILABLE,
            "qdrant_cloud_available": self._dependencies[DependencyName.QDRANT_SERVER].status == DependencyStatus.AVAILABLE,
            "ollama_available": self._dependencies[DependencyName.OLLAMA].status == DependencyStatus.AVAILABLE,
            "edge_shard_available": self._dependencies[DependencyName.QDRANT_EDGE].status == DependencyStatus.AVAILABLE,
        }

    def get_dependency_status(self, name: DependencyName) -> DependencyState:
        """Get status of a specific dependency."""
        return self._dependencies[name]

    def is_local_operational(self) -> bool:
        """
        Returns True if the core local stack is operational:
        SQLite + Qdrant Edge must be available.
        Ollama unavailability is tolerated (search still works).
        """
        sqlite = self._dependencies[DependencyName.SQLITE]
        edge = self._dependencies[DependencyName.QDRANT_EDGE]
        return (
            sqlite.status == DependencyStatus.AVAILABLE
            and edge.status == DependencyStatus.AVAILABLE
        )

    def is_copilot_operational(self) -> bool:
        """
        Returns True if the full Copilot pipeline can execute:
        SQLite + Qdrant Edge + Ollama must be available.
        """
        return (
            self.is_local_operational()
            and self._dependencies[DependencyName.OLLAMA].status == DependencyStatus.AVAILABLE
        )

    def register_event_listener(self, listener: Callable) -> None:
        """Register a callback for connectivity events (used for audit persistence)."""
        self._event_listeners.append(listener)


# =============================================================================
# Singleton
# =============================================================================

_connectivity_manager: Optional[ConnectivityManager] = None


def get_connectivity_manager() -> ConnectivityManager:
    """Get or create the singleton ConnectivityManager."""
    global _connectivity_manager
    if _connectivity_manager is None:
        _connectivity_manager = ConnectivityManager()
    return _connectivity_manager


def reset_connectivity_manager() -> None:
    """Reset the singleton (testing only)."""
    global _connectivity_manager
    _connectivity_manager = None
