"""
EDGEWISE AI — Devices API

Real edge device registration and inspection.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.api import DeviceCreate, DeviceListResponse, DeviceResponse
from app.services.device.service import DeviceService

router = APIRouter()


@router.post("", response_model=DeviceResponse, status_code=status.HTTP_201_CREATED)
async def register_device(
    device_in: DeviceCreate,
    db: AsyncSession = Depends(get_db),
) -> DeviceResponse:
    """Register a new edge device."""
    service = DeviceService(db)
    device = await service.register_device(device_in)
    return DeviceResponse.model_validate(device)


@router.get("", response_model=DeviceListResponse)
async def list_devices(
    db: AsyncSession = Depends(get_db),
) -> DeviceListResponse:
    """List all registered edge devices."""
    service = DeviceService(db)
    devices = await service.list_devices()
    return DeviceListResponse(
        devices=[DeviceResponse.model_validate(d) for d in devices]
    )


@router.get("/{device_id}", response_model=DeviceResponse)
async def get_device(
    device_id: str,
    db: AsyncSession = Depends(get_db),
) -> DeviceResponse:
    """Get details of a specific device by its UUID."""
    service = DeviceService(db)
    device = await service.get_device(device_id)
    return DeviceResponse.model_validate(device)
