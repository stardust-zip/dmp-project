"""Telemetry cleaning for forecasting (training + inference parity).

This is the pandas port of the standalone pipeline in ``forecasting_module/``
(``preprocessing.py`` + ``outlier.py``), which the backend originally skipped.
Raw telemetry from the loaders is *not* on a complete hourly grid (CSV path even
``dropna``s missing hours away), has unfiltered consumption spikes, and has
gaps. Feeding it straight to the feature builder was the root cause of poor
forecasting quality (XGBoost early-stopping at a handful of trees because the
target carried extreme outliers).

The single public entry point :func:`clean_telemetry_for_forecasting` is called
by BOTH ``train_forecasting_model`` and the inference overlay so the two paths
see identical data (no train/serve skew). It must stay a pure function of the
input frame.

Pipeline order mirrors the standalone module:

    negative -> null  →  align hourly grid  →  drop high-missing buildings
                      →  IQR outlier -> null  →  interpolate + seasonal-fill

Long gaps (> ``SEASONAL_MAX_GAP_HOURS``) are intentionally left null: the
feature builder (:func:`build_forecast_feature_matrix`) drops any row with a
null feature, so those rows are removed downstream rather than filled.

Note: for direct h-step-ahead forecasting, rolling features legitimately include
the current hour, so cleaning a value at time ``t`` is correct even though it is
later used to predict ``t + horizon``.
"""

from __future__ import annotations

import pandas as pd

from src.ml.forecasting.types import (
    IQR_MULTIPLIER,
    INTERP_MAX_GAP_HOURS,
    MISSING_RATE_THRESHOLD,
    SEASONAL_MAX_GAP_HOURS,
    TARGET_COL,
    TELEMETRY_FREQ,
)

# Columns that are constant per building and must be carried across the hourly
# grid after align (not interpolated as numeric series).
_STATIC_META_COLS = (
    "metric_type_id",
    "site_id",
    "sqm",
    "primaryspaceusage",
    "timezone",
)


def clean_telemetry_for_forecasting(
    df: pd.DataFrame,
    *,
    value_col: str = TARGET_COL,
    building_col: str = "building_id",
    timestamp_col: str = "timestamp",
    align_to_hour: bool = True,
    drop_high_missing: bool = False,
    return_stats: bool = False,
) -> pd.DataFrame | tuple[pd.DataFrame, dict[str, int]]:
    """Clean raw telemetry for forecasting.

    Steps (mirror ``forecasting_module``):
      * nullify negative consumption,
      * align to a complete hourly grid per building so gaps become null
        (``preprocessing.align_timestamps``),
      * drop buildings whose null-rate exceeds ``MISSING_RATE_THRESHOLD``
        (``preprocessing.handle_missing_consumption`` step 0),
      * flag IQR outliers per (building, hour-of-day) and null them
        (``outlier.detect_electricity_outliers``),
      * linear-interpolate gaps <= ``INTERP_MAX_GAP_HOURS`` and seasonal-fill
        gaps in (``INTERP_MAX_GAP_HOURS``, ``SEASONAL_MAX_GAP_HOURS``]
        (``preprocessing.handle_missing_consumption``).

    Parameters
    ----------
    drop_high_missing:
        When ``True`` (global/all-buildings training) buildings above the
        missing-rate threshold are dropped. Single-building callers pass
        ``False`` because the building was explicitly chosen.
    return_stats:
        When ``True`` returns ``(df, stats)`` so training can log a summary.

    Long-gap rows are left null and removed later by the feature builder.
    """
    if df.empty:
        return (df.copy(), _empty_stats()) if return_stats else df.copy()

    out = df.copy()
    out[timestamp_col] = pd.to_datetime(out[timestamp_col], utc=True, errors="coerce")
    out = out.dropna(subset=[timestamp_col])
    out[value_col] = pd.to_numeric(out[value_col], errors="coerce")

    _nullify_negative_consumption(out, value_col)

    if align_to_hour:
        out = _align_hourly_grid(out, timestamp_col, building_col)

    out = out.sort_values([building_col, timestamp_col]).reset_index(drop=True)

    buildings_dropped = 0
    dropped_building_ids: list[str] = []
    if drop_high_missing:
        out, buildings_dropped, dropped_building_ids = _drop_high_missing_buildings(
            out, value_col, building_col
        )

    outliers_flagged = _flag_outliers_iqr(out, timestamp_col, value_col, building_col)

    gaps_filled = _interpolate_and_seasonal_fill(out, value_col, building_col)

    stats = {
        "buildings_dropped": buildings_dropped,
        "dropped_building_ids": dropped_building_ids,
        "outliers_flagged": outliers_flagged,
        "gaps_filled": gaps_filled,
    }
    return (out, stats) if return_stats else out


def _empty_stats() -> dict:
    return {
        "buildings_dropped": 0,
        "dropped_building_ids": [],
        "outliers_flagged": 0,
        "gaps_filled": 0,
    }


def _nullify_negative_consumption(df: pd.DataFrame, value_col: str) -> None:
    """Physical sanity: consumption cannot be negative."""
    df.loc[df[value_col] < 0, value_col] = pd.NA


def _align_hourly_grid(
    df: pd.DataFrame, timestamp_col: str, building_col: str
) -> pd.DataFrame:
    """Reindex each building onto a complete hourly grid.

    Mirror of ``forecasting_module/preprocessing.py:align_timestamps``: missing
    hours become null consumption so interpolation has real gaps to fill. Static
    per-building metadata is forward/back-filled (it is constant by definition).
    """
    if df.empty:
        return df

    tz = df[timestamp_col].dt.tz
    pieces = []
    for building_id, group in df.groupby(building_col, sort=False):
        group = group.sort_values(timestamp_col)
        full_hours = pd.date_range(
            group[timestamp_col].min(),
            group[timestamp_col].max(),
            freq=TELEMETRY_FREQ,
            tz=tz,
        )
        indexed = group.set_index(timestamp_col)
        indexed = indexed.reindex(full_hours)
        indexed.index.name = timestamp_col
        indexed = indexed.reset_index()
        indexed[building_col] = building_id
        # Carry static metadata across the inserted null rows.
        for col in _STATIC_META_COLS:
            if col in indexed.columns:
                s = indexed[col].ffill().bfill()
                # If the whole building lacks a metadata value, keep it null.
                if s.notna().any():
                    indexed[col] = s
        pieces.append(indexed)

    out = pd.concat(pieces, ignore_index=True)
    # Preserve original column order where possible; new grid cols == old cols.
    return out[df.columns] if set(df.columns).issubset(out.columns) else out


def _drop_high_missing_buildings(
    df: pd.DataFrame, value_col: str, building_col: str
) -> tuple[pd.DataFrame, int, list[str]]:
    """Drop buildings whose consumption null-rate exceeds the threshold.

    Mirror of ``forecasting_module/preprocessing.py:handle_missing_consumption``
    step 0. Only meaningful for global/all-buildings training.

    Returns ``(filtered_df, n_dropped, dropped_building_ids)``. The dropped IDs
    travel with the model version (coverage artifact) so the forecast UI can hide
    buildings the model never saw during training.
    """
    if df.empty:
        return df, 0, []
    missing_rate = df.groupby(building_col)[value_col].apply(
        lambda s: s.isna().mean()
    )
    drop = missing_rate[missing_rate > MISSING_RATE_THRESHOLD].index.astype(str).tolist()
    keep = missing_rate[missing_rate <= MISSING_RATE_THRESHOLD].index
    out = df[df[building_col].isin(keep)].copy()
    return out, len(drop), drop


def _flag_outliers_iqr(
    df: pd.DataFrame,
    timestamp_col: str,
    value_col: str,
    building_col: str,
) -> int:
    """Flag consumption outliers per (building, hour-of-day) via IQR -> null.

    Mirror of ``forecasting_module/outlier.py:detect_electricity_outliers``.
    Values strictly outside ``[Q1 - IQR_MULTIPLIER*IQR, Q3 + IQR_MULTIPLIER*IQR]``
    within each (building, hour) group are nulled (the row is kept).
    """
    if df.empty:
        return 0
    df["_hour"] = df[timestamp_col].dt.hour
    observed = df[df[value_col].notna()]
    if observed.empty:
        df.drop(columns=["_hour"], inplace=True)
        return 0

    stats = (
        observed.groupby([building_col, "_hour"])[value_col]
        .quantile([0.25, 0.75])
        .unstack()
        .rename(columns={0.25: "Q1", 0.75: "Q3"})
    )
    stats["IQR"] = stats["Q3"] - stats["Q1"]
    stats["lower"] = stats["Q1"] - IQR_MULTIPLIER * stats["IQR"]
    stats["upper"] = stats["Q3"] + IQR_MULTIPLIER * stats["IQR"]

    # Map the per-(building,hour) fence onto each row via map on the index keys.
    # This keeps the result aligned to the ORIGINAL df index (merge would reorder).
    key = list(zip(df[building_col], df["_hour"]))
    lower_by_key = stats["lower"].to_dict()
    upper_by_key = stats["upper"].to_dict()
    lower = pd.Series([lower_by_key.get(k) for k in key], index=df.index)
    upper = pd.Series([upper_by_key.get(k) for k in key], index=df.index)

    non_null = df[value_col].notna()
    out_of_fence = non_null & (
        (df[value_col] < lower) | (df[value_col] > upper)
    )
    # Only flip rows where a fence was computed (group had >= 2 distinct values).
    has_fence = lower.notna() | upper.notna()
    mask = out_of_fence & has_fence
    n_flagged = int(mask.sum())

    df.loc[mask, value_col] = pd.NA
    df.drop(columns=["_hour"], inplace=True)
    return n_flagged


def _interpolate_and_seasonal_fill(
    df: pd.DataFrame, value_col: str, building_col: str
) -> int:
    """Fill consumption gaps: interpolate short, seasonal-fill medium.

    Mirror of ``forecasting_module/preprocessing.py:handle_missing_consumption``.
      * linear-interpolate gaps <= ``INTERP_MAX_GAP_HOURS``,
      * for gaps in (interp, seasonal] fill from ``shift(24)`` when available,
      * leave longer gaps null (feature builder drops them).
    """
    if df.empty:
        return 0

    filled_total = 0
    for _building_id, idx in df.groupby(building_col, sort=False).groups.items():
        group = df.loc[idx].sort_index()
        s = group[value_col]
        before = int(s.isna().sum())

        run_len = _null_run_lengths(s)
        interpolated = s.interpolate(method="linear", limit_direction="both")
        keep_interp = run_len <= INTERP_MAX_GAP_HOURS
        s = s.where(~(s.isna() & keep_interp), interpolated)

        # Seasonal fill for medium gaps (interp < run_len <= seasonal).
        shifted = s.shift(24)
        medium_gap = s.isna() & (run_len > INTERP_MAX_GAP_HOURS) & (
            run_len <= SEASONAL_MAX_GAP_HOURS
        )
        s = s.where(~(medium_gap & shifted.notna()), shifted)

        df.loc[group.index, value_col] = s
        filled_total += before - int(df.loc[group.index, value_col].isna().sum())

    return filled_total


def _null_run_lengths(series: pd.Series) -> pd.Series:
    """Length of the contiguous null run each position belongs to.

    Equivalent to ``forecasting_module/preprocessing._compute_null_run_lengths``.
    The length is assigned to every position of a run; only null positions are
    read downstream.
    """
    is_null = series.isna()
    new_run = is_null.ne(is_null.shift(1, fill_value=False))
    run_id = new_run.cumsum()
    return run_id.map(run_id.value_counts())
