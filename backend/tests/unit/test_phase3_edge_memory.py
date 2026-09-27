"""
EDGEWISE AI — Phase 3 Local Semantic Memory Test Suite

Covers the 20 mandatory Phase 3 requirements:
1. Edge package import
2. Shard creation
3. Vector insertion
4. Vector query
5. Vector retrieval
6. Shard info
7. Flush
8. Close
9. Reload persistence
10. Embedding generation
11. Dimension validation
12. Chunk embedding
13. Metadata payload
14. Semantic search endpoint
15. Filtering
16. Deterministic point IDs
17. Reindex without duplicates
18. Deletion behavior
19. Health integration
20. Restart persistence & real industrial document retrieval ("pump overheating")
"""

import json
import shutil
import tempfile
import time
from pathlib import Path
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import qdrant_edge
import qdrant_client
from app.core.config import get_settings
from app.core.database import get_db
from app.main import app
from app.models.database import Base, Document, DocumentChunk
from app.services.edge_memory import (
    EdgeMemoryService,
    LocalMemorySearch,
    VectorDimensionError,
    build_payload_filter,
    generate_point_id,
    get_edge_memory_service,
    reset_edge_memory_service,
)
from app.services.embeddings import (
    EmbeddingDimensionMismatchError,
    EmbeddingService,
    get_embedding_service,
    reset_embedding_service,
)
from app.services.health.service import HealthService
from app.services.ingestion.service import IngestionService


@pytest.fixture
def tmp_edge_dir():
    d = Path(tempfile.mkdtemp(prefix="edgewise_phase3_test_"))
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
async def test_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


# -----------------------------------------------------------------------------
# Test 1: Edge Package Import & Version Verification
# -----------------------------------------------------------------------------
def test_1_edge_package_import():
    assert hasattr(qdrant_edge, "EdgeShard")
    assert hasattr(qdrant_edge, "EdgeConfig")
    assert hasattr(qdrant_edge, "EdgeVectorParams")
    assert hasattr(qdrant_edge, "Point")
    assert hasattr(qdrant_edge, "UpdateOperation")
    assert hasattr(qdrant_edge, "QueryRequest")
    assert hasattr(qdrant_edge, "Query")
    assert hasattr(qdrant_edge, "Filter")
    assert hasattr(qdrant_edge, "Bm25")
    assert qdrant_client is not None


# -----------------------------------------------------------------------------
# Test 2: Shard Creation
# -----------------------------------------------------------------------------
def test_2_shard_creation(tmp_edge_dir):
    service = EdgeMemoryService(
        data_dir=str(tmp_edge_dir),
        mutable_dir=str(tmp_edge_dir / "mutable"),
        immutable_dir=str(tmp_edge_dir / "immutable"),
        dimension=384,
    )
    assert service.mutable_dir.exists()
    assert service.count_points("mutable") == 0
    service.close()


# -----------------------------------------------------------------------------
# Test 3: Vector Insertion
# -----------------------------------------------------------------------------
def test_3_vector_insertion(tmp_edge_dir):
    service = EdgeMemoryService(
        data_dir=str(tmp_edge_dir),
        mutable_dir=str(tmp_edge_dir / "mutable"),
        immutable_dir=str(tmp_edge_dir / "immutable"),
        dimension=4,
    )
    point_id = "00000000-0000-0000-0000-000000000001"
    vec = [0.1, 0.2, 0.3, 0.4]
    payload = {"filename": "test.txt", "doc_type": "manual"}
    service.upsert_chunk(point_id, vec, "sample text", payload)
    assert service.count_points("mutable") == 1
    service.close()


# -----------------------------------------------------------------------------
# Test 4: Vector Query
# -----------------------------------------------------------------------------
def test_4_vector_query(tmp_edge_dir):
    service = EdgeMemoryService(
        data_dir=str(tmp_edge_dir),
        mutable_dir=str(tmp_edge_dir / "mutable"),
        immutable_dir=str(tmp_edge_dir / "immutable"),
        dimension=4,
    )
    point_id = "00000000-0000-0000-0000-000000000001"
    service.upsert_chunk(point_id, [1.0, 0.0, 0.0, 0.0], "bearing alert", {"device": "pump-1"})

    hits = service.query_points(query_vector=[1.0, 0.0, 0.0, 0.0], limit=5)
    assert len(hits) == 1
    assert str(hits[0].id) == point_id
    assert hits[0].score >= 0.99
    service.close()


# -----------------------------------------------------------------------------
# Test 5: Vector Retrieval
# -----------------------------------------------------------------------------
def test_5_vector_retrieval(tmp_edge_dir):
    service = EdgeMemoryService(
        data_dir=str(tmp_edge_dir),
        mutable_dir=str(tmp_edge_dir / "mutable"),
        immutable_dir=str(tmp_edge_dir / "immutable"),
        dimension=4,
    )
    point_id = "00000000-0000-0000-0000-000000000002"
    service.upsert_chunk(point_id, [0.0, 1.0, 0.0, 0.0], "valve maintenance", {"site": "alpha"})

    records = service.retrieve_points([point_id], with_payload=True, with_vector=True)
    assert len(records) == 1
    assert str(records[0].id) == point_id
    assert records[0].payload["site"] == "alpha"
    service.close()


# -----------------------------------------------------------------------------
# Test 6: Shard Info
# -----------------------------------------------------------------------------
def test_6_shard_info(tmp_edge_dir):
    service = EdgeMemoryService(
        data_dir=str(tmp_edge_dir),
        mutable_dir=str(tmp_edge_dir / "mutable"),
        immutable_dir=str(tmp_edge_dir / "immutable"),
        dimension=4,
    )
    info = service.get_shard_info("mutable")
    assert info["status"] == "ready"
    assert info["points_count"] == 0
    assert "segments_count" in info
    service.close()


# -----------------------------------------------------------------------------
# Test 7: Flush
# -----------------------------------------------------------------------------
def test_7_flush(tmp_edge_dir):
    service = EdgeMemoryService(
        data_dir=str(tmp_edge_dir),
        mutable_dir=str(tmp_edge_dir / "mutable"),
        immutable_dir=str(tmp_edge_dir / "immutable"),
        dimension=4,
    )
    service.upsert_chunk("00000000-0000-0000-0000-000000000003", [0.5, 0.5, 0.5, 0.5], "txt", {})
    service.flush("mutable")
    assert service.last_flush_time is not None
    service.close()


# -----------------------------------------------------------------------------
# Test 8: Close
# -----------------------------------------------------------------------------
def test_8_close(tmp_edge_dir):
    service = EdgeMemoryService(
        data_dir=str(tmp_edge_dir),
        mutable_dir=str(tmp_edge_dir / "mutable"),
        immutable_dir=str(tmp_edge_dir / "immutable"),
        dimension=4,
    )
    service.close("mutable")
    assert service._mutable_shard is None


# -----------------------------------------------------------------------------
# Test 9: Reload Persistence
# -----------------------------------------------------------------------------
def test_9_reload_persistence(tmp_edge_dir):
    service = EdgeMemoryService(
        data_dir=str(tmp_edge_dir),
        mutable_dir=str(tmp_edge_dir / "mutable"),
        immutable_dir=str(tmp_edge_dir / "immutable"),
        dimension=4,
    )
    point_id = "00000000-0000-0000-0000-000000000009"
    service.upsert_chunk(point_id, [0.1, 0.2, 0.3, 0.4], "reloaded text", {"ver": 1})
    service.flush("mutable")
    service.close()

    # Reopen fresh instance pointing to same directory
    reloaded_service = EdgeMemoryService(
        data_dir=str(tmp_edge_dir),
        mutable_dir=str(tmp_edge_dir / "mutable"),
        immutable_dir=str(tmp_edge_dir / "immutable"),
        dimension=4,
    )
    assert reloaded_service.count_points("mutable") == 1
    hits = reloaded_service.query_points([0.1, 0.2, 0.3, 0.4], limit=1)
    assert len(hits) == 1
    assert str(hits[0].id) == point_id
    assert hits[0].payload["text"] == "reloaded text"
    reloaded_service.close()


# -----------------------------------------------------------------------------
# Test 10: Embedding Generation
# -----------------------------------------------------------------------------
def test_10_embedding_generation():
    emb = get_embedding_service()
    vec = emb.embed_text("Overheating turbine blade inspection")
    assert isinstance(vec, list)
    assert len(vec) == 384
    assert emb.last_latency_ms > 0


# -----------------------------------------------------------------------------
# Test 11: Dimension Validation (Fail Fast)
# -----------------------------------------------------------------------------
def test_11_dimension_validation():
    with pytest.raises(EmbeddingDimensionMismatchError):
        # MiniLM is 384 dimensions; expecting 512 must fail fast
        EmbeddingService(model_name="all-MiniLM-L6-v2", expected_dimension=512)


# -----------------------------------------------------------------------------
# Test 12: Chunk Embedding
# -----------------------------------------------------------------------------
def test_12_chunk_embedding():
    emb = get_embedding_service()
    chunks = [
        "Centrifugal pump bearing overheating procedure.",
        "Step 1: Check lube oil pressure and flow rate.",
        "Step 2: Measure vibration levels with handheld sensor.",
    ]
    vecs = emb.embed_texts(chunks, batch_size=2)
    assert len(vecs) == 3
    for v in vecs:
        assert len(v) == 384


# -----------------------------------------------------------------------------
# Test 13: Metadata Payload Traceability
# -----------------------------------------------------------------------------
def test_13_metadata_payload(tmp_edge_dir):
    service = EdgeMemoryService(
        data_dir=str(tmp_edge_dir),
        mutable_dir=str(tmp_edge_dir / "mutable"),
        immutable_dir=str(tmp_edge_dir / "immutable"),
        dimension=4,
    )
    point_id = "00000000-0000-0000-0000-000000000013"
    payload = {
        "document_id": "doc-uuid-13",
        "document_version_id": "ver-1",
        "chunk_id": "chunk-13",
        "source_id": "src-1",
        "device_id": "dev-1",
        "filename": "pump_sop.pdf",
        "page_start": 1,
        "page_end": 2,
        "document_type": "manual",
        "created_at": "2026-09-27T10:00:00Z",
        "content_hash": "hash123",
        "sensitivity": "internal",
    }
    service.upsert_chunk(point_id, [0.1, 0.2, 0.3, 0.4], "sample content", payload)

    records = service.retrieve_points([point_id], with_payload=True)
    assert len(records) == 1
    p = records[0].payload
    assert p["document_id"] == "doc-uuid-13"
    assert p["chunk_id"] == "chunk-13"
    assert p["filename"] == "pump_sop.pdf"
    assert p["page_start"] == 1
    assert p["sensitivity"] == "internal"
    assert p["text"] == "sample content"
    service.close()


# -----------------------------------------------------------------------------
# Test 14: Semantic Search Endpoint
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_14_semantic_search_endpoint(client: AsyncClient, db_session: AsyncSession):
    # Ingest document first
    ingestion = IngestionService(db_session)
    content = b"Centrifugal pump manual: in case of overheating, shutdown unit immediately."
    upload_res = await ingestion.ingest_document(
        filename="pump_emergency.txt",
        content=content,
        content_type="text/plain",
        title="Pump Emergency Manual",
        document_type="manual",
    )
    assert upload_res.processing_status == "completed"

    resp = await client.post("/api/search", json={"query": "pump overheating shutdown", "limit": 5})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_results"] >= 1
    assert "overheating" in data["results"][0]["content"].lower()
    assert data["results"][0]["score"] > 0.0
    assert data["results"][0]["document_title"] == "Pump Emergency Manual"
    assert data["retrieval_latency_ms"] > 0


# -----------------------------------------------------------------------------
# Test 15: Filtering
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_15_filtering(client: AsyncClient, db_session: AsyncSession):
    ingestion = IngestionService(db_session)

    # Ingest manual doc
    await ingestion.ingest_document(
        filename="pump_manual.txt",
        content=b"Pump overheating inspection guide.",
        content_type="text/plain",
        document_type="manual",
        sensitivity="internal",
    )
    # Ingest incident doc
    await ingestion.ingest_document(
        filename="incident_report.txt",
        content=b"Compressor overheating incident report.",
        content_type="text/plain",
        document_type="incident",
        sensitivity="restricted",
    )

    # Search with document_type filter = manual
    resp1 = await client.post(
        "/api/search",
        json={"query": "overheating", "document_type_filter": ["manual"]},
    )
    assert resp1.status_code == 200
    res1 = resp1.json()["results"]
    assert len(res1) >= 1
    for item in res1:
        assert item["document_type"] == "manual"

    # Search with sensitivity filter = restricted
    resp2 = await client.post(
        "/api/search",
        json={"query": "overheating", "sensitivity_filter": ["restricted"]},
    )
    assert resp2.status_code == 200
    res2 = resp2.json()["results"]
    assert len(res2) >= 1
    for item in res2:
        assert item["metadata"]["sensitivity"] == "restricted"


# -----------------------------------------------------------------------------
# Test 16: Deterministic Point IDs
# -----------------------------------------------------------------------------
def test_16_deterministic_point_ids():
    id1 = generate_point_id("doc-1", 0, "hash-abc")
    id2 = generate_point_id("doc-1", 0, "hash-abc")
    id3 = generate_point_id("doc-1", 1, "hash-abc")
    assert id1 == id2
    assert id1 != id3
    assert len(id1) == 36  # UUID standard string


# -----------------------------------------------------------------------------
# Test 17: Reindex Without Duplicates
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_17_reindex_without_duplicates(db_session: AsyncSession):
    ingestion = IngestionService(db_session)
    edge_service = get_edge_memory_service()

    content = b"Centrifugal pump bearing overheating protocol step 1 and step 2."
    upload = await ingestion.ingest_document(
        filename="reindex_test.txt",
        content=content,
        content_type="text/plain",
        document_type="manual",
    )
    doc_id = upload.id
    initial_points = edge_service.count_points("mutable")
    assert initial_points >= 1

    # Reindex the exact same document
    await ingestion.reindex_document(doc_id)
    after_points = edge_service.count_points("mutable")
    assert after_points == initial_points


# -----------------------------------------------------------------------------
# Test 18: Deletion Behavior (Soft Delete & Vector Removal)
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_18_deletion_behavior(client: AsyncClient, db_session: AsyncSession):
    ingestion = IngestionService(db_session)

    content = b"Secret motor malfunction protocol to be deleted."
    upload = await ingestion.ingest_document(
        filename="to_delete.txt",
        content=content,
        content_type="text/plain",
        document_type="manual",
    )
    doc_id = upload.id

    # Verify searchable initially
    s1 = await client.post("/api/search", json={"query": "Secret motor malfunction"})
    assert s1.status_code == 200
    assert any(item["document_id"] == doc_id for item in s1.json()["results"])

    # Soft-delete the document
    await ingestion.delete_document(doc_id)

    # Verify no longer returned in search
    s2 = await client.post("/api/search", json={"query": "Secret motor malfunction"})
    assert s2.status_code == 200
    assert not any(item["document_id"] == doc_id for item in s2.json()["results"])


# -----------------------------------------------------------------------------
# Test 19: Health & Readiness Integration
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_19_health_integration(client: AsyncClient):
    # /health
    h_resp = await client.get("/health")
    assert h_resp.status_code == 200
    comp_names = [c["name"] for c in h_resp.json()["components"]]
    assert "sqlite" in comp_names
    assert "edge" in comp_names
    assert "embedding" in comp_names

    # /health/ready
    r_resp = await client.get("/health/ready")
    assert r_resp.status_code == 200
    checks = r_resp.json()["checks"]
    assert checks["database"] is True
    assert checks["edge_shard"] is True
    assert checks["embedding"] is True

    # /system/connectivity
    c_resp = await client.get("/system/connectivity")
    assert c_resp.status_code == 200
    c_data = c_resp.json()
    assert c_data["local_database_available"] is True
    assert c_data["edge_shard_available"] is True


# -----------------------------------------------------------------------------
# Test 20: Real Document Search & Restart Persistence
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_20_restart_persistence_and_real_doc_search(db_session: AsyncSession):
    ingestion = IngestionService(db_session)
    edge_service = get_edge_memory_service()

    seed_dir = Path(__file__).resolve().parents[2] / "seed_data"

    # Ingest 5 industrial sample documents from real seed files
    docs = [
        ("pump_overhaul_guide.pdf", (seed_dir / "manuals" / "pump_overhaul_guide.pdf").read_bytes(), "application/pdf", "manual"),
        ("centrifugal_pump_manual.txt", (seed_dir / "manuals" / "centrifugal_pump_manual.txt").read_bytes(), "text/plain", "manual"),
        ("compressor_incident_report.md", (seed_dir / "incidents" / "compressor_incident_report.md").read_bytes(), "text/markdown", "incident"),
        ("equipment_registry.json", (seed_dir / "equipment" / "equipment_registry.json").read_bytes(), "application/json", "equipment"),
        ("turbine_inspection_sop.docx", (seed_dir / "maintenance" / "turbine_inspection_sop.docx").read_bytes(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "maintenance"),
    ]

    for fname, content, mtype, dtype in docs:
        await ingestion.ingest_document(
            filename=fname,
            content=content,
            content_type=mtype,
            document_type=dtype,
        )

    # Real query: "pump overheating"
    searcher = LocalMemorySearch()
    res = searcher.search(query="pump overheating", limit=5)
    assert res.total_results >= 1
    assert any("pump" in p.payload.get("text", "").lower() for p in res.results)

    # Mandatory persistence test: flush -> close -> reopen -> search again
    edge_service.flush("mutable")
    edge_service.close("mutable")
    edge_service.reopen("mutable")

    res_after_restart = searcher.search(query="pump overheating", limit=5)
    assert res_after_restart.total_results >= 1
    top_hit = res_after_restart.results[0]
    assert top_hit.score > 0.0
    assert "pump" in top_hit.payload["text"].lower()
