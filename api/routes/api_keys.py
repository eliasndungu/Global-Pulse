"""
Global-Pulse – API Key Management Routes
==========================================
Endpoints for B2B customers to:
  • Register as a customer
  • Issue/revoke API keys
  • List their active keys

All management endpoints require Bearer-token auth (admin JWT) in
a production deployment.  For this scaffold the endpoints are
left open so they can be secured at the infrastructure layer
(gateway / mTLS) or by adding an admin-role dependency.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from api.config import get_settings
from api.schemas import (
    APIKeyCreateRequest,
    APIKeyResponse,
    CustomerCreateRequest,
    CustomerResponse,
)
from db.connection import get_db
from db.models import APIKey, Customer

router = APIRouter()
pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ──────────────────────────────────────────────────────────────
#  Customers
# ──────────────────────────────────────────────────────────────

@router.post(
    "/customers",
    response_model=CustomerResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new B2B customer",
)
def create_customer(
    body: CustomerCreateRequest,
    db: Annotated[Session, Depends(get_db)],
) -> Customer:
    existing = db.query(Customer).filter_by(email=body.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A customer with this email already exists.",
        )
    customer = Customer(name=body.name, email=body.email)
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


@router.get(
    "/customers/{customer_id}",
    response_model=CustomerResponse,
    summary="Get customer details",
)
def get_customer(
    customer_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
) -> Customer:
    customer = db.query(Customer).filter_by(id=customer_id).first()
    if not customer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found.")
    return customer


# ──────────────────────────────────────────────────────────────
#  API Keys
# ──────────────────────────────────────────────────────────────

@router.post(
    "/customers/{customer_id}/keys",
    response_model=APIKeyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Issue a new API key for a customer",
)
def create_api_key(
    customer_id: uuid.UUID,
    body: APIKeyCreateRequest,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    customer = db.query(Customer).filter_by(id=customer_id, is_active=True).first()
    if not customer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found.")

    settings = get_settings()
    raw_key = secrets.token_urlsafe(32)
    prefix = raw_key[:8]
    key_hash = pwd_ctx.hash(raw_key)

    expires_at = None
    if settings.api_key_expire_days > 0:
        expires_at = datetime.now(timezone.utc) + timedelta(days=settings.api_key_expire_days)

    api_key = APIKey(
        customer_id=customer_id,
        key_prefix=prefix,
        key_hash=key_hash,
        label=body.label,
        expires_at=expires_at,
    )
    db.add(api_key)
    db.commit()
    db.refresh(api_key)

    # Return the raw key ONCE – it cannot be recovered later
    return {
        "id": api_key.id,
        "customer_id": api_key.customer_id,
        "key_prefix": api_key.key_prefix,
        "label": api_key.label,
        "expires_at": api_key.expires_at,
        "created_at": api_key.created_at,
        "raw_key": raw_key,  # only returned at creation time
    }


@router.delete(
    "/customers/{customer_id}/keys/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Revoke an API key",
)
def revoke_api_key(
    customer_id: uuid.UUID,
    key_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
) -> None:
    api_key = (
        db.query(APIKey)
        .filter_by(id=key_id, customer_id=customer_id, is_active=True)
        .first()
    )
    if not api_key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found.")
    api_key.is_active = False
    db.commit()


@router.get(
    "/customers/{customer_id}/keys",
    response_model=list[APIKeyResponse],
    summary="List active API keys for a customer",
)
def list_api_keys(
    customer_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
) -> list[APIKey]:
    return (
        db.query(APIKey)
        .filter_by(customer_id=customer_id, is_active=True)
        .all()
    )
