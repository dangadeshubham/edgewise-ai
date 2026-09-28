"""
Pytest configuration and shared fixtures for EDGEWISE AI tests.
"""

import os
import shutil
import tempfile
from pathlib import Path
from typing import AsyncGenerator

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Set testing environment variables before importing app modules
os.environ["AUTO_REGISTER_LOCAL_DEVICE"] = "false"

from app.core.config import get_settings
from app.core.database import get_db
from app.main import app


@pytest.fixture(scope="session")
def temp_data_dir():
    """Create a temporary directory for test database and shards."""
    temp_dir = tempfile.mkdtemp(prefix="edgewise_test_")
    yield Path(temp_dir)
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture(scope="session")
def test_db_path(temp_data_dir):
    """Path to the test SQLite database file."""
    db_file = temp_data_dir / "test_edgewise.db"
    return db_file


@pytest.fixture(scope="session")
def test_db_url(test_db_path):
    """Async SQLAlchemy database URL for tests."""
    return f"sqlite+aiosqlite:///{test_db_path.as_posix()}"


@pytest.fixture(scope="session")
def run_alembic_upgrade(test_db_path):
    """Run Alembic migrations on the test database."""
    backend_dir = Path(__file__).resolve().parents[1]
    alembic_cfg = Config(backend_dir / "alembic.ini")
    sync_url = f"sqlite:///{test_db_path.as_posix()}"
    alembic_cfg.set_main_option("sqlalchemy.url", sync_url)
    alembic_cfg.set_main_option("script_location", str(backend_dir / "alembic"))

    # Run upgrade head
    command.upgrade(alembic_cfg, "head")
    return alembic_cfg


@pytest.fixture(scope="session")
def async_engine(test_db_url, run_alembic_upgrade):
    """Create test async engine."""
    engine = create_async_engine(
        test_db_url,
        echo=False,
        connect_args={"check_same_thread": False},
    )
    yield engine


@pytest.fixture
async def db_session(async_engine) -> AsyncGenerator[AsyncSession, None]:
    """Yield an async session for a single test and clean up tables afterwards."""
    session_factory = async_sessionmaker(
        async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as session:
        yield session

    # Truncate tables to ensure complete test isolation
    async with session_factory() as clean_session:
        try:
            await clean_session.execute(text("DROP TRIGGER IF EXISTS trg_audit_events_prevent_delete"))
            await clean_session.execute(text("DROP TRIGGER IF EXISTS trg_audit_events_prevent_update"))
        except Exception:
            pass
        for tbl in [
            "conversation_messages",
            "conversations",
            "audit_events",
            "conflicts",
            "sync_attempts",
            "sync_items",
            "memory_records",
            "document_chunks",
            "document_versions",
            "documents",
            "sources",
            "devices",
        ]:
            await clean_session.execute(text(f"DELETE FROM {tbl}"))
        await clean_session.commit()


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Provide an AsyncClient with overridden database dependency."""
    async def override_get_db():
        try:
            yield db_session
            await db_session.commit()
        except Exception:
            await db_session.rollback()
            raise

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    app.dependency_overrides.clear()
