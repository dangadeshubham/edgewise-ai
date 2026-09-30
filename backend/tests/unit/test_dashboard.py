"""
Tests for Dashboard Metrics endpoint.
Verifies that dashboard metrics are calculated from real persisted state,
not hardcoded or fake numbers.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.seed.service import SeedService


@pytest.mark.asyncio
async def test_dashboard_metrics_calculated_from_real_state(
    client: AsyncClient, db_session: AsyncSession
):
    """GET /api/dashboard/metrics returns metrics calculated directly from persisted DB state."""
    # First seed data into the database
    seed_service = SeedService(db_session)
    await seed_service.seed_all()

    response = await client.get("/api/dashboard/metrics")
    assert response.status_code == 200
    data = response.json()

    # Total documents matches seeded documents
    assert data["total_documents"] >= 3
    # No fake completed documents
    assert data["processed_documents"] == 0
    # No fake vectors in seeded chunks
    assert data["embedded_chunks"] == 0
    assert data["local_vector_count"] == data["edge_mutable_points"] + data["edge_immutable_points"]
    # No fake conflicts
    assert data["open_conflicts"] == 0
    # Seeded memory records
    assert data["local_memory_records"] >= 4
    # Actual storage bytes > 0
    assert data["storage_usage_bytes"] > 0
    # Real connectivity state
    assert data["connectivity_state"] in ["online", "offline", "degraded", "syncing"]
    # Device info from configuration
    assert data["current_device_id"] is not None
