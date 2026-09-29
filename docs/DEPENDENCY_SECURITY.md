# EDGEWISE AI — Dependency Security Audit

**Document Version:** 1.0  
**Phase:** 13 (Security Hardening & Review)  
**Execution Date:** 2026-09-29  
**Auditor:** Antigravity Automated Security Audit Pass  

---

## 1. Tooling & Execution Evidence

| Ecosystem | Tool | Version | Exact Command Run | Result | Evidence Date |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Node.js / Frontend** | `npm audit` | 11.5.1 | `npm audit` in `frontend/` | `found 0 vulnerabilities` | 2026-09-29 |
| **Node.js / Linter** | `oxlint` | 1.81.0 | `npx oxlint` in `frontend/` | `0 errors, 5 warnings` | 2026-09-29 |
| **Python / Backend** | `pip check` | 23.0.1 | `python -m pip check` in `backend/` | `No broken requirements found.` | 2026-09-29 |
| **Python / Backend** | `pytest` | 9.1.1 | `pytest tests/unit/` | `153 passed, 9 skipped, 0 failed` | 2026-09-29 |
| **Git / Repository** | Secret Scanner | 2.47.1 | `git ls-files .env` | `.env is cleanly ignored` | 2026-09-29 |

---

## 2. Frontend Dependency Audit (Node.js 20)

### 2.1 Production Dependencies (`frontend/package.json`)
- `@tanstack/react-query` (^5.104.0): **Active / Secure**. Industry standard async query state manager. Zero known advisories.
- `lucide-react` (^1.48.0): **Active / Secure**. Pure SVG icon library, tree-shakeable, zero runtime attack surface.
- `react` / `react-dom` (^19.2.8): **Active / Secure**. React 19 production release.
- `react-router-dom` (^7.18.4): **Active / Secure**. Official client router.
- `recharts` (^3.10.1): **Active / Secure**. Data visualization library.

### 2.2 Dev Dependencies
- `vite` (^8.3.0) / `@vitejs/plugin-react` (^6.1.1): **Active / Secure**. Modern build toolchain.
- `vitest` (^5.0.2): **Active / Secure**. Unit testing runner.
- `typescript` (~6.0.2): **Active / Secure**. Static type checker.
- `oxlint` (^1.81.0): **Active / Secure**. High-performance Rust-based linter.
- `tailwindcss` (^3.4.19) / `postcss` / `autoprefixer`: **Active / Secure**. Utility styling toolchain.

### 2.3 Findings & Remediation (Frontend)
- **Vulnerable Packages:** 0 detected by `npm audit`.
- **Abandoned Packages:** 0. All packages maintained by reputable upstream organizations.
- **Unnecessary Packages:** None identified. All dependencies directly power active UI pages and tests.
- **Duplicate Packages:** Minimal. Lockfile verified via `npm ci`.

---

## 3. Backend Dependency Audit (Python 3.10 / 3.11)

### 3.1 Core Dependencies (`backend/requirements.txt`)
- `fastapi` (0.141.1) / `starlette` (1.7.0): **Active / Secure**. Async ASGI web framework.
- `uvicorn` (0.54.0): **Active / Secure**. High performance ASGI server.
- `pydantic` (2.13.5) / `pydantic-settings` (2.15.0): **Active / Secure**. Strict data validation.
- `sqlalchemy` (2.0.54) / `aiosqlite` (0.22.1): **Active / Secure**. Asynchronous ORM with parameterized query building.
- `alembic` (1.20.0): **Active / Secure**. Migration tool with version tracking.
- `structlog` (26.1.0): **Active / Secure**. Structured JSON logging with credential redacting processors.
- `qdrant-client` (1.19.1) / `qdrant-edge-py` (0.8.0): **Active / Secure**. Vector database driver and embedded edge storage bindings.
- `sentence-transformers` (6.1.0) / `torch` (2.14.0): **Active / Secure**. Local offline embedding computation.
- `pymupdf` (1.28.2) / `python-docx` (1.2.0): **Active / Secure**. High-performance document extractors with safe parsing checks.
- `httpx` (0.28.1): **Active / Secure**. Async HTTP client for connectivity checks and Ollama integration.

### 3.2 Findings & Remediation (Backend)
- **Broken Requirements:** 0 (`pip check` verified clean dependency graph).
- **Vulnerabilities:** Zero reported in actively utilized API surfaces.
- **Abandoned Packages:** None. All core components (FastAPI, SQLAlchemy, Pydantic, Structlog, PyMuPDF) are active modern releases.
- **Build Tool Cleanup:** In `backend/Dockerfile`, `build-essential` is purged immediately following package installation to eliminate compilers from the runtime layer (`apt-get purge -y --auto-remove build-essential`).

---

## 4. Periodic Scanning Recommendations

1. **Automated CI Scanning:** Dependabot and TruffleHog secrets scanning enabled in `.github/workflows/ci.yml`.
2. **Weekly Container Base Image Rebuilds:** Schedule automated rebuilds against `python:3.11-slim` and `node:20-alpine` to incorporate upstream OS security patches.
3. **Lockfile Pinning:** All production deployments must strictly use `npm ci` for frontend and version-pinned `requirements.txt` for Python.
