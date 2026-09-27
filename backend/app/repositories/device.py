"""
EDGEWISE AI — Device Repository

Data access for edge devices.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import Device
from app.repositories.base import BaseRepository


class DeviceRepository(BaseRepository[Device]):
    """Repository handling database operations for Device models."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Device, session)

    async def get_by_name_and_site(self, name: str, site: str) -> Optional[Device]:
        """Find an existing device with matching name and site."""
        result = await self.session.execute(
            select(Device).where(
                Device.name == name,
                Device.site == site,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_name(self, name: str) -> Optional[Device]:
        """Find an existing device by name."""
        result = await self.session.execute(
            select(Device).where(Device.name == name)
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> Sequence[Device]:
        """Return all registered devices sorted by creation timestamp."""
        result = await self.session.execute(
            select(Device).order_by(Device.created_at.desc())
        )
        return result.scalars().all()

    async def update_last_seen(self, device_id: str) -> Optional[Device]:
        """Update last_seen timestamp for a device."""
        device = await self.get_by_id(device_id)
        if device:
            device.last_seen = datetime.now(timezone.utc)
            device.updated_at = datetime.now(timezone.utc)
            await self.session.flush()
            await self.session.refresh(device)
        return device
