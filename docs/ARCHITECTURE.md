# EDGEWISE AI — System Architecture & Data Flows

## 1. System Topology & Component Hierarchy

EDGEWISE AI operates as an autonomous, single-tenant industrial edge appliance designed to function indefinitely without cloud connectivity. When network connectivity is established, bidirectional synchronization aligns local edge knowledge with a central Qdrant Server cluster.

```
┌────────────────────────────────────────────────────────────────────────┐
│                              EDGE DEVICE                               │
│                                                                        │
│   ┌──────────────────────────────────────────────────────────────┐     │
│   │                     React 19 SPA Frontend                    │     │
│   │       (Vite, Tailwind CSS, Lucide, Recharts, TanStack Query) │     │
│   └──────────────────────────────┬───────────────────────────────┘     │
│                                  │ HTTP / SSE                          │
│                                  ▼                                     │
│   ┌──────────────────────────────────────────────────────────────┐     │
│   │                     FastAPI Backend Core                     │     │
│   │       - Ingestion & Text Processing                          │     │
│   │       - Local Grounded Copilot RAG Subsystem                 │     │
│   │       - Durable SQLite Sync Queue & Worker                   │     │
│   │       - Granular Diff & Conflict Resolution Engine           │     │
│   │       - Sliding-Window Security Rate Limiters & Auth         │     │
│   └───┬──────────────────────────┬───────────────────────────┬───┘     │
│       │                          │                           │         │
│       ▼                          ▼                           ▼         │
│ ┌───────────┐      ┌───────────────────────────┐      ┌──────────────┐ │
│ │  SQLite   │      │        Qdrant Edge        │      │    Ollama    │ │
│ │ Database  │      │     (`qdrant-edge-py`)    │      │  Host Daemon │ │
│ │           │      │ ┌───────────────────────┐ │      │              │ │
│ │ - Relational│     │ │     Mutable Shard     │ │      │ - Llama 3 8B │ │
│ │   Metadata │     │ │ (Local Writes/Pending)│ │      │ - Qwen 2.5   │ │
│ │ - Durable │      │ └───────────────────────┘ │      │ - Mistral 7B │ │
│ │   Queue   │      │ ┌───────────────────────┐ │      │              │ │
│ │ - Immutable│     │ │    Immutable Shard    │ │      │ (Local GGUF  │ │
│ │   Audit   │      │ │  (Promoted Cloud Data)│ │      │  Inference)  │ │
│ └───────────┘      │ └───────────────────────┘ │      └──────────────┘ │
│                    └─────────────┬─────────────┘                       │
└──────────────────────────────────┼─────────────────────────────────────┘
                                   │
                                   │ Bidirectional Partial Snapshot Sync
                                   │ (REST / gRPC over HTTP)
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│                              CLOUD TIER                                │
│                                                                        │
│                    ┌───────────────────────────┐                       │
│                    │       Qdrant Server       │                       │
│                    │   (Central Distributed    │                       │
│                    │    Knowledge Cluster)     │                       │
│                    └───────────────────────────┘                       │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Document Ingestion Flow

The ingestion pipeline transforms raw unstructured industrial manuals, incident logs, and SOPs into dense and sparse searchable vectors:

```
[Raw Document (.pdf, .docx, .txt, .md)]
                │
                ▼
      [FileValidator]
      - Path traversal neutralization
      - MIME/Magic-byte verification
      - Size check (max 50 MB)
      - Decompression bomb protection
                │
                ▼
      [Text Extraction & Cleaning]
      - Header/footer artifact stripping
      - Normalization & Unicode canonicalization
                │
                ▼
      [Recursive Chunking]
      - 512-token chunks with 64-token overlap
      - Structural preservation of tables & lists
                │
                ▼
      [SentenceTransformers]
      - `all-MiniLM-L6-v2` dense embedding (384 dimensions)
      - Native BM25 sparse token analysis
                │
                ▼
      [Storage Commit]
      ├── 1. SQLite: Document metadata & MemoryRecord (sync_status='pending')
      ├── 2. Qdrant Edge: Insert into Mutable Shard WAL
      └── 3. Durable Sync Queue: Enqueue SyncItem (operation='UPSERT')
```

---

## 3. Local Search Flow

Edge searches execute strictly on-device with zero external network requests:

```
[User Search Query]
        │
        ▼
[Embedding Service] -> Generate 384-d dense vector + BM25 sparse query
        │
        ▼
[LocalMemorySearch Engine]
        ├── 1. Query Mutable Shard (Local recent writes)
        └── 2. Query Immutable Shard (Cloud-synced reference data)
        │
        ▼
[Score Fusion & Deduplication]
        - Reciprocal Rank Fusion (RRF) / Cosine similarity
        - Deduplicate overlapping chunks by logical chunk identifier
        │
        ▼
[Payload Metadata Filtering]
        - Filter by device_id, sensitivity, document_type
        │
        ▼
[Ranked Results + Latency Telemetry] -> Return to Frontend SPA (< 20 ms)
```

---

## 4. Grounded RAG Copilot Flow

RAG responses enforce strict citation integrity and defend against prompt injections:

```
[User Question]
        │
        ▼
[Semantic Retrieval Step]
        - Query Qdrant Edge with threshold (min score: 0.35, top-k: 5)
        │
   ┌────┴──────────────────────────────────────┐
   │ Check Insufficient Evidence Threshold     │
   └────┬──────────────────────────────────────┘
        │
        ├─► [Evidence <= Threshold] ──► [Immediate Refusal (< 27 ms)]
        │                               "I could not find sufficient evidence..."
        │                               (Bypasses LLM, prevents hallucination)
        ▼
[Context Assembly & Sanitization]
        - Context formatted as pure passive DATA with strict boundary delimiters
        - Strips adversarial instruction tokens ("Ignore previous...", "SYSTEM:")
        │
        ▼
[Local Ollama Generation]
        - System prompt strictly instructs model to answer using only supplied context
        - Emits grounded answer with zero invented citations
        │
        ▼
[Backend Citation Construction]
        - Citations constructed by backend from verified chunk metadata
        │
        ▼
[Conversation Message Persisted] -> SQLite conversations & message log
```

---

## 5. Bidirectional Synchronization Flow

Synchronizes edge devices with central Qdrant Server while maintaining local write availability:

```
[Sync Trigger (Scheduled Cron or Manual Button)]
                    │
                    ▼
         [Connectivity Check]
         - Probe Qdrant Server /healthz
         - If unavailable: Log event, back off exponentially, abort cycle
                    │
                    ▼
       [Phase 1: Edge ─► Cloud Drain]
       - Dequeue pending `SyncItem`s in batches (default: 100)
       - Batch upsert to remote Qdrant Server collection
       - Mark successfully uploaded items as COMPLETED
                    │
                    ▼
       [Phase 2: Enter Sync Barrier]
       - Acquire `_SYNC_BARRIER_LOCK` (prevents local shard corruption)
                    │
                    ▼
       [Phase 3: Cloud ─► Edge Refresh]
       - Fetch remote point updates and snapshot manifests
       - Conflict detection check against local SQLite state
       - If divergent revision: Record `Conflict` model (do not overwrite)
       - Ingest cloud points into local Immutable Shard
                    │
                    ▼
       [Phase 4: Mutable Shard Pruning]
       - Purge points from Mutable Shard only when confirmed in Immutable Shard
                    │
                    ▼
       [Phase 5: Release Barrier & Audit]
       - Release `_SYNC_BARRIER_LOCK`
       - Write append-only `AuditEvent` to SQLite (`SYNC_COMPLETED`)
```

---

## 6. Conflict Detection & Resolution Flow

Handles multi-device divergent edits using Optimistic Concurrency Control (OCC) and side-by-side visual review:

```
[Cloud Ingestion Detects Divergent Revision on Same Entity ID]
                               │
                               ▼
                    [ConflictDetector]
                    - Compare local_revision vs cloud_revision
                    - Compare local_content_hash vs cloud_content_hash
                               │
                               ▼
                    [Conflict Entity Created]
                    - Record in SQLite `conflicts` table (`status='open'`)
                    - Emits `CONFLICT_DETECTED` audit event
                               │
                               ▼
                    [DiffEngine Calculation]
                    - Compute line-by-line additions, deletions, modifications
                    - Calculate structured metadata field deltas
                               │
                               ▼
                    [Operator Decision (UI / API)]
                    ├── KEEP_LOCAL:
                    │   - Assign monotonic revision: max(local, cloud) + 1
                    │   - Enqueue follow-up sync to overwrite cloud
                    ├── KEEP_CLOUD:
                    │   - Overwrite local record with cloud payload
                    │   - Assign cloud revision
                    └── MANUAL_MERGE:
                        - Apply operator-edited merged text
                        - Increment monotonic revision
                               │
                               ▼
                    [Audit Trail Commitment]
                    - Update conflict record to `status='resolved'`
                    - Append-only trigger guarantees resolution provenance
```
