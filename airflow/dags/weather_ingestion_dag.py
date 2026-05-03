"""
Global-Pulse – Weather Data Ingestion DAG
==========================================
Fetches current weather for all major world ports from OpenWeatherMap
and stores observations in the `weather_observations` hypertable.

Schedule: every 30 minutes
"""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

DEFAULT_ARGS = {
    "owner": "global-pulse",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 3,
    "retry_delay": timedelta(minutes=5),
}


# ──────────────────────────────────────────────────────────────
#  Task callables
# ──────────────────────────────────────────────────────────────

def fetch_and_store_weather(**context) -> int:
    """Fetch weather for all major ports and upsert into TimescaleDB."""
    from adapters.weather_adapter import fetch_weather_all_ports
    from db.connection import db_session
    from db.models import WeatherObservation

    observations = fetch_weather_all_ports()

    if not observations:
        return 0

    inserted = 0
    with db_session() as session:
        for obs in observations:
            record = WeatherObservation(**obs)
            session.add(record)
            inserted += 1

    return inserted


def flag_severe_weather(**context) -> list[str]:
    """
    Scan recent weather observations and push XCom alerts for ports
    with severe conditions (high wind, low visibility).
    """
    from db.connection import db_session
    from sqlalchemy import text

    alert_sql = """
        SELECT DISTINCT location_name
        FROM weather_observations
        WHERE timestamp >= NOW() - INTERVAL '1 hour'
          AND (
              wind_speed_ms > 15            -- Beaufort 7+
              OR visibility_km < 1          -- Dense fog
          )
        ORDER BY location_name;
    """

    with db_session() as session:
        rows = session.execute(text(alert_sql)).fetchall()

    alerts = [r[0] for r in rows]

    if alerts:
        context["task_instance"].xcom_push(key="severe_weather_ports", value=alerts)

    return alerts


# ──────────────────────────────────────────────────────────────
#  DAG definition
# ──────────────────────────────────────────────────────────────

with DAG(
    dag_id="weather_ingestion",
    description="Fetch current weather for major world ports",
    default_args=DEFAULT_ARGS,
    start_date=datetime(2024, 1, 1),
    schedule="*/30 * * * *",
    catchup=False,
    max_active_runs=1,
    tags=["weather", "ingestion", "global-pulse"],
) as dag:

    fetch_weather = PythonOperator(
        task_id="fetch_and_store_weather",
        python_callable=fetch_and_store_weather,
    )

    check_severe = PythonOperator(
        task_id="flag_severe_weather",
        python_callable=flag_severe_weather,
    )

    fetch_weather >> check_severe  # type: ignore[operator]
