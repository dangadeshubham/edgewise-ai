# EDGEWISE AI

**Autonomous Edge Memory & Offline Intelligence Platform for Industrial Operations**

[![Lifecycle: Complete](https://img.shields.io/badge/Lifecycle-Phases%200--14%20Complete-brightgreen.svg)]()
[![Tests: 247 Passed](https://img.shields.io/badge/Tests-247%20Passed%20(100%25)-success.svg)]()
[![Engine: Qdrant Edge](https://img.shields.io/badge/Vector%20Engine-Qdrant%20Edge%200.8.0-blue.svg)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

---

## 1. Project Overview

**EDGEWISE AI** is a purpose-built, offline-first artificial intelligence platform designed for rugged industrial edge appliances and field terminals. In sectors like mining, maritime vessels, remote oil & gas refineries, power generation, and rail transit, field technicians operate in environments with intermittent, degraded, or non-existent internet connectivity. 

EDGEWISE AI allows edge devices to independently ingest technical documentation, perform sub-millisecond semantic search, and execute grounded Retrieval-Augmented Generation (RAG) using local LLMs — guaranteeing 100% operational autonomy while offline, and seamlessly synchronizing with a central cloud cluster whenever network connectivity is restored.

---

## 2. The Problem: The Fragility of Cloud-Only AI

Modern enterprise AI platforms assume constant, low-latency broadband internet access. When deployed into industrial field operations, cloud-dependent architectures introduce severe failure modes:
- **Total Operational Blindness**: If a field terminal loses satellite or cellular signal, technicians cannot query equipment manuals, SOPs, or incident histories.
- **Latency Spikes**: Round-tripping heavy vector and LLM queries over high-latency field connections (e.g., satellite links with > 800 ms RTT) degrades emergency response workflows.
- **Silent Multi-Master Data Loss**: Concurrent writes made on disconnected devices are frequently overwritten or lost when connectivity returns without deterministic conflict management.
- **Data Sovereignty Violations**: Sending sensitive operational telemetry or proprietary blueprints over public backhauls breaches strict industrial compliance mandates.

---

## 3. Why Edge AI?

By embedding vector memory, semantic indexing, relational queues, and language model inference directly onto the local edge device, EDGEWISE AI achieves:
1. **Guaranteed Autonomy**: Zero runtime dependency on cloud servers for search, retrieval, or question-answering.
2. **Sub-Millisecond Search**: Local vector similarity calculations execute in **0.54 ms – 0.58 ms** directly in host RAM and NVMe storage.
3. **Deterministic Synchronization**: SQLite-backed durable queues ensure that all local modifications survive power loss, crashes, or prolonged network outages.
4. **Provable Grounding**: Context gating prevents LLM hallucinations, refusing out-of-context queries in **26.73 ms** without invoking heavy model inference.

---

## 4. Product Architecture

EDGEWISE AI implements a decoupled two-tier architecture linking autonomous Edge Devices to a central Cloud Vector Cluster:

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
│   │       - Ingestion & Text Normalization Pipeline              │     │
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

For complete data flows, see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## 5. Local Memory Architecture

Local memory is implemented through an embedded dual-tier storage strategy:
- **Relational & State Storage (SQLite via SQLAlchemy Async)**: Stores document metadata, chunk text, device registries, durable sync items, conflict state, and immutable audit trails.
- **Dense & Sparse Vector Indexing (Qdrant Edge)**: In-process vector database providing hybrid dense (`all-MiniLM-L6-v2`, 384 dimensions) and native sparse BM25 indexing with metadata payload filtering.

---

## 6. The Role of Qdrant Edge

`qdrant-edge-py` runs natively within the Python backend process, leveraging Rust-backed memory-mapped segments without requiring a separate vector database daemon:
- **Dual-Shard Pattern**:
  - **Mutable Shard**: Write-Ahead Log (WAL) backed shard that immediately indexes all local writes, document uploads, and technician notes created on the edge device.
  - **Immutable Shard**: Read-only, highly optimized HNSW segment store periodically refreshed and reconstructed from central cloud snapshot payloads.
- **Unified Search Fusion**: Queries are dispatched concurrently to both shards; candidate points are merged and deduplicated by logical chunk identifiers.

---

## 7. The Role of Qdrant Server

A centralized, distributed **Qdrant Server** instance (`qdrant/qdrant:latest`) acts as the fleet-wide master repository:
- Aggregates validated vectors across multiple distributed edge devices.
- Serves as the authoritative source for baseline fleet knowledge and reference manuals.
- Supplies incremental change sets and snapshot manifests back to edge terminals during synchronization cycles.

---

## 8. Offline Workflow

When the edge terminal loses network connectivity, the system automatically transitions to `OFFLINE` state:
1. Search queries continue executing against local mutable and immutable shards with **0.0 ms degradation**.
2. Document uploads are extracted, chunked, embedded, and immediately searchable in the local mutable shard.
3. Local writes and modifications are enqueued in SQLite `sync_items` with monotonic revision tracking.
4. Local Copilot RAG queries continue generating grounded responses via Ollama on the device.

---

## 9. Synchronization Workflow

When connectivity to Qdrant Server is detected:
1. **Queue Drain**: The backend claims pending items from `sync_items` in batches (default: 100) and pushes them to the central Qdrant Server collection.
2. **Synchronization Barrier**: The engine enters a synchronization barrier (`_SYNC_BARRIER_LOCK`) to prevent interleaved mutations during shard promotion.
3. **Cloud Refresh**: The backend retrieves updated server manifests, detects upstream changes, and repopulates the local immutable shard.
4. **Mutable Shard Pruning**: Points are deleted from the local mutable shard **only after** their presence is cryptographically verified in the immutable shard.
5. **Audit Event**: Emits an immutable `SYNC_COMPLETED` audit event detailing upload counts, duration, and latency.

---

## 10. Conflict Resolution Subsystem

When the same knowledge record is modified concurrently on both the local edge device and the cloud cluster, EDGEWISE AI prevents silent data loss through Optimistic Concurrency Control (OCC):
- **Conflict Detection**: Compares `revision` integers and SHA-256 `content_hash` strings.
- **Granular Line Diff Engine**: Side-by-side visualization computes exact line additions, deletions, and metadata property changes.
- **Deterministic Resolution Strategies**:
  - `KEEP_LOCAL`: Preserves local edge changes, increments revision monotonically (`max(local, cloud) + 1`), and re-enqueues follow-up sync to overwrite cloud.
  - `KEEP_CLOUD`: Overwrites local record with cloud payload and updates local revision.
  - `MANUAL_MERGE`: Operator supplies custom merged text via UI/API, assigning a new authoritative revision.
- **Audit Immutability**: All conflict resolutions are committed to the SQLite `conflicts` and `audit_events` tables.

---

## 11. Grounded RAG Architecture (Local Copilot)

EDGEWISE AI enforces rigorous grounding to ensure operators receive verifiable technical facts:
- **Retrieval Separation**: Search retrieval and text generation are decoupled stages.
- **Passive Context Sandboxing**: Retrieved chunks are injected into LLM prompts inside strict XML-like delimiters, stripping instruction-override attempts (defending against prompt injection).
- **Backend-Constructed Citations**: Citations (source document, chunk ID, confidence score, filename) are constructed by the backend service—never invented by the LLM.
- **Grounded Refusal**: If no retrieved chunks satisfy the confidence threshold (`score >= 0.35`), the pipeline returns a refusal in **26.73 ms**, bypassing LLM generation entirely.

---

## 12. Security Model & Trust Boundaries

- **Deployment Archetype**: Single-tenant Edge Appliance / Field Terminal.
- **Trust Perimeter**: Operations within the local edge network (`LOCAL_EDGE_TRUSTED`) run with operator privileges.
- **Network Isolation**: Production Docker Compose publishes **only** necessary host ports (Backend `8000`, Frontend `5173`). Internal services (Qdrant Server `6333`, Ollama `11434`) are isolated to the Docker bridge network.
- **Defense in Depth**:
  - Sliding-window rate limiters protect vector search and upload endpoints from resource exhaustion.
  - Path traversal neutralization (URL-unquoting, null-byte stripping, 255-char ceiling) prevents filesystem escape.
  - HTTP security headers: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, tailored Content-Security-Policy (CSP).
  - SQLite database triggers enforce strict append-only immutability on audit logs.
  - Non-root container runtime (`appuser:10001`).

---

## 13. Quick Start (Production Compose)

Get EDGEWISE AI running in minutes using containerized orchestration:

```bash
# 1. Clone the repository
git clone https://github.com/your-org/edgewise-ai.git
cd edgewise-ai

# 2. Configure environment
cp .env.example .env

# 3. Launch containerized services
docker compose up -d --build

# 4. Populate realistic industrial maintenance fixture data
docker compose run --rm edgewise-backend python scripts/seed_db.py

# 5. Execute single-command deployment health verification
python scripts/verify_deployment.py

# 6. Access interfaces
# - Web Application UI: http://localhost:5173
# - FastAPI Swagger Docs: http://localhost:8000/docs
# - Live Health Probe:   http://localhost:8000/health/ready
```

---

## 14. Local Development (Native Environment)

```bash
# Terminal 1: Backend
cd backend
python -m venv .venv
source .venv/bin/activate       # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Terminal 2: Frontend
cd frontend
npm install
npm run dev

# Terminal 3: Qdrant Server & Ollama
# Ensure Qdrant is available on port 6333 and Ollama on port 11434
```

---

## 15. Configuration Parameters

All settings are driven via environment variables with validated defaults in `.env.example`:

| Variable | Default Value | Description |
|:---|:---|:---|
| `DEVICE_ID` | `edge-device-001` | Unique industrial asset identifier |
| `SQLITE_DATABASE_URL` | `sqlite+aiosqlite:///./data/sqlite/edgewise.db` | Local SQLite database path |
| `EDGE_DATA_DIR` | `./data/qdrant_edge` | Base directory for Qdrant Edge shards |
| `EDGE_BATCH_SIZE` | `32` | Optimal batch size for embedding throughput |
| `QDRANT_SERVER_URL` | `http://localhost:6333` | Central Qdrant Server endpoint |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Local Ollama daemon endpoint |
| `OLLAMA_DEFAULT_MODEL`| `llama3:latest` | Local LLM for Copilot RAG queries |
| `RATE_LIMIT_SEARCH_PER_MINUTE` | `60` | Search concurrency protection threshold |

---

## 16. Automated Testing & Verification

EDGEWISE AI enforces 100% pass rates across all test suites:

```bash
# Run backend unit tests (178 tests)
pytest backend/tests/unit -q

# Run backend integration tests (34 tests)
pytest backend/tests/integration -q

# Run frontend unit and flow tests (21 tests)
cd frontend && npx vitest run

# Run end-to-end 14-step physical system verification
python backend/benchmarks/verify_e2e_workflow.py

# Run one-command deployment verifier
python scripts/verify_deployment.py
```

---

## 17. Benchmark Environment & Empirical Results

All performance claims originate from direct measurements on physical host hardware:

| Benchmark Parameter | Measured Specification |
|:---|:---|
| **Host CPU** | AMD Ryzen 5 (6 Physical Cores, 12 Logical Processors) |
| **System RAM** | 15.34 GB Physical DDR4 |
| **Storage** | WDC PC SN530 NVMe SSD (PCIe Gen3 x4, 512 GB) |
| **Runtime Software**| Python 3.10.11, Node.js v22.14.0, Docker 29.2.1 |
| **Vector Library** | `qdrant-edge-py` v0.8.0, `sentence-transformers` 6.1.0 |

### Key Benchmark Metrics
- **Raw Edge Vector Query**: **0.54 ms – 0.58 ms** (Qdrant Edge native Rust scan).
- **Total Search Latency (p50)**: **16.07 ms – 17.12 ms** (including 384-d dense embedding).
- **Ingestion Throughput**: **67.4 chunks/sec** on CPU using optimal batch size 32.
- **Cloud Sync Throughput**: **401.16 items/sec** during bulk upload to live Qdrant Server.
- **Peak Process RSS**: **567.59 MB** across ingestion, search, RAG, and sync stress testing.
- **Frontend SPA Bundle**: **116.95 kB (gzip)**, hydrating in < 150 ms.

For detailed profiling, charts, and test runs, see [docs/PERFORMANCE_REPORT.md](docs/PERFORMANCE_REPORT.md).

---

## 18. Known Limitations & Disclosure

1. **Local LLM Token Generation Latency on CPU**:
   - On the benchmark machine without discrete CUDA acceleration, 7–8B parameter models (`llama3:latest`, `mistral:latest`, `qwen2.5:latest`) generate at approximately **6.6 – 6.9 tokens/sec**, taking **~51–56 seconds** for a complete 350-token answer. In production, streaming SSE should be enabled to display the first token in < 800 ms.
2. **Hardware Constraints on Low-Power Devices**:
   - Ultra-compact edge hardware (e.g. Raspberry Pi 4/5) will experience reduced embedding throughput (~15–20 chunks/s) and will require smaller quantized models (e.g., `llama3.2:1b` or `qwen2.5:1.5b`).
3. **Single-Tenant Edge Perimeter**:
   - The appliance is designed for trusted local network operation. Deployments exposed to untrusted external subnets must place an mTLS or OAuth2 reverse proxy (e.g., Envoy or Traefik) in front of port 8000.
4. **Physical Device Risk**:
   - While database access is restricted by non-root container permissions, edge terminals at high physical theft risk must utilize host Full Disk Encryption (LUKS / BitLocker).

---

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
