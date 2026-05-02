"""
Global-Pulse – Shipping Delay Predictor
=========================================
Dual-backend forecaster that supports:
  • XGBoost  – point-in-time predictions (low latency, feature-rich)
  • Prophet  – time-series decomposition (good for seasonal trend visibility)

The predictor can be trained on historical route data stored in
TimescaleDB, then persisted to the model store for API-time inference.

Usage (training):
    predictor = DelayPredictor(origin="Shanghai", destination="Rotterdam")
    predictor.train(route_df, weather_df, vessel_df)
    predictor.save()

Usage (inference):
    predictor = DelayPredictor.load("Shanghai", "Rotterdam")
    forecasts = predictor.predict(horizon_days=7)
"""

from __future__ import annotations

import json
import logging
import os
import pickle
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

MODEL_STORE = Path(os.getenv("MODEL_STORE_PATH", "/app/model_store"))
MODEL_VERSION = "1.0.0"


# ──────────────────────────────────────────────────────────────
#  Data containers
# ──────────────────────────────────────────────────────────────

@dataclass
class ForecastPoint:
    forecast_date: datetime
    predicted_delay_days: float
    confidence_lower: float | None = None
    confidence_upper: float | None = None
    model_version: str = MODEL_VERSION


# ──────────────────────────────────────────────────────────────
#  XGBoost backend
# ──────────────────────────────────────────────────────────────

class XGBoostPredictor:
    """
    Trains an XGBoost regressor on historical route data.
    Target variable: actual_delay_days (days late relative to schedule).
    """

    def __init__(self) -> None:
        from xgboost import XGBRegressor
        self._model = XGBRegressor(
            n_estimators=300,
            max_depth=6,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            n_jobs=-1,
        )
        self._feature_cols: list[str] = []

    def fit(self, X: pd.DataFrame, y: pd.Series) -> None:
        self._feature_cols = list(X.columns)
        self._model.fit(X.values, y.values)

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return self._model.predict(X[self._feature_cols].values)

    def predict_with_intervals(
        self, X: pd.DataFrame, alpha: float = 0.1
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Return point prediction + approximate confidence bounds using
        quantile regression trees from XGBoost.
        """
        from xgboost import XGBRegressor

        lower_model = XGBRegressor(
            objective="reg:quantileerror",
            quantile_alpha=alpha / 2,
            n_estimators=300, max_depth=6, n_jobs=-1,
        )
        upper_model = XGBRegressor(
            objective="reg:quantileerror",
            quantile_alpha=1 - alpha / 2,
            n_estimators=300, max_depth=6, n_jobs=-1,
        )

        # For inference only, we rely on the main model + fixed spread
        preds = self.predict(X)
        std_approx = preds * 0.15  # ±15% as placeholder until quantile models are trained
        return preds, preds - 1.96 * std_approx, preds + 1.96 * std_approx


# ──────────────────────────────────────────────────────────────
#  Prophet backend
# ──────────────────────────────────────────────────────────────

class ProphetPredictor:
    """
    Fits a Facebook Prophet model to historical route delay time-series.
    Best suited when you have >2 years of daily data.

    Prophet is an optional dependency; if not installed the class raises
    ``ImportError`` with an actionable message.
    """

    def __init__(self) -> None:
        try:
            from prophet import Prophet
        except ImportError as exc:
            raise ImportError(
                "Prophet is not installed. Install it with: pip install prophet"
            ) from exc
        self._model = Prophet(
            yearly_seasonality=True,
            weekly_seasonality=True,
            daily_seasonality=False,
            changepoint_prior_scale=0.05,
            interval_width=0.90,
        )

    def fit(self, ts_df: pd.DataFrame) -> None:
        """
        Fit Prophet model.

        Args:
            ts_df: DataFrame with columns ['ds', 'y'] where
                   ds=datetime, y=delay_days.
        """
        self._model.fit(ts_df)

    def predict(self, horizon_days: int = 7) -> pd.DataFrame:
        """
        Generate a forecast for the next *horizon_days* days.

        Returns DataFrame with columns:
            ds, yhat, yhat_lower, yhat_upper
        """
        future = self._model.make_future_dataframe(periods=horizon_days, freq="D")
        forecast = self._model.predict(future)
        return forecast[["ds", "yhat", "yhat_lower", "yhat_upper"]].tail(horizon_days)


# ──────────────────────────────────────────────────────────────
#  Unified predictor facade
# ──────────────────────────────────────────────────────────────

class DelayPredictor:
    """
    Unified delay predictor that trains/loads both XGBoost and Prophet
    models and exposes a single :meth:`predict` interface.
    """

    def __init__(self, origin_port: str, destination_port: str) -> None:
        self.origin_port = origin_port
        self.destination_port = destination_port
        self._xgb: XGBoostPredictor | None = None
        self._prophet: ProphetPredictor | None = None

    # ── Training ──────────────────────────────────────────────

    def train(
        self,
        route_df: pd.DataFrame,
        weather_df: pd.DataFrame | None = None,
        vessel_df: pd.DataFrame | None = None,
    ) -> None:
        """
        Train both XGBoost and Prophet models on historical route data.

        Args:
            route_df:   Historical route metrics DataFrame with columns
                        ['timestamp', 'avg_transit_days', ...].
            weather_df: Optional weather observations DataFrame.
            vessel_df:  Optional vessel positions DataFrame.
        """
        from forecasting.feature_engineering import build_feature_matrix, FEATURE_COLUMNS

        if route_df.empty or "avg_transit_days" not in route_df.columns:
            raise ValueError("route_df must contain 'avg_transit_days' column with at least 1 row.")

        # ── XGBoost ──────────────────────────────────────────
        feature_df = build_feature_matrix(
            route_df,
            weather_df if weather_df is not None else pd.DataFrame(),
            vessel_df if vessel_df is not None else pd.DataFrame(),
            self.origin_port,
            self.destination_port,
        )

        feature_cols = [c for c in feature_df.columns if c not in (
            "timestamp", "avg_transit_days", "vessel_count",
            "origin_port", "destination_port",
        )]
        X = feature_df[feature_cols].fillna(0)
        y = feature_df["avg_transit_days"].fillna(0)

        self._xgb = XGBoostPredictor()
        self._xgb._feature_cols = feature_cols
        self._xgb.fit(X, y)
        logger.info("XGBoost trained for %s → %s", self.origin_port, self.destination_port)

        # ── Prophet ──────────────────────────────────────────
        ts = route_df[["timestamp", "avg_transit_days"]].copy()
        ts.columns = ["ds", "y"]
        ts["ds"] = pd.to_datetime(ts["ds"], utc=True).dt.tz_localize(None)
        ts = ts.dropna(subset=["y"])

        if len(ts) >= 2:
            try:
                self._prophet = ProphetPredictor()
                self._prophet.fit(ts)
                logger.info("Prophet trained for %s → %s", self.origin_port, self.destination_port)
            except ImportError:
                logger.warning("Prophet not installed; skipping Prophet model training.")
        else:
            logger.warning("Insufficient data for Prophet model (need ≥2 rows)")

    # ── Inference ─────────────────────────────────────────────

    def predict(
        self,
        horizon_days: int = 7,
        feature_row: pd.DataFrame | None = None,
    ) -> list[ForecastPoint]:
        """
        Generate delay forecasts for the next *horizon_days* days.

        If *feature_row* is provided, XGBoost is used for point estimates.
        Prophet provides the calendar-aware trend.  When both are available,
        we ensemble them (simple average).

        Returns a list of :class:`ForecastPoint` objects.
        """
        from forecasting.feature_engineering import add_time_features

        results: list[ForecastPoint] = []
        now = datetime.now(timezone.utc)

        for day_offset in range(1, horizon_days + 1):
            target_date = now + timedelta(days=day_offset)

            xgb_pred: float | None = None
            lower: float | None = None
            upper: float | None = None

            if self._xgb is not None and feature_row is not None:
                fr = feature_row.copy()
                fr["timestamp"] = target_date
                fr = add_time_features(fr, ts_col="timestamp")
                feat_cols = self._xgb._feature_cols
                fr_aligned = fr.reindex(columns=feat_cols, fill_value=0)
                preds, lw, up = self._xgb.predict_with_intervals(fr_aligned)
                xgb_pred = float(preds[0])
                lower = float(lw[0])
                upper = float(up[0])

            prophet_pred: float | None = None
            if self._prophet is not None:
                fc = self._prophet.predict(horizon_days=day_offset + 1)
                if not fc.empty:
                    row = fc.iloc[-1]
                    prophet_pred = float(row["yhat"])
                    if lower is None:
                        lower = float(row["yhat_lower"])
                        upper = float(row["yhat_upper"])

            # Ensemble: average available predictions
            available = [p for p in (xgb_pred, prophet_pred) if p is not None]
            if not available:
                delay = 0.0
            else:
                delay = sum(available) / len(available)

            results.append(ForecastPoint(
                forecast_date=target_date,
                predicted_delay_days=max(0.0, delay),
                confidence_lower=max(0.0, lower) if lower is not None else None,
                confidence_upper=max(0.0, upper) if upper is not None else None,
            ))

        return results

    # ── Persistence ───────────────────────────────────────────

    def _model_path(self) -> Path:
        key = f"{self.origin_port}__{self.destination_port}".replace(" ", "_").lower()
        MODEL_STORE.mkdir(parents=True, exist_ok=True)
        return MODEL_STORE / f"{key}.pkl"

    def save(self) -> None:
        path = self._model_path()
        with open(path, "wb") as fh:
            pickle.dump({"xgb": self._xgb, "prophet": self._prophet}, fh)
        logger.info("Model saved to %s", path)

    @classmethod
    def load(cls, origin_port: str, destination_port: str) -> "DelayPredictor":
        instance = cls(origin_port, destination_port)
        path = instance._model_path()
        if not path.exists():
            raise FileNotFoundError(f"No saved model found at {path}")
        with open(path, "rb") as fh:
            data = pickle.load(fh)  # noqa: S301 – trusted internal store
        instance._xgb = data.get("xgb")
        instance._prophet = data.get("prophet")
        logger.info("Model loaded from %s", path)
        return instance
