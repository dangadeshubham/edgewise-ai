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
- [ ] Phase 13: Security review & hardening
- [ ] Phase 14: Performance optimization & benchmark

## Qdrant Edge Notes

Qdrant Edge is currently in beta. This project uses the `qdrant-edge-py` Python package with the documented dual-shard synchronization pattern:
- **Mutable shard**: Receives all local writes
- **Immutable shard**: Periodically refreshed from Qdrant Server via partial snapshots

See [Qdrant Edge Documentation](https://qdrant.tech/documentation/edge/) for current API reference.

## License

MIT
