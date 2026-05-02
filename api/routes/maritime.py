"""
Global-Pulse – Maritime Routes
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api.middleware.auth import require_api_key
from api.schemas import ShippingRouteResponse, VesselPositionResponse
from db.connection import get_db
from db.models import Customer, ShippingRoute, VesselPosition

router = APIRouter()


@router.get(
    "/vessels",
    response_model=list[VesselPositionResponse],
    summary="Latest vessel positions (last 10 minutes)",
)
def get_vessel_positions(
    customer: Annotated[Customer, Depends(require_api_key)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(default=100, ge=1, le=1000),
    mmsi: str | None = Query(default=None, description="Filter by MMSI"),
) -> list[VesselPosition]:
    q = db.query(VesselPosition).order_by(VesselPosition.timestamp.desc())
    if mmsi:
        q = q.filter(VesselPosition.mmsi == mmsi)
    return q.limit(limit).all()


@router.get(
    "/routes",
    response_model=list[ShippingRouteResponse],
    summary="Aggregated shipping route metrics",
)
def get_shipping_routes(
    customer: Annotated[Customer, Depends(require_api_key)],
    db: Annotated[Session, Depends(get_db)],
    origin: str | None = Query(default=None),
    destination: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
) -> list[ShippingRoute]:
    q = db.query(ShippingRoute).order_by(ShippingRoute.timestamp.desc())
    if origin:
        q = q.filter(ShippingRoute.origin_port == origin)
    if destination:
        q = q.filter(ShippingRoute.destination_port == destination)
    return q.limit(limit).all()
