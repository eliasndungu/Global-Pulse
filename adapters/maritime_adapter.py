"""
Global-Pulse – Maritime Adapter
Fetches real-time AIS vessel positions from the MarineTraffic API
(Expected API v2 JSON response format).

Environment variables required:
    MARINETRAFFIC_API_KEY  – your MarineTraffic API key

The adapter is deliberately stateless so it can be called from an
Airflow task, a FastAPI endpoint, or standalone scripts.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

import requests
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
#  Constants
# ──────────────────────────────────────────────────────────────

MARINE_TRAFFIC_BASE = "https://services.marinetraffic.com/api"
DEFAULT_TIMEOUT = 30  # seconds


# ──────────────────────────────────────────────────────────────
#  Internal helpers
# ──────────────────────────────────────────────────────────────

def _get_api_key() -> str:
    key = os.getenv("MARINETRAFFIC_API_KEY", "")
    if not key:
        raise EnvironmentError("MARINETRAFFIC_API_KEY environment variable is not set.")
    return key


def _parse_vessel(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalise a raw MarineTraffic vessel record into a canonical dict."""
    return {
        "mmsi": str(raw.get("MMSI", "")),
        "vessel_name": raw.get("SHIPNAME") or raw.get("NAME"),
        "latitude": float(raw.get("LAT", 0)),
        "longitude": float(raw.get("LON", 0)),
        "speed_knots": _to_float(raw.get("SPEED")),
        "heading": _to_float(raw.get("HEADING") or raw.get("COURSE")),
        "destination": raw.get("DESTINATION"),
        "status": raw.get("STATUS"),
        "timestamp": _parse_timestamp(raw.get("TIMESTAMP") or raw.get("TIME_OF_LATEST_POS")),
        "source": "marinetraffic",
    }


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    if isinstance(value, str):
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return datetime.now(timezone.utc)


# ──────────────────────────────────────────────────────────────
#  Public API
# ──────────────────────────────────────────────────────────────

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_not_exception_type(EnvironmentError),
    reraise=True,
)
def fetch_vessel_positions(
    *,
    min_lat: float = -90.0,
    max_lat: float = 90.0,
    min_lon: float = -180.0,
    max_lon: float = 180.0,
    vessel_type: int = 70,  # Cargo ships
    limit: int = 100,
) -> list[dict[str, Any]]:
    """
    Fetch vessel positions within a bounding box from MarineTraffic.

    Returns a list of normalised vessel-position dicts ready for DB insertion.
    """
    api_key = _get_api_key()
    url = f"{MARINE_TRAFFIC_BASE}/exportvessel/v:8/{api_key}/protocol:jsono"
    params = {
        "MINLAT": min_lat,
        "MAXLAT": max_lat,
        "MINLON": min_lon,
        "MAXLON": max_lon,
        "SHIPTYPE": vessel_type,
        "LIMIT": limit,
        "TIMESPAN": 10,  # minutes
    }

    logger.info("Fetching vessel positions from MarineTraffic (bbox=%s/%s/%s/%s)",
                min_lat, max_lat, min_lon, max_lon)

    resp = requests.get(url, params=params, timeout=DEFAULT_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()

    # MarineTraffic v8 returns {"data": [...]}
    records = data if isinstance(data, list) else data.get("data", [])
    vessels = [_parse_vessel(r) for r in records]

    logger.info("Fetched %d vessel positions", len(vessels))
    return vessels


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_not_exception_type(EnvironmentError),
    reraise=True,
)
def fetch_vessel_by_mmsi(mmsi: str) -> dict[str, Any] | None:
    """
    Fetch detailed information for a single vessel by MMSI.
    Returns None if the vessel is not found.
    """
    api_key = _get_api_key()
    url = f"{MARINE_TRAFFIC_BASE}/exportvesseltrack/v:1/{api_key}/protocol:jsono"
    params = {"mmsi": mmsi, "period": "daily", "days": 1}

    resp = requests.get(url, params=params, timeout=DEFAULT_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()

    records = data if isinstance(data, list) else data.get("data", [])
    if not records:
        return None
    return _parse_vessel(records[0])
