"""Unit tests for the forecasting training pipeline (Phase 1).

Exercises the pure pieces directly (no MLflow/DB):
- :func:`build_forecast_feature_matrix` (feature contract + direct-shift target)
- :func:`_fit_and_evaluate` for all three algorithms (LR / XGBoost / LightGBM)

The orchestration in :func:`train_forecasting_model` (telemetry loading + MLflow
registration) is thin glue verified end-to-end via the ``/models/train`` flow.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.ml.forecasting.feature_engineering import (
    FEATURE_COLUMNS,
    build_forecast_feature_matrix,
)
from src.ml.forecasting.training import _fit_and_evaluate
from src.schemas import MLAlgorithm


def _make_telemetry(n_hours: int = 500, n_buildings: int = 3) -> pd.DataFrame:
    """Synthetic hourly telemetry with a learnable seasonal+trend pattern."""
    ts = pd.date_range("2017-01-01", periods=n_hours, freq="h", tz="UTC")
    rows = []
    for b in range(n_buildings):
        for i, t in enumerate(ts):
            base = 10.0 + b * 5.0
            hourly = 3.0 * np.sin(2 * np.pi * t.hour / 24)
            consumption = base + hourly + 0.5 * i
            rows.append(
                {
                    "timestamp": t,
                    "consumption": float(consumption),
                    "metric_type_id": "electricity",
                    "building_id": f"B{b}",
                    "site_id": f"S{b}",
                    "sqm": float(100 + b * 50),
                    "primaryspaceusage": "Office",
                    "timezone": "UTC",
                }
            )
    return pd.DataFrame(rows)


def test_build_forecast_feature_matrix_contract_and_target():
    horizon = 24
    df = _make_telemetry()
    feature_df, feature_cols, cat_features = build_forecast_feature_matrix(df, horizon)

    # Feature contract matches the declared column set (consumption included).
    assert feature_cols == FEATURE_COLUMNS
    assert cat_features == ["building_id", "primaryspaceusage", "timezone"]

    # No nulls survive in the feature matrix or target.
    assert not feature_df[feature_cols + ["target"]].isnull().any().any()

    # Direct h-step-ahead: target at row t == consumption at row t+horizon (per building).
    b0 = feature_df[feature_df["building_id"] == "B0"].sort_values("timestamp").reset_index(drop=True)
    assert np.isclose(b0.loc[0, "target"], b0.loc[horizon, "consumption"])
    # lag_1h at row t == consumption at row t-1.
    assert np.isclose(b0.loc[1, "lag_1h"], b0.loc[0, "consumption"])


def test_build_forecast_feature_matrix_rejects_unsupported_weather_mode():
    df = _make_telemetry(n_hours=300, n_buildings=1)
    with pytest.raises(NotImplementedError):
        build_forecast_feature_matrix(df, weather_mode="forecast")


def _temporal_split(feature_df: pd.DataFrame):
    start = feature_df["timestamp"].min()
    end = feature_df["timestamp"].max()
    total = end - start
    train_end = start + total * 0.70
    test_start = end - total * 0.15
    train_df = feature_df[(feature_df["timestamp"] >= start) & (feature_df["timestamp"] <= train_end)]
    val_df = feature_df[(feature_df["timestamp"] > train_end) & (feature_df["timestamp"] < test_start)]
    test_df = feature_df[(feature_df["timestamp"] >= test_start) & (feature_df["timestamp"] <= end)]
    return train_df, val_df, test_df


@pytest.mark.parametrize(
    "algorithm",
    [MLAlgorithm.LinearRegression, MLAlgorithm.XGBoost, MLAlgorithm.LightGBM],
)
def test_fit_and_evaluate_all_algorithms(algorithm):
    feature_df, feature_cols, cat_features = build_forecast_feature_matrix(
        _make_telemetry(), forecast_horizon_hours=24
    )
    train_df, val_df, test_df = _temporal_split(feature_df)
    assert not train_df.empty and not val_df.empty and not test_df.empty

    pipeline, metrics = _fit_and_evaluate(
        train_df, val_df, test_df, feature_cols, cat_features, algorithm
    )

    assert {"test_mae", "test_rmse", "test_mape"} <= set(metrics)
    assert np.isfinite(metrics["test_mae"])
    assert np.isfinite(metrics["test_rmse"])
    assert metrics["test_mae"] >= 0.0

    # The fitted pipeline predicts from the raw feature frame (encoder+imputer inside).
    preds = pipeline.predict(test_df[feature_cols])
    assert len(preds) == len(test_df)
    assert np.all(np.asarray(preds) >= 0.0)  # predictions clipped to non-negative
