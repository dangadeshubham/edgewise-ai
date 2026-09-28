# Phase 10: Production Observability & Audit Telemetry

## 1. Overview

Phase 10 equips **EDGEWISE AI** with an enterprise-grade, privacy-conscious, and production-ready observability architecture. The system provides complete traceability from incoming HTTP requests to deep local operations (embedding, Qdrant Edge storage, RAG generation, durable synchronization, and conflict resolution) without leaking user data, embeddings, or authorization secrets.

---

## 2. Structured Logging & Secret Redaction

Logging is implemented via structlog and python logging in `backend/app/core/logging.py`.

### 2.1 Sensitive Key Sanitization
All logger processors intercept dictionaries and key-value pairs before serialization. The following keys are masked automatically with `[REDACTED]`:
- `password`, `token`, `secret`, `api_key`, `qdrant_api_key`, `access_token`, `refresh_token`, `authorization`, `private_key`

### 2.2 Bearer & JWT Regex Masking
Any message or string payload containing `Bearer <token>` or JWT patterns (`eyJ...`) is automatically rewritten to:
```
Bearer [REDACTED]
```

### 2.3 Vector & Payload Truncation
Embedding vectors and large document contents are never dumped raw to logs:
- Arrays of floats (embeddings) are detected and replaced with `[VECTOR_DIM_<dim>_TRUNCATED]`.
- Long document or payload strings are capped at 150 characters with `... [TRUNCATED]`.

---

## 3. Correlation Identifiers

Every operation within Edgewise AI is traceable via standardized UUIDv4 correlation identifiers:

- **Request ID (`X-Request-ID`)**: Generated or extracted at the HTTP perimeter by `backend/app/main.py`. Attached to every log line, response header, and audit record.
- **Operation ID**: Scoped to background and multi-stage workflows (e.g., ingestion pipeline, sync daemon batches, conflict resolutions).
- **Correlation Chain**:
  $$\text{Request ID} \longrightarrow \text{Operation ID} \longrightarrow \text{Audit Event ID}$$

---

## 4. Append-Only Audit Trail & SQLite Immutability

Audit events are stored in the SQLite `audit_events` table using canonical types defined in `backend/app/core/audit.py`.

### 4.1 Canonical Audit Event Types
- **Documents**: `DOCUMENT_UPLOADED`, `DOCUMENT_PROCESSED`, `DOCUMENT_FAILED`, `DOCUMENT_DELETED`, `DOCUMENT_REINDEXED`
- **Memory**: `MEMORY_CREATED`, `MEMORY_UPDATED`, `MEMORY_DELETED`
- **Devices**: `DEVICE_REGISTERED`, `DEVICE_UPDATED`
- **Connectivity**: `CONNECTIVITY_OFFLINE`, `CONNECTIVITY_ONLINE`, `DEPENDENCY_DEGRADED`, `DEPENDENCY_RECOVERED`
- **Synchronization**: `SYNC_STARTED`, `SYNC_UPLOAD_SUCCESS`, `SYNC_UPLOAD_FAILED`, `SYNC_DELETE_SUCCESS`, `SYNC_SNAPSHOT_STARTED`, `SYNC_SNAPSHOT_COMPLETED`, `SYNC_COMPLETED`
- **Conflicts**: `CONFLICT_DETECTED`, `CONFLICT_CLAIMED`, `CONFLICT_KEEP_LOCAL`, `CONFLICT_KEEP_CLOUD`, `CONFLICT_MERGED`, `CONFLICT_MANUAL`, `CONFLICT_DISMISSED`, `CONFLICT_RESOLVED`

### 4.2 SQLite Immutability Triggers
To enforce absolute non-repudiation and prevent tampering, SQLite triggers are installed via `backend/app/core/database.py`:
- `trg_audit_events_prevent_update`: Blocks any `UPDATE` statements on `audit_events`.
- `trg_audit_events_prevent_delete`: Blocks any `DELETE` statements on `audit_events`.
Attempting either operation raises `sqlite3.IntegrityError: Audit events are strictly append-only and immutable`.

### 4.3 Query Endpoint
Filtered querying is exposed via `GET /api/activity`:
- Supports filtering by `event_type`, `entity_type`, `entity_id`, `device_id`, `severity`, `start_date`, and `end_date`.
- Supports cursor/offset pagination (`page`, `page_size`).

---

## 5. Separated Telemetry & Metrics

### 5.1 Synchronization Subsystem
Sync telemetry cleanly partitions network latency from local queue delays:
- `queue_time_ms`: Time spent waiting in the durable queue prior to pickup.
- `remote_operation_time_ms`: Exact duration of remote Qdrant / Cloud API calls.
- `total_sync_run_time_ms`: End-to-end sync cycle execution time.
- `records_attempted`, `records_succeeded`, `records_failed`, `snapshot_status`.

### 5.2 Document Ingestion Pipeline
Ingestion phase timings are measured independently:
- `extraction_duration_ms`: Text extraction from file.
- `chunking_duration_ms`: Text splitting into semantic chunks.
- `embedding_duration_ms`: Ollama / embedding model latency.
- `edge_upsert_duration_ms`: Qdrant Edge local storage upsert.
- `total_ingestion_duration_ms`: Complete pipeline wall-clock time.

### 5.3 Local RAG Pipeline
RAG telemetry breaks down query lifecycle:
- `embedding_duration_ms`: Question vectorization.
- `retrieval_duration_ms`: Qdrant Edge vector search and score threshold filtering.
- `generation_duration_ms`: Ollama LLM context processing and streaming.
- `total_rag_duration_ms`: Total latency.
- `chunks_retrieved`, `sources_cited`, `confidence_score`.

### 5.4 Prometheus & JSON Metrics Endpoints
- `GET /metrics`: Standard Prometheus text exposition format (counters, gauges, histograms).
- `GET /api/metrics`: JSON summary format for dashboard consumption.

---

## 6. Standardized Error Taxonomy

Defined in `backend/app/core/errors.py`:

| Error Category | HTTP Code | Description |
|---|---|---|
| `VALIDATION_ERROR` | 422 | Schema or parameter validation failures |
| `STORAGE_ERROR` | 500 | SQLite or local disk persistence errors |
| `EMBEDDING_ERROR` | 502 | Local embedding generation failure |
| `EDGE_ERROR` | 500 | Qdrant Edge local vector storage errors |
| `OLLAMA_ERROR` | 502 | Ollama daemon failure or model unavailable |
| `NETWORK_ERROR` | 503 | Local network offline / probe unreachable |
| `REMOTE_ERROR` | 502 | Cloud Qdrant Server remote failure |
| `SYNC_ERROR` | 500 | Durable sync queue processing failure |
| `CONFLICT_ERROR` | 409 | Document or memory state conflict |
| `AUTHENTICATION_ERROR` | 401 | Missing or invalid authentication token |
| `RATE_LIMIT_ERROR` | 429 | Rate limit exceeded |
| `TIMEOUT_ERROR` | 504 | Operation timed out |

All API exceptions return standardized responses with error code, message, category, request ID, and timestamp.

---

## 7. Verified Test Suites & Quality Audit

### 7.1 Backend Test Suite (Pytest)
Command:
```bash
.venv\Scripts\python.exe -m pytest tests/unit/test_phase5_offline_first.py tests/unit/test_phase6_durable_sync.py tests/unit/test_phase7_real_sync.py tests/unit/test_phase8_conflict_resolution.py tests/unit/test_phase10_observability.py -v
```

- **Collected**: 84 tests
- **Passed**: 84 tests
- **Failed**: 0
- **Skipped**: 0
- **Warnings**: 2 (Qdrant client-server version compatibility checks in `test_section_27_cloud_to_edge_sync`)
- **Execution Time**: ~66.42s

#### Module Breakdown
| Test File | Phase Focus | Test Count | Status |
|---|---|---|---|
| `tests/unit/test_phase5_offline_first.py` | Phase 5: Offline-First Runtime & Connectivity Manager | 32 | PASSED (32/32) |
| `tests/unit/test_phase6_durable_sync.py` | Phase 6: Durable Sync Queue & State Machine | 20 | PASSED (20/20) |
| `tests/unit/test_phase7_real_sync.py` | Phase 7: Real Edge ↔ Cloud Synchronization | 9 | PASSED (9/9) |
| `tests/unit/test_phase8_conflict_resolution.py` | Phase 8: Conflict Detection & Resolution | 9 | PASSED (9/9) |
| `tests/unit/test_phase10_observability.py` | Phase 10: Observability, Metrics & Immutability | 14 | PASSED (14/14) |
| **Total** | | **84** | **PASSED (84/84)** |

### 7.2 Frontend Test Suite (Vitest)
Command:
```bash
npx vitest run
```

- **Test Files**: 2 passed (2)
- **Tests**: 21 passed (21)
- **Failed**: 0
- **Skipped**: 0

#### Suite Breakdown
| Test File | Test Suite Focus | Test Count | Status |
|---|---|---|---|
| `frontend/src/test/unit_components.test.tsx` | UI Component State, Status Badges & Navigation | 12 | PASSED (12/12) |
| `frontend/src/test/app_flows.test.tsx` | End-to-End Operational Flows & Sync Triggering | 9 | PASSED (9/9) |
| **Total** | | **21** | **PASSED (21/21)** |

