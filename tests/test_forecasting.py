"""
Tests – Forecasting Module
Tests the feature engineering pipeline and the delay predictor
without a database or trained model files.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest


# ──────────────────────────────────────────────────────────────
#  Feature Engineering
# ──────────────────────────────────────────────────────────────

def _make_route_df(n: int = 30) -> pd.DataFrame:
    """Create a synthetic route DataFrame with n rows."""
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return pd.DataFrame({
        "timestamp": [base + timedelta(days=i) for i in range(n)],
        "avg_transit_days": np.random.uniform(18, 25, size=n),
        "vessel_count": np.random.randint(50, 200, size=n),
        "origin_port": "Shanghai",
        "destination_port": "Rotterdam",
        "congestion_score": np.random.uniform(0.2, 0.8, size=n),
    })


def _make_weather_df(port: str, n: int = 30) -> pd.DataFrame:
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return pd.DataFrame({
        "timestamp": [base + timedelta(days=i) for i in range(n)],
        "location_name": port,
        "wind_speed_ms": np.random.uniform(2, 15, size=n),
        "wave_height_m": np.random.uniform(0.5, 4.0, size=n),
        "visibility_km": np.random.uniform(1, 20, size=n),
    })


def test_add_time_features():
    """add_time_features adds cyclic time columns."""
    from forecasting.feature_engineering import add_time_features

    df = _make_route_df(10)
    result = add_time_features(df)

    for col in ("hour_sin", "hour_cos", "dow_sin", "dow_cos", "month_sin", "month_cos", "is_weekend"):
        assert col in result.columns, f"Missing column: {col}"

    # Values should be in valid trigonometric ranges
    assert result["hour_sin"].between(-1, 1).all()
    assert result["hour_cos"].between(-1, 1).all()
    assert result["is_weekend"].isin([0, 1]).all()


def test_add_weather_features():
    """add_weather_features joins port weather onto the route DataFrame."""
    from forecasting.feature_engineering import add_weather_features

    route_df = _make_route_df(10)
    weather_df = pd.concat([
        _make_weather_df("Shanghai", 10),
        _make_weather_df("Rotterdam", 10),
    ])

    result = add_weather_features(route_df, weather_df, "Shanghai", "Rotterdam")

    assert "Shanghai_wind_ms" in result.columns
    assert "Rotterdam_wind_ms" in result.columns


def test_add_congestion_features():
    """add_congestion_features adds a congestion_score column."""
    from forecasting.feature_engineering import add_congestion_features

    route_df = _make_route_df(10)
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    vessel_df = pd.DataFrame({
        "timestamp": [base + timedelta(hours=h) for h in range(240)],  # 10 days of hourly data
        "mmsi": [f"MMSI{i % 50:05d}" for i in range(240)],
    })

    result = add_congestion_features(route_df, vessel_df)

    assert "congestion_score" in result.columns
    assert result["congestion_score"].between(0, 1).all()


def test_congestion_with_empty_vessel_df():
    """add_congestion_features handles empty vessel DataFrame gracefully."""
    from forecasting.feature_engineering import add_congestion_features

    route_df = _make_route_df(5)
    result = add_congestion_features(route_df, pd.DataFrame())

    assert "congestion_score" in result.columns
    assert (result["congestion_score"] == 0.0).all()


# ──────────────────────────────────────────────────────────────
#  Delay Predictor (XGBoost path)
# ──────────────────────────────────────────────────────────────

def test_delay_predictor_train_and_predict(tmp_path, monkeypatch):
    """DelayPredictor trains and produces a valid forecast list."""
    monkeypatch.setenv("MODEL_STORE_PATH", str(tmp_path))

    # Re-import with new env
    import importlib
    import forecasting.delay_predictor as mod
    importlib.reload(mod)

    route_df = _make_route_df(60)
    weather_df = pd.concat([
        _make_weather_df("Shanghai", 60),
        _make_weather_df("Rotterdam", 60),
    ])

    predictor = mod.DelayPredictor("Shanghai", "Rotterdam")
    predictor.train(route_df, weather_df=weather_df)

    forecasts = predictor.predict(horizon_days=5)

    assert len(forecasts) == 5
    for fp in forecasts:
        assert fp.predicted_delay_days >= 0
        assert isinstance(fp.forecast_date, datetime)
        assert fp.model_version == mod.MODEL_VERSION


def test_delay_predictor_save_load(tmp_path, monkeypatch):
    """DelayPredictor can be saved and re-loaded from disk."""
    monkeypatch.setenv("MODEL_STORE_PATH", str(tmp_path))

    import importlib
    import forecasting.delay_predictor as mod
    importlib.reload(mod)

    route_df = _make_route_df(40)
    predictor = mod.DelayPredictor("Busan", "Hamburg")
    predictor.train(route_df)
    predictor.save()

    loaded = mod.DelayPredictor.load("Busan", "Hamburg")
    forecasts = loaded.predict(horizon_days=3)

    assert len(forecasts) == 3
    assert all(fp.predicted_delay_days >= 0 for fp in forecasts)


def test_delay_predictor_load_missing_raises(tmp_path, monkeypatch):
    """DelayPredictor.load raises FileNotFoundError for unknown routes."""
    monkeypatch.setenv("MODEL_STORE_PATH", str(tmp_path))

    import importlib
    import forecasting.delay_predictor as mod
    importlib.reload(mod)

    with pytest.raises(FileNotFoundError):
        mod.DelayPredictor.load("Nowhere", "Nowhere2")


def test_delay_predictor_train_requires_data():
    """DelayPredictor.train raises ValueError on empty DataFrame."""
    from forecasting.delay_predictor import DelayPredictor

    with pytest.raises(ValueError, match="avg_transit_days"):
        predictor = DelayPredictor("A", "B")
        predictor.train(pd.DataFrame())
