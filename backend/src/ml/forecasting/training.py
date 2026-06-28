"""Forecasting model training.

Entry point :func:`train_forecasting_model` mirrors
:func:`src.ml.anomaly.detection.train_anomaly_detection_model`: same signature
``(request, db, *, mlflow_run, pipeline_log, append_log) -> dict`` so it drops
straight into the ``Forecasting`` branch of :func:`src.tasks.train_model_task`.

Design notes
------------
- Data: reuses the anomaly loader
  :func:`src.ml.anomaly.telemetry_loaders.load_telemetry_for_training` (read-only;
  anomaly code is not modified). It already extends the window by ``LOOKBACK_HOURS``
  so ``lag_168h`` can warm up.
- Model: a single scikit-learn :class:`~sklearn.pipeline.Pipeline`
  (``OrdinalEncoder`` + ``SimpleImputer`` -> estimator), logged via
  ``mlflow.sklearn``. The estimator is swappable per ``request.algorithm``
  (LinearRegression / XGBoost / LightGBM); exactly one is trained per request.
- Fitting: the preprocessor is fit on the training split, then transforms
  train/val/test; the estimator is fit directly (so ``eval_set`` can drive early
  stopping for tree models). The fitted steps are reassembled into a Pipeline
  purely for serialization.
"""

from __future__ import annotations

import gc
import logging

import lightgbm as lgb
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, root_mean_squared_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OrdinalEncoder
from sqlalchemy.orm import Session
from src.ml.anomaly.telemetry_loaders import (
    downcast_telemetry_dtypes,
    load_telemetry_for_training,
)
from src.ml.anomaly.weather_loaders import load_weather_for_range
from src.ml.forecasting.feature_engineering import build_forecast_feature_matrix
from src.ml.forecasting.model_registry import ForecastingMlflowRegistry
from src.ml.forecasting.preprocessing import clean_telemetry_for_forecasting
from src.ml.forecasting.types import (
    DEFAULT_FORECAST_HORIZON,
    DEFAULT_WEATHER_MODE,
    FORECAST_WEATHER_MODE,
    LOOKBACK_HOURS,
    RANDOM_STATE,
    forecast_model_name,
)
from src.models import AIPipelineLog
from src.schemas import MLAlgorithm, ModelTrainingRequest
from xgboost import XGBRegressor

logger = logging.getLogger(__name__)

TARGET_COLUMN = "target"
EARLY_STOPPING_ROUNDS = 100

# MAPE divides by the actual, so near-zero actuals blow it up without bound: a
# 0.001 kWh actual with a 5 kWh prediction is a 500,000% error. Masking only
# exact zeros (|y| <= 1e-9) left test MAPE at ~10,887% on real data; masking
# actuals <= 1 kWh brings it to a stable ~17%. See
# ``notebooks/forecasting/EDA/diagnose_mape.py`` for the measurement.
MAPE_MIN_ACTUAL = 1.0

# Tree-learner device. The Celery worker is CPU-only; on CPU n_jobs=-1 uses all
# cores, while on GPU a single job is preferred (XGBoost parallelizes on GPU).
TREE_DEVICE = "cpu"

# XGBoost: squared-error (RMSE) objective with RMSE-driven early stopping. This
# replaces the former reg:absoluteerror (MAE) objective. ``device``/``tree_method``
# require XGBoost >= 2.0 (pyproject pins >= 2.0.3). early_stopping_rounds=200 is
# set in the constructor (the LightGBM path keeps its own EARLY_STOPPING_ROUNDS).
XGB_PARAMS = {
    "objective": "reg:squarederror",
    "eval_metric": "rmse",
    "n_estimators": 2000,
    "early_stopping_rounds": 200,
    "learning_rate": 0.1,
    "max_depth": 8,
    "min_child_weight": 10,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "reg_alpha": 2,
    "reg_lambda": 1.0,
    "random_state": RANDOM_STATE,
    "n_jobs": -1 if TREE_DEVICE == "cpu" else 1,
    "tree_method": "hist",
    "device": TREE_DEVICE,
}
LGBM_PARAMS = {
    "objective": "regression",
    "metric": "rmse",
    "n_estimators": 2000,
    "learning_rate": 0.05,
    "max_depth": 8,
    "subsample": 0.85,
    "colsample_bytree": 0.85,
    "random_state": RANDOM_STATE,
    "verbose": -1,
}


def _make_estimator(algorithm: MLAlgorithm):
    algo = MLAlgorithm(algorithm)
    if algo == MLAlgorithm.LinearRegression:
        return LinearRegression()
    if algo == MLAlgorithm.XGBoost:
        return XGBRegressor(**XGB_PARAMS)
    if algo == MLAlgorithm.LightGBM:
        return LGBMRegressor(**LGBM_PARAMS)
    raise ValueError(f"Unsupported forecasting algorithm: {algorithm}")


def _build_preprocessor(
    cat_features: list[str], num_features: list[str]
) -> ColumnTransformer:
    return ColumnTransformer(
        transformers=[
            (
                "cat",
                OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1),
                cat_features,
            ),
            ("num", SimpleImputer(strategy="median"), num_features),
        ],
        remainder="drop",
    )


def _mape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Mean Absolute Percentage Error, returned as a PERCENT (e.g. 2.66 == 2.66%).

    Matches the frontend's ``unit: "%"`` rendering; ``test_mape`` stored in
    MLflow is therefore a percentage, not a raw ratio.

    Actuals <= ``MAPE_MIN_ACTUAL`` kWh are masked out before averaging. MAPE is
    unbounded and divides by the actual, so near-zero actuals (interpolated
    night-time consumption etc.) each contribute thousands of percent and
    dominate the mean; a 1 kWh floor keeps the metric stable while staying
    physically meaningful.
    """
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    mask = np.abs(y_true) > MAPE_MIN_ACTUAL
    if not mask.any():
        return float("nan")
    return float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100.0)


def _fit_and_evaluate(
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
    test_df: pd.DataFrame,
    feature_cols: list[str],
    cat_features: list[str],
    algorithm: MLAlgorithm,
) -> tuple[Pipeline, dict[str, float]]:
    """Fit preprocessor + estimator on the splits and score the test set.

    Pure (no MLflow/DB) so it is unit-testable directly. Returns the assembled
    fitted Pipeline and a metrics dict.
    """
    num_features = [c for c in feature_cols if c not in cat_features]
    preprocessor = _build_preprocessor(cat_features, num_features)
    preprocessor.fit(train_df[feature_cols])

    # Cast the transformed matrices to float32 before fitting: it halves the
    # memory of x_train/x_val/x_test (the largest allocations at training time on
    # the full grid), and XGBoost's tree_method="hist" consumes float32 natively.
    # Early stopping is keyed on iteration count, not dtype, so it is unaffected.
    x_train = preprocessor.transform(train_df[feature_cols]).astype(np.float32)
    x_test = preprocessor.transform(test_df[feature_cols]).astype(np.float32)
    y_train = train_df[TARGET_COLUMN].to_numpy(dtype=np.float32)
    y_test = test_df[TARGET_COLUMN].to_numpy(dtype=np.float32)

    estimator = _make_estimator(algorithm)
    fit_kwargs: dict = {}
    if algorithm != MLAlgorithm.LinearRegression and not val_df.empty:
        x_val = preprocessor.transform(val_df[feature_cols]).astype(np.float32)
        y_val = val_df[TARGET_COLUMN].to_numpy(dtype=np.float32)
        fit_kwargs["eval_set"] = [(x_val, y_val)]
        if algorithm == MLAlgorithm.LightGBM:
            fit_kwargs["callbacks"] = [
                lgb.early_stopping(
                    EARLY_STOPPING_ROUNDS, first_metric_only=True, verbose=False
                ),
                lgb.log_evaluation(0),
            ]
    estimator.fit(x_train, y_train, **fit_kwargs)

    pred = np.clip(np.asarray(estimator.predict(x_test), dtype=float), 0.0, None)
    metrics = {
        "test_mae": float(mean_absolute_error(y_test, pred)),
        "test_rmse": float(root_mean_squared_error(y_test, pred)),
        "test_mape": _mape(y_test, pred),
    }
    pipeline = Pipeline([("features", preprocessor), ("model", estimator)])
    return pipeline, metrics


def _split_by_timestamps(df: pd.DataFrame, start, end) -> pd.DataFrame:
    return df[(df["timestamp"] >= start) & (df["timestamp"] <= end)].copy()


def train_forecasting_model(
    request: ModelTrainingRequest,
    db: Session,
    *,
    mlflow_run,
    pipeline_log: AIPipelineLog,
    append_log,
) -> dict[str, object]:
    """Train and register a direct h-step-ahead forecasting model.

    Mirrors :func:`src.ml.anomaly.detection.train_anomaly_detection_model`. Returns
    a dict of numeric metrics (consumed by ``train_model_task`` -> ``mlflow.log_metrics``).
    """
    if len(request.metrics) != 1:
        raise ValueError("Forecasting training requires exactly one metric per model.")

    horizon = int(getattr(request, "forecast_horizon_hours", DEFAULT_FORECAST_HORIZON))
    weather_mode = getattr(request, "weather_mode", DEFAULT_WEATHER_MODE)
    # Forecasting always trains XGBoost (the UI no longer offers a choice).
    algorithm = MLAlgorithm.XGBoost

    # --- Determine whether we're training per-building or globally ---
    target_building_id = request.building_id or None
    is_per_building = bool(target_building_id)

    # --- Compute dynamic model name ---
    model_name = forecast_model_name(
        building_id=target_building_id,
        metric=request.metrics[0],
    )
    if is_per_building:
        append_log(
            f"Per-building training for building={target_building_id} "
            f"-> model name: {model_name}"
        )
    else:
        append_log(f"Global training (all buildings) -> model name: {model_name}")

    # --- Load telemetry (reuse anomaly loader: CSV/DB + 168h lookback + metadata) ---
    append_log(
        f"Loading telemetry for metric={request.metrics[0]} "
        f"(lookback {LOOKBACK_HOURS}h for lag warmup)..."
    )
    df = load_telemetry_for_training(db, request)
    if df.empty:
        raise ValueError("No telemetry data found for the requested date range.")

    # --- Filter to single building if per-building training ---
    if is_per_building:
        df = df[df["building_id"] == target_building_id].copy()
        if df.empty:
            raise ValueError(
                f"No telemetry for building '{target_building_id}' "
                f"in the requested date range."
            )
        append_log(f"Filtered to building '{target_building_id}': {len(df):,} rows.")
    else:
        append_log(f"Loaded {len(df):,} rows, {df['building_id'].nunique()} buildings.")

    # Downcast float64->float32 BEFORE cleaning so the ~2.5x hourly-grid expansion
    # and the IQR/interpolate steps operate on half-size numerics. Mirrors the
    # anomaly module's downcast_telemetry_dtypes (the portable part of its memory
    # strategy; anomaly's chunked training is not viable here because forecasting
    # uses XGBRegressor, whose sklearn API has no incremental/init_model fit).
    downcast_telemetry_dtypes(df)

    # --- Clean telemetry: hourly align, IQR outliers->null, interpolate/seasonal-fill.
    # Single shared cleaner with inference (no train/serve skew). High-missing
    # buildings are only dropped in global (all-buildings) mode; a single,
    # explicitly-chosen building is never dropped here. ---
    append_log("Cleaning telemetry (hourly align, IQR outliers, gap fill)...")
    df, clean_stats = clean_telemetry_for_forecasting(
        df, drop_high_missing=not is_per_building, return_stats=True
    )
    if df.empty:
        raise ValueError(
            "Telemetry is empty after cleaning (all buildings dropped or no valid "
            "consumption); provide a wider/cleaner time range."
        )
    append_log(
        f"Cleaned telemetry: {clean_stats['outliers_flagged']:,} outliers flagged, "
        f"{clean_stats['gaps_filled']:,} gaps interpolated, "
        f"{clean_stats['buildings_dropped']} buildings dropped (>30% missing)."
    )

    # Re-downcast (cleaning may upcast during align/interpolate) and release the
    # transient intermediates before the feature-matrix build allocates again.
    downcast_telemetry_dtypes(df)
    gc.collect()

    # --- Phase 2: load weather when weather_mode == "forecast" ---
    # Direct h-step-ahead: weather features reference the target time T+H, so load
    # weather covering [start, end + horizon] (target times). The feature builder
    # shifts it by -H internally. Weather coverage is ~2016-2017; rows outside it
    # have NaN weather and are dropped by the builder's dropna (training mode), so
    # a range extending beyond 2016-2017 reduces the training set.
    weather_df = pd.DataFrame()
    if weather_mode == FORECAST_WEATHER_MODE:
        site_ids = df["site_id"].dropna().unique().tolist()
        if site_ids:
            wstart = pd.Timestamp(request.time_range_start)
            wend = pd.Timestamp(request.time_range_end) + pd.Timedelta(hours=horizon)
            weather_df, _weather_cols = load_weather_for_range(db, site_ids, wstart, wend)
            if weather_df.empty:
                append_log(
                    "No weather data for the requested range; "
                    "rows without weather coverage will be dropped."
                )
            else:
                append_log(f"Weather loaded: {_weather_cols}")
        else:
            append_log("No site_ids in telemetry; skipping weather load.")

    # --- Feature matrix (single shared builder; used by inference too) ---
    append_log(
        f"Building feature matrix (horizon={horizon}h, weather={weather_mode})..."
    )
    feature_df, feature_cols, cat_features = build_forecast_feature_matrix(
        df, horizon, weather_mode, weather_df=weather_df
    )
    if feature_df.empty:
        raise ValueError(
            "Feature matrix is empty after lag warmup + null drop; "
            "provide a wider time range."
        )

    # --- For per-building training, drop building_id from categorical features ---
    # (there is only one building, so it provides no signal)
    if is_per_building and "building_id" in cat_features:
        cat_features = [c for c in cat_features if c != "building_id"]
        if "building_id" in feature_cols:
            feature_cols = [c for c in feature_cols if c != "building_id"]
        append_log("Dropped 'building_id' from features (single-building mode).")

    append_log(
        f"Feature matrix: {len(feature_df):,} rows x {len(feature_cols)} features."
    )

    # --- Temporal split (70/15/15 of the requested range) ---
    start = pd.Timestamp(request.time_range_start)
    end = pd.Timestamp(request.time_range_end)
    total = end - start
    train_end = start + total * 0.70
    test_start = end - total * 0.15
    train_df = _split_by_timestamps(feature_df, start, train_end)
    val_df = _split_by_timestamps(feature_df, train_end, test_start)
    test_df = _split_by_timestamps(feature_df, test_start, end)
    append_log(
        f"Split -> train={len(train_df):,} val={len(val_df):,} test={len(test_df):,}."
    )
    if train_df.empty or test_df.empty:
        raise ValueError("Train or test split is empty; provide a wider time range.")
    if algorithm != MLAlgorithm.LinearRegression and val_df.empty:
        raise ValueError(
            "Validation split is empty; cannot apply early stopping. Widen the time range."
        )

    # Capture the values we still need from the large frames, then FREE them
    # before the fit. This is the peak-memory moment: the cleaned frame (df),
    # the full feature matrix (feature_df), the three split copies, the
    # transformed X matrices, and XGBoost's internal allocations all overlap.
    # The splits are independent copies, so deleting df/feature_df is safe.
    # Mirrors anomaly's `del df; gc.collect()` before training.
    trained_building_ids = sorted(df["building_id"].astype(str).unique().tolist())
    training_rows = len(feature_df)
    n_buildings = int(feature_df["building_id"].nunique())
    del df, feature_df
    gc.collect()

    # --- Train + evaluate ---
    append_log(f"Training {algorithm.value} (direct {horizon}h-ahead)...")
    pipeline, metrics = _fit_and_evaluate(
        train_df, val_df, test_df, feature_cols, cat_features, algorithm
    )
    append_log(
        f"Test MAE={metrics['test_mae']:.4f} RMSE={metrics['test_rmse']:.4f} "
        f"MAPE={metrics['test_mape']:.4f}%"
    )

    # --- Register to MLflow ---
    append_log("Logging model to MLflow...")
    registry = ForecastingMlflowRegistry()
    version = registry.log_model(
        pipeline,
        feature_cols,
        metrics,
        request,
        horizon=horizon,
        algorithm=algorithm.value,
        weather_mode=weather_mode,
        model_name=model_name,
    )
    append_log(f"Model registered as {model_name}.")

    # --- Record building coverage so the forecast UI can hide dropped buildings. ---
    # trained_building_ids was captured before the fit (df is freed by then).
    dropped_building_ids = sorted(clean_stats.get("dropped_building_ids", []))
    registry.log_coverage_artifact(
        trained_building_ids=trained_building_ids,
        dropped_building_ids=dropped_building_ids,
    )
    append_log(
        f"Coverage: {len(trained_building_ids)} building(s) trained, "
        f"{len(dropped_building_ids)} dropped (>30% missing)."
    )

    # Auto-promote the freshly trained version to production so inference can
    # load it immediately (no manual MLflow UI step required).
    if version:
        registry.promote_version(version, model_name=model_name)
        append_log(f"Promoted version {version} to the 'production' alias.")

    return {
        "test_mae": metrics["test_mae"],
        "test_rmse": metrics["test_rmse"],
        "test_mape": metrics["test_mape"],
        "training_rows": float(training_rows),
        "n_buildings": float(n_buildings),
        "horizon": float(horizon),
    }
