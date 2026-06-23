"""Recursive future forecasting for a single building (Phase 2).

The production forecasting model is a *direct h-step-ahead* estimator trained so
that ``feature(T) -> consumption(T + H)`` where ``H`` is the (model-fixed)
horizon (typically 24h). To produce a **smooth hourly** forecast line — instead
of one point every H hours — we step the issue time ``T`` forward one hour at a
time and read off ``consumption(T + H)``.

Two regions are forecast:

* **Overlay** ``[overlay_start, input_end]``: honest H-ahead forecasts over the
  *recent past*. Every issue time ``T = target - H`` lies inside the actuals
  window, so all lags/rolling features are computed on **real** consumption.
  This is what the operator compares against the actual line.
* **Future** ``(input_end, input_end + forecast_hours]``: recursive *wave*
  forecasting. Each wave advances ``H`` hours; the previous wave's forecasts are
  appended to the consumption series so the next wave's lags/rolling are fed by
  them — error accumulates per wave, which is the honest autoregressive
  behaviour the user asked for.

Only the **future** region is persisted to ``ForecastResult``; the overlay is for
display only (it would duplicate information the actuals already convey).
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd
from src.ml.forecasting.feature_engineering import build_forecast_feature_matrix
from src.ml.forecasting.model_registry import ForecastingMlflowRegistry
from src.ml.forecasting.preprocessing import clean_telemetry_for_forecasting
from src.ml.forecasting.store import ForecastResultStore, _ensure_meter_device
from src.ml.forecasting.types import LOOKBACK_HOURS

logger = logging.getLogger(__name__)

_ONE_HOUR = pd.Timedelta(hours=1)


class ForecastError(Exception):
    """Domain error raised during forecasting; carries an HTTP status code."""

    def __init__(self, detail: str, status_code: int = 422) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def _to_utc_ts(value: Any) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _static_columns(df: pd.DataFrame) -> dict[str, Any]:
    """Carry-over static (building-level) columns when synthesizing future rows."""
    row = df.iloc[0]
    return {
        "building_id": row["building_id"],
        "metric_type_id": row["metric_type_id"],
        "site_id": row.get("site_id"),
        "sqm": row.get("sqm"),
        "primaryspaceusage": row.get("primaryspaceusage"),
        "timezone": row.get("timezone"),
    }


def forecast_for_building(
    db,
    *,
    building_id: str,
    metric_type_id: str,
    input_start,
    input_end,
    forecast_hours: int,
) -> dict[str, Any]:
    """Forecast consumption for one building.

    Parameters mirror the operator request: an input window of **actuals**
    (must be >= ``LOOKBACK_HOURS`` so lag/rolling-168h exist) plus how many
    ``forecast_hours`` of the future to predict. Returns a merged timeline with
    nullable ``actual`` / ``forecast`` per timestamp plus metadata; future
    forecasts are persisted to ``ForecastResult``.
    """
    input_start = _to_utc_ts(input_start)
    input_end = _to_utc_ts(input_end)
    # UI date inputs often arrive as end-of-day ``23:59:59`` while telemetry is
    # hourly. Align to the feature matrix frequency so issue-time lookups match.
    input_start = input_start.floor("h")
    input_end = input_end.floor("h")

    if input_end <= input_start:
        raise ForecastError("input_end must be after input_start.")
    if not 1 <= forecast_hours <= LOOKBACK_HOURS:
        raise ForecastError(
            f"forecast_hours must be between 1 and {LOOKBACK_HOURS}.",
        )

    # Try building-specific model first, then fall back to global
    from src.ml.forecasting.types import forecast_model_name

    building_model = forecast_model_name(building_id=building_id, metric=metric_type_id)
    loaded = ForecastingMlflowRegistry().load_production_forecast_model(
        model_name=building_model
    )
    used_model_name = building_model
    if loaded is None:
        loaded = ForecastingMlflowRegistry().load_production_forecast_model()
        used_model_name = "dmp_energy_forecasting"
    if loaded is None:
        raise ForecastError(
            "No production forecasting model is available. Train one first.",
            status_code=404,
        )
    pipeline, feature_cols, _cat_features, horizon, metric_tag, run_id = loaded
    supported_metrics = {m.strip() for m in str(metric_tag).split(",") if m.strip()}
    if supported_metrics and metric_type_id not in supported_metrics:
        raise ForecastError(
            f"The production forecasting model was trained for metric(s) "
            f"{sorted(supported_metrics)}, but '{metric_type_id}' was requested.",
        )
    if not run_id:
        raise ForecastError(
            "Production forecasting model is missing its MLflow run_id; "
            "cannot persist forecast results.",
            status_code=503,
        )

    H = horizon
    H_td = pd.Timedelta(hours=H)
    required_history_hours = LOOKBACK_HOURS + H
    if (input_end - input_start) < pd.Timedelta(hours=required_history_hours):
        raise ForecastError(
            f"Input window must be at least {required_history_hours}h for a "
            f"{H}h-horizon model to compute lag/rolling features.",
        )

    # --- Load actuals for this building across the input window ---
    from src.ml.anomaly.telemetry_loaders import query_telemetry_window

    df = query_telemetry_window(db, input_start, input_end, metrics=[metric_type_id])
    df = df[df["building_id"] == building_id].copy()
    if df.empty:
        raise ForecastError(
            f"No telemetry found for building '{building_id}' "
            f"(metric '{metric_type_id}') in the input window.",
        )
    df = df.sort_values("timestamp").reset_index(drop=True)

    # --- Clean actuals ONCE with the same logic as training (no train/serve
    # skew). The recursive-wave predictions appended into series_df below are
    # model outputs (already clipped >= 0) and must NOT be re-cleaned, so this
    # runs before series_df = df.copy() and is never reapplied in the loop. ---
    df = clean_telemetry_for_forecasting(df, drop_high_missing=False)
    if df.empty:
        raise ForecastError(
            f"No usable telemetry for building '{building_id}' "
            f"(metric '{metric_type_id}') after cleaning; the building may have "
            f"excessive missing data in the input window.",
        )

    overlay_start = input_start + pd.Timedelta(hours=LOOKBACK_HOURS) + H_td

    # --- Overlay: honest H-ahead forecasts on REAL features ---
    feat_actual, _, _ = build_forecast_feature_matrix(
        df, forecast_horizon_hours=H, weather_mode="none", include_target=False
    )
    overlay_map: dict[pd.Timestamp, float] = {}
    t_lo = overlay_start - H_td  # = input_start + LOOKBACK
    t_hi = input_end - H_td
    if t_lo <= t_hi:
        overlay_feat = feat_actual[
            (feat_actual["timestamp"] >= t_lo) & (feat_actual["timestamp"] <= t_hi)
        ]
        if not overlay_feat.empty:
            yhat = pipeline.predict(overlay_feat[feature_cols]).clip(min=0)
            for t, y in zip(overlay_feat["timestamp"], yhat):
                overlay_map[t + H_td] = float(y)

    # --- Future: recursive wave forecasting ---
    static = _static_columns(df)
    series_df = df.copy()
    future_map: dict[pd.Timestamp, float] = {}
    cursor = input_end + _ONE_HOUR
    produced = 0
    while produced < forecast_hours:
        wave_size = min(H, forecast_hours - produced)
        wave_targets = pd.date_range(
            cursor, periods=wave_size, freq="1h", tz=input_start.tzinfo
        )
        wave_t_issue = wave_targets - H_td

        feat, _, _ = build_forecast_feature_matrix(
            series_df,
            forecast_horizon_hours=H,
            weather_mode="none",
            include_target=False,
        )
        avail = feat[feat["timestamp"].isin(wave_t_issue)]
        if avail.empty:
            missing = [t for t in wave_t_issue]
            raise ForecastError(
                "Could not build features for the forecast window "
                f"(missing issue times: {missing}). The input window may have gaps.",
            )
        pred_by_t = dict(
            zip(avail["timestamp"], pipeline.predict(avail[feature_cols]).clip(min=0))
        )
        if len(pred_by_t) != wave_size:
            missing = [t for t in wave_t_issue if t not in pred_by_t]
            raise ForecastError(
                "Could not build features for every forecast step "
                f"(missing issue times: {missing}). The input window may have gaps.",
            )
        yhat_ordered = [float(pred_by_t[t]) for t in wave_t_issue]

        appended = pd.DataFrame(
            {
                "timestamp": wave_targets,
                "consumption": yhat_ordered,
                "building_id": static["building_id"],
                "metric_type_id": static["metric_type_id"],
                "site_id": static["site_id"],
                "sqm": static["sqm"],
                "primaryspaceusage": static["primaryspaceusage"],
                "timezone": static["timezone"],
            }
        )
        series_df = pd.concat([series_df, appended], ignore_index=True)
        for target, y in zip(wave_targets, yhat_ordered):
            future_map[target] = y
        produced += wave_size
        cursor = cursor + pd.Timedelta(hours=wave_size)

    # --- Persist future forecasts only ---
    device_id = f"meter_{metric_type_id}_{building_id}"
    _ensure_meter_device(db, building_id, metric_type_id)
    records = [
        {
            "timestamp": ts.to_pydatetime(),
            "device_id": device_id,
            "metric_type_id": metric_type_id,
            "predicted_value": value,
            "mlflow_run_id": run_id,
        }
        for ts, value in sorted(future_map.items())
    ]
    ForecastResultStore(db).upsert(records)
    logger.info(
        "Persisted %d future forecast points for building=%s metric=%s",
        len(records),
        building_id,
        metric_type_id,
    )

    # --- Merged timeline for the chart ---
    actual_map = {
        pd.Timestamp(ts): float(v)
        for ts, v in zip(df["timestamp"], df["consumption"])
        if pd.notna(v)
    }
    forecast_map = {**overlay_map, **future_map}
    all_ts = sorted(set(actual_map) | set(forecast_map))
    points = [
        {
            "timestamp": ts.to_pydatetime(),
            "actual": actual_map.get(ts),
            "forecast": forecast_map.get(ts),
        }
        for ts in all_ts
    ]

    return {
        "building_id": building_id,
        "site_id": static["site_id"],
        "metric_type": metric_type_id,
        "horizon_hours": H,
        "model_name": used_model_name,
        "model_run_id": run_id,
        "input_start": input_start.to_pydatetime(),
        "input_end": input_end.to_pydatetime(),
        "forecast_hours": forecast_hours,
        "divider_timestamp": input_end.to_pydatetime(),
        "points": points,
    }
