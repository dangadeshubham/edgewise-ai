# EDGEWISE AI — Phase 5: Offline-First Runtime

## Overview

Phase 5 converts the EDGEWISE AI platform from a local RAG implementation into a
genuinely **offline-first** application at the application architecture level.

> **Phase 5 is NOT cloud synchronization.**
> Cloud synchronization remains Phase 6/7. No conflict resolution is implemented.

## What Was Implemented

### 1. Connectivity Manager (State Machine)

A real connectivity state machine that independently tracks each dependency:

| Dependency      | What It Monitors                    | Required for Offline? |
|-----------------|-------------------------------------|----------------------|
| **SQLite**      | Local database via `SELECT 1`       | **YES** (critical)    |
| **Qdrant Edge** | Local vector shard health           | YES (search)          |
| **Ollama**      | LLM API + model availability        | No (search works without it) |
| **Internet**    | Public endpoint probe               | No                    |
| **Qdrant Server** | Cloud vector DB health            | No                    |

**States:**
- `ONLINE` — all dependencies available
- `OFFLINE` — internet unavailable, local stack works
- `DEGRADED` — some dependencies impaired
- `SYNC_PENDING` — local changes awaiting future sync (Phase 6)
- `SYNCING` — active synchronization (Phase 6+)

**Key principle:** `internet unavailable` ≠ `everything unavailable`.

### 2. Offline-First Principle

Core local functionality works without internet, Qdrant Server, or cloud APIs:
- ✅ Local documents remain usable
- ✅ Local search remains usable
- ✅ Local RAG remains usable
- ✅ Local memories can be created
- ✅ Local metadata changes persist
- ✅ Application remains usable

### 3. Failure Isolation

| Scenario | Result |
|----------|--------|
| Qdrant Server unreachable | SQLite + Qdrant Edge + Ollama continue working |
| Ollama unavailable | Search still works, Copilot reports dependency error |
| Internet unavailable | Local AI still works |
| Qdrant Edge unavailable | Reports semantic search dependency error |
| SQLite unavailable | Reports storage failure — app NOT operational |

### 4. Connectivity Events

Real events are persisted:
- `DEVICE_ONLINE` — internet connectivity restored
- `DEVICE_OFFLINE` — internet connectivity lost
- `DEPENDENCY_DEGRADED` — a dependency became unavailable
- `DEPENDENCY_RECOVERED` — a dependency recovered
- `STATE_CHANGED` — top-level state transition

No fake events are generated.

### 5. LocalWriteService

Clean abstraction for all local knowledge writes:

1. **Validate** — content, type, length
2. **Persist to SQLite** — memory record
3. **Write to Qdrant Edge** — vector embedding
4. **Create sync metadata** — SyncItem for Phase 6
5. **Create audit event** — immutable trail

### 6. Offline Document Ingestion

Verified pipeline with zero cloud dependency:
```
UPLOAD → EXTRACT → CHUNK → EMBED → QDRANT EDGE → READY
```

### 7. Offline Copilot

Verified pipeline with zero cloud dependency:
```
Question → local embedding → Qdrant Edge retrieval → local Ollama → grounded answer → real citations
```

### 8. API Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /system/connectivity` | Per-dependency status with state machine |
| `GET /health` | Component health with latency measurements |
| `GET /health/ready` | Kubernetes readiness (SQLite + Edge + Embedding) |
| `GET /health/live` | Kubernetes liveness (always alive) |
| `POST /api/memory` | Create memory via LocalWriteService |
| `GET /api/memory` | List memory records with filtering |
| `DELETE /api/memory/{id}` | Soft-delete with Edge cleanup |

### 9. UI System Status Indicator

The Copilot interface now shows:
- **ONLINE** (green dot) — all systems operational
- **OFFLINE** (amber dot) — "Local AI Available" instead of misleading "Connected"
- **DEGRADED** (red dot) — check dependencies

Expandable panel shows per-dependency status.

### 10. Model Configurability

The Ollama model is configurable via `OLLAMA_MODEL` environment variable,
allowing smaller models for edge devices without code changes.

## File Changes

### New Files
- `app/services/connectivity/manager.py` — Connectivity state machine
- `app/services/local_write/service.py` — LocalWriteService
- `app/services/local_write/__init__.py` — Package init
- `tests/unit/test_phase5_offline_first.py` — 32 test cases

### Modified Files
- `app/services/connectivity/service.py` — Delegates to ConnectivityManager
- `app/services/connectivity/__init__.py` — Exports manager types
- `app/services/health/service.py` — Offline-first health logic
- `app/api/v1/health.py` — Updated connectivity endpoint
- `app/api/v1/memory.py` — Full implementation (was 501 stubs)
- `app/schemas/api.py` — ConnectivityResponse with per-dependency status
- `app/core/config.py` — Added SYNC_PENDING state
- `app/main.py` — ConnectivityManager lifecycle + background polling
- `frontend/index.html` — System status indicator
- `frontend/copilot.js` — Connectivity polling + status panel
- `frontend/style.css` — Status indicator styles

## Phase Roadmap (Corrected Terminology)

| Phase | Description | Status |
|-------|-------------|--------|
| Phase 1-3 | SQLite + Qdrant Edge + Embeddings + Ingestion | ✅ Complete |
| Phase 4 | Local RAG + Ollama + Citations + Conversations | ✅ Complete |
| **Phase 5** | **Offline-first runtime** | ✅ **Complete** |
| Phase 6 | Durable synchronization queue | ⏳ Not started |
| Phase 7 | Qdrant Edge ↔ Server synchronization | ⏳ Not started |
| Phase 8 | Conflict resolution | ⏳ Not started |

## Remaining Limitations

1. **No cloud synchronization** — sync metadata is created but not processed
2. **No conflict resolution** — conflicts are modeled but not resolved
3. **No latency benchmarks** — model configurability added but no claims
4. **Connectivity polling is periodic** — 30-second intervals, not push-based
5. **No WebSocket** for real-time status — uses polling from frontend

## Test Results

```
32 passed in 48.70s

Tests:
- Connectivity state determination (9 tests)
- Dependency isolation failure matrix (5 tests)
- Connectivity events (4 tests)
- Connectivity status export (2 tests)
- LocalWriteService write path (5 tests)
- Health API accuracy (4 tests)
- Memory API (3 tests)
```
