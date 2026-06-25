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
from src.ml.forecasting.preprocessing import clean_telemetry_for_forecasting
from src.ml.forecasting.training import _fit_and_evaluate, _mape
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


# --------------------------------------------------------------------------
# MAPE unit (returns percent, not ratio) — regression for the 458% bug.
# --------------------------------------------------------------------------


def test_mape_returns_percent():
    y_true = np.array([10.0, 20.0, 30.0])
    y_pred = np.array([11.0, 19.0, 33.0])
    ratio = np.mean(np.abs((y_true - y_pred) / y_true))
    result = _mape(y_true, y_pred)
    assert np.isfinite(result)
    assert np.isclose(result, ratio * 100.0)
    assert 1.0 < result < 100.0  # a sensible percentage, not 0.02 nor ~400


def test_mape_masks_near_zero_actuals():
    """Actuals <= MAPE_MIN_ACTUAL kWh are excluded so they can't blow up MAPE.

    Regression for the ~10,887% MAPE caused by interpolated near-zero actuals
    (see ``notebooks/forecasting/EDA/diagnose_mape.py``).
    """
    from src.ml.forecasting.training import MAPE_MIN_ACTUAL

    # The first actual is ~0; without the mask this point alone would be a
    # 1,000,000% error. It must be dropped, leaving only the 10/20/30 points.
    y_true = np.array([0.001, 10.0, 20.0, 30.0])
    y_pred = np.array([10.0, 11.0, 19.0, 33.0])
    result = _mape(y_true, y_pred)

    kept = y_true > MAPE_MIN_ACTUAL
    expected = np.mean(np.abs((y_true[kept] - y_pred[kept]) / y_true[kept])) * 100.0
    assert np.isfinite(result)
    assert np.isclose(result, expected)
    assert result < 100.0  # not exploded by the 0.001 actual

    # All actuals below the floor -> nothing to average -> NaN (not inf/raise).
    assert np.isnan(_mape(np.array([0.0, 0.5]), np.array([1.0, 2.0])))


# --------------------------------------------------------------------------
# Telemetry cleaning (preprocessing port).
# --------------------------------------------------------------------------


def _flat_telemetry(n_hours: int = 200, building: str = "B0") -> pd.DataFrame:
    """Deterministic, slowly-drifting hourly consumption (no outliers/gaps)."""
    ts = pd.date_range("2017-01-01", periods=n_hours, freq="h", tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": ts,
            "consumption": [10.0 + 0.5 * i for i in range(n_hours)],
            "metric_type_id": "electricity",
            "building_id": building,
            "site_id": "S0",
            "sqm": 100.0,
            "primaryspaceusage": "Office",
            "timezone": "UTC",
        }
    )


def test_clean_flags_outlier_spike():
    df = _flat_telemetry()
    df.loc[100, "consumption"] = 1_000_000.0  # huge spike vs neighbours ~60
    cleaned, stats = clean_telemetry_for_forecasting(df.copy(), return_stats=True)
    assert stats["outliers_flagged"] >= 1
    assert cleaned.loc[100, "consumption"] < 1_000_000.0


def test_clean_interpolates_short_gap():
    df = _flat_telemetry()
    df.loc[50:52, "consumption"] = np.nan  # 3h gap <= INTERP_MAX_GAP_HOURS=6
    cleaned, stats = clean_telemetry_for_forecasting(df.copy(), return_stats=True)
    assert cleaned.loc[50:52, "consumption"].notna().all()
    assert stats["gaps_filled"] >= 3


def test_clean_seasonal_fills_medium_gap():
    df = _flat_telemetry(n_hours=300)
    df.loc[100:109, "consumption"] = np.nan  # 10h gap in (6, 24], t-24h exists
    cleaned, _ = clean_telemetry_for_forecasting(df.copy(), return_stats=True)
    # Medium gaps fill from shift(24) where available.
    assert cleaned.loc[105:109, "consumption"].notna().all()


def test_clean_leaves_long_gap_as_nan():
    df = _flat_telemetry(n_hours=300)
    df.loc[100:139, "consumption"] = np.nan  # 40h gap > SEASONAL_MAX_GAP_HOURS=24
    cleaned, _ = clean_telemetry_for_forecasting(df.copy(), return_stats=True)
    # Long gaps stay null (feature builder drops them).
    assert cleaned.loc[110:130, "consumption"].isna().all()


def test_clean_drops_high_missing_building():
    base = _flat_telemetry(building="B0")
    bad = _flat_telemetry(building="B1")
    bad.loc[bad.sample(frac=0.6, random_state=0).index, "consumption"] = np.nan  # 60% missing
    df = pd.concat([base, bad], ignore_index=True)
    cleaned, stats = clean_telemetry_for_forecasting(
        df.copy(), drop_high_missing=True, return_stats=True
    )
    assert "B1" not in set(cleaned["building_id"])
    assert "B0" in set(cleaned["building_id"])
    assert stats["buildings_dropped"] == 1


def test_clean_is_idempotent():
    df = _flat_telemetry()
    once = clean_telemetry_for_forecasting(df.copy())
    twice = clean_telemetry_for_forecasting(once.copy())
    a = once["consumption"].dropna().to_numpy()
    b = twice["consumption"].dropna().to_numpy()
    assert len(a) == len(b)
    assert np.allclose(a, b)
