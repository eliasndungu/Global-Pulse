"""
Global-Pulse – Pydantic request/response schemas.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field


# ──────────────────────────────────────────────────────────────
#  Customers & API Keys
# ──────────────────────────────────────────────────────────────

class CustomerCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr


class CustomerResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    email: str
    is_active: bool
    created_at: datetime


class APIKeyCreateRequest(BaseModel):
    label: str | None = Field(None, max_length=100)


class APIKeyResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    customer_id: uuid.UUID
    key_prefix: str
    label: str | None
    expires_at: datetime | None
    created_at: datetime
    raw_key: str | None = None  # only present on initial creation


# ──────────────────────────────────────────────────────────────
#  Vessel Positions
# ──────────────────────────────────────────────────────────────

class VesselPositionResponse(BaseModel):
    model_config = {"from_attributes": True}

    mmsi: str
    vessel_name: str | None
    latitude: float
    longitude: float
    speed_knots: float | None
    heading: float | None
    destination: str | None
    status: str | None
    timestamp: datetime
    source: str


# ──────────────────────────────────────────────────────────────
#  Shipping Routes
# ──────────────────────────────────────────────────────────────

class ShippingRouteResponse(BaseModel):
    model_config = {"from_attributes": True}

    timestamp: datetime
    origin_port: str
    destination_port: str
    vessel_count: int
    avg_transit_days: float | None
    congestion_score: float | None


# ──────────────────────────────────────────────────────────────
#  Weather
# ──────────────────────────────────────────────────────────────

class WeatherObservationResponse(BaseModel):
    model_config = {"from_attributes": True}

    timestamp: datetime
    location_name: str
    latitude: float
    longitude: float
    temperature_c: float | None
    wind_speed_ms: float | None
    wind_direction: float | None
    wave_height_m: float | None
    visibility_km: float | None
    condition: str | None
    source: str


# ──────────────────────────────────────────────────────────────
#  News
# ──────────────────────────────────────────────────────────────

class NewsArticleResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    published_at: datetime
    title: str
    summary: str | None
    url: str
    source_feed: str
    tags: str | None


# ──────────────────────────────────────────────────────────────
#  Forecasting
# ──────────────────────────────────────────────────────────────

class ForecastRequest(BaseModel):
    origin_port: str = Field(..., examples=["Shanghai"])
    destination_port: str = Field(..., examples=["Rotterdam"])
    horizon_days: int = Field(default=7, ge=1, le=30)


class ForecastPointResponse(BaseModel):
    model_config = {"from_attributes": True, "protected_namespaces": ()}

    forecast_date: datetime
    predicted_delay_days: float
    confidence_lower: float | None
    confidence_upper: float | None
    model_version: str


class ForecastResponse(BaseModel):
    origin_port: str
    destination_port: str
    forecasts: list[ForecastPointResponse]
