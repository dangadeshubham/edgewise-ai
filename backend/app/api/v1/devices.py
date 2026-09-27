"""Devices API — List and inspect edge devices."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.api import DeviceListResponse, DeviceResponse

router = APIRouter()


@router.get("", response_model=DeviceListResponse)
async def list_devices(db: AsyncSession = Depends(get_db)):
    """List all registered edge devices."""
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.get("/{device_id}", response_model=DeviceResponse)
async def get_device(device_id: str, db: AsyncSession = Depends(get_db)):
    """Get details of a specific device."""
    raise HTTPException(status_code=501, detail="Not yet implemented")
