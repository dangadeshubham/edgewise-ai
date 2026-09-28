"""
EDGEWISE AI — Phase 10 Observability, Telemetry & Audit Tests

Validates:
1. Request ID propagation and tracing headers
2. Correlated operation ID generation
3. Audit event creation across state changes
4. Audit append-only immutability (triggers & repository guardrails)
5. Audit querying and pagination on GET /api/activity
6. Separated sync telemetry (queue, remote, total)
7. Detailed ingestion phase telemetry
8. RAG telemetry and latency breakdown
9. Operational health telemetry
10. Prometheus (/metrics) and JSON (/api/metrics) telemetry endpoints
11. Automated secret & token redaction in logs
12. Standardized error taxonomy categorization
13. End-to-end trace correlation
14. Failure mode observability and error metric increments
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditEventType, normalize_event_type
from app.core.database import install_audit_immutability
from app.core.errors import (
    EdgewiseConflictError,
    EdgewiseEdgeError,
    EdgewiseException,
    EdgewiseStorageError,
    EdgewiseValidationError,
    ErrorCategory,
)
from app.core.logging import (
    generate_operation_id,
    generate_request_id,
    redact_processor,
    redact_sensitive_value,
)
from app.core.metrics import get_metrics_registry
from app.models.database import AuditEvent
from app.repositories.audit import AuditRepository


@pytest.mark.asyncio
class TestPhase10Observability:
    """Complete Phase 10 verification test suite."""

    # 1. Request ID Propagation
    async def test_request_id_propagation(self, client: AsyncClient) -> None:
        # Client supplies custom request ID
        resp = await client.get("/health", headers={"X-Request-ID": "test-req-1234"})
        assert resp.status_code == 200
        assert resp.headers.get("X-Request-ID") == "test-req-1234"
        assert "X-Response-Time-Ms" in resp.headers

        # Client omits request ID -> system auto-generates
        resp_auto = await client.get("/health")
        assert resp_auto.status_code == 200
        req_id = resp_auto.headers.get("X-Request-ID")
        assert req_id is not None
        assert len(req_id) >= 6

    # 2. Operation ID Creation
    async def test_operation_id_creation(self) -> None:
        op_ingest = generate_operation_id("ingest")
        op_sync = generate_operation_id("sync")
        op_conf = generate_operation_id("conf-res")

        assert op_ingest.startswith("ingest-")
        assert op_sync.startswith("sync-")
        assert op_conf.startswith("conf-res-")
        assert op_ingest != generate_operation_id("ingest")

    # 3. Audit Event Creation
    async def test_audit_event_creation(self, db_session: AsyncSession) -> None:
        repo = AuditRepository(db_session)
        event = await repo.log_event(
            event_type=AuditEventType.DOCUMENT_UPLOADED.value,
            description="Operational maintenance spec uploaded",
            entity_type="document",
            entity_id="doc-999",
            details={"file_size": 1024, "type": "pdf"},
            severity="info",
            request_id="req-abc",
            operation_id="ingest-xyz",
            device_id="edge-node-01",
        )
        await db_session.commit()

        assert event.id is not None
        assert event.event_type == AuditEventType.DOCUMENT_UPLOADED.value
        assert event.operation_id == "ingest-xyz"
        assert event.request_id == "req-abc"
        assert json.loads(event.details_json)["file_size"] == 1024

    # 4. Audit Immutability (SQLite Triggers & Repository Guardrails)
    async def test_audit_immutability(self, db_session: AsyncSession) -> None:
        repo = AuditRepository(db_session)
        event = await repo.log_event(
            event_type="IMMUTABLE_TEST",
            description="Original description",
            severity="info",
        )
        await db_session.commit()
        event_id = str(event.id)

        # Repository-level protection
        with pytest.raises(EdgewiseStorageError) as exc_update:
            await repo.update(event)
        assert "append-only" in str(exc_update.value)

        with pytest.raises(EdgewiseStorageError) as exc_del:
            await repo.delete(event_id)
        assert "append-only" in str(exc_del.value)

        from sqlalchemy.exc import IntegrityError

        # Database engine-level protection (SQLite Triggers)
        await install_audit_immutability(db_session)
        await db_session.commit()

        with pytest.raises((OperationalError, IntegrityError)) as db_exc_update:
            await db_session.execute(
                text(f"UPDATE audit_events SET description = 'tampered' WHERE id = '{event_id}'")
            )
        assert "immutable" in str(db_exc_update.value).lower()
        await db_session.rollback()

        with pytest.raises((OperationalError, IntegrityError)) as db_exc_delete:
            await db_session.execute(
                text(f"DELETE FROM audit_events WHERE id = '{event_id}'")
            )
        assert "immutable" in str(db_exc_delete.value).lower()
        await db_session.rollback()

    # 5. Audit Query & Pagination (GET /api/activity)
    async def test_audit_filtering_and_pagination(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        repo = AuditRepository(db_session)
        # Create a set of distinct events
        await repo.log_event(
            event_type=AuditEventType.DOCUMENT_UPLOADED.value,
            description="Doc 1 uploaded",
            entity_type="document",
            entity_id="doc-1",
            severity="info",
        )
        await repo.log_event(
            event_type=AuditEventType.DOCUMENT_FAILED.value,
            description="Doc 2 failed",
            entity_type="document",
            entity_id="doc-2",
            severity="error",
        )
        await repo.log_event(
            event_type=AuditEventType.SYNC_COMPLETED.value,
            description="Sync finished",
            entity_type="sync_run",
            severity="info",
        )
        await db_session.commit()

        # Filter by severity
        resp_err = await client.get("/api/activity?severity=error")
        assert resp_err.status_code == 200
        data_err = resp_err.json()
        assert data_err["total"] >= 1
        assert all(item["severity"] == "error" for item in data_err["items"])

        # Filter by entity type
        resp_doc = await client.get("/api/activity?entity_type=document")
        assert resp_doc.status_code == 200
        data_doc = resp_doc.json()
        assert data_doc["total"] >= 2
        assert all(item["entity_type"] == "document" for item in data_doc["items"])

        # Pagination test
        resp_paged = await client.get("/api/activity?page=1&page_size=1")
        assert resp_paged.status_code == 200
        data_paged = resp_paged.json()
        assert len(data_paged["items"]) == 1
        assert data_paged["page"] == 1
        assert data_paged["page_size"] == 1

    # 6. Sync Telemetry Separation (Queue, Remote, Total)
    async def test_sync_telemetry_separation(self, db_session: AsyncSession) -> None:
        repo = AuditRepository(db_session)
        telemetry = {
            "sync_run_id": "sync-run-001",
            "start_time": datetime.now(timezone.utc).isoformat(),
            "end_time": datetime.now(timezone.utc).isoformat(),
            "duration_ms": 145.2,
            "queue_time_ms": 25.1,
            "remote_operation_time_ms": 120.1,
            "total_sync_run_time_ms": 145.2,
            "records_attempted": 10,
            "uploaded": 8,
            "deleted": 1,
            "failed": 1,
            "conflicts": 0,
            "snapshot_status": "applied",
        }
        await repo.log_event(
            event_type=AuditEventType.SYNC_COMPLETED.value,
            description="Sync finished with separated telemetry",
            entity_type="sync_run",
            entity_id="sync-run-001",
            details=telemetry,
            operation_id="sync-run-001",
        )
        await db_session.commit()

        items, _ = await repo.query_events(event_type=AuditEventType.SYNC_COMPLETED.value)
        assert len(items) >= 1
        stored_details = json.loads(items[0].details_json)
        assert stored_details["queue_time_ms"] == 25.1
        assert stored_details["remote_operation_time_ms"] == 120.1
        assert stored_details["total_sync_run_time_ms"] == 145.2

    # 7. Ingestion Telemetry Recording
    async def test_ingestion_telemetry_recording(self, db_session: AsyncSession) -> None:
        repo = AuditRepository(db_session)
        telemetry = {
            "file_size": 24500,
            "document_type": "pdf",
            "extraction_duration_ms": 18.5,
            "chunking_duration_ms": 7.2,
            "embedding_duration_ms": 42.0,
            "edge_upsert_duration_ms": 14.1,
            "total_ingestion_duration_ms": 81.8,
            "chunk_count": 6,
            "embedding_count": 6,
            "operation_id": "ingest-test-77",
        }
        await repo.log_event(
            event_type=AuditEventType.DOCUMENT_PROCESSED.value,
            description="Doc processed with full timing breakdown",
            entity_type="document",
            entity_id="doc-77",
            details=telemetry,
            operation_id="ingest-test-77",
        )
        await db_session.commit()

        items, _ = await repo.query_events(entity_id="doc-77")
        assert len(items) == 1
        det = json.loads(items[0].details_json)
        assert det["extraction_duration_ms"] == 18.5
        assert det["chunking_duration_ms"] == 7.2
        assert det["embedding_duration_ms"] == 42.0
        assert det["edge_upsert_duration_ms"] == 14.1
        assert det["total_ingestion_duration_ms"] == 81.8

    # 8. RAG Latency Telemetry
    async def test_rag_latency_telemetry(self, client: AsyncClient) -> None:
        from app.services.rag.service import RAGResponse, RAGService

        mock_rag_result = RAGResponse(
            conversation_id="conv-obs-1",
            answer="Pressure within tolerance 120-140 PSI.",
            sources=[],
            retrieval_latency_ms=12.4,
            generation_latency_ms=58.2,
            total_latency_ms=75.1,
            embedding_latency_ms=4.5,
            offline_mode=True,
            model_used="qwen2.5:3b",
            chunk_count=3,
            source_count=1,
            top_retrieval_score=0.92,
            retrieval_threshold_applied=0.6,
            insufficient_evidence=False,
        )

        with patch.object(RAGService, "query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = mock_rag_result
            resp = await client.post(
                "/api/copilot/query",
                json={"question": "What is the pressure limit?", "conversation_id": "conv-obs-1"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["embedding_latency_ms"] == 4.5
            assert data["retrieval_latency_ms"] == 12.4
            assert data["generation_latency_ms"] == 58.2
            assert data["total_latency_ms"] == 75.1
            assert data["evidence"]["top_retrieval_score"] == 0.92
            assert data["offline_mode"] is True

    # 9. Health & System Connectivity Telemetry
    async def test_health_telemetry_fields(self, client: AsyncClient) -> None:
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "components" in data
        for c in data["components"]:
            assert "latency_ms" in c
            assert "consecutive_failures" in c

        conn_resp = await client.get("/system/connectivity")
        assert conn_resp.status_code == 200
        conn_data = conn_resp.json()
        assert "state" in conn_data
        assert "dependencies" in conn_data

    # 10. Metrics Endpoints (Prometheus & JSON)
    async def test_metrics_endpoints(self, client: AsyncClient) -> None:
        metrics = get_metrics_registry()
        metrics.inc_request("GET", "/health", 200)
        metrics.observe_request_duration("GET", "/health", 0.015)
        metrics.inc_ingestion("completed", 5)

        # Plaintext Prometheus format
        prom_resp = await client.get("/metrics")
        assert prom_resp.status_code == 200
        assert "text/plain" in prom_resp.headers["content-type"]
        body = prom_resp.text
        assert "edgewise_requests_total" in body
        assert "edgewise_chunks_ingested_total" in body

        # JSON format
        json_resp = await client.get("/api/metrics")
        assert json_resp.status_code == 200
        j_data = json_resp.json()
        assert "counters" in j_data
        assert "histograms" in j_data

    # 11. Security & Secret Redaction
    async def test_secret_redaction(self) -> None:
        # String secret values
        raw_secret_str = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.e30.secret"
        redacted_str = redact_sensitive_value(raw_secret_str)
        assert "Bearer [REDACTED]" in redacted_str
        assert "eyJhbGciOi" not in redacted_str

        # Inline API Key
        raw_key = "qdrant_api_key='sk-test-live-key-999'"
        assert "sk-test-live-key-999" not in redact_sensitive_value(raw_key)

        # Dictionary processor
        log_dict = {
            "request_id": "req-1",
            "qdrant_api_key": "secret-super-key",
            "authorization": "Bearer token-12345",
            "password": "mypassword",
            "message": "User login attempt",
            "document_content": "A" * 300,
            "vector": [0.1] * 128,
        }
        processed = redact_processor(None, "info", log_dict)
        assert processed["qdrant_api_key"] == "[REDACTED]"
        assert processed["authorization"] == "[REDACTED]"
        assert processed["password"] == "[REDACTED]"
        assert "[TRUNCATED" in str(processed["document_content"])
        assert "[VECTOR_DIM_128_TRUNCATED]" == processed["vector"]

    # 12. Standardized Error Taxonomy
    async def test_error_taxonomy_categorization(self) -> None:
        val_err = EdgewiseValidationError("Invalid schema parameter", details={"field": "size"})
        assert val_err.category == ErrorCategory.VALIDATION_ERROR
        assert val_err.status_code == 400
        assert val_err.retryable is False

        edge_err = EdgewiseEdgeError("Vector index corrupted")
        assert edge_err.category == ErrorCategory.EDGE_ERROR
        assert edge_err.status_code == 503
        assert edge_err.retryable is True

        conf_err = EdgewiseConflictError("Revision divergence")
        assert conf_err.category == ErrorCategory.CONFLICT_ERROR
        assert conf_err.status_code == 409
        assert conf_err.retryable is False

    # 13. End-to-End Trace Correlation
    async def test_e2e_trace_correlation(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        req_id = "trace-req-88"
        op_id = generate_operation_id("ingest")

        repo = AuditRepository(db_session)
        await repo.log_event(
            event_type=AuditEventType.DOCUMENT_UPLOADED.value,
            description="Doc traceable creation",
            entity_type="document",
            entity_id="doc-trace-88",
            request_id=req_id,
            operation_id=op_id,
        )
        await db_session.commit()

        resp = await client.get("/api/activity?entity_id=doc-trace-88")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 1
        item = data["items"][0]
        assert item["request_id"] == req_id
        assert item["operation_id"] == op_id

    # 14. Observability Under Failure Conditions
    async def test_failure_observability(self, client: AsyncClient) -> None:
        metrics = get_metrics_registry()
        initial_val_errors = metrics._counters.get('edgewise_errors_total{category="VALIDATION_ERROR"}', 0)

        # Trigger validation failure (422)
        resp = await client.post("/api/documents", files={"invalid": b""})
        assert resp.status_code == 422
        payload = resp.json()
        assert payload.get("category") == "VALIDATION_ERROR"
        assert "request_id" in payload

        new_val_errors = metrics._counters.get('edgewise_errors_total{category="VALIDATION_ERROR"}', 0)
        assert new_val_errors >= initial_val_errors + 1
