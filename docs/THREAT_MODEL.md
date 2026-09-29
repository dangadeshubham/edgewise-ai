# EDGEWISE AI — Threat Model & Security Architecture

**Document Version:** 1.0  
**Phase:** 13 (Security Hardening & Review)  
**System Classification:** Single-Tenant Offline-First Edge AI Appliance  
**Last Updated:** 2026-09-29  

---

## 1. System Trust Boundary & Data Flow

```mermaid
flowchart TD
    Attacker[External / Network Attacker] -->|1. Untrusted Network Boundary| ReverseProxy[Nginx Reverse Proxy / Host Port 5173 / 8000]
    ReverseProxy -->|2. HTTP Request with Security Headers| Frontend[React SPA Client]
    Frontend -->|3. REST API Requests| API[FastAPI Backend Application]
    
    subgraph Edge Appliance Trust Boundary [Local Edge Perimeter (Field Terminal)]
        API -->|4. Parameterized Queries & Triggers| SQLite[(SQLite Database / edgewise.db)]
        API -->|5. Unprivileged Filesystem IO| LocalStorage[(Upload & Processed Dirs)]
        API -->|6. Embedded In-Process PyO3 Binding| QdrantEdge[(Qdrant Edge Vector Storage)]
        API -->|7. Internal Container Bridge Network| Ollama[Ollama Local LLM Container]
    end

    subgraph Cloud / Central Mirror Boundary [Remote Central Infrastructure]
        API -.->|8. Encrypted HTTPS/gRPC Sync| QdrantServer[(Central Qdrant Server)]
    end
```

---

## 2. Threat Analysis Matrix

### Threat 1: Malicious Uploaded Document (RAG Injection / Decompression Bomb / File Traversal)
- **Attack Surface:** `POST /api/documents` (Multipart file upload).
- **Threat Vector:**
  - Path traversal in filename (`../../etc/shadow`, `..\windows\win.ini`, `%2e%2e%2f`).
  - OpenXML/ZIP decompression bomb (expanding multi-gigabyte payloads in memory/disk).
  - Malformed PDF or JSON payloads causing parser crash or infinite recursion.
  - Poison document containing prompt-injection directives (`"Ignore previous instructions..."`).
- **Impact:** Remote filesystem overwrite, Denial of Service (OOM/Disk exhaustion), LLM instruction hijack.
- **Current Mitigation:**
  - `FileValidator.sanitize_filename` enforces URL decoding, directory delimiter stripping, null-byte rejection, and a 255-character ceiling.
  - Server-generated UUID storage names (`{document_id}_{sanitized_filename}`) with path boundary enforcement preventing directory escape.
  - Decompression bomb detection checking uncompressed archive size (max 50 MB) and compression ratios.
  - Strict JSON nesting depth validator (max 50 levels).
  - PDF `%PDF-` header signature verification.
  - RAG prompt assembly strictly encapsulates document text within `--- EVIDENCE ---` data tags with explicit prompt-level instruction override denial.
- **Remaining Risk:** Highly novel semantic prompt injection embedded in syntactically valid documents cannot be completely eliminated by deterministic sanitizers without LLM evaluation.

---

### Threat 2: Malicious Technician / Physical Field Tampering
- **Attack Surface:** Physical access to edge device storage hardware and USB/serial ports.
- **Threat Vector:** Local user extracts SQLite database file (`edgewise.db`), modifies immutable audit logs, or tampers with vector shard files.
- **Impact:** Audit tampering, loss of telemetry integrity, unauthorized reading of stored edge memory.
- **Current Mitigation:**
  - SQLite database triggers (`trg_audit_events_prevent_update`, `trg_audit_events_prevent_delete`) prevent tampering or record deletion within the database engine.
  - Non-root container runtime (`appuser:appuser`, UID 10001) isolates process privileges.
  - Filesystem paths and database files are isolated within dedicated container volumes.
- **Remaining Risk:** Physical device theft or raw block-device manipulation without Full Disk Encryption (LUKS/BitLocker) allows offline inspection. Hardware-level full disk encryption must be enabled at the host OS tier.

---

### Threat 3: Compromised Edge Device (Lateral Cloud Risk)
- **Attack Surface:** Edge device compromised by adversary attempting to pollute cloud vector index.
- **Threat Vector:** Adversary modifies local vector payloads or crafts malicious delete requests to purge cloud knowledge.
- **Impact:** Poisoning of central Qdrant cloud memory or deletion of operational knowledge across edge fleets.
- **Current Mitigation:**
  - Smart Sync sensitivity policy strictly prevents `confidential` or `restricted` local data from entering sync pipelines.
  - Conflict resolution system preserves conflicting revisions (`Conflict` entity) rather than silently overwriting cloud data.
  - Tombstone deletion markers require valid record existence.
- **Remaining Risk:** If an edge node is granted full write access to the central Qdrant collection, it can write points within its scope. Central collection ACLs / namespace isolation should be applied in multi-tenant environments.

---

### Threat 4: Compromised Cloud Credentials
- **Attack Surface:** Environment variable `QDRANT_API_KEY` or central API keys.
- **Threat Vector:** Key leak via source code, logs, frontend bundles, or error responses.
- **Impact:** Adversary obtains full administrative access to central Qdrant cloud database.
- **Current Mitigation:**
  - Zero hardcoded secrets in repository; verified by git audit and CI secret scanner.
  - `.env` ignored in `.gitignore`; `.env.example` contains blank placeholders only.
  - Frontend bundle scanned during build (`Vite` bundle contains no `QDRANT_API_KEY` or backend secrets).
  - Backend structured logging redacts credentials and API keys via structlog processors.
  - Error exception handlers return sanitized client messages, never exposing connection strings or credentials.
- **Remaining Risk:** Operator mismanagement of host environment variables or Docker daemon inspection by host users with root privileges.

---

### Threat 5: Network Attacker (Man-in-the-Middle / Traffic Snooping)
- **Attack Surface:** In-transit traffic between frontend browser, backend API, Ollama, and Qdrant Server.
- **Threat Vector:** Packet inspection or session tampering across field network.
- **Impact:** Eavesdropping on operational documents, search queries, and AI responses.
- **Current Mitigation:**
  - Docker Compose isolates Ollama (port 11434) and Qdrant Server (port 6333) to internal bridge network (`edgewise-network`) without publishing host ports in production.
  - HTTP Security headers (`X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, `Content-Security-Policy`) enforced on all responses.
  - CORS strictly configured to environment-specified origins, disallowing credentials with wildcard `*`.
- **Remaining Risk:** Production deployment requires TLS termination (HTTPS) at the Nginx / ingress controller layer when traversed over public or untrusted field networks.

---

### Threat 6: Malicious Sync Payload / Deserialization Exploit
- **Attack Surface:** `POST /api/sync/run` and Cloud-to-Edge vector snapshot ingestion.
- **Threat Vector:** Adversary crafts invalid snapshot archive or vector point payload containing corrupted JSON or vector dimension mismatch.
- **Impact:** Edge crash during snapshot refresh, corrupted SQLite state.
- **Current Mitigation:**
  - Qdrant Server payload format validated prior to local insertion.
  - Atomic transaction handling in `ConflictService` and `EdgeCloudSyncService`; transactional rollback prevents half-synced or corrupt state.
  - Snapshot application updates immutable shard path atomically and flushes before committing state.
- **Remaining Risk:** Out-of-memory condition if cloud snapshot exceeds physical RAM on resource-constrained edge hardware.

---

### Threat 7: Corrupted Local State / Process Crash
- **Attack Surface:** Sudden power loss or process termination during file ingestion or vector commit.
- **Threat Vector:** Mid-write crash leaves partial files on disk or unindexed database chunks.
- **Impact:** Inconsistent state, ghost documents, or corrupted vector indices.
- **Current Mitigation:**
  - Database writes use ACID async transactions with explicit commit/rollback.
  - Orphaned `PROCESSING` sync jobs and pending ingestion records are detected and recovered on startup (`recover_abandoned()`).
  - Edge mutable shards are explicitly flushed and closed on graceful shutdown; WAL journaling ensures crash recovery.
  - Comprehensive integrity verification script (`scripts/verify_integrity.py`) detects and repairs divergence.
- **Remaining Risk:** Hard hardware failure or physical flash wear without hardware redundancy.
