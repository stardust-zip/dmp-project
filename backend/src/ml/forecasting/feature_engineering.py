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
    ALLOWED_WEATHER_MODES,
    CAT_FEATURES,
    DEFAULT_FORECAST_HORIZON,
    DEFAULT_WEATHER_MODE,
    FORECAST_WEATHER_MODE,
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


def _already_coerced(df: pd.DataFrame) -> bool:
    """True when df already has the dtypes the builder expects.

    Cleaned telemetry (output of ``clean_telemetry_for_forecasting``) is already
    coerced, so :func:`_coerce_input` can skip copying it (see its fast path).
    """
    if "timestamp" not in df.columns or TARGET_COL not in df.columns:
        return False
    if not isinstance(df["timestamp"].dtype, pd.DatetimeTZDtype):
        return False
    if not pd.api.types.is_numeric_dtype(df[TARGET_COL]):
        return False
    for col in CAT_FEATURES:
        if col in df.columns and not isinstance(df[col].dtype, pd.CategoricalDtype):
            return False
    return True


def _coerce_input(df: pd.DataFrame) -> pd.DataFrame:
    # Fast path: cleaned telemetry is already coerced. Return it AS-IS to avoid
    # copying the ~25M-row grid — that copy plus the caller's reference doubled
    # peak memory and caused the worker OOM. The caller's frame is only READ
    # below (groupby + assign on per-group copies), never mutated, so sharing the
    # reference is safe. Raw inputs (e.g. unit tests) take the copy+coerce path.
    if _already_coerced(df):
        return df
    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df[TARGET_COL] = pd.to_numeric(df[TARGET_COL], errors="coerce")
    if "sqm" in df.columns:
        df["sqm"] = pd.to_numeric(df["sqm"], errors="coerce")
    # Encode categorical metadata as pandas "category" (NOT "string"): object
    # string columns cost ~50 bytes/row (~1 GB/column on the full grid) and were
    # the dominant RAM consumer. "category" stores int codes (~20 MB/column).
    for col in CAT_FEATURES:
        if col in df.columns:
            df[col] = df[col].astype("category")
    if "site_id" in df.columns and "site_id" not in CAT_FEATURES:
        df["site_id"] = df["site_id"].astype("category")
    return df


def build_forecast_feature_matrix(
    df: pd.DataFrame,
    forecast_horizon_hours: int = DEFAULT_FORECAST_HORIZON,
    weather_mode: str = DEFAULT_WEATHER_MODE,
    *,
    include_target: bool = True,
    weather_df: pd.DataFrame | None = None,
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
    if weather_mode not in ALLOWED_WEATHER_MODES:
        raise ValueError(
            f"weather_mode={weather_mode!r} is not supported. "
            f"Allowed: {sorted(ALLOWED_WEATHER_MODES)}."
        )
    if "consumption" not in df.columns or "timestamp" not in df.columns:
        raise ValueError("Input must contain 'timestamp' and 'consumption' columns.")

    out = _coerce_input(df)

    # Columns a row must have non-null to survive. We dropna PER BUILDING inside
    # the loop so the accumulator holds ONLY survivors (~3x fewer rows than the
    # full aligned grid) — the key memory win: we never materialize features for
    # the ~17M warmup/gap rows that would be discarded anyway. Calendar is
    # computed inside the loop so the per-group dropna uses the full
    # FEATURE_COLUMNS set (identical to the old post-concat dropna semantics).
    energy_required = list(FEATURE_COLUMNS) + (["target"] if include_target else [])

    survivor_parts: list[pd.DataFrame] = []
    # observed=True: building_id is a category; only iterate over building IDs
    # actually present (avoids emitting empty groups for unused categories).
    for _building_id, group in out.groupby("building_id", sort=False, observed=True):
        group = group.sort_values("timestamp")
        s = group[TARGET_COL]
        ts = group["timestamp"]
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
            hour=ts.dt.hour.astype("float32"),
            day_of_week=ts.dt.dayofweek.astype("float32"),
            month=ts.dt.month.astype("float32"),
            is_weekend=(ts.dt.dayofweek >= 5).astype("float32"),
        )
        # Direct h-step-ahead target (training only). At inference we do not have
        # the future actual, so the target column is omitted and rows are kept.
        if include_target:
            part["target"] = s.shift(-forecast_horizon_hours).astype("float32")
        part = part.dropna(subset=energy_required)
        if not part.empty:
            survivor_parts.append(part)

    del out  # free the coerced full grid before concat (only survivors needed)
    out = (
        pd.concat(survivor_parts, ignore_index=True)
        if survivor_parts
        else pd.DataFrame()
    )
    del survivor_parts

    # --- Phase 2: weather features (forecast mode), merged onto survivors ---
    # Direct h-step-ahead: a row at issue time T predicts consumption(T+H), so the
    # weather feature it carries must be weather at the TARGET time T+H. Relabel
    # the weather frame's timestamps to T = obs_time - H (gap-safe on exogenous
    # data) then left-merge on [timestamp, site_id]. Identical in training and
    # inference -> no skew. Done on survivors (cheaper than on the full grid).
    weather_feature_cols: list[str] = []
    if (
        weather_mode == FORECAST_WEATHER_MODE
        and weather_df is not None
        and not weather_df.empty
        and not out.empty
    ):
        wshift = weather_df.copy()
        wshift["timestamp"] = pd.to_datetime(wshift["timestamp"], utc=True) - pd.Timedelta(
            hours=forecast_horizon_hours
        )
        out = out.merge(wshift, on=["timestamp", "site_id"], how="left")
        weather_feature_cols = [
            c for c in wshift.columns if c not in ("timestamp", "site_id")
        ]
        for c in weather_feature_cols:
            if c in out.columns:
                out[c] = out[c].astype("float32")
        # Training: drop survivors lacking weather coverage (partial-coverage
        # handling). Inference KEEPS weather NaN — the future region is ffilled
        # upstream and residual gaps go to the pipeline's SimpleImputer.
        if include_target:
            out = out.dropna(subset=weather_feature_cols)

    feature_cols = list(FEATURE_COLUMNS) + weather_feature_cols

    missing = [c for c in feature_cols if c not in out.columns]
    if missing:
        raise ValueError(f"Telemetry is missing required columns: {missing}")

    out = out.reset_index(drop=True)
    cat_features = [c for c in CAT_FEATURES if c in FEATURE_COLUMNS]
    return out, feature_cols, cat_features
