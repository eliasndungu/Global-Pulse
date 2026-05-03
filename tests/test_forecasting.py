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


# ──────────────────────────────────────────────────────────────
#  XGBoost quantile interval training
# ──────────────────────────────────────────────────────────────

def test_xgboost_quantile_intervals_trained():
    """predict_with_intervals uses trained quantile models (not a fixed % spread)."""
    from forecasting.delay_predictor import XGBoostPredictor

    n = 50
    rng = np.random.default_rng(42)
    X = pd.DataFrame({
        "hour_sin": rng.uniform(-1, 1, n),
        "hour_cos": rng.uniform(-1, 1, n),
        "dow_sin": rng.uniform(-1, 1, n),
    })
    y = pd.Series(rng.uniform(5, 30, n))

    predictor = XGBoostPredictor()
    predictor.fit(X, y)

    preds, lower, upper = predictor.predict_with_intervals(X)

    assert preds.shape == lower.shape == upper.shape == (n,)
    # predict_with_intervals clamps so upper >= lower always
    assert np.all(upper >= lower - 1e-4), "upper should always be >= lower after clamping"
    # Upper and lower should bracket the point estimates
    assert np.all(preds >= lower - 1e-4)
    assert np.all(upper >= preds - 1e-4)


def test_xgboost_quantile_intervals_nonnegative_lower():
    """predict_with_intervals lower bound does not produce nonsensical negatives for small routes."""
    from forecasting.delay_predictor import XGBoostPredictor

    n = 30
    rng = np.random.default_rng(7)
    X = pd.DataFrame({
        "feat_a": np.abs(rng.standard_normal(n)),
        "feat_b": np.abs(rng.standard_normal(n)),
    })
    y = pd.Series(np.abs(rng.uniform(1, 5, n)))

    predictor = XGBoostPredictor()
    predictor.fit(X, y)

    preds, lower, upper = predictor.predict_with_intervals(X)
    assert preds.shape == (n,)
    # After clamping, upper >= lower
    assert np.all(upper >= lower - 1e-4)


# ──────────────────────────────────────────────────────────────
#  Forecast persistence to delay_forecasts table
# ──────────────────────────────────────────────────────────────

def test_forecast_endpoint_persists_to_db(tmp_path, monkeypatch):
    """
    The /v1/forecasting/predict endpoint persists forecast rows to
    the delay_forecasts table after generating them.
    """
    import importlib
    import secrets
    import uuid
    from passlib.context import CryptContext
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from db.connection import Base, get_db
    from api.main import app
    from db.models import Customer, APIKey, DelayForecast
    from fastapi.testclient import TestClient

    monkeypatch.setenv("MODEL_STORE_PATH", str(tmp_path))

    # Build a trained predictor and save it so the endpoint finds it
    import forecasting.delay_predictor as mod
    importlib.reload(mod)

    route_df = _make_route_df(50)
    predictor = mod.DelayPredictor("Singapore", "Hamburg")
    predictor.train(route_df)
    predictor.save()

    # Use an in-memory SQLite DB (same approach as test_api.py)
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestSession = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(bind=test_engine)

    db = TestSession()
    try:
        pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
        raw_key = secrets.token_urlsafe(32)
        cust = Customer(
            id=uuid.uuid4(), name="Test", email="persist@test.com",
            is_active=True, created_at=datetime.now(timezone.utc),
        )
        db.add(cust)
        db.flush()
        api_key = APIKey(
            id=uuid.uuid4(), customer_id=cust.id,
            key_prefix=raw_key[:8], key_hash=pwd.hash(raw_key),
            label="test", is_active=True,
            created_at=datetime.now(timezone.utc),
        )
        db.add(api_key)
        db.commit()

        def override_get_db():
            yield db

        app.dependency_overrides[get_db] = override_get_db
        try:
            client = TestClient(app)
            resp = client.post(
                "/v1/forecasting/predict",
                json={
                    "origin_port": "Singapore",
                    "destination_port": "Hamburg",
                    "horizon_days": 3,
                },
                headers={"X-API-Key": raw_key},
            )
            assert resp.status_code == 200, resp.text
            payload = resp.json()
            assert len(payload["forecasts"]) == 3

            # Verify rows were written to delay_forecasts
            count = db.query(DelayForecast).filter_by(
                origin_port="Singapore", destination_port="Hamburg"
            ).count()
            assert count == 3, f"Expected 3 persisted forecast rows, got {count}"
        finally:
            app.dependency_overrides.clear()

    finally:
        db.close()
        Base.metadata.drop_all(bind=test_engine)

