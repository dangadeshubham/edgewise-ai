# EDGEWISE AI

**Offline Intelligence. Persistent Memory. Intelligent Sync.**

An offline-first AI Edge Memory & Intelligence Platform for industrial field operations. Built for environments with intermittent connectivity, EDGEWISE AI enables edge devices to store, search, and reason over local knowledge — then synchronize with a central cloud when connectivity returns.

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        EDGE DEVICE                                │
│                                                                    │
│  ┌──────────┐   ┌──────────────┐   ┌───────────────────────────┐  │
│  │ React    │   │  FastAPI     │   │  Qdrant Edge              │  │
│  │ Frontend │◄──┤  Backend     │◄──┤  ├─ Mutable Shard (local) │  │
│  │ (Vite)   │   │              │   │  └─ Immutable Shard (sync)│  │
│  └──────────┘   │  ┌─────────┐ │   └───────────────────────────┘  │
│                  │  │ SQLite  │ │                                   │
│                  │  │ (meta)  │ │   ┌───────────────────────────┐  │
│                  │  └─────────┘ │   │  Ollama (Local LLM)      │  │
│                  └──────────────┘   └───────────────────────────┘  │
│                         │                                          │
│                    SQLite-backed                                    │
│                    Durable Sync Queue                               │
└─────────────────────────┬──────────────────────────────────────────┘
                          │ (when online)
                          ▼
              ┌───────────────────────┐
              │  Qdrant Server/Cloud  │
              │  (Central Collection) │
              └───────────────────────┘
```

## Key Capabilities

- **Local Memory**: Persistent vector storage via Qdrant Edge
- **Offline Retrieval**: Semantic search without internet
- **Local AI**: RAG-powered Q&A via Ollama
- **Durable Sync Queue**: SQLite-backed, survives restarts
- **Cloud Synchronization**: Dual-shard pattern with partial snapshots
- **Conflict Detection**: Application-layer conflict handling with user resolution
- **Observability**: Structured logging, audit trail, health checks

## Use Case: Remote Industrial Maintenance

Field technicians access equipment manuals, maintenance procedures, incident reports, and troubleshooting guides — even without network connectivity. New observations and records are stored locally and synchronized when connectivity returns.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React, Vite, TypeScript, Tailwind CSS |
| Backend | Python, FastAPI, Pydantic |
| Local DB | SQLite (via SQLAlchemy + aiosqlite) |
| Local Vectors | Qdrant Edge (`qdrant-edge-py`) |
| Cloud Vectors | Qdrant Server |
| Local LLM | Ollama |
| Embeddings | sentence-transformers (all-MiniLM-L6-v2) |
| Deployment | Docker, Docker Compose |

## Quick Start

```bash
# 1. Clone repository and configure environment
cp .env.example .env

# 2. Launch all containerized services
docker compose up -d --build

# 3. (Optional) Populate fixture seed data
docker compose run --rm edgewise-backend python scripts/seed_db.py

# 4. Verify end-to-end deployment health
python scripts/verify_deployment.py

# 5. Access the application
# Frontend UI: http://localhost:5173
# Backend API: http://localhost:8000/docs
# Health Probe: http://localhost:8000/health/ready
```

See [docs/PHASE12_DEPLOYMENT.md](docs/PHASE12_DEPLOYMENT.md) for full deployment, volume backup, disaster recovery, and production operations guides.

## Local Development

```bash
# Option A: Local Docker Dev Mode (with hot reloading and debug ports)
docker compose -f docker-compose.dev.yml up

# Option B: Native Host Environment
# Backend
cd backend
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend
npm install
npm run dev
```

## API Documentation

OpenAPI documentation is auto-generated at:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## Security & Trust Architecture (Phase 13)

For detailed security review, threat modeling, and dependency audits, see:
- [docs/SECURITY_REVIEW.md](docs/SECURITY_REVIEW.md)
- [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md)
- [docs/DEPENDENCY_SECURITY.md](docs/DEPENDENCY_SECURITY.md)

### Security Model & Trust Boundaries
- **Deployment Archetype**: Single-tenant Edge Appliance / Field Terminal.
- **Trust Boundary**: Local Edge Network (`LOCAL_EDGE_TRUSTED`). Operations originating within the local field terminal perimeter are executed with local operator privileges.
- **Authentication Status**: Endpoints operate in unauthenticated appliance mode by default. A formal authorization interface (`backend/app/core/auth.py`) is provided with API key and permission enforcement hooks. Multi-user enterprise RBAC is deferred to Phase 14+.
- **Secrets Management**: Zero credentials or tokens in tracked source. Environment variables drive configuration via `.env` (ignored by git). Production logs redact secrets via structlog filters. Frontend distribution bundles contain zero backend credentials.
- **Network Isolation**: Production Docker Compose publishes **only** necessary host ports (Backend `8000`, Frontend `5173`). Internal services (Qdrant Server `6333`, Ollama `11434`) are isolated to the internal Docker bridge network without host port publishing.
- **Defense in Depth**:
  - In-process sliding-window rate limiting on high-risk endpoints (upload, search, copilot, sync, reindex).
  - Strict file upload validation: path traversal neutralization (URL-unquoting), 255-character filename ceiling, OpenXML decompression bomb rejection, JSON nesting depth bounds.
  - HTTP security headers: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, tailored Content-Security-Policy (CSP).
  - Non-root container runtime (`appuser:10001`) with runtime compilers purged.
  - Parameterized SQLite access with append-only audit trail immutability triggers.

### Known Risks & Deployment Recommendations
- **Physical Device Access**: Local SQLite database and vector storage are protected by container non-root boundaries. For high-theft physical risk environments, Full Disk Encryption (LUKS or BitLocker) must be enabled on the host operating system.
- **Untrusted / Remote Networks**: If exposing edge nodes beyond the local private subnet, an upstream reverse proxy or API Gateway (e.g., Nginx, Envoy, Traefik) enforcing mutual TLS (mTLS) or OAuth2 authentication must be placed in front of the terminal.

## Performance & Reliability Validation (Phase 14)

EDGEWISE AI has completed comprehensive empirical performance, scalability, and resilience validation on physical host hardware and live containerized services. For complete data and methodology, see:
- [docs/PERFORMANCE_REPORT.md](docs/PERFORMANCE_REPORT.md) — Comprehensive empirical benchmark report
- [docs/RELIABILITY_REPORT.md](docs/RELIABILITY_REPORT.md) — Long-run stability, 10 recovery scenarios & regression results

### Measured Performance Highlights
- **Sub-Millisecond Vector Scan**: Native Rust `qdrant-edge-py` nearest-neighbor queries execute in **0.54 ms – 0.58 ms**. Total search latency with embedding is **16 – 19 ms** (p50) across 2,000 document chunks.
- **Ingestion & Embedding Throughput**: Ingestion runs at **67.4 chunks/sec** on CPU using optimal batch size 32 (saving 73 MB RAM over batch 64).
- **Fast Grounded RAG Refusal**: Out-of-context queries bypass LLM generation entirely and return grounded refusal in **26.73 ms**.
- **High-Throughput Cloud Synchronization**: Batched uploads to live Qdrant Server sustain **401 items/sec** across network boundaries.
- **Zero Memory Growth**: Sustained 50-cycle stress testing showed 0 uncollected allocations, 0 thread leaks, and 0 queue corruptions.
- **Lean Production Frontend**: Vite/React SPA bundle compiles to **116.95 kB (gzipped)**, hydrating in < 150 ms.

### System Capabilities & Scope Summary
- **Implemented Capabilities**: Dual-shard embedded vector memory (`qdrant-edge-py`), offline-first semantic search, grounded local RAG with citation construction, SQLite-backed durable sync queue, bidirectional cloud sync with live Qdrant Server, granular diff engine & optimistic concurrency control (OCC), append-only immutable audit logging, non-root Docker deployment, sliding-window rate limiting.
- **Tested Capabilities**: 233 automated test cases (178 backend unit, 34 backend integration, 21 frontend vitest), 10 failure-recovery scenarios, end-to-end 14-step physical verification pipeline, and controlled concurrency load testing.
- **Deployment Assumptions**: Single-tenant Edge Appliance / Field Terminal operating within a trusted local network perimeter. Multi-tenant internet exposure requires an upstream reverse proxy enforcing mTLS/OAuth2.
- **Hardware Profile Assessed**: AMD Ryzen 5 (6c/12t), 16GB RAM, NVMe SSD, CPU tensor evaluation.

## Project Status

- [x] Phase 0: Architecture & repository setup
- [x] Phase 1: Backend skeleton + database + health checks
- [x] Phase 2: Document ingestion + local storage
- [x] Phase 3: Qdrant Edge integration + retrieval
- [x] Phase 4: Local RAG with Ollama & ground truth validation
- [x] Phase 5: Offline-First runtime & connectivity state machine
- [x] Phase 6: Durable SQLite sync queue & crash recovery
- [x] Phase 7: Real Qdrant Server & Cloud-to-Edge synchronization
- [x] Phase 8: Real conflict detection presentation & resolution engine
- [x] Phase 9: Production frontend SPA
- [x] Phase 10: Production observability & immutable audit telemetry
- [x] Phase 11: Deliberate failure-injection, hardening & resilience validation
- [x] Phase 12: Production containerization, orchestration & CI/CD
- [x] Phase 13: Security review & platform hardening pass
- [x] Phase 14: Performance optimization, reliability & final system validation (COMPLETE)

*EDGEWISE AI engineering lifecycle is complete.*

## Qdrant Edge Notes

Qdrant Edge is currently in beta. This project uses the `qdrant-edge-py` Python package with the documented dual-shard synchronization pattern:
- **Mutable shard**: Receives all local writes
- **Immutable shard**: Periodically refreshed from Qdrant Server via partial snapshots

See [Qdrant Edge Documentation](https://qdrant.tech/documentation/edge/) for current API reference.

## License

MIT

