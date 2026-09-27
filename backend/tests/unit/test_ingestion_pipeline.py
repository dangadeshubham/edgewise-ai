"""
EDGEWISE AI — Phase 2 Comprehensive Ingestion Pipeline Tests

Covers all 20 required tests:
1. Upload valid TXT
2. Upload valid Markdown
3. Upload valid JSON
4. Upload valid DOCX
5. Upload valid PDF
6. Reject unsupported extension
7. Reject oversized file
8. Reject invalid file
9. SHA-256 generated correctly
10. Duplicate content detected
11. PDF page metadata preserved
12. Chunking produces deterministic chunks
13. Chunk overlap works
14. Document version created
15. Old version retained after replacement
16. Delete works
17. Reindex behavior is correct for Phase 2
18. Failed processing is persisted
19. Restart preserves documents/chunks/versions
20. Audit events are created
"""

import hashlib
import io
import json
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models.database import AuditEvent, Document, DocumentChunk, DocumentVersion
from app.services.ingestion.chunker import DocumentChunker
from app.services.ingestion.extractor import ExtractedDocument, PageContent
from app.services.ingestion.service import IngestionService

SEED_DIR = Path(__file__).resolve().parents[2] / "seed_data"


# =============================================================================
# 1-5: Valid File Uploads for all 5 formats
# =============================================================================

@pytest.mark.asyncio
async def test_1_upload_valid_txt(client: AsyncClient, db_session: AsyncSession):
    """1. Upload valid TXT file."""
    txt_path = SEED_DIR / "manuals" / "centrifugal_pump_manual.txt"
    with open(txt_path, "rb") as f:
        file_bytes = f.read()

    files = {"file": ("centrifugal_pump_manual.txt", file_bytes, "text/plain")}
    data = {
        "title": "Centrifugal Pump Manual",
        "document_type": "manual",
        "sensitivity": "internal",
    }
    response = await client.post("/api/documents", files=files, data=data)
    assert response.status_code == 201
    resp_data = response.json()

    assert resp_data["processing_status"] == "completed"
    assert resp_data["is_duplicate"] is False
    assert resp_data["content_hash"] == hashlib.sha256(file_bytes).hexdigest()
    assert resp_data["file_size"] == len(file_bytes)

    # Verify persisted in SQLite
    doc_res = await db_session.execute(
        select(Document).where(Document.id == resp_data["id"])
    )
    doc = doc_res.scalar_one_or_none()
    assert doc is not None
    assert doc.chunk_count > 0
    assert doc.processing_status == "completed"


@pytest.mark.asyncio
async def test_2_upload_valid_markdown(client: AsyncClient, db_session: AsyncSession):
    """2. Upload valid Markdown file."""
    md_path = SEED_DIR / "incidents" / "compressor_incident_report.md"
    with open(md_path, "rb") as f:
        file_bytes = f.read()

    files = {"file": ("compressor_incident_report.md", file_bytes, "text/markdown")}
    data = {"title": "Compressor Incident Report", "document_type": "incident"}
    response = await client.post("/api/documents", files=files, data=data)
    assert response.status_code == 201
    resp_data = response.json()

    assert resp_data["processing_status"] == "completed"
    assert resp_data["is_duplicate"] is False

    chunks_res = await db_session.execute(
        select(DocumentChunk).where(DocumentChunk.document_id == resp_data["id"])
    )
    chunks = chunks_res.scalars().all()
    assert len(chunks) >= 1
    # Check that Markdown heading is retained in content
    assert any("# INCIDENT INVESTIGATION REPORT" in c.content for c in chunks)


@pytest.mark.asyncio
async def test_3_upload_valid_json(client: AsyncClient, db_session: AsyncSession):
    """3. Upload valid JSON file."""
    json_path = SEED_DIR / "equipment" / "equipment_registry.json"
    with open(json_path, "rb") as f:
        file_bytes = f.read()

    files = {"file": ("equipment_registry.json", file_bytes, "application/json")}
    data = {"title": "Equipment Registry Specs", "document_type": "equipment"}
    response = await client.post("/api/documents", files=files, data=data)
    assert response.status_code == 201
    resp_data = response.json()

    assert resp_data["processing_status"] == "completed"

    chunks_res = await db_session.execute(
        select(DocumentChunk).where(DocumentChunk.document_id == resp_data["id"])
    )
    chunks = chunks_res.scalars().all()
    assert len(chunks) >= 1
    # Check that flattened key-value structure is present
    assert any("PUMP-CP-400A" in c.content for c in chunks)


@pytest.mark.asyncio
async def test_4_upload_valid_docx(client: AsyncClient, db_session: AsyncSession):
    """4. Upload valid DOCX file."""
    docx_path = SEED_DIR / "maintenance" / "turbine_inspection_sop.docx"
    with open(docx_path, "rb") as f:
        file_bytes = f.read()

    files = {
        "file": (
            "turbine_inspection_sop.docx",
            file_bytes,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    }
    data = {"title": "Turbine Inspection SOP", "document_type": "maintenance"}
    response = await client.post("/api/documents", files=files, data=data)
    assert response.status_code == 201
    resp_data = response.json()

    assert resp_data["processing_status"] == "completed"

    chunks_res = await db_session.execute(
        select(DocumentChunk).where(DocumentChunk.document_id == resp_data["id"])
    )
    chunks = chunks_res.scalars().all()
    assert len(chunks) >= 1
    # Paragraphs and table cell contents should be extracted
    assert any("SOP-PM-440" in c.content for c in chunks)
    assert any("Nozzle Guide Vanes" in c.content for c in chunks)


@pytest.mark.asyncio
async def test_5_upload_valid_pdf(client: AsyncClient, db_session: AsyncSession):
    """5. Upload valid multi-page PDF."""
    pdf_path = SEED_DIR / "manuals" / "pump_overhaul_guide.pdf"
    with open(pdf_path, "rb") as f:
        file_bytes = f.read()

    files = {"file": ("pump_overhaul_guide.pdf", file_bytes, "application/pdf")}
    data = {"title": "Pump Overhaul Guide", "document_type": "manual"}
    response = await client.post("/api/documents", files=files, data=data)
    assert response.status_code == 201
    resp_data = response.json()

    assert resp_data["processing_status"] == "completed"

    doc_res = await db_session.execute(
        select(Document).where(Document.id == resp_data["id"])
    )
    doc = doc_res.scalar_one()
    assert doc.chunk_count >= 2


# =============================================================================
# 6-8: Validation & Rejections
# =============================================================================

@pytest.mark.asyncio
async def test_6_reject_unsupported_extension(client: AsyncClient):
    """6. Reject unsupported file extensions with HTTP 422."""
    files = {"file": ("malicious_script.exe", b"binary executable content", "application/octet-stream")}
    response = await client.post("/api/documents", files=files)
    assert response.status_code == 422
    err = response.json()
    assert "unsupported file extension" in err["detail"].lower()


@pytest.mark.asyncio
async def test_7_reject_oversized_file(client: AsyncClient, monkeypatch):
    """7. Reject file exceeding max_upload_size_mb with HTTP 413."""
    from app.core.config import Settings
    custom_settings = Settings(max_upload_size_mb=0)
    monkeypatch.setattr("app.services.ingestion.validator.get_settings", lambda: custom_settings)

    large_bytes = b"X" * 1500
    files = {"file": ("large_doc.txt", large_bytes, "text/plain")}
    response = await client.post("/api/documents", files=files)
    assert response.status_code == 413
    assert "exceeds maximum allowed limit" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_8_reject_invalid_file(client: AsyncClient):
    """8. Reject malformed file content with HTTP 422."""
    # Corrupted PDF (missing %PDF- header)
    corrupt_pdf = b"NOT_A_REAL_PDF_HEADER_JUST_GARBAGE"
    files = {"file": ("fake_manual.pdf", corrupt_pdf, "application/pdf")}
    response = await client.post("/api/documents", files=files)
    assert response.status_code == 422
    assert "malformed pdf" in response.json()["detail"].lower()

    # Corrupted JSON
    corrupt_json = b"{invalid_json_missing_quotes: true,"
    files_json = {"file": ("broken.json", corrupt_json, "application/json")}
    resp_json = await client.post("/api/documents", files=files_json)
    assert resp_json.status_code == 422
    assert "malformed json" in resp_json.json()["detail"].lower()


# =============================================================================
# 9-10: Hash & Deduplication
# =============================================================================

@pytest.mark.asyncio
async def test_9_sha256_generated_correctly(client: AsyncClient):
    """9. SHA-256 generated correctly on uploaded content."""
    content = b"Unique content for SHA-256 test: Pump Bearing Serial #PB-99482."
    expected_hash = hashlib.sha256(content).hexdigest()

    files = {"file": ("sha_test.txt", content, "text/plain")}
    response = await client.post("/api/documents", files=files)
    assert response.status_code == 201
    data = response.json()
    assert data["content_hash"] == expected_hash


@pytest.mark.asyncio
async def test_10_duplicate_content_detected(client: AsyncClient, db_session: AsyncSession):
    """10. Check duplicate content: does not unnecessarily reprocess and reports duplicate."""
    content = b"Deterministic duplicate content test: Valve V-12 maintenance record."
    files1 = {"file": ("valve_initial.txt", content, "text/plain")}

    # First upload -> 201 Created
    resp1 = await client.post("/api/documents", files=files1)
    assert resp1.status_code == 201
    doc1 = resp1.json()

    # Second upload with different filename but identical bytes
    files2 = {"file": ("valve_renamed.txt", content, "text/plain")}
    resp2 = await client.post("/api/documents", files=files2)
    assert resp2.status_code == 200
    doc2 = resp2.json()

    assert doc2["id"] == doc1["id"]
    assert doc2["is_duplicate"] is True
    assert doc2["processing_status"] == "duplicate"
    assert "duplicate" in doc2["message"].lower()

    # Verify audit event for duplicate was created
    audit_res = await db_session.execute(
        select(AuditEvent).where(
            AuditEvent.event_type == "duplicate_detected",
            AuditEvent.entity_id == doc1["id"],
        )
    )
    audit = audit_res.scalar_one_or_none()
    assert audit is not None


# =============================================================================
# 11-13: Chunking & Metadata
# =============================================================================

@pytest.mark.asyncio
async def test_11_pdf_page_metadata_preserved(client: AsyncClient, db_session: AsyncSession):
    """11. PDF page metadata is preserved in chunks."""
    pdf_path = SEED_DIR / "manuals" / "pump_overhaul_guide.pdf"
    with open(pdf_path, "rb") as f:
        file_bytes = f.read()

    files = {"file": ("pump_paged.pdf", file_bytes, "application/pdf")}
    response = await client.post("/api/documents", files=files)
    assert response.status_code == 201
    doc_id = response.json()["id"]

    chunks_res = await db_session.execute(
        select(DocumentChunk)
        .where(DocumentChunk.document_id == doc_id)
        .order_by(DocumentChunk.chunk_index)
    )
    chunks = chunks_res.scalars().all()
    assert len(chunks) >= 2

    # Verify page numbers exist in metadata
    meta0 = json.loads(chunks[0].metadata_json)
    assert meta0["page_start"] == 1
    assert meta0["page_end"] == 1

    last_meta = json.loads(chunks[-1].metadata_json)
    assert last_meta["page_start"] == 2


def test_12_chunking_produces_deterministic_chunks():
    """12. Chunking produces identical chunks for identical inputs."""
    chunker = DocumentChunker(chunk_size=100, chunk_overlap=20)
    text = (
        "Paragraph 1: Centrifugal pump overhaul procedure.\n\n"
        "Paragraph 2: Laser alignment tolerances and radial clearances.\n\n"
        "Paragraph 3: Mechanical seal lubrication and flush piping."
    )
    doc1 = ExtractedDocument(text=text, pages=[PageContent(page_number=1, text=text)])
    doc2 = ExtractedDocument(text=text, pages=[PageContent(page_number=1, text=text)])

    chunks1 = chunker.chunk_document(doc1, "doc-test-12")
    chunks2 = chunker.chunk_document(doc2, "doc-test-12")

    assert len(chunks1) == len(chunks2)
    for c1, c2 in zip(chunks1, chunks2):
        assert c1.chunk_index == c2.chunk_index
        assert c1.content == c2.content
        assert c1.content_hash == c2.content_hash
        assert c1.char_count == c2.char_count
        assert c1.token_estimate == c2.token_estimate


def test_13_chunk_overlap_works():
    """13. Chunk overlap ensures tail of previous chunk appears in next chunk."""
    chunker = DocumentChunker(chunk_size=60, chunk_overlap=25)
    text = (
        "First segment of technical inspection text. "
        "Second segment discussing vibration velocity sensor readings. "
        "Third segment detailing bearing temperatures."
    )
    doc = ExtractedDocument(text=text)
    chunks = chunker.chunk_document(doc, "doc-overlap-test")

    assert len(chunks) >= 2
    # Verify overlap exists between chunk 0 and chunk 1
    chunk0_words = chunks[0].content.split()
    chunk1_words = chunks[1].content.split()
    # At least one shared word due to overlap
    common_words = set(chunk0_words[-4:]) & set(chunk1_words[:4])
    assert len(common_words) > 0, "Chunks must share words across boundary due to overlap"


# =============================================================================
# 14-15: Versions & Version Replacement
# =============================================================================

@pytest.mark.asyncio
async def test_14_document_version_created(client: AsyncClient, db_session: AsyncSession):
    """14. DocumentVersion record created on initial ingestion."""
    content = b"Version 1 content: initial installation specs."
    files = {"file": ("v1_doc.txt", content, "text/plain")}
    response = await client.post("/api/documents", files=files)
    doc_id = response.json()["id"]

    versions_res = await db_session.execute(
        select(DocumentVersion).where(DocumentVersion.document_id == doc_id)
    )
    versions = versions_res.scalars().all()
    assert len(versions) == 1
    assert versions[0].version == 1
    assert versions[0].content_hash == hashlib.sha256(content).hexdigest()


@pytest.mark.asyncio
async def test_15_old_version_retained_after_replacement(db_session: AsyncSession):
    """15. Updating document content creates a new version while retaining old versions."""
    service = IngestionService(db_session)

    # Initial version 1
    initial_content = b"Original baseline manual for Pump Unit 1."
    res1 = await service.ingest_document("pump_manual.txt", initial_content)
    doc_id = res1.id

    # Create version 2 with updated content
    updated_content = b"Updated revision 2 manual with revised bearing tolerances for Pump Unit 1."
    v2 = await service.update_document_version(doc_id, updated_content, "Updated tolerances")
    assert v2.version == 2

    # Verify both versions exist in database
    versions = await service.get_versions(doc_id)
    assert len(versions) == 2
    assert [v.version for v in versions] == [1, 2]
    assert versions[0].content_hash == hashlib.sha256(initial_content).hexdigest()
    assert versions[1].content_hash == hashlib.sha256(updated_content).hexdigest()

    # Document current version is updated
    doc = await service.doc_repo.get_by_id(doc_id)
    assert doc.version == 2
    assert doc.content_hash == hashlib.sha256(updated_content).hexdigest()


# =============================================================================
# 16-17: Delete & Reindex
# =============================================================================

@pytest.mark.asyncio
async def test_16_delete_works(client: AsyncClient, db_session: AsyncSession):
    """16. Delete endpoint soft-deletes the document and records audit event."""
    content = b"Temporary document to be deleted."
    files = {"file": ("delete_me.txt", content, "text/plain")}
    resp = await client.post("/api/documents", files=files)
    doc_id = resp.json()["id"]

    # Delete
    del_resp = await client.delete(f"/api/documents/{doc_id}")
    assert del_resp.status_code == 200
    assert "deleted" in del_resp.json()["message"].lower()

    # GET /api/documents/{id} now returns 404
    get_resp = await client.get(f"/api/documents/{doc_id}")
    assert get_resp.status_code == 404

    # Document is excluded from active list
    list_resp = await client.get("/api/documents")
    assert not any(d["id"] == doc_id for d in list_resp.json()["items"])

    # Audit event recorded
    audit_res = await db_session.execute(
        select(AuditEvent).where(
            AuditEvent.event_type == "document_deleted",
            AuditEvent.entity_id == doc_id,
        )
    )
    assert audit_res.scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_17_reindex_behavior(client: AsyncClient, db_session: AsyncSession):
    """17. Reindex re-extracts and chunks stored document and updates chunk_count."""
    content = b"Reindex test: Line 1.\n\nLine 2 with specifications.\n\nLine 3."
    files = {"file": ("reindex_target.txt", content, "text/plain")}
    resp = await client.post("/api/documents", files=files)
    doc_id = resp.json()["id"]

    reindex_resp = await client.post(f"/api/documents/{doc_id}/reindex")
    assert reindex_resp.status_code == 200
    assert reindex_resp.json()["data"]["chunk_count"] > 0

    # Verify chunks exist and audit event logged
    audit_res = await db_session.execute(
        select(AuditEvent).where(
            AuditEvent.event_type == "document_reindexed",
            AuditEvent.entity_id == doc_id,
        )
    )
    assert audit_res.scalar_one_or_none() is not None


# =============================================================================
# 18-20: Error Persistence, Restart & Audit Events
# =============================================================================

@pytest.mark.asyncio
async def test_18_failed_processing_is_persisted(client: AsyncClient, db_session: AsyncSession):
    """18. Failed extraction (image-only PDF with no text) persists failed status and error."""
    image_pdf_path = SEED_DIR / "manuals" / "image_only_scanned_sample.pdf"
    with open(image_pdf_path, "rb") as f:
        file_bytes = f.read()

    files = {"file": ("image_only_scanned_sample.pdf", file_bytes, "application/pdf")}
    response = await client.post("/api/documents", files=files)
    # Processing fails with 422
    assert response.status_code == 422
    assert "image-only pdf; ocr not available" in response.json()["detail"].lower()

    # Verify that the failed document record was persisted with diagnostic error
    content_hash = hashlib.sha256(file_bytes).hexdigest()
    doc_res = await db_session.execute(
        select(Document).where(Document.content_hash == content_hash)
    )
    doc = doc_res.scalar_one_or_none()
    assert doc is not None
    assert doc.processing_status == "failed"
    assert "ocr not available" in doc.processing_error.lower()


@pytest.mark.asyncio
async def test_19_restart_preserves_documents_chunks_and_versions(
    temp_data_dir, test_db_url, client: AsyncClient
):
    """19. Application restart preserves documents, chunks, and versions in SQLite."""
    content = b"Persistence test across database engine dispose and reopen."
    files = {"file": ("restart_persist.txt", content, "text/plain")}
    resp = await client.post("/api/documents", files=files)
    assert resp.status_code == 201
    doc_id = resp.json()["id"]

    # Reconnect with a new independent engine (simulating restart)
    new_engine = create_async_engine(test_db_url, echo=False)
    async with new_engine.begin() as conn:
        doc_row = (
            await conn.execute(
                select(Document.id, Document.title, Document.chunk_count).where(
                    Document.id == doc_id
                )
            )
        ).fetchone()
        assert doc_row is not None
        assert doc_row[0] == doc_id

        chunks = (
            await conn.execute(
                select(DocumentChunk.id).where(DocumentChunk.document_id == doc_id)
            )
        ).fetchall()
        assert len(chunks) > 0

        versions = (
            await conn.execute(
                select(DocumentVersion.id).where(DocumentVersion.document_id == doc_id)
            )
        ).fetchall()
        assert len(versions) == 1

    await new_engine.dispose()


@pytest.mark.asyncio
async def test_20_audit_events_are_created(client: AsyncClient, db_session: AsyncSession):
    """20. Real audit events are created throughout the document lifecycle."""
    content = b"Lifecycle audit verification content."
    files = {"file": ("audit_doc.txt", content, "text/plain")}
    resp = await client.post("/api/documents", files=files)
    doc_id = resp.json()["id"]

    # Check that document_uploaded and processing_completed were logged
    events_res = await db_session.execute(
        select(AuditEvent)
        .where(AuditEvent.entity_id == doc_id)
        .order_by(AuditEvent.created_at)
    )
    events = events_res.scalars().all()
    event_types = [e.event_type for e in events]

    assert "document_uploaded" in event_types
    assert "processing_started" in event_types
    assert "processing_completed" in event_types
