"""
EDGEWISE AI — Database Engine & Session Management

Async SQLite via SQLAlchemy + aiosqlite.
"""

from __future__ import annotations

from pathlib import Path
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

settings = get_settings()

# Ensure the database directory exists
db_path = settings.sqlite_database_url.replace("sqlite+aiosqlite:///", "")
Path(db_path).parent.mkdir(parents=True, exist_ok=True)

engine = create_async_engine(
    settings.sqlite_database_url,
    echo=False,
    connect_args={"check_same_thread": False},
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency: yields an async database session."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


from sqlalchemy import text


async def install_audit_immutability(conn) -> None:
    """Installs database triggers to enforce append-only immutability on audit_events."""
    await conn.execute(
        text(
            """
            CREATE TRIGGER IF NOT EXISTS trg_audit_events_prevent_update
            BEFORE UPDATE ON audit_events
            BEGIN
                SELECT RAISE(ABORT, 'Audit events are strictly append-only and immutable');
            END;
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE TRIGGER IF NOT EXISTS trg_audit_events_prevent_delete
            BEFORE DELETE ON audit_events
            BEGIN
                SELECT RAISE(ABORT, 'Audit events are strictly append-only and immutable');
            END;
            """
        )
    )


async def init_db() -> None:
    """Create all tables and install immutability triggers. Used for initial setup."""
    from app.models.database import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await install_audit_immutability(conn)


async def close_db() -> None:
    """Dispose engine connections."""
    await engine.dispose()
