"""
Alembic environment configuration for EDGEWISE AI.
"""

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Add backend to path so we can import our models
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.models.database import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

custom_url = config.get_main_option("sqlalchemy.url")
if not custom_url or custom_url == "sqlite:///./data/sqlite/edgewise.db":
    settings = get_settings()
    sync_url = settings.sqlite_database_url.replace("sqlite+aiosqlite:///", "sqlite:///")
    config.set_main_option("sqlalchemy.url", sync_url)
    target_url = sync_url
else:
    target_url = custom_url

# Ensure database directory exists
db_file_str = target_url.replace("sqlite:///", "")
if db_file_str and not db_file_str.startswith(":memory:"):
    Path(db_file_str).parent.mkdir(parents=True, exist_ok=True)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
