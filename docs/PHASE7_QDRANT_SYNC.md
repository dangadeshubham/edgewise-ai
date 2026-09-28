# EDGEWISE AI — Phase 7: Real Qdrant Edge ↔ Cloud Synchronization

## 1. Overview & System Versions

Phase 7 implements real, bidirectional synchronization between the embedded **Qdrant Edge** engine on local terminals and the remote **Qdrant Server** cluster.

### Verified Production Environment
| Component | Verified Package / Binary Version | Role |
|---|---|---|
| **Qdrant Server** | `1.19.1` (build `6ab21cac`) | Remote cloud vector store & snapshot coordinator |
| **qdrant-client** | `1.19.1` | Python REST / gRPC client with async support |
| **qdrant_edge** | Embedded native binary engine | Local mutable & immutable shard vector storage |
| **Sentence-Transformers** | `all-MiniLM-L6-v2` (dim=384) | Local embedding generation |
| **SQLite (aiosqlite)** | SQLite 3 | Relational metadata, queue state, and conflict tracking |

---

## 2. Bidirectional Synchronization Architecture

```
                  ┌──────────────────────────────────────────────┐
                  │              QDRANT SERVER                   │
                  │   - Collection: edgewise-knowledge           │
                  │   - Vector dimension: 384 (Cosine)           │
                  │   - Snapshots API: /collections/{col}/...    │
                  └───────────────▲──────────────┬───────────────┘
                                  │              │
                   Edge → Cloud   │              │ Cloud → Edge
                   Vector Upsert  │              │ Shard Ingestion
                   & Delete Sync  │              │ & Snapshot Pull
                                  │              │
    ┌─────────────────────────────┼──────────────▼────────────────────────────┐
    │ EDGEWISE RUNTIME            │                                           │
    │                             │                                           │
    │  [Local Write]              │                                           │
    │        │                    │                                           │
    │        ▼                    │                                           │
    │  [SQLite SyncItem] ──► [SyncEngine] ──► [QdrantServerSyncBackend]       │
    │  (status=PENDING)         (Claim)               (REST HTTP/2)           │
    │                                                                         │
    │  [SYNCHRONIZATION BARRIER]                                              │
    │  ┌───────────────────────────────────────────────────────────────────┐  │
    │  │ 1. PREPARE_SYNC (Lock acquired)                                   │  │
    │  │ 2. DRAIN_LOCAL_UPLOADS (Push all pending items)                   │  │
    │  │ 3. OBTAIN_SERVER_DATA (Fetch points / create snapshot)            │  │
    │  │ 4. APPLY_IMMUTABLE (Rebuild local immutable shard)                │  │
    │  │ 5. VERIFY_IMMUTABLE (Verify point retrieval & indexing)           │  │
    │  │ 6. MUTABLE CLEANUP (Purge only verified duplicate points)         │  │
    │  │ 7. RESUME_NORMAL (Release barrier lock)                           │  │
    │  └───────────────────────────────────────────────────────────────────┘  │
    │                                                                         │
    │  [Local Shards]                                                         │
    │     ├──► [Mutable Shard]   (Local writes, uncommitted changes)          │
    │     └──► [Immutable Shard] (Server-synchronized baseline)               │
    │                 │                                                       │
    │                 ▼                                                       │
    │       [Unified Local Search] (Merge, deduplicate by point ID, rank)     │
    └─────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Edge → Cloud Flow (Local Changes to Server)

1. **Local Mutation**: `LocalWriteService` writes to SQLite `MemoryRecord`, indexes the vector into the local mutable shard, and creates a `SyncItem(status="pending")`.
2. **Batch Claiming**: `SyncEngine` claims eligible items atomically using `SyncQueueService.claim_pending()`.
3. **Smart Placement Check**: The backend inspects record sensitivity:
   - If sensitivity is in `LOCAL_ONLY_SENSITIVITIES` (`confidential`, `restricted`), remote sync is skipped, and the item is marked as local-only with an audit event.
4. **Deterministic Point IDs**: Point IDs are deterministically derived via `generate_point_id_from_chunk_id(record_id)` (matching Phase 3 UUID namespaces). Retries always address the identical remote point ID.
5. **Remote Upsert**: `AsyncQdrantClient.upsert()` transfers the 384-dimensional dense vector and structured metadata payload to Qdrant Server.
6. **Remote Verification**: `AsyncQdrantClient.retrieve()` verifies point existence on Qdrant Server before completion acknowledgement.
7. **Commit & Telemetry**: `SyncItem` is updated to `SYNCED`, and a detailed `SyncAttempt` record is written to SQLite.

---

## 4. Cloud → Edge Flow (Server State to Local Engine)

1. **Snapshot / Point Polling**: `QdrantServerSyncBackend.fetch_server_points()` or `create_snapshot()` pulls the remote collection state.
2. **Immutable Shard Recreation**: `EdgeMemoryService.init_immutable_shard()` creates or refreshes the clean immutable segment directory.
3. **Point Ingestion**: Server vectors and payloads are ingested into the immutable shard with native BM25 sparse index generation.
4. **Flush & Verification**: `EdgeMemoryService.flush("immutable")` writes WAL to disk. `is_healthy("immutable")` confirms point index readability.
5. **Unified Search Path**: `LocalMemorySearch` immediately queries both mutable and immutable shards, returning deduplicated results ordered by similarity score.

---

## 5. Synchronization Barrier Protocol

To ensure consistency during immutable shard recreation, `EdgeCloudSyncService` enforces an asynchronous barrier lock (`_SYNC_BARRIER_LOCK`):

| Phase | Barrier State | Action |
|---|---|---|
| 1 | `PREPARE_SYNC` | Acquire barrier lock; pause background shard modifications. |
| 2 | `DRAIN_LOCAL_UPLOADS` | Execute pending batch uploads to Qdrant Server. |
| 3 | `OBTAIN_SERVER_DATA` | Fetch remote points or trigger server snapshot. |
| 4 | `APPLY_IMMUTABLE` | Reconstruct immutable shard on disk. |
| 5 | `VERIFY_IMMUTABLE` | Query immutable shard to ensure integrity. |
| 6 | `MUTABLE_CLEANUP` | Remove verified synced points from mutable shard. |
| 7 | `NORMAL` | Release barrier lock; resume standard operations. |

---

## 6. Mutable Shard Cleanup (Data Loss Prevention Priority)

To avoid data loss, a vector is **never** purged from the mutable shard simply because an HTTP upload succeeded. A point is only removed if:
1. `SyncItem.status == 'synced'` (Qdrant Server accepted and verified).
2. The point is positively retrieved and verified in the newly rebuilt **immutable shard**.
3. The synchronization barrier successfully passed.

---

## 7. Cloud-to-Edge Conflict Detection

Reconciliation detects and classifies discrepancies:
- `NO_CHANGE`: Local revision and content hash match remote values.
- `LOCAL_NEWER`: Local revision > remote revision; local edits take precedence.
- `REMOTE_NEWER`: Remote revision > local revision and local has no uncommitted edits; local record is safely fast-forwarded.
- `CONFLICT`: Independent local and remote edits with diverging content hashes.
  - A persistent `Conflict` record is created in SQLite (`conflicts` table).
  - Both local and remote metadata are preserved without loss.
  - Local `MemoryRecord` is marked `sync_status = "conflict"`.

---

## 8. Delete & Tombstone Semantics

- Soft-deleting a record removes the vector from the mutable shard and enqueues a `SyncItem(operation="delete")`.
- When synchronized, `QdrantServerSyncBackend.delete()` removes the point from Qdrant Server.
- Cloud → Edge sync ensures that deleted points cannot be resurrected from older snapshots.

---

## 9. Security & Secrets Management

- **No Secrets in Code or UI**: `QDRANT_API_KEY` is loaded exclusively from environment variables or `.env`.
- **Sanitized Payloads**: Sensitive keys (ending in `_token`, `_secret`, `_password`, `_key`) are stripped from payloads prior to enqueueing.
- **Log Masking**: API keys and tokens are automatically masked as `[REDACTED]` in error logging.
