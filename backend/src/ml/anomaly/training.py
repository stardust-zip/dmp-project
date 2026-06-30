from __future__ import annotations

import gc
import logging
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error

from src.ml.anomaly.feature_engineering import build_feature_matrix
from src.ml.anomaly.telemetry_loaders import downcast_telemetry_dtypes
from src.ml.anomaly.types import LOOKBACK_HOURS

logger = logging.getLogger(__name__)

TARGET_COL = "consumption"
RANDOM_STATE = 42
EARLY_STOPPING_ROUNDS = 200
LGB_PARAMS = {
    "objective": "regression",
    "metric": "rmse",
    "boosting_type": "gbdt",
    "n_estimators": 1000,
    "learning_rate": 0.04,
    "num_leaves": 511,
    "max_depth": 8,
    "min_child_samples": 1500,
    "subsample": 0.85,
    "subsample_freq": 1,
    "colsample_bytree": 0.85,
    "reg_alpha": 2.0,
    "reg_lambda": 3.0,
    "random_state": RANDOM_STATE,
    "verbose": -1,
}
CHUNK_TRAINING_THRESHOLD_DAYS = 365
DEFAULT_CHUNK_MONTHS = 12
CHUNK_N_ESTIMATORS = 500


@dataclass
class TrainingResult:
    final_model: lgb.LGBMRegressor
    early_stop_model: lgb.LGBMRegressor
    val_df: pd.DataFrame
    metrics: dict
    feature_cols: list[str]
    cat_features: list[str]
    feature_df: pd.DataFrame | None


def _rmse(y_true, y_pred) -> float:
    return float(np.sqrt(mean_squared_error(y_true, y_pred)))


def _split_by_dates(df: pd.DataFrame, start, end) -> pd.DataFrame:
    return df[(df["timestamp"] >= start) & (df["timestamp"] <= end)].copy()


def _date_chunks(
    start: pd.Timestamp, end: pd.Timestamp, months: int
) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    chunks = []
    cur = start
    while cur < end:
        nxt = pd.Timestamp(cur + pd.DateOffset(months=months))
        chunks.append((cur, min(nxt, end)))
        cur = nxt
    return chunks


def train_lgbm(
    df: pd.DataFrame,
    feature_cols: list[str],
    cat_features: list[str],
    train_end: pd.Timestamp,
    test_start: pd.Timestamp,
    append_log: Callable[[str], None] = lambda _: None,
) -> TrainingResult:
    df_start = df["timestamp"].min()
    val_start = train_end + timedelta(hours=1)
    val_end = test_start - timedelta(hours=1)
    final_train_df = _split_by_dates(df, df_start, train_end).dropna(subset=[TARGET_COL])
    val_df = _split_by_dates(df, val_start, val_end).dropna(subset=[TARGET_COL])
    fit_df = _split_by_dates(df, df_start, val_end).dropna(subset=[TARGET_COL])
    test_df = _split_by_dates(df, test_start, df["timestamp"].max()).dropna(subset=[TARGET_COL])

    append_log(
        f"Split — Train: {df_start.date()} → {train_end.date()} "
        f"({len(final_train_df):,} rows, {final_train_df['building_id'].nunique()} buildings) | "
        f"Val: {val_start.date()} → {val_end.date()} ({len(val_df):,} rows) | "
        f"Test: {test_start.date()} → {df['timestamp'].max().date()} ({len(test_df):,} rows)."
    )
    append_log(f"Features: {len(feature_cols)} total, {len(cat_features)} categorical.")
    append_log("Fitting early-stop model (train split only)...")
    early_stop_model = lgb.LGBMRegressor(**LGB_PARAMS)
    early_stop_model.fit(
        final_train_df[feature_cols],
        final_train_df[TARGET_COL],
        eval_set=[(val_df[feature_cols], val_df[TARGET_COL])],
        eval_metric="rmse",
        categorical_feature=cat_features,
        callbacks=[
            lgb.early_stopping(EARLY_STOPPING_ROUNDS, first_metric_only=True, verbose=False),
            lgb.log_evaluation(100),
        ],
    )
    best_iteration = early_stop_model.best_iteration_ or LGB_PARAMS["n_estimators"]
    best_val_rmse = early_stop_model.best_score_.get("valid_0", {}).get("rmse", float("nan"))
    append_log(f"Early-stop done: best_iteration={best_iteration}, val_rmse={best_val_rmse:.4f}.")

    append_log(f"Fitting final model on train+val ({len(fit_df):,} rows)...")
    final_params = {**LGB_PARAMS, "n_estimators": best_iteration}
    final_model = lgb.LGBMRegressor(**final_params)
    final_model.fit(fit_df[feature_cols], fit_df[TARGET_COL], categorical_feature=cat_features)

    test_pred = final_model.predict(test_df[feature_cols]).clip(min=0)
    metrics = {
        "test_rmse": _rmse(test_df[TARGET_COL], test_pred),
        "test_mae": float(mean_absolute_error(test_df[TARGET_COL], test_pred)),
        "best_iteration": best_iteration,
        "cv_folds": [],
    }
    append_log(
        f"Test evaluation: RMSE={metrics['test_rmse']:.4f}, MAE={metrics['test_mae']:.4f} "
        f"({len(test_df):,} rows, {test_df['building_id'].nunique()} buildings)."
    )
    return TrainingResult(
        final_model=final_model,
        early_stop_model=early_stop_model,
        val_df=val_df,
        metrics=metrics,
        feature_cols=feature_cols,
        cat_features=cat_features,
        feature_df=df,
    )


def train_lgbm_chunked(
    chunk_source: Callable[[pd.Timestamp, pd.Timestamp], pd.DataFrame],
    start: pd.Timestamp,
    end: pd.Timestamp,
    train_end: pd.Timestamp,
    test_start: pd.Timestamp,
    use_weather: bool,
    weather_df: pd.DataFrame,
    weather_feature_cols: list[str],
    chunk_months: int = DEFAULT_CHUNK_MONTHS,
    append_log: Callable[[str], None] = lambda _: None,
) -> TrainingResult:
    train_chunks = _date_chunks(start, train_end, chunk_months)
    val_start = train_end + timedelta(hours=1)
    val_end = test_start - timedelta(hours=1)

    append_log(
        f"Chunked training: {len(train_chunks)} chunk(s) x {chunk_months} months, "
        f"{CHUNK_N_ESTIMATORS} trees/chunk (fixed budget, no early stopping per chunk)."
    )

    # Load the global val set once before the chunk loop so every chunk uses the
    # same held-out future window for early stopping instead of a local 2-week window.
    append_log(f"Loading global validation set ({val_start.date()} → {val_end.date()})...")
    val_raw = chunk_source(val_start, val_end)
    downcast_telemetry_dtypes(val_raw)
    vw_df = pd.DataFrame()
    if use_weather and not weather_df.empty:
        mask = (
            (weather_df["timestamp"] >= val_start - timedelta(hours=LOOKBACK_HOURS))
            & (weather_df["timestamp"] <= val_end)
        )
        vw_df = weather_df.loc[mask].copy()
    global_val_feat, feature_cols, cat_features = build_feature_matrix(
        val_raw, use_weather and not vw_df.empty, vw_df, weather_feature_cols
    )
    global_val_df = global_val_feat[
        (global_val_feat["timestamp"] >= val_start) & (global_val_feat["timestamp"] <= val_end)
    ].dropna(subset=[TARGET_COL])
    del val_raw, vw_df, global_val_feat
    gc.collect()
    append_log(f"Global val: {len(global_val_df):,} rows, {global_val_df['building_id'].nunique()} buildings.")

    prev_booster: lgb.Booster | str | None = None
    prev_tmp_path: str | None = None
    chunk_model: lgb.LGBMRegressor | None = None

    for i, (chunk_start, chunk_end) in enumerate(train_chunks):
        append_log(f"  Chunk {i + 1}/{len(train_chunks)}: {chunk_start.date()} → {chunk_end.date()}")
        chunk_raw = chunk_source(chunk_start, chunk_end)
        if chunk_raw.empty:
            append_log(f"  Chunk {i + 1}: no telemetry, skipping.")
            continue
        downcast_telemetry_dtypes(chunk_raw)
        append_log(
            f"  Chunk {i + 1}: loaded {len(chunk_raw):,} rows, "
            f"{chunk_raw['building_id'].nunique()} buildings."
        )

        cw_df = pd.DataFrame()
        cw_cols: list[str] = []
        if use_weather and not weather_df.empty:
            mask = (
                (weather_df["timestamp"] >= chunk_start - timedelta(hours=LOOKBACK_HOURS))
                & (weather_df["timestamp"] <= chunk_end)
            )
            cw_df = weather_df.loc[mask].copy()
            cw_cols = weather_feature_cols

        feat_df, f_cols, c_feats = build_feature_matrix(
            chunk_raw, use_weather and not cw_df.empty, cw_df, cw_cols
        )
        del chunk_raw, cw_df
        gc.collect()

        if not feature_cols:
            feature_cols, cat_features = f_cols, c_feats

        # Train on the full chunk — global val handles early stopping, no local split needed.
        chunk_tr = feat_df[
            (feat_df["timestamp"] >= chunk_start) & (feat_df["timestamp"] <= chunk_end)
        ].dropna(subset=[TARGET_COL])
        del feat_df
        gc.collect()

        if chunk_tr.empty:
            append_log(f"  Chunk {i + 1}: empty training split, skipping.")
            continue

        append_log(f"  Chunk {i + 1}: training on {len(chunk_tr):,} rows...")
        new_model = lgb.LGBMRegressor(**{**LGB_PARAMS, "n_estimators": CHUNK_N_ESTIMATORS})
        fit_kwargs: dict = {"categorical_feature": cat_features}
        if prev_booster is not None:
            fit_kwargs["init_model"] = prev_booster
        if not global_val_df.empty:
            fit_kwargs["eval_set"] = [(global_val_df[feature_cols], global_val_df[TARGET_COL])]
            fit_kwargs["eval_metric"] = "rmse"
            fit_kwargs["callbacks"] = [lgb.log_evaluation(1)]

        new_model.fit(chunk_tr[feature_cols], chunk_tr[TARGET_COL], **fit_kwargs)
        total_trees = new_model.booster_.num_trees()
        val_rmse = new_model.best_score_.get("valid_0", {}).get("rmse", float("nan"))
        is_last_chunk = (i == len(train_chunks) - 1)

        if not is_last_chunk and not global_val_df.empty:
            # For intermediate chunks: find best_iter on global val, save a pruned model
            # so the next chunk starts from the optimal point, not an overfitted tail.
            step = 100
            chunk_best_iter = total_trees
            chunk_best_rmse = float("inf")
            for num_iter in range(step, total_trees + 1, step):
                pred = new_model.predict(global_val_df[feature_cols], num_iteration=num_iter).clip(min=0)
                rmse_val = _rmse(global_val_df[TARGET_COL], pred)
                if rmse_val < chunk_best_rmse:
                    chunk_best_rmse = rmse_val
                    chunk_best_iter = num_iter
            tmp_fd, tmp_path = tempfile.mkstemp(suffix=".txt", prefix=f"lgb_chunk{i + 1}_")
            os.close(tmp_fd)
            new_model.booster_.save_model(tmp_path, num_iteration=chunk_best_iter)
            if prev_tmp_path is not None:
                try:
                    os.unlink(prev_tmp_path)
                except OSError:
                    pass
            prev_booster = tmp_path
            prev_tmp_path = tmp_path
            append_log(
                f"  Chunk {i + 1}: done — total_trees={total_trees}, "
                f"best_iter={chunk_best_iter}, val_rmse={chunk_best_rmse:.4f}. "
                f"Saved pruned model → init for chunk {i + 2}."
            )
        else:
            if prev_tmp_path is not None:
                try:
                    os.unlink(prev_tmp_path)
                except OSError:
                    pass
                prev_tmp_path = None
            prev_booster = new_model.booster_
            append_log(
                f"  Chunk {i + 1}: done — trees_this_chunk={CHUNK_N_ESTIMATORS}, "
                f"val_rmse={val_rmse:.4f}, total_trees={total_trees}."
            )

        del chunk_tr
        if chunk_model is not None:
            del chunk_model
        chunk_model = new_model
        gc.collect()

    if chunk_model is None:
        raise ValueError("No training data found across all chunks.")

    final_model = chunk_model
    total_trees = final_model.booster_.num_trees()
    append_log(f"Chunk training complete: {total_trees} total trees accumulated.")
    val_df = global_val_df

    # Post-training best-iteration search on global val.
    # Each chunk trains for the full CHUNK_N_ESTIMATORS budget, so the optimal
    # stopping point may be before the last tree. Sweep in steps of 100 to find it.
    append_log(f"Searching best iteration on global val ({len(global_val_df):,} rows)...")
    step = 100
    best_iter = total_trees
    best_val_rmse = float("inf")
    for num_iter in range(step, total_trees + 1, step):
        pred = final_model.predict(global_val_df[feature_cols], num_iteration=num_iter).clip(min=0)
        rmse_val = _rmse(global_val_df[TARGET_COL], pred)
        if rmse_val < best_val_rmse:
            best_val_rmse = rmse_val
            best_iter = num_iter
    append_log(f"Best iteration: {best_iter}/{total_trees}, val_rmse={best_val_rmse:.4f}.")

    append_log(f"Loading test set ({test_start.date()} → {end.date()})...")
    test_raw = chunk_source(test_start, end)
    downcast_telemetry_dtypes(test_raw)
    tw_df = pd.DataFrame()
    if use_weather and not weather_df.empty:
        mask = (
            (weather_df["timestamp"] >= test_start - timedelta(hours=LOOKBACK_HOURS))
            & (weather_df["timestamp"] <= end)
        )
        tw_df = weather_df.loc[mask].copy()
    test_feat, _, _ = build_feature_matrix(test_raw, use_weather and not tw_df.empty, tw_df, weather_feature_cols)
    test_df = test_feat[test_feat["timestamp"] >= test_start].dropna(subset=[TARGET_COL])
    append_log(f"Test set: {len(test_df):,} rows, {test_df['building_id'].nunique()} buildings.")
    test_pred = np.array(final_model.predict(test_df[feature_cols], num_iteration=best_iter)).clip(min=0)
    metrics = {
        "test_rmse": _rmse(test_df[TARGET_COL], test_pred),
        "test_mae": float(mean_absolute_error(test_df[TARGET_COL], test_pred)),
        "best_iteration": best_iter,
        "cv_folds": [],
    }
    append_log(
        f"Test evaluation: RMSE={metrics['test_rmse']:.4f}, MAE={metrics['test_mae']:.4f} "
        f"(using best_iteration={best_iter})."
    )
    return TrainingResult(
        final_model=final_model,
        early_stop_model=final_model,
        val_df=val_df,
        metrics=metrics,
        feature_cols=feature_cols,
        cat_features=cat_features,
        feature_df=None,
    )


def compute_residual_stats(
    early_stop_model: lgb.LGBMRegressor,
    val_df: pd.DataFrame,
    feature_cols: list[str],
    append_log: Callable[[str], None] = lambda _: None,
) -> pd.DataFrame:
    append_log(f"Residual calibration: scoring {len(val_df):,} val rows across {val_df['building_id'].nunique()} buildings...")
    cal_pred = early_stop_model.predict(val_df[feature_cols]).clip(min=0)
    cal_resid = pd.DataFrame({
        "building_id": val_df["building_id"].values,
        "primaryspaceusage": val_df["primaryspaceusage"].astype(str).values if "primaryspaceusage" in val_df.columns else "",
        "sub_primaryspaceusage": val_df["sub_primaryspaceusage"].astype(str).values if "sub_primaryspaceusage" in val_df.columns else "",
        "resid": val_df[TARGET_COL].values - cal_pred,
    })
    resid_stats = (
        cal_resid.groupby("building_id")["resid"]
        .agg(
            resid_median="median",
            resid_mad=lambda x: float(np.median(np.abs(x - np.median(x)))),
        )
        .reset_index()
    )
    bld_meta = cal_resid[["building_id", "primaryspaceusage", "sub_primaryspaceusage"]].drop_duplicates("building_id")
    resid_stats = bld_meta.merge(resid_stats, on="building_id", how="left")

    nan_mask = resid_stats["resid_median"].isna()
    if nan_mask.any():
        # Level 1: fallback to sub_primaryspaceusage group median
        group_fb_sub = (
            resid_stats.loc[~nan_mask]
            .groupby("sub_primaryspaceusage")[["resid_median", "resid_mad"]]
            .median()
            .rename(columns={"resid_median": "fb_median_sub", "resid_mad": "fb_mad_sub"})
        )
        resid_stats = resid_stats.merge(group_fb_sub, on="sub_primaryspaceusage", how="left")
        resid_stats.loc[nan_mask, "resid_median"] = resid_stats.loc[nan_mask, "fb_median_sub"]
        resid_stats.loc[nan_mask, "resid_mad"] = resid_stats.loc[nan_mask, "fb_mad_sub"]
        resid_stats.drop(columns=["fb_median_sub", "fb_mad_sub"], inplace=True)

        # Level 2: remaining nulls fallback to primaryspaceusage group median
        still_nan = resid_stats["resid_median"].isna()
        if still_nan.any():
            group_fb_psu = (
                resid_stats.loc[~still_nan]
                .groupby("primaryspaceusage")[["resid_median", "resid_mad"]]
                .median()
                .rename(columns={"resid_median": "fb_median_psu", "resid_mad": "fb_mad_psu"})
            )
            resid_stats = resid_stats.merge(group_fb_psu, on="primaryspaceusage", how="left")
            resid_stats.loc[still_nan, "resid_median"] = resid_stats.loc[still_nan, "fb_median_psu"]
            resid_stats.loc[still_nan, "resid_mad"] = resid_stats.loc[still_nan, "fb_mad_psu"]
            resid_stats.drop(columns=["fb_median_psu", "fb_mad_psu"], inplace=True)

    resid_stats.drop(columns=["primaryspaceusage", "sub_primaryspaceusage"], inplace=True)
    n_direct = int((~resid_stats["resid_median"].isna()).sum())
    n_fallback = len(resid_stats) - n_direct
    append_log(
        f"Residual calibration done: {n_direct} buildings with direct coverage, "
        f"{n_fallback} using group fallback."
    )
    return resid_stats
