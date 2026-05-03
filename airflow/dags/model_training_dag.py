"""
Global-Pulse – Model Retraining DAG
=====================================
Periodically retrains delay-forecast models for all active shipping routes
stored in TimescaleDB and saves the updated models to the model store.

Schedule: daily at 02:00 UTC (low-traffic window)

The DAG:
  1. Discovers all active routes with sufficient historical data (≥30 days).
  2. Trains a ``DelayPredictor`` (XGBoost + optional Prophet) per route.
  3. Saves the trained model to the configured ``MODEL_STORE_PATH``.
  4. Writes a summary row to the ``delay_forecasts`` table covering the
     next 7 days so that the API can serve cached forecasts quickly.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
#  DAG defaults
# ──────────────────────────────────────────────────────────────

DEFAULT_ARGS = {
    "owner": "global-pulse",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=10),
}

# Minimum number of historical data points required before training
MIN_TRAINING_ROWS = 30


# ──────────────────────────────────────────────────────────────
#  Task callables
# ──────────────────────────────────────────────────────────────

def discover_routes(**context) -> list[dict]:
    """
    Query TimescaleDB for distinct origin/destination pairs that have
    at least ``MIN_TRAINING_ROWS`` observations.  Pushes the list to
    XCom for downstream tasks.
    """
    from db.connection import db_session
    from sqlalchemy import text

    sql = text("""
        SELECT origin_port, destination_port, COUNT(*) AS n
        FROM   shipping_routes
        WHERE  avg_transit_days IS NOT NULL
        GROUP  BY origin_port, destination_port
        HAVING COUNT(*) >= :min_rows
        ORDER  BY n DESC;
    """)

    routes = []
    with db_session() as session:
        rows = session.execute(sql, {"min_rows": MIN_TRAINING_ROWS}).fetchall()
        for row in rows:
            routes.append({
                "origin_port": row.origin_port,
                "destination_port": row.destination_port,
                "n": row.n,
            })

    logger.info("Found %d trainable routes", len(routes))
    context["task_instance"].xcom_push(key="routes", value=routes)
    return routes


def train_and_save_models(**context) -> int:
    """
    For each route discovered by ``discover_routes``, fetch the most
    recent 1 000 observations, train a ``DelayPredictor``, and save it.

    Returns the number of models successfully trained.
    """
    import pandas as pd
    from db.connection import db_session
    from forecasting.delay_predictor import DelayPredictor
    from sqlalchemy import text

    routes: list[dict] = context["task_instance"].xcom_pull(
        task_ids="discover_routes", key="routes"
    ) or []

    route_sql = text("""
        SELECT timestamp, avg_transit_days, vessel_count, congestion_score
        FROM   shipping_routes
        WHERE  origin_port      = :origin
          AND  destination_port = :dest
          AND  avg_transit_days IS NOT NULL
        ORDER  BY timestamp DESC
        LIMIT  1000;
    """)

    trained = 0
    for route in routes:
        origin = route["origin_port"]
        dest = route["destination_port"]
        try:
            with db_session() as session:
                rows = session.execute(
                    route_sql,
                    {"origin": origin, "dest": dest},
                ).fetchall()

            if not rows:
                logger.warning("No rows for %s → %s, skipping", origin, dest)
                continue

            route_df = pd.DataFrame(
                rows,
                columns=["timestamp", "avg_transit_days", "vessel_count", "congestion_score"],
            )

            predictor = DelayPredictor(origin, dest)
            predictor.train(route_df)
            predictor.save()
            trained += 1
            logger.info("Trained model for %s → %s (%d rows)", origin, dest, len(rows))

        except Exception:  # noqa: BLE001
            logger.exception("Failed to train model for %s → %s", origin, dest)

    logger.info("Successfully trained %d/%d models", trained, len(routes))
    return trained


def persist_forecasts(**context) -> int:
    """
    For each successfully saved model, generate a 7-day forecast and
    persist the points to the ``delay_forecasts`` table.  Existing rows
    for the same route + forecast_date are deleted first to avoid
    duplicates.
    """
    from datetime import timezone

    import pandas as pd
    from db.connection import db_session
    from db.models import DelayForecast
    from forecasting.delay_predictor import DelayPredictor
    from sqlalchemy import text

    routes: list[dict] = context["task_instance"].xcom_pull(
        task_ids="discover_routes", key="routes"
    ) or []

    written = 0
    for route in routes:
        origin = route["origin_port"]
        dest = route["destination_port"]
        try:
            predictor = DelayPredictor.load(origin, dest)
        except FileNotFoundError:
            logger.warning("No saved model for %s → %s, skipping forecast persist", origin, dest)
            continue

        try:
            points = predictor.predict(horizon_days=7)
            now = datetime.now(timezone.utc)

            with db_session() as session:
                # Remove stale future forecasts for this route
                session.execute(
                    text(
                        "DELETE FROM delay_forecasts "
                        "WHERE origin_port = :origin "
                        "  AND destination_port = :dest "
                        "  AND forecast_date >= NOW();"
                    ),
                    {"origin": origin, "dest": dest},
                )
                for fp in points:
                    session.add(DelayForecast(
                        created_at=now,
                        origin_port=origin,
                        destination_port=dest,
                        forecast_date=fp.forecast_date,
                        predicted_delay_days=fp.predicted_delay_days,
                        confidence_lower=fp.confidence_lower,
                        confidence_upper=fp.confidence_upper,
                        model_version=fp.model_version,
                    ))
            written += len(points)
            logger.info("Persisted %d forecast points for %s → %s", len(points), origin, dest)

        except Exception:  # noqa: BLE001
            logger.exception("Failed to persist forecasts for %s → %s", origin, dest)

    return written


# ──────────────────────────────────────────────────────────────
#  DAG definition
# ──────────────────────────────────────────────────────────────

with DAG(
    dag_id="model_training",
    description="Retrain delay-forecast models for all active shipping routes",
    default_args=DEFAULT_ARGS,
    start_date=datetime(2024, 1, 1),
    schedule_interval="0 2 * * *",   # 02:00 UTC daily
    catchup=False,
    max_active_runs=1,
    tags=["ml", "forecasting", "training", "global-pulse"],
) as dag:

    discover = PythonOperator(
        task_id="discover_routes",
        python_callable=discover_routes,
    )

    train = PythonOperator(
        task_id="train_and_save_models",
        python_callable=train_and_save_models,
    )

    write_forecasts = PythonOperator(
        task_id="persist_forecasts",
        python_callable=persist_forecasts,
    )

    discover >> train >> write_forecasts  # type: ignore[operator]
