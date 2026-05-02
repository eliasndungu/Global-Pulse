"""
Global-Pulse – Feature Engineering for Delay Prediction
=========================================================
Transforms raw DB records into a feature matrix suitable for
XGBoost or Prophet model training and inference.
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd


# ──────────────────────────────────────────────────────────────
#  Datetime features
# ──────────────────────────────────────────────────────────────

def add_time_features(df: pd.DataFrame, ts_col: str = "timestamp") -> pd.DataFrame:
    """
    Expand a datetime column into cyclic and categorical time features.
    Modifies *df* in-place and returns it.
    """
    dt = pd.to_datetime(df[ts_col], utc=True)

    df["hour_sin"] = np.sin(2 * np.pi * dt.dt.hour / 24)
    df["hour_cos"] = np.cos(2 * np.pi * dt.dt.hour / 24)
    df["dow_sin"]  = np.sin(2 * np.pi * dt.dt.dayofweek / 7)
    df["dow_cos"]  = np.cos(2 * np.pi * dt.dt.dayofweek / 7)
    df["month_sin"] = np.sin(2 * np.pi * dt.dt.month / 12)
    df["month_cos"] = np.cos(2 * np.pi * dt.dt.month / 12)
    df["is_weekend"] = (dt.dt.dayofweek >= 5).astype(int)

    return df


# ──────────────────────────────────────────────────────────────
#  Weather features
# ──────────────────────────────────────────────────────────────

def add_weather_features(
    route_df: pd.DataFrame,
    weather_df: pd.DataFrame,
    origin_port: str,
    destination_port: str,
) -> pd.DataFrame:
    """
    Join weather readings for origin and destination ports onto
    the route time-series DataFrame.

    Expected *weather_df* columns: timestamp, location_name,
        wind_speed_ms, wave_height_m, visibility_km
    """
    def _latest_weather(port: str) -> pd.DataFrame:
        subset = weather_df[weather_df["location_name"] == port].copy()
        subset = subset.sort_values("timestamp")
        # Forward-fill on a 30-min grid
        subset = subset.set_index("timestamp").resample("30min").ffill().reset_index()
        return subset.rename(columns={
            "wind_speed_ms": f"{port}_wind_ms",
            "wave_height_m": f"{port}_wave_m",
            "visibility_km": f"{port}_vis_km",
        })[[
            "timestamp",
            f"{port}_wind_ms",
            f"{port}_wave_m",
            f"{port}_vis_km",
        ]]

    route_df = route_df.copy()
    route_df["timestamp"] = pd.to_datetime(route_df["timestamp"], utc=True)

    for port in (origin_port, destination_port):
        try:
            w = _latest_weather(port)
            w["timestamp"] = pd.to_datetime(w["timestamp"], utc=True)
            route_df = pd.merge_asof(
                route_df.sort_values("timestamp"),
                w.sort_values("timestamp"),
                on="timestamp",
                direction="backward",
            )
        except Exception:  # noqa: BLE001
            # Weather data unavailable for this port – fill with defaults
            route_df[f"{port}_wind_ms"] = 0.0
            route_df[f"{port}_wave_m"] = 0.0
            route_df[f"{port}_vis_km"] = 10.0

    return route_df


# ──────────────────────────────────────────────────────────────
#  Congestion features
# ──────────────────────────────────────────────────────────────

def add_congestion_features(
    route_df: pd.DataFrame,
    vessel_positions_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Compute a rolling vessel-count (proxy for congestion) per hour
    and join it onto the route DataFrame.
    """
    if vessel_positions_df.empty:
        route_df["congestion_score"] = 0.0
        return route_df

    vp = vessel_positions_df.copy()
    vp["timestamp"] = pd.to_datetime(vp["timestamp"], utc=True)
    hourly = (
        vp.set_index("timestamp")
        .resample("1h")["mmsi"]
        .nunique()
        .rename("vessel_count")
        .reset_index()
    )
    # Normalise [0,1]
    max_count = hourly["vessel_count"].max() or 1
    hourly["congestion_score"] = hourly["vessel_count"] / max_count

    route_df = route_df.copy()
    route_df["timestamp"] = pd.to_datetime(route_df["timestamp"], utc=True)
    # Drop any pre-existing congestion_score to avoid column name conflicts after merge
    route_df = route_df.drop(columns=["congestion_score"], errors="ignore")
    route_df = pd.merge_asof(
        route_df.sort_values("timestamp"),
        hourly[["timestamp", "congestion_score"]].sort_values("timestamp"),
        on="timestamp",
        direction="backward",
    )
    route_df["congestion_score"] = route_df["congestion_score"].fillna(0.0)
    return route_df

FEATURE_COLUMNS: list[str] = [
    "hour_sin", "hour_cos",
    "dow_sin", "dow_cos",
    "month_sin", "month_cos",
    "is_weekend",
    "congestion_score",
    # Weather cols are dynamically named; they are added by the caller
]


def build_feature_matrix(
    route_df: pd.DataFrame,
    weather_df: pd.DataFrame,
    vessel_positions_df: pd.DataFrame,
    origin_port: str,
    destination_port: str,
) -> pd.DataFrame:
    """
    Run the full feature pipeline and return a DataFrame ready
    for model training or inference.
    """
    df = route_df.copy()
    df = add_time_features(df, ts_col="timestamp")
    df = add_weather_features(df, weather_df, origin_port, destination_port)
    df = add_congestion_features(df, vessel_positions_df)
    return df
