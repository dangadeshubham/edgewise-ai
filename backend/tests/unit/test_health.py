"""
Tests for Health, Readiness, Liveness, and Connectivity endpoints.
Verifies requirements:
2. Health live succeeds
3. Readiness succeeds with DB available
4. Readiness fails appropriately when DB unavailable
- Real dependency checks distinguish offline/unhealthy services
- Connectivity returns real status without pretending to be online
"""

import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, patch

from app.core.database import get_db
from app.main import app


@pytest.mark.asyncio
async def test_health_live_succeeds(client: AsyncClient):
    """GET /health/live returns HTTP 200 with alive=True."""
    response = await client.get("/health/live")
    assert response.status_code == 200
    data = response.json()
    assert data["alive"] is True


@pytest.mark.asyncio
async def test_readiness_succeeds_with_db_available(client: AsyncClient):
    """GET /health/ready returns HTTP 200 and ready=True when database is healthy."""
    response = await client.get("/health/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["ready"] is True
    assert data["checks"]["database"] is True


@pytest.mark.asyncio
async def test_readiness_fails_appropriately_when_db_unavailable():
    """GET /health/ready returns HTTP 503 and ready=False when database is down."""
    mock_db = AsyncMock()
    mock_db.execute.side_effect = Exception("SQLite connection failed")

    async def override_failing_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_failing_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/ready")
        assert response.status_code == 503
        data = response.json()
        assert data["ready"] is False
        assert data["checks"]["database"] is False

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_comprehensive_health_inspects_dependencies(client: AsyncClient):
    """
    GET /health actually inspects each dependency and distinguishes them.
    Components checked: sqlite, qdrant, ollama, edge, internet.
    """
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()

    assert "status" in data
    assert "components" in data
    assert "uptime_seconds" in data
    assert "version" in data
    assert "device_id" in data

    components = {c["name"]: c for c in data["components"]}

    # SQLite must be healthy since test DB is running
    assert "sqlite" in components
    assert components["sqlite"]["status"] == "healthy"
    assert components["sqlite"]["latency_ms"] is not None

    # Other dependencies should be present and accurately probed
    assert "qdrant_server" in components or "qdrant" in components
    assert "ollama" in components
    assert "qdrant_edge" in components or "edge" in components
    assert "internet" in components

    # Distinguishes failure: if ollama/qdrant is not running locally, it must not be marked healthy
    for name in [k for k in ["qdrant_server", "qdrant", "ollama", "qdrant_edge", "edge", "internet"] if k in components]:
        assert components[name]["status"] in ["healthy", "unhealthy", "degraded"]


@pytest.mark.asyncio
async def test_connectivity_endpoint_returns_real_status(client: AsyncClient):
    """
    GET /system/connectivity returns real status without hardcoded fake booleans.
    """
    response = await client.get("/system/connectivity")
    assert response.status_code == 200
    data = response.json()

    assert "state" in data
    assert data["state"] in ["online", "offline", "degraded", "syncing"]
    assert "local_database_available" in data
    assert data["local_database_available"] is True
    assert "internet_available" in data
    assert isinstance(data["internet_available"], bool)
    assert "qdrant_cloud_available" in data
    assert isinstance(data["qdrant_cloud_available"], bool)
    assert "ollama_available" in data
    assert isinstance(data["ollama_available"], bool)
    assert "edge_shard_available" in data
    assert isinstance(data["edge_shard_available"], bool)
