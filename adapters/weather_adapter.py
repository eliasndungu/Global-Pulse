"""
Global-Pulse – Weather Adapter
Fetches current weather and marine forecasts from the OpenWeatherMap API.

Environment variables required:
    OPENWEATHER_API_KEY  – your OpenWeatherMap API key

Canonical port coordinates are kept locally so we can enrich
each weather reading with a human-readable port name.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

import requests
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

OWM_BASE = "https://api.openweathermap.org/data/2.5"
DEFAULT_TIMEOUT = 20

# A curated list of major world ports (name, lat, lon)
MAJOR_PORTS: list[tuple[str, float, float]] = [
    ("Shanghai", 31.2304, 121.4737),
    ("Singapore", 1.2897, 103.8501),
    ("Rotterdam", 51.9225, 4.4792),
    ("Los Angeles", 33.7291, -118.2648),
    ("Hamburg", 53.5753, 9.9687),
    ("Antwerp", 51.2213, 4.4051),
    ("Busan", 35.1796, 129.0756),
    ("Dubai (Jebel Ali)", 24.9987, 55.0595),
    ("Colombo", 6.9319, 79.8478),
    ("Durban", -29.8587, 31.0218),
]


def _get_api_key() -> str:
    key = os.getenv("OPENWEATHER_API_KEY", "")
    if not key:
        raise EnvironmentError("OPENWEATHER_API_KEY environment variable is not set.")
    return key


def _parse_current(location_name: str, lat: float, lon: float, raw: dict) -> dict[str, Any]:
    main = raw.get("main", {})
    wind = raw.get("wind", {})
    weather_list = raw.get("weather", [{}])
    condition = weather_list[0].get("description") if weather_list else None

    ts_unix = raw.get("dt")
    if ts_unix:
        ts = datetime.fromtimestamp(ts_unix, tz=timezone.utc)
    else:
        ts = datetime.now(timezone.utc)

    return {
        "timestamp": ts,
        "location_name": location_name,
        "latitude": lat,
        "longitude": lon,
        "temperature_c": main.get("temp"),
        "wind_speed_ms": wind.get("speed"),
        "wind_direction": wind.get("deg"),
        "wave_height_m": None,  # Not available in standard OWM current endpoint
        "visibility_km": raw.get("visibility", None) and raw["visibility"] / 1000,
        "condition": condition,
        "source": "openweathermap",
    }


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_not_exception_type(EnvironmentError),
    reraise=True,
)
def fetch_weather_for_port(
    location_name: str,
    lat: float,
    lon: float,
) -> dict[str, Any]:
    """Fetch current weather observation for a single port."""
    api_key = _get_api_key()
    url = f"{OWM_BASE}/weather"
    params = {"lat": lat, "lon": lon, "appid": api_key, "units": "metric"}

    logger.info("Fetching weather for %s (%.4f, %.4f)", location_name, lat, lon)
    resp = requests.get(url, params=params, timeout=DEFAULT_TIMEOUT)
    resp.raise_for_status()

    return _parse_current(location_name, lat, lon, resp.json())


def fetch_weather_all_ports(
    ports: list[tuple[str, float, float]] | None = None,
) -> list[dict[str, Any]]:
    """
    Fetch current weather for all major ports (or a custom list).

    Returns a list of normalised weather observation dicts.
    """
    targets = ports or MAJOR_PORTS
    results: list[dict[str, Any]] = []

    for name, lat, lon in targets:
        try:
            obs = fetch_weather_for_port(name, lat, lon)
            results.append(obs)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to fetch weather for %s: %s", name, exc)

    logger.info("Fetched weather for %d/%d ports", len(results), len(targets))
    return results
