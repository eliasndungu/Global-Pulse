"""
Global-Pulse – Weather Routes
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api.middleware.auth import require_api_key
from api.schemas import WeatherObservationResponse
from db.connection import get_db
from db.models import Customer, WeatherObservation

router = APIRouter()


@router.get(
    "/observations",
    response_model=list[WeatherObservationResponse],
    summary="Latest weather observations for world ports",
)
def get_weather_observations(
    customer: Annotated[Customer, Depends(require_api_key)],
    db: Annotated[Session, Depends(get_db)],
    location: str | None = Query(default=None, description="Filter by port/location name"),
    limit: int = Query(default=50, ge=1, le=500),
) -> list[WeatherObservation]:
    q = db.query(WeatherObservation).order_by(WeatherObservation.timestamp.desc())
    if location:
        q = q.filter(WeatherObservation.location_name.ilike(f"%{location}%"))
    return q.limit(limit).all()
