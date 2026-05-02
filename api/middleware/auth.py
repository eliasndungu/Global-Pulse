"""
Global-Pulse – Auth Middleware / API-Key dependency
====================================================
FastAPI dependency that validates an incoming X-API-Key header
against the bcrypt-hashed keys stored in TimescaleDB.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from db.connection import get_db
from db.models import APIKey, Customer

logger = logging.getLogger(__name__)

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(
    raw_key: Annotated[str | None, Security(api_key_header)],
    db: Annotated[Session, Depends(get_db)],
) -> Customer:
    """
    FastAPI dependency.  Validates X-API-Key header.
    Returns the associated Customer on success, raises 401 on failure.
    """
    if not raw_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key header.",
        )

    prefix = raw_key[:8]

    # Candidate lookup by prefix (avoids full-table bcrypt scan)
    candidates = (
        db.query(APIKey)
        .filter(
            APIKey.key_prefix == prefix,
            APIKey.is_active.is_(True),
        )
        .all()
    )

    matched: APIKey | None = None
    for candidate in candidates:
        if pwd_ctx.verify(raw_key, candidate.key_hash):
            matched = candidate
            break

    if matched is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired API key.",
        )

    # Check expiry
    if matched.expires_at:
        expires_at = matched.expires_at
        # Normalise to UTC-aware for databases that store naive datetimes (e.g. SQLite in tests)
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at < datetime.now(timezone.utc):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API key has expired.",
            )

    # Update last-used timestamp (fire-and-forget style)
    try:
        matched.last_used_at = datetime.now(timezone.utc)
        db.commit()
    except Exception:  # noqa: BLE001
        logger.warning("Failed to update last_used_at for API key %s", matched.id, exc_info=True)
        db.rollback()

    customer = db.query(Customer).filter_by(id=matched.customer_id, is_active=True).first()
    if not customer:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Customer account is inactive.",
        )

    return customer
