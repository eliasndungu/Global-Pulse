"""
Global-Pulse – Forecasting Routes
===================================
Endpoint to request AI-powered delay forecasts for a shipping route.
Requires a valid X-API-Key header.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from api.middleware.auth import require_api_key
from api.schemas import ForecastRequest, ForecastResponse
from db.connection import get_db
from db.models import Customer, DelayForecast

router = APIRouter()


@router.post(
    "/predict",
    response_model=ForecastResponse,
    summary="Predict shipping delays for a route",
    description=(
        "Returns a day-by-day delay forecast (in days) for the specified "
        "origin→destination shipping route over the requested horizon. "
        "Results are also persisted to the delay_forecasts table."
    ),
)
def predict_delays(
    body: ForecastRequest,
    customer: Annotated[Customer, Depends(require_api_key)],
    db: Annotated[Session, Depends(get_db)],
) -> ForecastResponse:
    import pandas as pd
    from forecasting.delay_predictor import DelayPredictor

    # Load a pre-trained model if available, otherwise train on-the-fly
    try:
        predictor = DelayPredictor.load(body.origin_port, body.destination_port)
    except FileNotFoundError:
        # Attempt to train from historical data in the DB
        route_sql = text("""
            SELECT timestamp, avg_transit_days
            FROM shipping_routes
            WHERE origin_port = :origin
              AND destination_port = :dest
            ORDER BY timestamp
            LIMIT 1000;
        """)
        rows = db.execute(
            route_sql,
            {"origin": body.origin_port, "dest": body.destination_port},
        ).fetchall()

        if not rows:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    f"No historical data found for route "
                    f"{body.origin_port} → {body.destination_port}. "
                    "Ingest data first via the ETL pipeline."
                ),
            )

        route_df = pd.DataFrame(rows, columns=["timestamp", "avg_transit_days"])
        predictor = DelayPredictor(body.origin_port, body.destination_port)
        predictor.train(route_df)
        predictor.save()

    forecast_points = predictor.predict(horizon_days=body.horizon_days)

    # Persist forecast results to delay_forecasts table
    now = datetime.now(timezone.utc)
    for fp in forecast_points:
        record = DelayForecast(
            created_at=now,
            origin_port=body.origin_port,
            destination_port=body.destination_port,
            forecast_date=fp.forecast_date,
            predicted_delay_days=fp.predicted_delay_days,
            confidence_lower=fp.confidence_lower,
            confidence_upper=fp.confidence_upper,
            model_version=fp.model_version,
        )
        db.add(record)
    try:
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()

    return ForecastResponse(
        origin_port=body.origin_port,
        destination_port=body.destination_port,
        forecasts=[
            {
                "forecast_date": fp.forecast_date,
                "predicted_delay_days": fp.predicted_delay_days,
                "confidence_lower": fp.confidence_lower,
                "confidence_upper": fp.confidence_upper,
                "model_version": fp.model_version,
            }
            for fp in forecast_points
        ],
    )

