"""Constants for the forecasting training/inference pipeline.

Mirrors the structure of :mod:`src.ml.anomaly.types`. Forecasting reuses the
anomaly data loader (:func:`src.ml.anomaly.telemetry_loaders.load_telemetry_for_training`)
but builds its own feature matrix (see :mod:`src.ml.forecasting.feature_engineering`).
"""

from __future__ import annotations

# Registered MLflow model name. Like anomaly, a single global model (building_id is a
# categorical feature), ignoring the per-site name computed in tasks.py.
MODEL_NAME = "dmp_energy_forecasting"

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

# Categorical features passed through OrdinalEncoder(handle_unknown="use_encoded_value").
CAT_FEATURES = ["building_id", "primaryspaceusage", "timezone"]

DEFAULT_METRIC_TYPE = "electricity"
RANDOM_STATE = 42
