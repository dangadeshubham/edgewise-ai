"""
EDGEWISE AI — Fixture Seed Service

Loads realistic industrial maintenance fixture data:
- Devices
- Sources (manuals, incidents, maintenance, notes, equipment)
- Document metadata
- Memory records (equipment specs, technician notes, incident logs, PM records)

Idempotent: running multiple times never duplicates records or raises errors.
Strictly creates fixture data only — no fake operational metrics, fake syncs,
or fake vector counts.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import Device, Document, DocumentVersion, MemoryRecord, Source

log = structlog.get_logger("edgewise.seed")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _find_seed_dir() -> Path:
    """Locate seed_data directory from current file location or cwd."""
    candidates = [
        Path(__file__).resolve().parents[3] / "seed_data",
        Path.cwd() / "seed_data",
        Path.cwd() / "backend" / "seed_data",
    ]
    for p in candidates:
        if p.exists() and p.is_dir():
            return p
    return candidates[0]


class SeedService:
    """Loads realistic industrial maintenance fixture data into the database."""

    def __init__(self, session: AsyncSession, seed_dir: Optional[Path] = None) -> None:
        self.session = session
        self.seed_dir = seed_dir or _find_seed_dir()

    async def seed_all(self) -> dict[str, int]:
        """Load all fixture datasets in foreign-key dependency order."""
        devices_count = await self.seed_devices()
        sources_count = await self.seed_sources()
        docs_count = await self.seed_documents()
        memories_count = await self.seed_memory_records()

        await self.session.commit()

        summary = {
            "devices": devices_count,
            "sources": sources_count,
            "documents": docs_count,
            "memory_records": memories_count,
        }
        await log.ainfo("seed_data_loaded", **summary)
        return summary

    async def seed_devices(self) -> int:
        """Seed realistic edge devices."""
        file_path = self.seed_dir / "devices.json"
        if not file_path.exists():
            return 0

        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        now = utcnow()
        inserted = 0
        for item in data:
            existing = await self.session.execute(
                select(Device).where(Device.id == item["id"])
            )
            if existing.scalar_one_or_none() is None:
                device = Device(
                    id=item["id"],
                    name=item["name"],
                    site=item["site"],
                    status=item.get("status", "active"),
                    software_version=item.get("software_version", "0.1.0"),
                    pending_changes=0,
                    last_seen=now,
                    last_sync=None,
                    created_at=now,
                    updated_at=now,
                )
                self.session.add(device)
                inserted += 1

        await self.session.flush()
        return inserted

    async def seed_sources(self) -> int:
        """Seed realistic industrial knowledge sources."""
        file_path = self.seed_dir / "sources.json"
        if not file_path.exists():
            return 0

        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        now = utcnow()
        inserted = 0
        for item in data:
            existing = await self.session.execute(
                select(Source).where(Source.id == item["id"])
            )
            if existing.scalar_one_or_none() is None:
                source = Source(
                    id=item["id"],
                    name=item["name"],
                    source_type=item["source_type"],
                    description=item.get("description"),
                    created_at=now,
                )
                self.session.add(source)
                inserted += 1

        await self.session.flush()
        return inserted

    async def seed_documents(self) -> int:
        """Seed realistic document metadata and initial versions."""
        file_path = self.seed_dir / "documents.json"
        if not file_path.exists():
            return 0

        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        now = utcnow()
        inserted = 0
        for item in data:
            existing = await self.session.execute(
                select(Document).where(Document.id == item["id"])
            )
            if existing.scalar_one_or_none() is None:
                doc = Document(
                    id=item["id"],
                    device_id=item["device_id"],
                    source_id=item.get("source_id"),
                    filename=item["filename"],
                    original_filename=item.get("original_filename", item["filename"]),
                    mime_type=item["mime_type"],
                    file_size=item["file_size"],
                    content_hash=item["content_hash"],
                    file_path=item["file_path"],
                    title=item.get("title"),
                    description=item.get("description"),
                    document_type=item.get("document_type"),
                    processing_status=item.get("processing_status", "pending"),
                    sensitivity=item.get("sensitivity", "internal"),
                    sync_status=item.get("sync_status", "pending"),
                    version=item.get("version", 1),
                    revision=item.get("revision", 1),
                    origin_device=item.get("origin_device"),
                    chunk_count=item.get("chunk_count", 0),
                    total_tokens=item.get("total_tokens", 0),
                    created_at=now,
                    updated_at=now,
                )
                self.session.add(doc)

                # Also insert initial version 1 record
                version_record = DocumentVersion(
                    document_id=doc.id,
                    version=1,
                    content_hash=doc.content_hash,
                    file_size=doc.file_size,
                    change_summary="Initial fixture upload",
                    created_by_device=doc.device_id,
                    created_at=now,
                )
                self.session.add(version_record)
                inserted += 1

        await self.session.flush()
        return inserted

    async def seed_memory_records(self) -> int:
        """Seed realistic industrial memory records (equipment, notes, incidents, PM)."""
        file_path = self.seed_dir / "memory_records.json"
        if not file_path.exists():
            return 0

        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        now = utcnow()
        inserted = 0
        for item in data:
            existing = await self.session.execute(
                select(MemoryRecord).where(MemoryRecord.id == item["id"])
            )
            if existing.scalar_one_or_none() is None:
                record = MemoryRecord(
                    id=item["id"],
                    device_id=item["device_id"],
                    source_id=item.get("source_id"),
                    document_id=item.get("document_id"),
                    chunk_id=item.get("chunk_id"),
                    content=item["content"],
                    content_hash=item["content_hash"],
                    record_type=item["record_type"],
                    sensitivity=item.get("sensitivity", "internal"),
                    sync_status=item.get("sync_status", "pending"),
                    version=item.get("version", 1),
                    revision=item.get("revision", 1),
                    origin_device=item.get("origin_device"),
                    metadata_json=item.get("metadata_json"),
                    created_at=now,
                    updated_at=now,
                )
                self.session.add(record)
                inserted += 1

        await self.session.flush()
        return inserted
