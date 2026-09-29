# EDGEWISE AI — Phase 13 Comprehensive Security Review & Hardening Report

**Document Version:** 1.0  
**Phase:** 13 (Platform Hardening & Security Audit)  
**Execution Date:** 2026-09-29  
**Review Status:** Completed & Hardened  
**Scope:** Complete repository audit across Frontend, Backend, Ingestion, Storage, Vector Engines, LLM Runtimes, Docker, and CI/CD.

---

## 1. Security Inventory

| Component | Technology | Primary Function | Primary Threat Vector | Current Hardening State |
| :--- | :--- | :--- | :--- | :--- |
| **React Frontend** | React 19, Vite 8, TypeScript | Single Page Interface for field operators | XSS, CSRF, Clickjacking, credential leaks | Hardened CSP, strict no-secrets client bundle |
| **FastAPI Backend** | Python 3.11, FastAPI, Uvicorn | Core application business logic & REST APIs | Remote code execution, DoS, error leakage | Hardened rate limiting, error sanitization, auth interface |
| **SQLite Storage** | SQLAlchemy 2.0, aiosqlite | Local ACID metadata & operational state | SQL injection, unauthorized data tampering | Parameterized queries only, append-only audit triggers |
| **Qdrant Edge** | `qdrant-edge-py` (PyO3) | In-process embedded vector memory | Shard corruption, file disclosure | Dedicated storage path, directory isolation |
| **Qdrant Server** | Qdrant Official Docker Container | Cloud mirror & sync target | Network exposure, unauthorized cloud writes | Internal bridge network only; zero host port publishing in prod |
| **Ollama LLM** | Ollama Local Container Runtime | Offline grounded generation | Instruction injection, prompt leakage | Strict evidence encapsulation, network isolation |
| **Docker / Compose** | Docker, Alpine Linux, Debian Slim | Containerized orchestration | Container breakout, root execution, image bloat | Non-root `appuser:10001`, compilers purged, minimal images |
| **CI/CD** | GitHub Actions | Automated build, test, and audit pipeline | Leaked pipeline secrets, malicious PR injection | Least privilege `contents: read`, automated secret scanner |
| **File Uploads** | Multipart Form Ingestion | Document extraction (PDF, DOCX, TXT, JSON, MD) | Path traversal, zip bombs, MIME spoofing | Hardened `FileValidator`, decompression bomb limits, safe names |
| **APIs** | REST Endpoints (/api/v1/*) | Operational queries, search, copilot, sync | Resource exhaustion, exception leaks | Pydantic validation limits, HTTP 429 rate limiting |
| **Structured Logs** | `structlog` | Observability & audit events | Credential leaks, PII exposure in logs | Redacting structlog processor for sensitive keys |
| **Environment Vars** | `pydantic-settings` | 12-factor configuration | Hardcoded credentials | `.env` ignored in git, `.env.example` placeholders only |
| **Local Storage** | Host bind volumes | Persistent database and vector shards | Directory traversal escape | Path boundary checks enforcing `upload_dir` containment |
| **Sync Subsystem** | Durable queue, state machine | Edge-to-cloud bidirectional synchronization | Data leak of confidential records | Smart Sync sensitivity filter (confidential records local-only) |
| **Conflict Subsystem** | Vector diff & atomic resolution | Branch divergence reconciliation | Inconsistent state, silent overwrite | ACID transaction rollback, full conflict revision audit trail |

---

## 2. Findings Classification & Remediations

### Finding 1 [HIGH] — Internal Error Details Leaked in HTTP 500 Responses
- **Affected Component:** `backend/app/api/v1/search.py` and `backend/app/api/v1/copilot.py`
- **Threat:** Sensitive Information Disclosure. Raw exception strings `str(exc)` from internal server exceptions were returned directly in HTTP 500 responses (`detail=f"Semantic search failed: {str(exc)}"` and `detail=f"Copilot query failed: {str(exc)[:200]}"`). This could expose database paths, internal host directories, and system call errors to external clients.
- **Evidence:** `backend/app/api/v1/search.py:169`, `backend/app/api/v1/copilot.py:139`.
- **Remediation:** Standardized and sanitized error responses to return generic, client-safe error messages (`detail="Semantic search failed due to an internal server error."`) while capturing the full exception traceback server-side in structured logs with associated `request_id`.
- **Test Covering Remediation:** `tests/unit/test_phase13_security.py::test_16_error_message_sanitization`.

---

### Finding 2 [HIGH] — Unbounded Filename Length and DOCX Decompression Bomb Vulnerability
- **Affected Component:** `backend/app/services/ingestion/validator.py`
- **Threat:** Denial of Service (DoS) and Resource Exhaustion. The upload validator lacked maximum filename length bounds (permitting buffer exhaustion or filesystem errors) and did not inspect the uncompressed size of OpenXML (`.docx`) archives, exposing the edge appliance to zip decompression bombs.
- **Evidence:** `FileValidator.sanitize_filename` lacked length checks; `_check_file_integrity` only verified `is_zipfile` without calculating aggregate uncompressed stream sizes.
- **Remediation:**
  1. Enforced `MAX_FILENAME_LENGTH = 255` in `FileValidator.sanitize_filename`.
  2. Implemented aggregate uncompressed archive size limit (`MAX_UNCOMPRESSED_ARCHIVE_BYTES = 50MB`) and compression ratio check (`MAX_DECOMPRESSION_RATIO = 50.0`) in `_check_file_integrity`.
  3. Added ZipSlip prevention by verifying no archive member filename contains `..` or leading `/`.
- **Test Covering Remediation:** `tests/unit/test_phase13_security.py::test_4_invalid_file_and_decompression_bomb` and `test_5_malicious_filename`.

---

### Finding 3 [HIGH] — URL-Encoded Directory Traversal in File Upload Pipeline
- **Affected Component:** `backend/app/services/ingestion/validator.py` & `service.py`
- **Threat:** Path Traversal / Arbitrary Filesystem Overwrite. An adversary could supply URL percent-encoded directory traversal sequences (`%2e%2e%2f` or `..%5c`) to bypass naive regex stripping and escape the upload directory.
- **Evidence:** `validator.py` performed basename extraction without pre-decoding URL percent sequences.
- **Remediation:**
  1. Integrated `urllib.parse.unquote` prior to delimiter stripping and traversal token neutralization.
  2. Added explicit check in `ingest_document`: resolved disk storage path must strictly begin with `upload_dir.resolve()`.
  3. Ensured server-generated UUID storage names (`{document_id}_{sanitized_filename}`) prevent file collision attacks.
- **Test Covering Remediation:** `tests/unit/test_phase13_security.py::test_1_path_traversal`.

---

### Finding 4 [HIGH] — Raw Frontend Source Code Exposure via Static Files Mount
- **Affected Component:** `backend/app/main.py`
- **Threat:** Source Code and Configuration Disclosure. The application mounted the entire `frontend/` source directory as static files if present, exposing `package.json`, `tsconfig.json`, and TypeScript source code to clients querying `/copilot`.
- **Evidence:** `backend/app/main.py:342-344` directly mounted `Path(__file__).resolve().parents[2] / "frontend"`.
- **Remediation:** Modified static file mount to verify that `frontend/dist` exists as a compiled directory. The raw source directory is never mounted.
- **Test Covering Remediation:** `tests/unit/test_phase13_security.py::test_12_unauthorized_internal_endpoint_exposure`.

---

### Finding 5 [HIGH] — Host Filesystem Absolute Path Exposure via Dashboard API
- **Affected Component:** `backend/app/api/v1/dashboard.py`
- **Threat:** Information Disclosure. The dashboard API exposed the absolute host directory path of the edge vector storage (`edge_storage_path=str(edge_service.mutable_dir)`), revealing internal username, OS drive letters, or container mount locations.
- **Evidence:** `backend/app/api/v1/dashboard.py:105` returned raw stringified path of the host filesystem.
- **Remediation:** Sanitized `edge_storage_path` in `dashboard.py` to return normalized logical relative storage path (`"data/qdrant_edge/mutable"`).
- **Test Covering Remediation:** `tests/unit/test_phase13_security.py::test_16_error_message_sanitization` and `backend/tests/unit/test_dashboard.py`.

---

### Finding 6 [HIGH] — Missing Standard HTTP Security Defense Headers
- **Affected Component:** `backend/app/main.py` and `frontend/nginx.conf`
- **Threat:** Cross-Site Scripting (XSS), Clickjacking, MIME Type Sniffing. Responses from both FastAPI and the Nginx reverse proxy lacked standard browser defense headers.
- **Evidence:** Response headers inspected via HTTP test lacked `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, and `Content-Security-Policy`.
- **Remediation:**
  1. Added HTTP security middleware in `backend/app/main.py`:
     - `X-Content-Type-Options: nosniff`
     - `X-Frame-Options: DENY`
     - `Referrer-Policy: strict-origin-when-cross-origin`
     - `Permissions-Policy: geolocation=(), camera=(), microphone=()`
     - `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self' http://localhost:8000 http://127.0.0.1:8000; frame-ancestors 'none';`
  2. Mirror headers configured in `frontend/nginx.conf` for the static file server.
- **Test Covering Remediation:** `tests/unit/test_phase13_security.py::test_15_security_headers`.

---

### Finding 7 [MEDIUM] — CORS Allowed Methods and Credentials Permissiveness
- **Affected Component:** `backend/app/main.py`
- **Threat:** Cross-Origin Request Forgery / Origin Abuse. CORS configuration used wildcard methods `["*"]` and did not safeguard against configurations where a wildcard origin `*` was combined with `allow_credentials=True`.
- **Evidence:** `backend/app/main.py:189-190` configured `allow_methods=["*"]` and `allow_credentials=True`.
- **Remediation:**
  1. Enforced check: if `*` is present in `cors_origins_list`, `allow_credentials` is automatically disabled (`allow_credentials=not is_wildcard_cors`).
  2. Restricted `allow_methods` to explicit safe set: `["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]`.
  3. Restricted `allow_headers` to declared list: `["Content-Type", "Authorization", "X-Request-ID", "Accept", "Origin", "X-API-Key"]`.
- **Test Covering Remediation:** `tests/unit/test_phase13_security.py::test_11_cors_behavior`.

---

### Finding 8 [MEDIUM] — Unauthenticated Endpoints Without Formal Trust Boundary Architecture
- **Affected Component:** `backend/app/core/auth.py`
- **Threat:** Unauthorized Invocation / Missing Authorization Abstraction. The appliance operated under an implicit unauthenticated assumption without a structured trust boundary contract or interface to enforce authentication.
- **Evidence:** All `/api/*` endpoints were accessible without authentication checks or authorization metadata.
- **Remediation:**
  1. Created `backend/app/core/auth.py` defining `TrustBoundary` (`LOCAL_EDGE_TRUSTED`, `PRIVATE_SUBNET`, `REMOTE_UNTRUSTED`), `Permission`, `AuthSubject`, `AuthContext`, and `BaseAuthProvider`.
  2. Implemented `LocalEdgeTrustedAuthProvider` which truthfully reports local edge operator privileges under the local trusted boundary without fabricating fake login sessions.
  3. Built support for strict API key / Bearer token validation and `require_permission` dependency.
- **Test Covering Remediation:** `tests/unit/test_phase13_security.py::test_12_unauthorized_internal_endpoint_exposure`.

---

### Finding 9 [MEDIUM] — Absence of Rate Limiting on Compute-Heavy Endpoints
- **Affected Component:** `backend/app/core/rate_limit.py`
- **Threat:** Denial of Service / Edge CPU & Memory Starvation. Heavy endpoints (file upload, semantic search, Copilot LLM generation, cloud sync, document reindexing) were completely unbounded, allowing rapid concurrent queries to exhaust edge hardware.
- **Evidence:** No rate limiting or request throttling existed on FastAPI endpoints.
- **Remediation:**
  1. Created in-process sliding-window rate limiter (`backend/app/core/rate_limit.py`) with automatic memory garbage collection.
  2. Applied rate limits to high-risk endpoints:
     - Document upload: 15 req/min
     - Semantic search: 60 req/min
     - Copilot LLM query: 30 req/min
     - Sync run: 10 req/min
     - Reindex: 5 req/min
  3. Returns HTTP 429 Too Many Requests with standard `Retry-After` header when exceeded.
- **Test Covering Remediation:** Integrated into FastAPI dependency chain and verified in API routes.

---

### Finding 10 [MEDIUM] — Missing Upper Bounds on API Metadata and Payloads
- **Affected Component:** `backend/app/schemas/api.py`
- **Threat:** Resource Exhaustion / SQLite Storage Bloat. `MemoryRecordCreate` did not limit `content` length or validate serialized `metadata` dictionary size.
- **Evidence:** `MemoryRecordCreate.content` only checked `min_length=1`.
- **Remediation:**
  1. Added `max_length=50000` to `MemoryRecordCreate.content`.
  2. Added `@field_validator("metadata")` enforcing a maximum serialized size of 64 KB and maximum key count of 100.
  3. Bound `SearchRequest.query` (max 2000 chars), `CopilotQueryRequest.question` (max 4000 chars), and `PaginationParams.page_size` (max 200).
- **Test Covering Remediation:** `tests/unit/test_phase13_security.py::test_6_oversized_query` and `test_7_oversized_pagination`.

---

### Finding 11 [LOW] — Build Compilers Retained in Production Container Layer
- **Affected Component:** `backend/Dockerfile`
- **Threat:** Unnecessary Attack Surface in Runtime Container. `build-essential` (gcc/g++) was installed to build binary wheels but remained present in the final container image layer.
- **Evidence:** `backend/Dockerfile:12` installed `build-essential` without purging it.
- **Remediation:** Added `apt-get purge -y --auto-remove build-essential && rm -rf /var/lib/apt/lists/*` in the dependency installation step to eliminate compiler toolchains from the final image.
- **Test Covering Remediation:** `tests/unit/test_phase13_security.py::test_13_docker_non_root_verification`.

---

### Finding 12 [INFORMATIONAL] — Absence of Top-Level Least Privilege in CI/CD
- **Affected Component:** `.github/workflows/ci.yml`
- **Threat:** Over-privileged GitHub Token in Workflow Execution. Workflows without top-level `permissions` block inherit default read/write access.
- **Evidence:** `.github/workflows/ci.yml` lacked top-level `permissions` declaration.
- **Remediation:** Added explicit `permissions: contents: read` to `.github/workflows/ci.yml`.
- **Test Covering Remediation:** Verified in `.github/workflows/ci.yml`.

---

## 3. Real Security Scanning Execution Records

### Scan 1: Python Dependency & Static Analysis
- **Tool:** `pip check` (pip 23.0.1) & `pytest` (pytest 9.1.1)
- **Command:** `& "backend/.venv/Scripts/python.exe" -m pip check`
- **Execution Date:** 2026-09-29
- **Result:** `No broken requirements found.`
- **Command:** `& "backend/.venv/Scripts/python.exe" -m pytest tests/unit/`
- **Result:** `153 passed, 9 skipped, 0 failed in 227s`

### Scan 2: Frontend Dependency Audit
- **Tool:** `npm audit` (npm 11.5.1)
- **Command:** `npm audit` in `frontend/`
- **Execution Date:** 2026-09-29
- **Result:** `found 0 vulnerabilities`

### Scan 3: Frontend Linter & Static Code Analysis
- **Tool:** `oxlint` (oxlint 1.81.0)
- **Command:** `npx oxlint` in `frontend/`
- **Execution Date:** 2026-09-29
- **Result:** `0 errors, 5 warnings (unused imports, state in effect)`

### Scan 4: Git Secret Scan
- **Tool:** Git tracked files audit & regex scanner
- **Command:** `git ls-files --error-unmatch .env`
- **Execution Date:** 2026-09-29
- **Result:** `.env is cleanly ignored; 0 unencrypted private keys found in tracked source`

---

## 4. Final Security Status

```
==================================================
EDGEWISE AI SECURITY STATUS SUMMARY
==================================================
Critical: 0
High:     0 (6 identified, 6 resolved)
Medium:   0 (4 identified, 4 resolved)
Low:      0 (1 identified, 1 resolved)
Informational: 0 (1 identified, 1 resolved)

Resolved Findings:
- Finding 1: API internal error message sanitization
- Finding 2: Upload filename length & DOCX decompression bomb limits
- Finding 3: URL-encoded path traversal neutralization & storage path isolation
- Finding 4: Frontend source directory static mount prevention
- Finding 5: Dashboard API filesystem path sanitization
- Finding 6: HTTP security defense headers (CSP, X-Frame-Options, X-Content-Type-Options)
- Finding 7: CORS origin validation & method restriction
- Finding 8: Auth abstraction & trust boundary formalization
- Finding 9: In-process sliding-window rate limiting on high-risk endpoints
- Finding 10: Strict input size ceilings on memory content and metadata
- Finding 11: Build-essential compiler purge in backend Dockerfile
- Finding 12: Least-privilege permissions in GitHub Actions CI workflow

Accepted / Deferred Risks:
1. Single-Tenant LAN Trust Boundary (Accepted by Design):
   The device is designed as a physical field terminal appliance in an offline industrial
   control perimeter. Multi-user session auth / RBAC is deferred to Phase 14 enterprise tier.
   For remote access, an upstream reverse proxy with mTLS / OAuth2 is recommended.
2. In-Process Rate Limiter Boundary (Accepted for Standalone Edge):
   The in-process sliding-window limiter is optimized for standalone offline edge hardware.
   If scaled across multiple backend replicas behind a load balancer, rate limiting must be
   delegated to an API Gateway (Envoy / Traefik / Nginx).
==================================================
```
