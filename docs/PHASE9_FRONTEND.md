# Phase 9: EDGEWISE AI Production Frontend Documentation

## 1. Executive Summary & Architecture Overview

The EDGEWISE AI Phase 9 frontend is an industrial-grade operations dashboard engineered specifically for offline-first edge deployment. Built with **React 19**, **TypeScript**, **Vite**, **Tailwind CSS v3**, **TanStack React Query v5**, and **React Router v7**, it communicates exclusively with real FastAPI backend endpoints and persistent SQLite / Qdrant Edge state.

No metrics, sync queues, conflict states, search results, or device counts are simulated or fabricated.

```
┌────────────────────────────────────────────────────────────────────────┐
│                        EDGE OPERATOR INTERFACE                         │
├───────────────────┬────────────────────────────────────────────────────┤
│                   │ Global Header: Node ID, Connectivity Badge, Modal │
│                   ├────────────────────────────────────────────────────┤
│   Side Navigation │ Main Content Viewport:                             │
│   - Dashboard     │ - Operations Metric Cards                          │
│   - AI Copilot    │ - Real-time Queue & Conflict Resolution Matrices   │
│   - Memory        │ - Document Pipeline & Chunks                       │
│   - Documents     │ - Audit Timelines & Device Topology                │
│   - Sync Center   ├────────────────────────────────────────────────────┤
│   - Conflicts     │ Reactive Query Pipeline (TanStack Query v5)        │
│   - Devices       │ Controlled Polling / Invalidation on Mutations     │
│   - Activity      ├────────────────────────────────────────────────────┤
│   - Settings      │ REST Client Layer (`/api/v1/*`, `/health`, etc.)   │
└───────────────────┴────────────────────────────────────────────────────┘
```

---

## 2. Directory Layout & Component Architecture

```
frontend/
├── index.html
├── package.json
├── vite.config.ts
├── tailwind.config.js
├── postcss.config.js
├── tsconfig.json
├── tsconfig.app.json
├── src/
│   ├── main.tsx                         # DOM entrypoint
│   ├── App.tsx                          # Router & React Query Client Provider
│   ├── index.css                        # Industrial theme tokens & utility classes
│   ├── types/
│   │   └── api.ts                       # Strictly typed FastAPI contracts & schemas
│   ├── services/
│   │   └── api.ts                       # Centralized fetch wrapper & typed endpoints
│   ├── components/
│   │   ├── layout/
│   │   │   ├── AppLayout.tsx            # Shell with sidebar, topbar, and mobile drawer
│   │   │   ├── Sidebar.tsx              # Operations navigation bar
│   │   │   └── Topbar.tsx               # Node identity & system health connectivity trigger
│   │   ├── common/
│   │   │   ├── StatusBadge.tsx          # Industrial color-coded badge component
│   │   │   ├── MetricCard.tsx           # Telemetry metric widget with pulse loaders
│   │   │   ├── SearchBar.tsx            # Debounced accessible search input
│   │   │   ├── FilterBar.tsx            # Multi-facet filter toggle bar
│   │   │   ├── Pagination.tsx           # Controlled cursor pagination
│   │   │   ├── EmptyState.tsx           # Empty state with actionable cues
│   │   │   ├── ErrorState.tsx           # Error callout with retry action
│   │   │   ├── LoadingState.tsx         # Inline pulse loader
│   │   │   ├── ConfirmDialog.tsx        # Accessible action confirmation modal
│   │   │   └── Toast.tsx                # Contextual operator notification
│   │   └── system/
│   │       └── DependencyHealthModal.tsx # Detailed subsystem isolation inspection
│   ├── pages/
│   │   ├── DashboardPage.tsx            # Operational telemetry & subsystem overview
│   │   ├── CopilotPage.tsx              # Grounded RAG chat & verifiable source modal
│   │   ├── MemoryPage.tsx               # Edge memory explorer & pagination
│   │   ├── DocumentsPage.tsx            # Ingestion pipeline, quotas & chunk inspection
│   │   ├── SyncPage.tsx                 # Durable queue inspector & manual sync trigger
│   │   ├── ConflictsPage.tsx            # 3-way conflict diffing & heuristic resolution
│   │   ├── DevicesPage.tsx              # Edge cluster topology & telemetry
│   │   ├── ActivityPage.tsx             # System audit & operational event log
│   │   └── SettingsPage.tsx             # Local node diagnostics (zero secrets)
│   └── test/
│       ├── setup.ts                     # Jest DOM & vitest setup
│       ├── unit_components.test.tsx     # Atomic component unit tests
│       └── app_flows.test.tsx           # End-to-end integration flow tests
```

---

## 3. Operational Routes & Capabilities

| Route | Page | Purpose |
|---|---|---|
| `/` | `DashboardPage` | Real edge metrics: mutable/immutable vector points, pending sync queue, conflicts count, local vs. cloud status. |
| `/copilot` | `CopilotPage` | Grounded local RAG inquiry with citation cards, score confidence, chunk modals, and hallucination warnings. |
| `/memory` | `MemoryPage` | SQLite + Qdrant Edge memory browser with sensitivity filters, revisions, and sync indicators. |
| `/documents` | `DocumentsPage` | Document upload, file size validation, chunk distribution, and ingestion error handling. |
| `/sync` | `SyncPage` | Durable SQLite sync queue manager, retry counters, item details modal, and live `SYNC NOW` action. |
| `/conflicts` | `ConflictsPage` | Side-by-side local vs. cloud diff viewer, audit history, and Keep Local / Keep Cloud / Suggested Merge actions. |
| `/devices` | `DevicesPage` | Edge node cluster registry, site locations, sync state, and heartbeat tracking. |
| `/activity` | `ActivityPage` | Chronological audit log with severity filtering (INFO, WARNING, ERROR, CRITICAL). |
| `/settings` | `SettingsPage` | Device identification, embedding models, Qdrant Edge paths, with strict secret masking. |

---

## 4. Backend API Endpoints Consumed

All data bindings connect directly to real FastAPI endpoints:

| Subsystem | Method & Endpoint | Response Model |
|---|---|---|
| **Connectivity** | `GET /system/connectivity` | `ConnectivityStatusResponse` |
| **Health** | `GET /health` | `HealthCheckResponse` |
| **Dashboard** | `GET /api/dashboard/metrics` | `DashboardMetricsResponse` |
| **Copilot** | `POST /api/copilot/query`<br>`GET /api/copilot/conversations` | `CopilotQueryResponse`<br>`ConversationListResponse` |
| **Memory** | `GET /api/memory` | `MemoryListResponse` |
| **Documents** | `GET /api/documents`<br>`POST /api/documents` | `DocumentListResponse`<br>`DocumentResponse` |
| **Sync** | `GET /api/sync/status`<br>`GET /api/sync/queue`<br>`GET /api/sync/history`<br>`POST /api/sync/run` | `SyncStatusResponse`<br>`SyncQueueListResponse`<br>`SyncHistoryResponse`<br>`SyncResultResponse` |
| **Conflicts** | `GET /api/conflicts`<br>`GET /api/conflicts/{id}`<br>`POST /api/conflicts/{id}/resolve` | `ConflictListResponse`<br>`ConflictDetailResponse`<br>`ConflictResolveResponse` |
| **Devices** | `GET /api/devices` | `DeviceListResponse` |
| **Activity** | `GET /api/activity` | `ActivityListResponse` |

---

## 5. Connectivity & Offline UX

The interface executes state evaluation without simulated timers:
- **`ONLINE`**: Internet, SQLite, Qdrant Edge, Ollama, and Qdrant Server all report healthy.
- **`DEGRADED`**: Cloud Qdrant Server is unreachable, but local AI services (SQLite, Qdrant Edge, Ollama) remain operational. A non-intrusive warning header appears: *"Cloud synchronization unavailable. Local AI remains operational."*
- **`OFFLINE`**: Network is completely disconnected. The operator can still run local RAG queries, view documents, browse memory, and record changes. Mutations are enqueued to the durable SQLite queue.
- **`SYNCING`**: Active synchronization cycle in progress.

Clicking the connectivity badge in the top bar opens the **Dependency Health Modal**, showing the isolated status, latency, and endpoint of each subsystem:
- SQLite Database
- Qdrant Edge Local Store
- Ollama LLM Runtime
- Internet Connectivity
- Cloud Qdrant Server

---

## 6. Security & Secret Isolation

Strict operational safety rules are enforced:
1. **Zero Secret Exposure**: `.env` files, API keys, Bearer tokens, authorization headers, and secrets are strictly excluded from frontend state, DOM, and bundle.
2. **Safe Rendering**: All text chunks, document contents, and LLM responses are escaped as safe React string children. No `dangerouslySetInnerHTML` is used.
3. **Internal Path Masking**: Host filesystem paths are never displayed; clean API entity identifiers and filenames are used throughout.

---

## 7. Verification & Test Suite Summary

### Frontend Unit & Component Tests
`frontend/src/test/unit_components.test.tsx` (12 tests)
- `StatusBadge` styling and status variants
- `MetricCard` skeleton pulse and value formatting
- `SearchBar` debounce and clear callback
- `Pagination` page navigation boundaries and disability states
- `ConfirmDialog` modal presentation, confirmation, and cancellation triggers

### Frontend End-to-End Operational Flows
`frontend/src/test/app_flows.test.tsx` (9 tests)
1. **Dashboard Flow**: Loads real dashboard metrics and telemetry counters.
2. **Connectivity Flow**: Validates degraded/offline status transitions and warnings.
3. **Copilot Flow**: Submits inquiry, validates grounded citation cards, and opens evidence modal.
4. **Documents Flow**: Lists documents and displays accurate error callout on upload rejection.
5. **Memory Flow**: Filters memory records and tests cursor pagination.
6. **Sync Flow**: Displays pending queue items and triggers `POST /api/sync/run`.
7. **Conflict Flow**: Side-by-side diffing and resolution via Keep Local / Keep Cloud / Suggested Merge.
8. **Stale Concurrency (HTTP 409)**: Gracefully detects concurrent edits and prompts operator reload.
9. **Topology & Settings**: Inspects device cluster and verifies complete absence of secrets.

**Total Vitest Tests**: 21 passed (2 test suites, 0 failures).

### Backend Regression Tests
- `backend/tests/unit/test_phase5_offline_first.py`
- `backend/tests/unit/test_phase6_durable_sync.py`
- `backend/tests/unit/test_phase7_real_sync.py`
- `backend/tests/unit/test_phase8_conflict_resolution.py`

**Total Pytest Tests**: 70 passed in 116s (0 failures).
