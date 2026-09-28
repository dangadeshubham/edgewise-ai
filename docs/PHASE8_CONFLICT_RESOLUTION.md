# EDGEWISE AI — Phase 8: Real Conflict Detection Presentation & Resolution Architecture

## 1. Overview & Objectives

In Phase 7, EDGEWISE AI introduced genuine Edge ↔ Cloud bidirectional synchronization using live Qdrant Server and local Qdrant Edge mutable/immutable shards. In that phase, whenever divergent revisions were discovered, a conflict boundary quarantined both versions in SQLite's persistent `conflicts` table without overwriting either side.

**Phase 8** operationalizes real, production-ready **conflict presentation and conflict resolution**:
1. **Side-by-Side Diff Presentation**: Granular line-by-line additions, deletions, unchanged lines, and structured JSON/metadata comparison.
2. **Explicit Human Decisions**:
   - `KEEP_LOCAL`: Local version verified as authoritative; assigned a monotonic revision bump; scheduled for remote upload.
   - `KEEP_CLOUD`: Cloud version adopted; local SQLite and Qdrant Edge mutable vectors updated immediately to replace stale state.
   - `MERGE`: Deterministic merge synthesis constructed and approved by human operator; assigned monotonic revision and scheduled for synchronization.
   - `MANUAL`: Free-form operator override validated with SHA-256 and saved.
3. **No AI Autonomous Resolution**: The LLM may suggest an unapproved merge (`"AI suggested merge"`), but never automatically modifies production data.
4. **Optimistic Concurrency Control**: Multi-operator locking via conflict versions (`version`), preventing race conditions.
5. **Transactional Integrity & Auditability**: Every transition creates immutable audit events (`CONFLICT_CLAIMED`, `CONFLICT_RESOLVED`, etc.).

---

## 2. Conflict State Machine

```
              ┌─────────────┐
              │    OPEN     │
              └──────┬──────┘
                     │ (claim)
                     ▼
              ┌─────────────┐
        ┌────►│  IN_REVIEW  │◄────┐
        │     └──────┬──────┘     │
        │            │            │
(stale  │      (resolve/dismiss)  │
retry)  │            │            │
        │     ┌──────┴──────┐     │
        │     ▼             ▼     │
  ┌─────────────┐     ┌─────────────┐
  │  RESOLVED   │     │  DISMISSED  │
  └─────────────┘     └─────────────┘
   (terminal)          (terminal)
```

- **`OPEN`**: Conflict was detected by the sync engine upon discovering divergent revisions/content hashes between Edge and Cloud.
- **`IN_REVIEW`**: Operator claimed review ownership of the conflict (`POST /api/conflicts/{id}/claim`), incrementing the conflict version.
- **`RESOLVED`**: Operator chose an explicit resolution (`keep_local`, `keep_cloud`, `merge`, or `manual`). Both original versions remain stored in the conflict record and resolution metadata.
- **`DISMISSED`**: Conflict was administratively dismissed without altering underlying local or remote data.

---

## 3. Resolution Options & Semantics

| Resolution | Local Content | SQLite Revision | Qdrant Edge Vector | Follow-up SyncItem | Remote Cloud State |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`KEEP_LOCAL`** | Preserved | $\max(local, cloud) + 1$ | Preserved (rev updated) | `PENDING` (upsert) | Cloud will be updated on next sync |
| **`KEEP_CLOUD`** | Overwritten with cloud | $\max(local, cloud) + 1$ | Re-embedded with cloud content | None (`SYNCED`) | Already matches cloud |
| **`MERGE`** | Human-approved synthesis | $\max(local, cloud) + 1$ | Re-embedded with merged content | `PENDING` (upsert) | Cloud will be updated on next sync |
| **`MANUAL`** | Arbitrary operator override | $\max(local, cloud) + 1$ | Re-embedded with manual text | `PENDING` (upsert) | Cloud will be updated on next sync |
| **`DISMISSED`** | Preserved | Unchanged | Unchanged | None | Quarantined |

---

## 4. Revision Rules & Monotonicity

To guarantee eventual consistency across disconnected devices without revision collision:
1. **Monotonic Invariant**:
   $$\text{revision}_{\text{resolved}} = \max(\text{revision}_{\text{local}}, \text{revision}_{\text{cloud}}) + 1$$
2. **Never Reuse Revisions**: An older revision number is never reassigned to a record.
3. **Traceability**: Original local revision and cloud revision remain immutable inside the `conflicts` record and `resolution_metadata_json`.

---

## 5. Non-Autonomous AI Merge Policy

Per Section 6 and Section 22:
- **No Silent LLM Merges**: LLMs are never permitted to autonomously select winners or commit merged data to production.
- **Explicitly Labeled Suggestions**:
  - Endpoint `POST /api/conflicts/{id}/suggest-merge` returns a structured proposal with `label: "AI suggested merge"` and `requires_user_approval: true`.
  - The UI displays an amber warning banner informing the operator that the content is an unapproved suggestion that must be verified.

---

## 6. Optimistic Concurrency Control

When two operators or automated nodes view the same conflict simultaneously:
1. Every conflict row maintains an integer `version` field (starts at 1).
2. Mutation requests (`claim`, `resolve`, `dismiss`) accept an `expected_version` parameter.
3. If `expected_version != conflict.version`:
   - System rejects the request immediately with `HTTP 409 Conflict` (`ConflictConcurrencyError`).
   - Prevents lost updates or simultaneous divergent resolutions.

---

## 7. Edge Memory & Vector Consistency

To prevent stale vectors from lingering in local search or RAG:
1. When `KEEP_CLOUD`, `MERGE`, or `MANUAL` is executed, [`ConflictService`](file:///E:/CUBIC%20CODE%20HACKATHON/edgewise-ai/backend/app/services/conflict/service.py) generates a fresh 384-dimensional embedding via [`EmbeddingService`](file:///E:/CUBIC%20CODE%20HACKATHON/edgewise-ai/backend/app/services/embeddings/service.py).
2. The vector point in the local Qdrant Edge mutable shard (`point_id = generate_point_id_from_chunk_id(record_id)`) is upserted with the new text, revision, and content hash.
3. The mutable shard is flushed to disk (`flush("mutable")`).
4. Unified local memory search queries both shards and immediately reflects the authoritative resolved text.

---

## 8. Audit Trail Specifications

Every conflict action produces immutable records in SQLite `audit_events`:

| Action | Primary Audit Event | Secondary Event | Severity |
| :--- | :--- | :--- | :--- |
| Conflict Detected (Sync) | `conflict_detected` | — | `warning` |
| Review Claimed | `conflict_claimed` | — | `info` |
| Keep Local Selected | `conflict_keep_local` | `conflict_resolved` | `info` |
| Keep Cloud Selected | `conflict_keep_cloud` | `conflict_resolved` | `info` |
| Merge Approved | `conflict_merged` | `conflict_resolved` | `info` |
| Manual Override Saved | `conflict_manual` | `conflict_resolved` | `info` |
| Conflict Dismissed | `conflict_dismissed` | — | `info` |

---

## 9. Security & Input Protection

- **XSS & HTML Injection Protection**: Content from both local and remote nodes is rendered via strict DOM escaping (`escapeHtml`).
- **Payload Limits**: Merged and manual inputs enforce a strict 1 MB maximum length.
- **Secret Redaction**: No sensitive credentials or filesystem paths are leaked in conflict metadata or diff structures.
