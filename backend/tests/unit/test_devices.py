"""
Tests for Edge Device registration and retrieval.
Verifies requirements:
5. Device creation works
6. Device retrieval works
7. Duplicate device validation works
9. API validation rejects invalid data
- Device has all 8 required fields (UUID, name, site, status, created_at, updated_at, last_seen, last_sync)
- Request ID propagation
"""

import uuid
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_device_creation_with_generated_uuid(client: AsyncClient):
    """POST /api/devices creates a device with an automatically generated UUID."""
    payload = {
        "name": "Generator Room Terminal 1",
        "site": "site-alpha",
        "status": "active",
        "software_version": "0.1.0",
    }
    response = await client.post("/api/devices", json=payload)
    assert response.status_code == 201
    data = response.json()

    # Verify UUID format
    assert "id" in data
    parsed_uuid = uuid.UUID(data["id"])
    assert str(parsed_uuid) == data["id"]

    # Verify all 8 required fields
    assert data["name"] == "Generator Room Terminal 1"
    assert data["site"] == "site-alpha"
    assert data["status"] == "active"
    assert "created_at" in data and data["created_at"] is not None
    assert "updated_at" in data and data["updated_at"] is not None
    assert "last_seen" in data and data["last_seen"] is not None
    assert "last_sync" in data  # Can be None initially
    assert data["pending_changes"] == 0

    # Verify Request-ID header is attached
    assert "x-request-id" in response.headers


@pytest.mark.asyncio
async def test_device_creation_with_provided_uuid(client: AsyncClient):
    """POST /api/devices creates a device with a client-supplied valid UUID."""
    custom_uuid = str(uuid.uuid4())
    payload = {
        "id": custom_uuid,
        "name": "Turbine Bay Scanner 2",
        "site": "site-beta",
        "status": "active",
        "software_version": "0.1.0",
    }
    response = await client.post("/api/devices", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["id"] == custom_uuid
    assert data["name"] == "Turbine Bay Scanner 2"


@pytest.mark.asyncio
async def test_device_retrieval_works(client: AsyncClient):
    """GET /api/devices/{id} retrieves the specific device details."""
    # First create a device
    device_id = str(uuid.uuid4())
    create_resp = await client.post(
        "/api/devices",
        json={
            "id": device_id,
            "name": "Cooling Tower Logger 3",
            "site": "site-gamma",
            "status": "active",
        },
    )
    assert create_resp.status_code == 201

    # Now retrieve it
    get_resp = await client.get(f"/api/devices/{device_id}")
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert data["id"] == device_id
    assert data["name"] == "Cooling Tower Logger 3"
    assert data["site"] == "site-gamma"


@pytest.mark.asyncio
async def test_device_list_works(client: AsyncClient):
    """GET /api/devices returns all registered devices."""
    # Register a device first
    await client.post(
        "/api/devices",
        json={"name": "Listing Test Device", "site": "site-list"},
    )
    response = await client.get("/api/devices")
    assert response.status_code == 200
    data = response.json()
    assert "devices" in data
    assert isinstance(data["devices"], list)
    assert len(data["devices"]) >= 1
    assert any(d["name"] == "Listing Test Device" for d in data["devices"])


@pytest.mark.asyncio
async def test_duplicate_device_id_rejected(client: AsyncClient):
    """POST /api/devices rejects duplicate device ID with HTTP 409."""
    device_id = str(uuid.uuid4())
    payload1 = {
        "id": device_id,
        "name": "Primary Pump Monitor A",
        "site": "site-delta",
    }
    resp1 = await client.post("/api/devices", json=payload1)
    assert resp1.status_code == 201

    # Attempt to create with identical ID
    payload2 = {
        "id": device_id,
        "name": "Different Monitor Name",
        "site": "site-delta",
    }
    resp2 = await client.post("/api/devices", json=payload2)
    assert resp2.status_code == 409
    data = resp2.json()
    assert "already registered" in data["detail"].lower()


@pytest.mark.asyncio
async def test_duplicate_device_name_and_site_rejected(client: AsyncClient):
    """POST /api/devices rejects duplicate name+site with HTTP 409."""
    payload1 = {
        "name": "Boiler Room Sensor Unit 9",
        "site": "site-epsilon",
    }
    resp1 = await client.post("/api/devices", json=payload1)
    assert resp1.status_code == 201

    # Attempt to create with different ID but same name and site
    payload2 = {
        "name": "Boiler Room Sensor Unit 9",
        "site": "site-epsilon",
    }
    resp2 = await client.post("/api/devices", json=payload2)
    assert resp2.status_code == 409
    data = resp2.json()
    assert "already registered" in data["detail"].lower()


@pytest.mark.asyncio
async def test_api_validation_rejects_invalid_data(client: AsyncClient):
    """Requirement 9: API validation rejects invalid payloads with HTTP 422."""
    # 1. Invalid UUID format
    resp_bad_uuid = await client.post(
        "/api/devices",
        json={"id": "not-a-valid-uuid", "name": "Bad Device", "site": "site-alpha"},
    )
    assert resp_bad_uuid.status_code == 422
    err_data = resp_bad_uuid.json()
    assert err_data["error"] == "validation_error"
    assert "id" in err_data["detail"]

    # 2. Missing required field (name)
    resp_missing_name = await client.post(
        "/api/devices",
        json={"site": "site-alpha"},
    )
    assert resp_missing_name.status_code == 422
    assert "name" in resp_missing_name.json()["detail"]

    # 3. Missing required field (site)
    resp_missing_site = await client.post(
        "/api/devices",
        json={"name": "No Site Device"},
    )
    assert resp_missing_site.status_code == 422
    assert "site" in resp_missing_site.json()["detail"]

    # 4. Invalid status value
    resp_invalid_status = await client.post(
        "/api/devices",
        json={"name": "Bad Status Dev", "site": "site-alpha", "status": "unknown_status"},
    )
    assert resp_invalid_status.status_code == 422
    assert "status" in resp_invalid_status.json()["detail"]

    # 5. Empty name (length < 1)
    resp_empty_name = await client.post(
        "/api/devices",
        json={"name": "", "site": "site-alpha"},
    )
    assert resp_empty_name.status_code == 422


@pytest.mark.asyncio
async def test_get_nonexistent_device_returns_404(client: AsyncClient):
    """GET /api/devices/{id} for non-existent device returns HTTP 404."""
    random_id = str(uuid.uuid4())
    response = await client.get(f"/api/devices/{random_id}")
    assert response.status_code == 404
    data = response.json()
    assert data["error"] == "http_404"
    assert "not found" in data["detail"].lower()
