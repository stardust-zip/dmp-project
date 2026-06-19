"""Unit tests for forecasting inference (Phase 2).

The recursive/overlay logic in :func:`forecast_for_building` is exercised with a
*real* small LinearRegression pipeline (trained on synthetic telemetry) plus
mocked MLflow / telemetry / persistence seams — mirroring the approach in
``test_anomaly_inference.py`` (no live MLflow, DB, or Postgres required).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.ml.anomaly import telemetry_loaders
from src.ml.forecasting import inference as inference_module
from src.ml.forecasting.feature_engineering import build_forecast_feature_matrix
from src.ml.forecasting.inference import ForecastError, forecast_for_building
from src.ml.forecasting.training import _fit_and_evaluate
from src.ml.forecasting.types import LOOKBACK_HOURS
from src.schemas import MLAlgorithm


def _make_single_building_telemetry(n_hours: int = 600) -> pd.DataFrame:
    """Synthetic hourly telemetry for one building with a learnable pattern."""
    ts = pd.date_range("2017-01-01", periods=n_hours, freq="h", tz="UTC")
    rows = []
    for i, t in enumerate(ts):
        base = 20.0
        hourly = 5.0 * np.sin(2 * np.pi * t.hour / 24)
        weekly = 2.0 * np.sin(2 * np.pi * t.dayofweek / 7)
        consumption = base + hourly + weekly + 0.01 * i
        rows.append(
            {
                "timestamp": t,
                "consumption": float(consumption),
                "metric_type_id": "electricity",
                "building_id": "B0",
                "site_id": "S0",
                "sqm": 150.0,
                "primaryspaceusage": "Office",
                "timezone": "UTC",
            }
        )
    return pd.DataFrame(rows)


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


def _train_pipeline(horizon: int = 24):
    df = _make_single_building_telemetry()
    feature_df, feature_cols, cat_features = build_forecast_feature_matrix(df, horizon)
    train_df, val_df, test_df = _temporal_split(feature_df)
    pipeline, _metrics = _fit_and_evaluate(
        train_df, val_df, test_df, feature_cols, cat_features, MLAlgorithm.LinearRegression
    )
    return pipeline, feature_cols, cat_features, df


def _install_mocks(monkeypatch, pipeline, feature_cols, cat_features, df):
    """Mock the MLflow registry, telemetry loader, and persistence seams."""
    monkeypatch.setattr(
        inference_module.ForecastingMlflowRegistry,
        "load_production_forecast_model",
        lambda self, model_name="dmp_energy_forecasting": (pipeline, feature_cols, cat_features, 24, "electricity", "run-123"),
    )
    monkeypatch.setattr(
        inference_module.ForecastResultStore,
        "upsert",
        lambda self, records, commit=True: len(records),
    )
    monkeypatch.setattr(inference_module, "_ensure_meter_device", lambda *a, **k: None)
    monkeypatch.setattr(
        telemetry_loaders,
        "query_telemetry_window",
        lambda db, start, end, metrics=None: df[
            (df["timestamp"] >= pd.Timestamp(start)) & (df["timestamp"] <= pd.Timestamp(end))
        ].copy(),
    )


def test_feature_matrix_include_target_false_keeps_future_rows():
    df = _make_single_building_telemetry(n_hours=300)
    feat_true, _, _ = build_forecast_feature_matrix(df, 24)
    feat_false, _, _ = build_forecast_feature_matrix(df, 24, include_target=False)

    assert "target" not in feat_false.columns
    # Training mode drops the last `horizon` rows (null target); inference keeps them.
    assert len(feat_false) > len(feat_true)
    assert len(feat_false) - len(feat_true) == 24


def test_forecast_for_building_recursive(monkeypatch):
    pipeline, feature_cols, cat_features, df = _train_pipeline()
    _install_mocks(monkeypatch, pipeline, feature_cols, cat_features, df)

    input_start = pd.Timestamp("2017-01-01 00:00", tz="UTC")
    input_end = input_start + pd.Timedelta(hours=400)
    forecast_hours = 48

    result = forecast_for_building(
        db=None,
        building_id="B0",
        metric_type_id="electricity",
        input_start=input_start,
        input_end=input_end,
        forecast_hours=forecast_hours,
    )

    assert result["building_id"] == "B0"
    assert result["metric_type"] == "electricity"
    assert result["horizon_hours"] == 24
    assert result["forecast_hours"] == forecast_hours
    assert result["model_run_id"] == "run-123"
    assert pd.Timestamp(result["divider_timestamp"]) == input_end

    divider = pd.Timestamp(result["divider_timestamp"])
    future_pts = [p for p in result["points"] if pd.Timestamp(p["timestamp"]) > divider]

    # Smooth hourly future line, exactly forecast_hours long.
    assert len(future_pts) == forecast_hours
    assert all(p["forecast"] is not None for p in future_pts)
    assert all(p["actual"] is None for p in future_pts)
    assert all(np.isfinite(p["forecast"]) and p["forecast"] >= 0 for p in future_pts)
    # Future timestamps are contiguous hourly steps.
    future_ts = [pd.Timestamp(p["timestamp"]) for p in future_pts]
    diffs = pd.unique(pd.Series(future_ts).diff().dropna())
    assert len(diffs) == 1 and diffs[0] == pd.Timedelta(hours=1)

    # Overlay: first timestamp with BOTH actual+forecast == input_start + 168h + 24h.
    overlay_start = input_start + pd.Timedelta(hours=LOOKBACK_HOURS + 24)
    both = [p for p in result["points"] if p["actual"] is not None and p["forecast"] is not None]
    assert len(both) > 0
    assert min(pd.Timestamp(p["timestamp"]) for p in both) == overlay_start


def test_forecast_for_building_floors_end_of_day_input(monkeypatch):
    pipeline, feature_cols, cat_features, df = _train_pipeline()
    _install_mocks(monkeypatch, pipeline, feature_cols, cat_features, df)

    input_start = pd.Timestamp("2017-01-01 00:00:00", tz="UTC")
    input_end = pd.Timestamp("2017-01-17 16:59:59", tz="UTC")

    result = forecast_for_building(
        db=None,
        building_id="B0",
        metric_type_id="electricity",
        input_start=input_start,
        input_end=input_end,
        forecast_hours=24,
    )

    assert pd.Timestamp(result["divider_timestamp"]) == pd.Timestamp(
        "2017-01-17 16:00:00", tz="UTC"
    )


def test_forecast_for_building_rejects_short_input_window(monkeypatch):
    pipeline, feature_cols, cat_features, df = _train_pipeline()
    _install_mocks(monkeypatch, pipeline, feature_cols, cat_features, df)

    input_start = pd.Timestamp("2017-01-01 00:00", tz="UTC")
    input_end = input_start + pd.Timedelta(hours=100)  # < 168h
    with pytest.raises(ForecastError):
        forecast_for_building(
            db=None,
            building_id="B0",
            metric_type_id="electricity",
            input_start=input_start,
            input_end=input_end,
            forecast_hours=24,
        )


def test_forecast_for_building_requires_lag_plus_model_horizon(monkeypatch):
    pipeline, feature_cols, cat_features, df = _train_pipeline()
    _install_mocks(monkeypatch, pipeline, feature_cols, cat_features, df)

    input_start = pd.Timestamp("2017-01-01 00:00", tz="UTC")
    input_end = input_start + pd.Timedelta(hours=180)  # >= 168h but < 168h + 24h
    with pytest.raises(ForecastError, match="at least 192h"):
        forecast_for_building(
            db=None,
            building_id="B0",
            metric_type_id="electricity",
            input_start=input_start,
            input_end=input_end,
            forecast_hours=24,
        )


def test_forecast_for_building_rejects_bad_forecast_hours(monkeypatch):
    pipeline, feature_cols, cat_features, df = _train_pipeline()
    _install_mocks(monkeypatch, pipeline, feature_cols, cat_features, df)

    input_start = pd.Timestamp("2017-01-01 00:00", tz="UTC")
    input_end = input_start + pd.Timedelta(hours=400)
    with pytest.raises(ForecastError):
        forecast_for_building(
            db=None,
            building_id="B0",
            metric_type_id="electricity",
            input_start=input_start,
            input_end=input_end,
            forecast_hours=0,
        )


def test_forecast_for_building_no_production_model(monkeypatch):
    monkeypatch.setattr(
        inference_module.ForecastingMlflowRegistry,
        "load_production_forecast_model",
        lambda self, model_name="dmp_energy_forecasting": None,
    )
    input_start = pd.Timestamp("2017-01-01 00:00", tz="UTC")
    input_end = input_start + pd.Timedelta(hours=400)
    with pytest.raises(ForecastError) as exc:
        forecast_for_building(
            db=None,
            building_id="B0",
            metric_type_id="electricity",
            input_start=input_start,
            input_end=input_end,
            forecast_hours=24,
        )
    assert exc.value.status_code == 404
