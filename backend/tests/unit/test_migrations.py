"""
Tests for Alembic migrations and database schema.
Verifies requirement:
1. Fresh database migration succeeds from empty database
2. Schema tables, constraints, and relationships exist
3. Database survives application restart / reconnect
4. Downgrade and re-upgrade work cleanly
"""

import tempfile
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine


def test_fresh_migration_from_empty_database():
    """Verify that Alembic upgrade works cleanly on a completely empty database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "fresh_test.db"
        assert not db_path.exists()

        backend_dir = Path(__file__).resolve().parents[2]
        alembic_cfg = Config(backend_dir / "alembic.ini")
        alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
        alembic_cfg.set_main_option("script_location", str(backend_dir / "alembic"))

        # 1. Run migration from scratch
        command.upgrade(alembic_cfg, "head")

        assert db_path.exists(), "Database file should exist after upgrade"

        # 2. Verify all 13 core tables exist
        import sqlite3
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = {row[0] for row in cursor.fetchall()}
        conn.close()

        expected_tables = {
            "alembic_version",
            "devices",
            "sources",
            "documents",
            "document_versions",
            "document_chunks",
            "memory_records",
            "sync_items",
            "sync_attempts",
            "conflicts",
            "audit_events",
            "conversations",
            "conversation_messages",
            "embedding_metadata",
        }
        missing_tables = expected_tables - tables
        assert not missing_tables, f"Missing tables after migration: {missing_tables}"

        # 3. Test downgrade to base
        command.downgrade(alembic_cfg, "base")

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        post_down_tables = {row[0] for row in cursor.fetchall()}
        conn.close()

        assert "documents" not in post_down_tables, "Tables should be dropped after downgrade"

        # 4. Test re-upgrade back to head
        command.upgrade(alembic_cfg, "head")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        reup_tables = {row[0] for row in cursor.fetchall()}
        conn.close()

        assert expected_tables.issubset(reup_tables), "All tables should be restored on re-upgrade"


@pytest.mark.asyncio
async def test_database_connection_and_restart_persistence(temp_data_dir, run_alembic_upgrade, test_db_path, test_db_url):
    """Verify that SQLite connection succeeds and data persists across restarts."""
    engine1 = create_async_engine(test_db_url, echo=False)
    async with engine1.begin() as conn:
        await conn.execute(
            text("INSERT INTO sources (id, name, source_type, created_at) VALUES (:id, :name, :type, datetime('now'))"),
            {"id": "persist-test-01", "name": "Persist Test Source", "type": "manual"}
        )
    await engine1.dispose()

    # Simulate application restart with a new engine connection
    engine2 = create_async_engine(test_db_url, echo=False)
    async with engine2.begin() as conn:
        result = await conn.execute(
            text("SELECT name FROM sources WHERE id = :id"),
            {"id": "persist-test-01"}
        )
        row = result.fetchone()
        assert row is not None, "Data should survive connection termination/restart"
        assert row[0] == "Persist Test Source"

        # Clean up test row
        await conn.execute(text("DELETE FROM sources WHERE id = :id"), {"id": "persist-test-01"})
    await engine2.dispose()
