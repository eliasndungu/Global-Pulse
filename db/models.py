"""
Global-Pulse – ORM models (SQLAlchemy 2.x).
All time-series tables are converted to TimescaleDB hypertables
via the migration script (001_initial_schema.sql).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.connection import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ──────────────────────────────────────────────────────────────
#  API Key Management
# ──────────────────────────────────────────────────────────────

class Customer(Base):
    """B2B customer record."""

    __tablename__ = "customers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )

    api_keys: Mapped[list["APIKey"]] = relationship(
        back_populates="customer", cascade="all, delete-orphan"
    )


class APIKey(Base):
    """Hashed API key issued to a B2B customer."""

    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    key_prefix: Mapped[str] = mapped_column(String(10), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    label: Mapped[str] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    customer: Mapped["Customer"] = relationship(back_populates="api_keys")


# ──────────────────────────────────────────────────────────────
#  Maritime / Shipping
# ──────────────────────────────────────────────────────────────

class VesselPosition(Base):
    """AIS vessel position snapshot – TimescaleDB hypertable on *timestamp*."""

    __tablename__ = "vessel_positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    mmsi: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    vessel_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    speed_knots: Mapped[float | None] = mapped_column(Float, nullable=True)
    heading: Mapped[float | None] = mapped_column(Float, nullable=True)
    destination: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source: Mapped[str] = mapped_column(String(50), default="marinetraffic", nullable=False)


class ShippingRoute(Base):
    """Aggregated shipping route metrics – TimescaleDB hypertable."""

    __tablename__ = "shipping_routes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    origin_port: Mapped[str] = mapped_column(String(100), nullable=False)
    destination_port: Mapped[str] = mapped_column(String(100), nullable=False)
    vessel_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    avg_transit_days: Mapped[float | None] = mapped_column(Float, nullable=True)
    congestion_score: Mapped[float | None] = mapped_column(Float, nullable=True)


# ──────────────────────────────────────────────────────────────
#  Weather
# ──────────────────────────────────────────────────────────────

class WeatherObservation(Base):
    """Weather reading at a port/location – TimescaleDB hypertable."""

    __tablename__ = "weather_observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    location_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    wind_speed_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    wind_direction: Mapped[float | None] = mapped_column(Float, nullable=True)
    wave_height_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    visibility_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    condition: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source: Mapped[str] = mapped_column(String(50), default="openweathermap", nullable=False)


# ──────────────────────────────────────────────────────────────
#  News / RSS
# ──────────────────────────────────────────────────────────────

class NewsArticle(Base):
    """Parsed news article from RSS feeds."""

    __tablename__ = "news_articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str] = mapped_column(String(1000), nullable=False, unique=True)
    source_feed: Mapped[str] = mapped_column(String(255), nullable=False)
    tags: Mapped[str | None] = mapped_column(String(500), nullable=True)

    __table_args__ = (UniqueConstraint("url", name="uq_news_url"),)


# ──────────────────────────────────────────────────────────────
#  Forecast results
# ──────────────────────────────────────────────────────────────

class DelayForecast(Base):
    """Stored delay forecast for a shipping route."""

    __tablename__ = "delay_forecasts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False, index=True
    )
    origin_port: Mapped[str] = mapped_column(String(100), nullable=False)
    destination_port: Mapped[str] = mapped_column(String(100), nullable=False)
    forecast_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    predicted_delay_days: Mapped[float] = mapped_column(Float, nullable=False)
    confidence_lower: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_upper: Mapped[float | None] = mapped_column(Float, nullable=True)
    model_version: Mapped[str] = mapped_column(String(50), nullable=False)
