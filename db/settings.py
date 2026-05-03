"""
Global-Pulse – Database settings helper.
Reads connection details from environment variables.
"""

from __future__ import annotations

import os


def get_db_url() -> str:
    """Return a SQLAlchemy-compatible connection URL from env vars."""
    user = os.getenv("POSTGRES_USER", "globalpulse")
    password = os.getenv("POSTGRES_PASSWORD", "changeme")
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DB", "globalpulse")
    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db}"
