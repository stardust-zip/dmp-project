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
    for col in CAT_FEATURES:
        if col in df.columns:
            df[col] = df[col].astype("string")
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

    out = _coerce_input(df).sort_values(["building_id", "timestamp"]).reset_index(drop=True)

    grouped = out.groupby("building_id", sort=False)[TARGET_COL]

    # Calendar features from the timestamp.
    out["hour"] = out["timestamp"].dt.hour.astype("float32")
    out["day_of_week"] = out["timestamp"].dt.dayofweek.astype("float32")
    out["month"] = out["timestamp"].dt.month.astype("float32")
    out["is_weekend"] = (out["day_of_week"] >= 5).astype("float32")

    # Lag features (strictly past).
    out["lag_1h"] = grouped.shift(1).astype("float32")
    out["lag_24h"] = grouped.shift(24).astype("float32")
    out["lag_168h"] = grouped.shift(LOOKBACK_HOURS).astype("float32")

    # Rolling features INCLUDING the current hour (legitimate for direct forecasting).
    out["rolling_mean_24h"] = grouped.transform(
        lambda s: s.rolling(24, min_periods=1).mean()
    ).astype("float32")
    out["rolling_std_24h"] = grouped.transform(
        lambda s: s.rolling(24, min_periods=2).std()
    ).astype("float32")
    out["rolling_mean_168h"] = grouped.transform(
        lambda s: s.rolling(LOOKBACK_HOURS, min_periods=1).mean()
    ).astype("float32")
    out["rolling_std_168h"] = grouped.transform(
        lambda s: s.rolling(LOOKBACK_HOURS, min_periods=2).std()
    ).astype("float32")

    # Direct h-step-ahead target (training only). At inference we do not have
    # the future actual, so the target column is omitted and rows are kept.
    if include_target:
        out["target"] = grouped.shift(-forecast_horizon_hours).astype("float32")

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
