"""
Global-Pulse – Database connection & session management.
Uses SQLAlchemy 2.x with psycopg2 driver for TimescaleDB/PostgreSQL.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from db.settings import get_db_url


# ──────────────────────────────────────────────────────────────
#  Engine
# ──────────────────────────────────────────────────────────────

def _build_engine():
    url = get_db_url()
    engine = create_engine(
        url,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
        echo=bool(os.getenv("SQLALCHEMY_ECHO", "")),
    )
    return engine


engine = _build_engine()

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


# ──────────────────────────────────────────────────────────────
#  Base model
# ──────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""


# ──────────────────────────────────────────────────────────────
#  Dependency helpers
# ──────────────────────────────────────────────────────────────

def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def db_session() -> Generator[Session, None, None]:
    """Context manager for use outside FastAPI (e.g., Airflow tasks)."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
