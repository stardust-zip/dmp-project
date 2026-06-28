"""Forecasting feature engineering.

Single shared feature builder used by BOTH training and inference to avoid
train/serve skew. This is a pandas port of the proven logic in
``forecasting_module/feature_engineering.py`` (the standalone notebook pipeline),
adapted to the column contract produced by the anomaly telemetry loader.

Forecasting is *direct h-step-ahead*: the target at row ``t`` is
``consumption.shift(-horizon)``. Therefore rolling features are computed
**including the current hour** (no ``shift(1)``), because every value up to and
including ``t`` is observed before the forecast target ``t + horizon``. This
differs from the anomaly feature builder, which must ``shift(1)`` because it
predicts the *current* hour.
"""

from __future__ import annotations

import pandas as pd

from src.ml.forecasting.types import (
    CAT_FEATURES,
    DEFAULT_FORECAST_HORIZON,
    DEFAULT_WEATHER_MODE,
    LOOKBACK_HOURS,
    TARGET_COL,
)

# Deterministic order: categoricals first (mirrors the standalone notebook's
# feature column order), then metadata + calendar + lag/rolling numeric features.
FEATURE_COLUMNS: list[str] = [
    "building_id",
    "primaryspaceusage",
    "timezone",
    "sqm",
    "hour",
    "day_of_week",
    "month",
    "is_weekend",
    "lag_1h",
    "lag_24h",
    "lag_168h",
    "rolling_mean_24h",
    "rolling_std_24h",
    "rolling_mean_168h",
    "rolling_std_168h",
]


def _coerce_input(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df[TARGET_COL] = pd.to_numeric(df[TARGET_COL], errors="coerce")
    if "sqm" in df.columns:
        df["sqm"] = pd.to_numeric(df["sqm"], errors="coerce")
    # Encode categorical metadata as pandas "category" (NOT "string"). On the full
    # electricity grid the loader returns ~20M rows: object string columns cost
    # ~50 bytes/row each (~1 GB per column) and were the dominant RAM consumer —
    # the root cause of the worker OOM during feature-matrix build. "category"
    # stores them as int codes (~20 MB per column) with identical values.
    for col in CAT_FEATURES:
        if col in df.columns:
            df[col] = df[col].astype("category")
    # site_id rides along as static metadata (it is not a model feature) but is
    # equally bloated as a string; categorize it too so it stops multiplying RAM
    # across the copies the builder makes below.
    if "site_id" in df.columns and "site_id" not in CAT_FEATURES:
        df["site_id"] = df["site_id"].astype("category")
    return df


def build_forecast_feature_matrix(
    df: pd.DataFrame,
    forecast_horizon_hours: int = DEFAULT_FORECAST_HORIZON,
    weather_mode: str = DEFAULT_WEATHER_MODE,
    *,
    include_target: bool = True,
) -> tuple[pd.DataFrame, list[str], list[str]]:
    """Build the forecasting feature matrix from raw telemetry.

    Parameters
    ----------
    df:
        Output of :func:`src.ml.anomaly.telemetry_loaders.load_telemetry_for_training`
        (columns include ``timestamp``, ``consumption``, ``building_id``,
        ``site_id``, ``sqm``, ``primaryspaceusage``, ``timezone``).
    forecast_horizon_hours:
        Direct forecast horizon ``h``. Target = ``consumption.shift(-h)``.
    weather_mode:
        ``"none"`` for energy-only features (MVP). Other modes are Phase 2.
    include_target:
        When ``True`` (training) the direct-horizon ``target`` column is added
        and rows with a null target are dropped. When ``False`` (inference /
        recursive forecasting) no target is computed and rows are kept as long
        as every feature column is non-null — future timestamps have no known
        actual to use as a target.

    Returns
    -------
    (feature_df, feature_cols, cat_features)
        ``feature_df`` keeps ``timestamp`` and ``consumption`` (for splitting /
        evaluation) plus ``target`` (when ``include_target``) and all feature
        columns; rows with any null feature (and null target when training) are
        dropped. ``feature_cols`` is the ordered list fed to the model;
        ``cat_features`` the subset that is categorical.
    """
    if weather_mode != DEFAULT_WEATHER_MODE:
        raise NotImplementedError(
            f"weather_mode={weather_mode!r} is not supported yet (MVP is energy-only)."
        )
    if "consumption" not in df.columns or "timestamp" not in df.columns:
        raise ValueError("Input must contain 'timestamp' and 'consumption' columns.")

    out = _coerce_input(df)

    # Lag / rolling / target are computed per building in a SINGLE pass (each
    # group time-sorted) rather than as N separate ``grouped.transform(lambda)``
    # calls. The transform pattern allocated one full-length float64 Series per
    # feature AND re-aligned it to the original index — multiplying peak memory
    # ~8x and triggering the worker OOM on the full electricity grid. Computing
    # per group keeps only one small frame alive at a time; the concat at the end
    # is the single large allocation. Calendar features are added afterwards on
    # the concatenated frame (cheap and vectorized). The cleaner already returns
    # rows sorted by (building, timestamp); the per-group sort below is kept for
    # robustness (e.g. inference passes a single building sorted by timestamp).
    parts: list[pd.DataFrame] = []
    # observed=True: building_id is now a category; only iterate over building
    # IDs actually present (mirrors the original object-dtype groupby behaviour
    # and avoids emitting empty groups for unused categories).
    for _building_id, group in out.groupby("building_id", sort=False, observed=True):
        group = group.sort_values("timestamp")
        s = group[TARGET_COL]
        part = group.assign(
            lag_1h=s.shift(1).astype("float32"),
            lag_24h=s.shift(24).astype("float32"),
            lag_168h=s.shift(LOOKBACK_HOURS).astype("float32"),
            # Rolling features include the current hour (legitimate for direct
            # h-step-ahead forecasting: every value up to and including t is
            # observed before the forecast target t + horizon).
            rolling_mean_24h=s.rolling(24, min_periods=1).mean().astype("float32"),
            rolling_std_24h=s.rolling(24, min_periods=2).std().astype("float32"),
            rolling_mean_168h=s.rolling(LOOKBACK_HOURS, min_periods=1).mean().astype("float32"),
            rolling_std_168h=s.rolling(LOOKBACK_HOURS, min_periods=2).std().astype("float32"),
        )
        # Direct h-step-ahead target (training only). At inference we do not have
        # the future actual, so the target column is omitted and rows are kept.
        if include_target:
            part["target"] = s.shift(-forecast_horizon_hours).astype("float32")
        parts.append(part)

    out = pd.concat(parts, ignore_index=True)
    del parts

    # Calendar features from the timestamp.
    out["hour"] = out["timestamp"].dt.hour.astype("float32")
    out["day_of_week"] = out["timestamp"].dt.dayofweek.astype("float32")
    out["month"] = out["timestamp"].dt.month.astype("float32")
    out["is_weekend"] = (out["day_of_week"] >= 5).astype("float32")

    missing = [c for c in FEATURE_COLUMNS if c not in out.columns]
    if missing:
        raise ValueError(f"Telemetry is missing required columns: {missing}")

    required = list(FEATURE_COLUMNS) + (["target"] if include_target else [])
    before = len(out)
    out = out.dropna(subset=required).reset_index(drop=True)
    dropped = before - len(out)
    if dropped:
        # Boundary rows (lag/rolling warmup) and the target tail are dropped.
        # Logged by the caller; kept silent here to stay a pure function.
        pass

    cat_features = [c for c in CAT_FEATURES if c in FEATURE_COLUMNS]
    return out, list(FEATURE_COLUMNS), cat_features
