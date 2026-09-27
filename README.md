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
# 1. Clone and configure
cp .env.example .env
# Edit .env with your settings

# 2. Start all services
docker-compose up -d

# 3. Pull an Ollama model
docker exec -it edgewise-ai-ollama-1 ollama pull llama3.2:3b

# 4. Access the application
# Frontend: http://localhost:5173
# Backend API: http://localhost:8000/docs
# Health: http://localhost:8000/health
```

## Local Development

```bash
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

This project is under active development. See the phased implementation plan in `docs/`.

### Implementation Phases
- [x] Phase 0: Architecture & repository setup
- [ ] Phase 1: Backend skeleton + database + health checks
- [ ] Phase 2: Document ingestion + local storage
- [ ] Phase 3: Qdrant Edge integration + retrieval
- [ ] Phase 4: Ollama + RAG + citations
- [ ] Phase 5: Offline-first behavior
- [ ] Phase 6: Durable synchronization queue
- [ ] Phase 7: Qdrant Server synchronization
- [ ] Phase 8: Conflict detection/resolution
- [ ] Phase 9: Frontend dashboard
- [ ] Phase 10: Observability + audit
- [ ] Phase 11: Testing
- [ ] Phase 12: Docker + CI/CD
- [ ] Phase 13: Security review
- [ ] Phase 14: Performance review

## Qdrant Edge Notes

Qdrant Edge is currently in beta. This project uses the `qdrant-edge-py` Python package with the documented dual-shard synchronization pattern:
- **Mutable shard**: Receives all local writes
- **Immutable shard**: Periodically refreshed from Qdrant Server via partial snapshots

See [Qdrant Edge Documentation](https://qdrant.tech/documentation/edge/) for current API reference.

## License

MIT
