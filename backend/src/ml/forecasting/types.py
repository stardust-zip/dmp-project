"""Constants for the forecasting training/inference pipeline.

Mirrors the structure of :mod:`src.ml.anomaly.types`. Forecasting reuses the
anomaly data loader (:func:`src.ml.anomaly.telemetry_loaders.load_telemetry_for_training`)
but builds its own feature matrix (see :mod:`src.ml.forecasting.feature_engineering`).
"""

from __future__ import annotations

import re

# Base registered MLflow model name. When training on all buildings this is used
# directly. When training on a specific building the name becomes
# ``dmp_energy_forecasting_{building_id}_{metric}``.
MODEL_NAME = "dmp_energy_forecasting"


def forecast_model_name(
    base_name: str = MODEL_NAME,
    *,
    building_id: str | None = None,
    metric: str | None = None,
) -> str:
    """Compute the MLflow registered model name for a forecasting model.

    - ``building_id=None``  → global model (``base_name``).
    - ``building_id`` given  → per-building model ``{base_name}_{building_id}_{metric}``.
    """
    if not building_id:
        return base_name
    safe_building = _safe_name(building_id)
    safe_metric = _safe_name(metric or "")
    parts = [base_name, safe_building]
    if safe_metric:
        parts.append(safe_metric)
    return "_".join(parts)


def _safe_name(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return normalized.strip("._-") or "unknown"


# Target column produced by the telemetry loader (= the meter reading we forecast).
TARGET_COL = "consumption"

# Largest lag in hours. The anomaly loader already extends the query window by this
# amount so lag features can warm up at the start of the requested range.
LOOKBACK_HOURS = 168

# Direct h-step-ahead forecasting: target = consumption.shift(-horizon). A model is
# horizon-specific, so the horizon is logged as an MLflow tag.
DEFAULT_FORECAST_HORIZON = 24

# MVP is energy-only features. weather_mode="forecast" (future-weather shift) is Phase 2.
DEFAULT_WEATHER_MODE = "none"

# Phase 2: weather features aligned to the target time (weather(T+H) on an issue-time T
# row). The set of modes the forecasting pipeline accepts.
FORECAST_WEATHER_MODE = "forecast"
ALLOWED_WEATHER_MODES = {"none", FORECAST_WEATHER_MODE}

# Categorical features passed through OrdinalEncoder(handle_unknown="use_encoded_value").
CAT_FEATURES = ["building_id", "primaryspaceusage", "timezone"]

DEFAULT_METRIC_TYPE = "electricity"
RANDOM_STATE = 42

# Preprocessing (ported from forecasting_module/config.py + outlier.py + preprocessing.py).
IQR_MULTIPLIER = 3.0            # IQR fence per (building_id, hour_of_day)
INTERP_MAX_GAP_HOURS = 6        # linear-interpolate gaps <= this many hours
SEASONAL_MAX_GAP_HOURS = 24     # seasonal-fill (t-24h) for gaps in (6, 24]
MISSING_RATE_THRESHOLD = 0.30   # drop buildings whose consumption null-rate exceeds this
TELEMETRY_FREQ = "1h"           # hourly grid used when aligning timestamps
