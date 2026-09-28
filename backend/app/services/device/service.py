"""
EDGEWISE AI — Device Service

Business logic for device registration and management.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Sequence

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import Device
from app.repositories.device import DeviceRepository
from app.schemas.api import DeviceCreate


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DeviceService:
    """Service handling edge device registration and identity."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = DeviceRepository(session)

    async def register_device(self, data: DeviceCreate) -> Device:
        """
        Register a new edge device.
        Ensures valid UUID identity and prevents duplicates.
        """
        # 1. Resolve UUID
        if data.id:
            try:
                device_id = str(uuid.UUID(data.id))
            except (ValueError, AttributeError):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Device ID '{data.id}' is not a valid UUID format.",
                )
        else:
            device_id = str(uuid.uuid4())

        # 2. Check for duplicate ID
        existing_id = await self.repo.get_by_id(device_id)
        if existing_id is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Device with ID '{device_id}' is already registered.",
            )

        # 3. Check for duplicate Name + Site identity
        existing_identity = await self.repo.get_by_name_and_site(data.name, data.site)
        if existing_identity is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Device '{data.name}' at site '{data.site}' is already registered.",
            )

        # 4. Create and persist device
        now = utcnow()
        device = Device(
            id=device_id,
            name=data.name,
            site=data.site,
            status=data.status,
            software_version=data.software_version,
            pending_changes=0,
            last_seen=now,
            last_sync=None,
            created_at=now,
            updated_at=now,
        )

        created_device = await self.repo.create(device)

        from app.repositories.audit import AuditRepository
        audit_repo = AuditRepository(self.session)
        await audit_repo.log_event(
            event_type="DEVICE_REGISTERED",
            description=f"Device '{data.name}' registered at site '{data.site}'.",
            entity_type="device",
            entity_id=device_id,
            details={"name": data.name, "site": data.site, "software_version": data.software_version},
            severity="info",
            device_id=device_id,
        )

        return created_device

    async def get_device(self, device_id: str) -> Device:
        """Retrieve a registered device by its UUID."""
        device = await self.repo.get_by_id(device_id)
        if device is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Device with ID '{device_id}' was not found.",
            )
        return device

    async def list_devices(self) -> Sequence[Device]:
        """List all registered edge devices."""
        return await self.repo.list_all()
