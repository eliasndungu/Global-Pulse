"""
Tests – REST API
Tests the FastAPI application using the TestClient and an in-memory
SQLite database (so no live PostgreSQL/TimescaleDB is needed).

Note: TimescaleDB-specific DDL (hypertables, compression) is skipped
in tests; we rely only on standard SQLAlchemy ORM operations.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from db.connection import Base, get_db
from api.main import app

# ──────────────────────────────────────────────────────────────
#  In-memory SQLite test database
# ──────────────────────────────────────────────────────────────

SQLITE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLITE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)


@pytest.fixture(autouse=True, scope="module")
def create_tables():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db_session) -> TestClient:
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ──────────────────────────────────────────────────────────────
#  Health & root
# ──────────────────────────────────────────────────────────────

def test_root_endpoint(client):
    resp = client.get("/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["service"] == "Global-Pulse DaaS API"
    assert data["status"] == "ok"


def test_health_endpoint(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ──────────────────────────────────────────────────────────────
#  Customer management
# ──────────────────────────────────────────────────────────────

def test_create_customer(client):
    resp = client.post("/v1/api-keys/customers", json={
        "name": "Acme Shipping Co.",
        "email": "ops@acme.com",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["email"] == "ops@acme.com"
    assert data["is_active"] is True
    assert "id" in data


def test_create_customer_duplicate_email(client):
    payload = {"name": "Beta Corp", "email": "duplicate@beta.com"}
    client.post("/v1/api-keys/customers", json=payload)
    resp = client.post("/v1/api-keys/customers", json=payload)
    assert resp.status_code == 409


def test_get_customer(client):
    create_resp = client.post("/v1/api-keys/customers", json={
        "name": "Gamma Logistics",
        "email": "info@gamma.com",
    })
    customer_id = create_resp.json()["id"]

    resp = client.get(f"/v1/api-keys/customers/{customer_id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Gamma Logistics"


def test_get_customer_not_found(client):
    resp = client.get(f"/v1/api-keys/customers/{uuid.uuid4()}")
    assert resp.status_code == 404


# ──────────────────────────────────────────────────────────────
#  API Key management
# ──────────────────────────────────────────────────────────────

def test_create_and_use_api_key(client, db_session):
    """Full lifecycle: create customer → issue key → use key on protected endpoint."""
    # 1. Create customer
    cust = client.post("/v1/api-keys/customers", json={
        "name": "Delta Trade Ltd",
        "email": "admin@delta.com",
    }).json()
    customer_id = cust["id"]

    # 2. Issue API key
    key_resp = client.post(
        f"/v1/api-keys/customers/{customer_id}/keys",
        json={"label": "test-key"},
    )
    assert key_resp.status_code == 201
    key_data = key_resp.json()
    raw_key = key_data["raw_key"]
    assert raw_key is not None
    assert len(raw_key) > 10

    # 3. Use raw key to call a protected endpoint (weather)
    # No weather data in DB → empty list, but auth should succeed (200)
    weather_resp = client.get(
        "/v1/weather/observations",
        headers={"X-API-Key": raw_key},
    )
    assert weather_resp.status_code == 200


def test_protected_endpoint_requires_key(client):
    """Calling a protected endpoint without an API key returns 401."""
    resp = client.get("/v1/weather/observations")
    assert resp.status_code == 401


def test_protected_endpoint_rejects_invalid_key(client):
    """An invalid API key returns 401."""
    resp = client.get(
        "/v1/weather/observations",
        headers={"X-API-Key": "invalid_key_xyz"},
    )
    assert resp.status_code == 401


def test_revoke_api_key(client):
    """A revoked key can no longer be used."""
    cust = client.post("/v1/api-keys/customers", json={
        "name": "Epsilon Global",
        "email": "cto@epsilon.com",
    }).json()
    customer_id = cust["id"]

    key_data = client.post(
        f"/v1/api-keys/customers/{customer_id}/keys",
        json={"label": "temp-key"},
    ).json()
    raw_key = key_data["raw_key"]
    key_id = key_data["id"]

    # Confirm key works
    assert client.get(
        "/v1/weather/observations",
        headers={"X-API-Key": raw_key},
    ).status_code == 200

    # Revoke
    revoke_resp = client.delete(f"/v1/api-keys/customers/{customer_id}/keys/{key_id}")
    assert revoke_resp.status_code == 204

    # Key should no longer work
    assert client.get(
        "/v1/weather/observations",
        headers={"X-API-Key": raw_key},
    ).status_code == 401


def test_list_api_keys(client):
    cust = client.post("/v1/api-keys/customers", json={
        "name": "Zeta Corp",
        "email": "keys@zeta.com",
    }).json()
    customer_id = cust["id"]

    # Issue two keys
    client.post(f"/v1/api-keys/customers/{customer_id}/keys", json={"label": "key-1"})
    client.post(f"/v1/api-keys/customers/{customer_id}/keys", json={"label": "key-2"})

    resp = client.get(f"/v1/api-keys/customers/{customer_id}/keys")
    assert resp.status_code == 200
    keys = resp.json()
    assert len(keys) == 2
    labels = {k["label"] for k in keys}
    assert labels == {"key-1", "key-2"}
