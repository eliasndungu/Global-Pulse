"""
Global-Pulse – Maritime Data Ingestion DAG
==========================================
Fetches real-time AIS vessel positions from the MarineTraffic API
and persists them to the TimescaleDB `vessel_positions` hypertable.

Schedule: every 10 minutes
"""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

# ──────────────────────────────────────────────────────────────
#  DAG defaults
# ──────────────────────────────────────────────────────────────

DEFAULT_ARGS = {
    "owner": "global-pulse",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 3,
    "retry_delay": timedelta(minutes=2),
}

# Bounding boxes for major shipping regions
REGIONS: list[dict] = [
    {"name": "Asia-Pacific",   "min_lat": -10, "max_lat": 45, "min_lon": 90,  "max_lon": 180},
    {"name": "Europe-Atlantic","min_lat":  30, "max_lat": 70, "min_lon": -20, "max_lon": 40},
    {"name": "Indian-Ocean",   "min_lat": -40, "max_lat": 30, "min_lon": 30,  "max_lon": 90},
    {"name": "Americas",       "min_lat": -55, "max_lat": 60, "min_lon": -90, "max_lon": -20},
]


# ──────────────────────────────────────────────────────────────
#  Task callables
# ──────────────────────────────────────────────────────────────

def fetch_and_store_vessels(region: dict, **context) -> int:
    """
    Fetch vessel positions for *region* and upsert into TimescaleDB.
    Returns the number of rows inserted.
    """
    from adapters.maritime_adapter import fetch_vessel_positions
    from db.connection import db_session
    from db.models import VesselPosition

    vessels = fetch_vessel_positions(
        min_lat=region["min_lat"],
        max_lat=region["max_lat"],
        min_lon=region["min_lon"],
        max_lon=region["max_lon"],
        limit=500,
    )

    if not vessels:
        return 0

    inserted = 0
    with db_session() as session:
        for v in vessels:
            pos = VesselPosition(**v)
            session.merge(pos)
            inserted += 1

    return inserted


def aggregate_shipping_routes(**context) -> None:
    """
    Aggregate vessel positions into hourly shipping route metrics.
    Runs after all region fetches have completed.
    """
    from db.connection import db_session
    from sqlalchemy import text

    sql = """
        INSERT INTO shipping_routes (
            timestamp, origin_port, destination_port, vessel_count,
            avg_transit_days, congestion_score
        )
        SELECT
            date_trunc('hour', NOW())             AS timestamp,
            COALESCE(destination, 'UNKNOWN')      AS origin_port,
            'AGGREGATE'                            AS destination_port,
            COUNT(*)                               AS vessel_count,
            NULL                                   AS avg_transit_days,
            CASE
                WHEN COUNT(*) > 200 THEN 0.8
                WHEN COUNT(*) > 100 THEN 0.5
                ELSE 0.2
            END                                    AS congestion_score
        FROM vessel_positions
        WHERE timestamp >= NOW() - INTERVAL '1 hour'
          AND destination IS NOT NULL
        GROUP BY destination
        ON CONFLICT DO NOTHING;
    """

    with db_session() as session:
        session.execute(text(sql))


# ──────────────────────────────────────────────────────────────
#  DAG definition
# ──────────────────────────────────────────────────────────────

with DAG(
    dag_id="maritime_ingestion",
    description="Fetch real-time AIS vessel positions and aggregate shipping metrics",
    default_args=DEFAULT_ARGS,
    start_date=datetime(2024, 1, 1),
    schedule_interval="*/10 * * * *",
    catchup=False,
    max_active_runs=1,
    tags=["maritime", "ingestion", "global-pulse"],
) as dag:

    region_tasks = []
    for region in REGIONS:
        task = PythonOperator(
            task_id=f"fetch_vessels_{region['name'].lower().replace('-', '_')}",
            python_callable=fetch_and_store_vessels,
            op_kwargs={"region": region},
        )
        region_tasks.append(task)

    aggregate_task = PythonOperator(
        task_id="aggregate_shipping_routes",
        python_callable=aggregate_shipping_routes,
    )

    # All region fetches must complete before aggregation
    region_tasks >> aggregate_task  # type: ignore[operator]
