"""
Tests for Seed fixture loader.
Verifies requirements:
8. Seed data loads correctly
- Loads devices, sources, documents, and memory records
- Idempotent: multiple runs do not duplicate data or error
- Strictly fixture data: no fake operational metrics, fake vector counts,
  or fake sync events
"""

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import (
    Conflict,
    Device,
    Document,
    DocumentChunk,
    DocumentVersion,
    MemoryRecord,
    Source,
    SyncAttempt,
    SyncItem,
)
from app.services.seed.service import SeedService


@pytest.mark.asyncio
async def test_seed_data_loads_correctly(db_session: AsyncSession):
    """Requirement 8: Seed data loads realistic industrial maintenance records correctly."""
    service = SeedService(db_session)
    summary = await service.seed_all()

    assert summary["devices"] >= 3
    assert summary["sources"] >= 5
    assert summary["documents"] >= 3
    assert summary["memory_records"] >= 4

    # Verify devices persisted
    devices_res = await db_session.execute(select(Device))
    devices = devices_res.scalars().all()
    device_names = {d.name for d in devices}
    assert "Site-A Field Terminal" in device_names
    assert "Pump House Station 4" in device_names

    # Verify sources persisted
    sources_res = await db_session.execute(select(Source))
    sources = sources_res.scalars().all()
    source_types = {s.source_type for s in sources}
    assert "manual" in source_types
    assert "incident" in source_types
    assert "maintenance" in source_types
    assert "note" in source_types
    assert "equipment" in source_types

    # Verify documents persisted with valid metadata
    docs_res = await db_session.execute(select(Document))
    docs = docs_res.scalars().all()
    assert len(docs) >= 3
    for d in docs:
        assert d.content_hash is not None
        assert d.mime_type in ["application/pdf", "text/markdown"]
        assert d.file_size > 0
        assert d.processing_status == "pending"  # No fake completion
        assert d.sync_status == "pending"        # No fake sync

    # Verify document_versions created
    doc_versions_res = await db_session.execute(select(DocumentVersion))
    versions = doc_versions_res.scalars().all()
    assert len(versions) >= 3

    # Verify memory_records persisted
    memories_res = await db_session.execute(select(MemoryRecord))
    memories = memories_res.scalars().all()
    record_types = {m.record_type for m in memories}
    assert "record" in record_types
    assert "observation" in record_types
    assert "note" in record_types


@pytest.mark.asyncio
async def test_seed_idempotency(db_session: AsyncSession):
    """Running seed a second time does not duplicate records or crash."""
    service = SeedService(db_session)

    # First run
    await service.seed_all()
    count1 = (await db_session.execute(select(func.count(Device.id)))).scalar()

    # Second run
    summary2 = await service.seed_all()
    count2 = (await db_session.execute(select(func.count(Device.id)))).scalar()

    assert count1 == count2, "Duplicate records were inserted on second seed run"
    assert summary2["devices"] == 0, "No new devices should be inserted on second run"
    assert summary2["sources"] == 0
    assert summary2["documents"] == 0
    assert summary2["memory_records"] == 0


@pytest.mark.asyncio
async def test_seed_contains_no_fake_operational_metrics(db_session: AsyncSession):
    """
    CRITICAL REQUIREMENT:
    Verify that seed data does not insert fake operational metrics:
    - No fake sync attempts
    - No fake conflicts
    - No fake embedded vector points
    """
    service = SeedService(db_session)
    await service.seed_all()

    # 1. Zero sync attempts
    attempts_res = await db_session.execute(select(func.count(SyncAttempt.id)))
    assert attempts_res.scalar() == 0, "Seed must not contain fake sync attempts"

    # 2. Zero conflicts
    conflicts_res = await db_session.execute(select(func.count(Conflict.id)))
    assert conflicts_res.scalar() == 0, "Seed must not contain fake conflicts"

    # 3. No fake vector points
    chunks_res = await db_session.execute(
        select(func.count(DocumentChunk.id)).where(DocumentChunk.is_embedded.is_(True))
    )
    assert chunks_res.scalar() == 0, "Seed must not contain fake embedded vector chunks"
