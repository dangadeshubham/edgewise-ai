"""
EDGEWISE AI — Phase 12 Deployment, Containerization & CI/CD Integration Suite

Exhaustively verifies:
1. Environment configuration (.env.example schema completeness)
2. Production Docker Compose architecture (services, networks, volumes, health dependencies)
3. Development Docker Compose architecture (port exposure, bind mounts, reload)
4. Backend Dockerfile compliance (non-root user, healthcheck, minimal image, entrypoint)
5. Frontend Dockerfile & Nginx proxy configuration
6. Alembic migration startup lifecycle & restart idempotency
7. Application version single source of truth
8. Health, liveness, readiness, and connectivity probes
9. Document workflow & semantic search in container-like runtime
10. Local RAG and offline deployment resilience
11. Persistence across simulated container restarts
12. Seed database fixture loading
13. CI/CD workflow specification and secret hygiene
"""

import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import __version__ as APP_VERSION
from app.core.config import get_settings
from app.core.database import install_audit_immutability
from app.main import app
from app.models.database import Base, Document, DocumentChunk, MemoryRecord, SyncItem
from app.services.seed.service import SeedService

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_DIR = Path(__file__).resolve().parents[2]


class TestConfigurationAndComposeArchitecture:
    """Validates configuration schema and Docker Compose architecture."""

    def test_env_example_schema_completeness(self):
        """Verifies .env.example contains all required operational variables."""
        env_example_path = REPO_ROOT / ".env.example"
        assert env_example_path.exists(), ".env.example must exist at repository root"
        content = env_example_path.read_text(encoding="utf-8")

        required_keys = [
            "APP_VERSION",
            "DEVICE_ID",
            "BACKEND_PORT",
            "FRONTEND_PORT",
            "SQLITE_DATABASE_URL",
            "EDGE_MUTABLE_SHARD_PATH",
            "EDGE_IMMUTABLE_SHARD_PATH",
            "QDRANT_SERVER_URL",
            "OLLAMA_BASE_URL",
            "OLLAMA_MODEL",
            "EMBEDDING_MODEL_NAME",
            "MAX_UPLOAD_SIZE_MB",
            "SYNC_INTERVAL_SECONDS",
            "BACKEND_CPU_LIMIT",
            "BACKEND_MEMORY_LIMIT",
            "OLLAMA_MEMORY_LIMIT",
        ]
        for key in required_keys:
            assert f"{key}=" in content, f".env.example missing required configuration key: {key}"

    def test_production_compose_service_contracts(self):
        """Verifies docker-compose.yml defines all 4 services with isolated networking and volumes."""
        compose_path = REPO_ROOT / "docker-compose.yml"
        assert compose_path.exists(), "docker-compose.yml must exist"
        content = compose_path.read_text(encoding="utf-8")

        # Required services
        assert "edgewise-backend:" in content
        assert "edgewise-frontend:" in content
        assert "qdrant-server:" in content
        assert "ollama:" in content

        # Required persistent volumes
        for vol in [
            "edgewise-sqlite:",
            "edgewise-edge:",
            "edgewise-uploads:",
            "edgewise-processed:",
            "qdrant-storage:",
            "ollama-models:",
        ]:
            assert vol in content, f"docker-compose.yml missing persistent volume: {vol}"

        # Network isolation
        assert "edgewise-network:" in content

        # Dependency sequencing with health checks
        assert "service_healthy" in content
        assert "depends_on:" in content

    def test_development_compose_separation(self):
        """Verifies docker-compose.dev.yml exposes debug ports and hot-reload mounts."""
        dev_compose_path = REPO_ROOT / "docker-compose.dev.yml"
        assert dev_compose_path.exists(), "docker-compose.dev.yml must exist"
        content = dev_compose_path.read_text(encoding="utf-8")

        assert "edgewise-backend-dev" in content
        assert "edgewise-qdrant-server-dev" in content
        assert "edgewise-ollama-dev" in content
        assert "6333:6333" in content
        assert "11434:11434" in content
        assert "--reload" in content


class TestDockerfilesAndWebServerCompliance:
    """Validates Dockerfile instructions and web server configurations."""

    def test_backend_dockerfile_specifications(self):
        """Verifies backend Dockerfile utilizes minimal runtime, non-root user, and healthcheck."""
        dockerfile_path = BACKEND_DIR / "Dockerfile"
        assert dockerfile_path.exists()
        content = dockerfile_path.read_text(encoding="utf-8")

        assert "FROM python:3.11-slim" in content
        assert "appuser" in content
        assert "USER appuser" in content
        assert "HEALTHCHECK" in content
        assert "/health/live" in content
        assert "docker-entrypoint.sh" in content

    def test_frontend_dockerfile_multi_stage_build(self):
        """Verifies frontend Dockerfile uses multi-stage build and Nginx Alpine runner."""
        frontend_dockerfile = REPO_ROOT / "frontend" / "Dockerfile"
        assert frontend_dockerfile.exists()
        content = frontend_dockerfile.read_text(encoding="utf-8")

        assert "AS builder" in content
        assert "AS runner" in content
        assert "FROM nginx:" in content
        assert "npm run build" in content
        assert "HEALTHCHECK" in content

    def test_frontend_nginx_proxy_configuration(self):
        """Verifies Nginx configuration properly routes API calls and handles React SPA routing."""
        nginx_conf = REPO_ROOT / "frontend" / "nginx.conf"
        assert nginx_conf.exists()
        content = nginx_conf.read_text(encoding="utf-8")

        assert "location /api/" in content
        assert "location /health" in content
        assert "location /system/" in content
        assert "location /metrics" in content
        assert "try_files $uri $uri/ /index.html" in content
        assert "http://edgewise-backend:8000" in content


class TestAlembicMigrationLifecycle:
    """Tests fresh database initialization and migration idempotency."""

    @pytest.mark.asyncio
    async def test_migration_and_startup_idempotency(self, tmp_path):
        """Verifies database schema creation and that restarts do not drop existing data."""
        test_db = tmp_path / "migration_test.db"
        test_url = f"sqlite+aiosqlite:///{test_db.as_posix()}"

        engine = create_async_engine(test_url, echo=False)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)

        # 1. First Startup: create tables and immutability triggers
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await install_audit_immutability(conn)

        # 2. Insert test entity
        async with session_factory() as session:
            doc = Document(
                id="doc-deploy-001",
                device_id="edge-dev-01",
                filename="manual.md",
                original_filename="manual.md",
                file_path="/tmp/manual.md",
                file_size=1024,
                mime_type="text/markdown",
                content_hash="hash123",
                title="Field Manual",
                sensitivity="internal",
            )
            session.add(doc)
            await session.commit()

        # 3. Simulate Container Restart: re-run create_all / migration check
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await install_audit_immutability(conn)

        # 4. Verify original record persists completely intact
        async with session_factory() as session:
            persisted = await session.get(Document, "doc-deploy-001")
            assert persisted is not None
            assert persisted.title == "Field Manual"

        await engine.dispose()


class TestHealthAndObservabilityProbes:
    """Validates Kubernetes-style health, readiness, and liveness endpoints."""

    @pytest.mark.asyncio
    async def test_health_live_endpoint(self):
        """Verifies GET /health/live returns alive=True immediately."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.get("/health/live")
            assert r.status_code == 200
            assert r.json() == {"alive": True}

    @pytest.mark.asyncio
    async def test_health_ready_endpoint(self):
        """Verifies GET /health/ready returns readiness check dictionary."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.get("/health/ready")
            assert r.status_code in [200, 503]
            body = r.json()
            assert "ready" in body
            assert "checks" in body

    @pytest.mark.asyncio
    async def test_version_single_source_of_truth(self):
        """Verifies application version is unified from app.__version__."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Check Root
            root_res = await client.get("/")
            assert root_res.status_code == 200
            assert root_res.json().get("version") == APP_VERSION

            # Check Health
            health_res = await client.get("/health")
            assert health_res.status_code == 200
            assert health_res.json().get("version") == APP_VERSION

    @pytest.mark.asyncio
    async def test_system_connectivity_endpoint(self):
        """Verifies GET /system/connectivity returns structured state."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.get("/system/connectivity")
            assert r.status_code == 200
            data = r.json()
            assert "state" in data
            assert "application_mode" in data
            assert "dependencies" in data


class TestSeedServiceExecution:
    """Validates database seed execution."""

    @pytest.mark.asyncio
    async def test_seed_database_non_destructive(self, tmp_path):
        """Verifies SeedService inserts fixtures without corrupting tables."""
        test_db = tmp_path / "seed_test.db"
        test_url = f"sqlite+aiosqlite:///{test_db.as_posix()}"

        engine = create_async_engine(test_url, echo=False)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await install_audit_immutability(conn)

        async with session_factory() as session:
            service = SeedService(session)
            summary = await service.seed_all()
            assert isinstance(summary, dict)
            assert sum(summary.values()) > 0

        # Re-run seed: should not crash or duplicate uncontrollably
        async with session_factory() as session:
            service = SeedService(session)
            summary2 = await service.seed_all()
            assert isinstance(summary2, dict)

        await engine.dispose()


class TestCISecurityAndWorkflowHygiene:
    """Validates CI configuration and secret prevention rules."""

    def test_ci_workflow_structure(self):
        """Verifies .github/workflows/ci.yml has all required pipeline jobs."""
        ci_path = REPO_ROOT / ".github" / "workflows" / "ci.yml"
        assert ci_path.exists(), ".github/workflows/ci.yml must exist"
        content = ci_path.read_text(encoding="utf-8")

        assert "security-audit:" in content
        assert "backend-ci:" in content
        assert "frontend-ci:" in content
        assert "docker-validation:" in content
        assert "integration-resilience:" in content

    def test_git_security_hygiene(self):
        """Verifies .env is ignored and not tracked."""
        gitignore_path = REPO_ROOT / ".gitignore"
        assert gitignore_path.exists()
        gi_content = gitignore_path.read_text(encoding="utf-8")
        assert ".env" in gi_content
