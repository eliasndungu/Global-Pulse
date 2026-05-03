"""
Alembic environment for Global-Pulse.

Reads the DB URL from the same ``get_db_url()`` helper used by the
application so that there is a single source of truth for connection
settings.  The ORM Base is imported so Alembic can diff the schema
for ``--autogenerate``.
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# ── Make project root importable ─────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from db.connection import Base  # noqa: E402  (after sys.path setup)
from db.settings import get_db_url  # noqa: E402

# ── Alembic config object ────────────────────────────────────
config = context.config

# Inject the dynamic DB URL so alembic.ini can stay URL-free
config.set_main_option("sqlalchemy.url", get_db_url())

# Set up file-based logging from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import all models so Alembic can detect them for autogenerate
import db.models  # noqa: F401, E402

target_metadata = Base.metadata


# ── Offline mode (generate SQL without a live DB) ────────────

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Generates SQL scripts without connecting to the database.
    Useful for generating migration SQL to review before applying.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # TimescaleDB hypertable DDL is handled in the initial migration;
        # tell Alembic not to try to diff those statements.
        include_schemas=False,
    )
    with context.begin_transaction():
        context.run_migrations()


# ── Online mode (connect and apply) ──────────────────────────

def run_migrations_online() -> None:
    """Run migrations in 'online' mode with a live DB connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
