from __future__ import annotations

import gc
import logging
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
EARLY_STOPPING_ROUNDS = 100
LGB_PARAMS = {
    "objective": "regression",
    "metric": "rmse",
    "boosting_type": "gbdt",
    "n_estimators": 3000,
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
DEFAULT_CHUNK_MONTHS = 3
CHUNK_N_ESTIMATORS = 1000
CHUNK_VAL_WEEKS = 2


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
) -> TrainingResult:
    df_start = df["timestamp"].min()
    val_duration = test_start - train_end
    val_chunk = val_duration / 4
    fold_metrics = []

    for i in range(4):
        fold_train_end = train_end + i * val_chunk
        fold_val_start = fold_train_end + timedelta(hours=1)
        fold_val_end = train_end + (i + 1) * val_chunk
        tr = _split_by_dates(df, df_start, fold_train_end).dropna(subset=[TARGET_COL])
        va = _split_by_dates(df, fold_val_start, fold_val_end).dropna(subset=[TARGET_COL])
        if tr.empty or va.empty:
            continue

        fold_model = lgb.LGBMRegressor(**LGB_PARAMS)
        fold_model.fit(
            tr[feature_cols],
            tr[TARGET_COL],
            eval_set=[(va[feature_cols], va[TARGET_COL])],
            eval_metric="rmse",
            categorical_feature=cat_features,
            callbacks=[
                lgb.early_stopping(EARLY_STOPPING_ROUNDS, first_metric_only=True, verbose=False),
                lgb.log_evaluation(100),
            ],
        )
        pred = fold_model.predict(va[feature_cols]).clip(min=0)
        fold_metrics.append({
            "fold": i + 1,
            "val_rmse": _rmse(va[TARGET_COL], pred),
            "val_mae": float(mean_absolute_error(va[TARGET_COL], pred)),
            "best_iteration": fold_model.best_iteration_,
        })
        del fold_model

    val_start = train_end + timedelta(hours=1)
    val_end = test_start - timedelta(hours=1)
    final_train_df = _split_by_dates(df, df_start, train_end).dropna(subset=[TARGET_COL])
    val_df = _split_by_dates(df, val_start, val_end).dropna(subset=[TARGET_COL])
    fit_df = _split_by_dates(df, df_start, val_end).dropna(subset=[TARGET_COL])
    test_df = _split_by_dates(df, test_start, df["timestamp"].max()).dropna(subset=[TARGET_COL])

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
    final_params = {**LGB_PARAMS, "n_estimators": best_iteration}
    final_model = lgb.LGBMRegressor(**final_params)
    final_model.fit(fit_df[feature_cols], fit_df[TARGET_COL], categorical_feature=cat_features)

    test_pred = final_model.predict(test_df[feature_cols]).clip(min=0)
    metrics = {
        "test_rmse": _rmse(test_df[TARGET_COL], test_pred),
        "test_mae": float(mean_absolute_error(test_df[TARGET_COL], test_pred)),
        "best_iteration": best_iteration,
        "cv_folds": fold_metrics,
    }
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
    append_log(
        f"Chunked training: {len(train_chunks)} chunk(s) x {chunk_months} months, "
        f"up to {CHUNK_N_ESTIMATORS} trees/chunk with per-chunk early stopping."
    )

    feature_cols: list[str] = []
    cat_features: list[str] = []
    prev_booster: lgb.Booster | None = None
    chunk_model: lgb.LGBMRegressor | None = None

    for i, (chunk_start, chunk_end) in enumerate(train_chunks):
        append_log(f"  Chunk {i + 1}/{len(train_chunks)}: {chunk_start.date()} -> {chunk_end.date()}")
        chunk_raw = chunk_source(chunk_start, chunk_end)
        if chunk_raw.empty:
            append_log(f"  Chunk {i + 1}: no telemetry, skipping.")
            continue
        downcast_telemetry_dtypes(chunk_raw)

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

        chunk_val_cutoff = chunk_end - timedelta(weeks=CHUNK_VAL_WEEKS)
        chunk_tr = feat_df[
            (feat_df["timestamp"] >= chunk_start) & (feat_df["timestamp"] <= chunk_val_cutoff)
        ].dropna(subset=[TARGET_COL])
        chunk_va = feat_df[
            (feat_df["timestamp"] > chunk_val_cutoff) & (feat_df["timestamp"] <= chunk_end)
        ].dropna(subset=[TARGET_COL])
        del feat_df
        gc.collect()

        if chunk_tr.empty:
            append_log(f"  Chunk {i + 1}: empty training split, skipping.")
            continue

        new_model = lgb.LGBMRegressor(**{**LGB_PARAMS, "n_estimators": CHUNK_N_ESTIMATORS})
        fit_kwargs: dict = {"categorical_feature": cat_features}
        if prev_booster is not None:
            fit_kwargs["init_model"] = prev_booster
        if not chunk_va.empty:
            fit_kwargs["eval_set"] = [(chunk_va[feature_cols], chunk_va[TARGET_COL])]
            fit_kwargs["eval_metric"] = "rmse"
            fit_kwargs["callbacks"] = [
                lgb.early_stopping(EARLY_STOPPING_ROUNDS, first_metric_only=True, verbose=False),
                lgb.log_evaluation(200),
            ]

        new_model.fit(chunk_tr[feature_cols], chunk_tr[TARGET_COL], **fit_kwargs)
        append_log(
            f"  Chunk {i + 1}: best_iteration={new_model.best_iteration_ or CHUNK_N_ESTIMATORS}"
        )
        prev_booster = new_model.booster_
        del chunk_tr, chunk_va
        if chunk_model is not None:
            del chunk_model
        chunk_model = new_model
        gc.collect()

    if chunk_model is None:
        raise ValueError("No training data found across all chunks.")

    final_model = chunk_model
    total_trees = final_model.booster_.num_trees()

    val_start = train_end + timedelta(hours=1)
    val_end = test_start - timedelta(hours=1)
    val_raw = chunk_source(val_start, val_end)
    downcast_telemetry_dtypes(val_raw)
    vw_df = pd.DataFrame()
    if use_weather and not weather_df.empty:
        mask = (
            (weather_df["timestamp"] >= val_start - timedelta(hours=LOOKBACK_HOURS))
            & (weather_df["timestamp"] <= val_end)
        )
        vw_df = weather_df.loc[mask].copy()
    val_feat, _, _ = build_feature_matrix(val_raw, use_weather and not vw_df.empty, vw_df, weather_feature_cols)
    val_df = val_feat[
        (val_feat["timestamp"] >= val_start) & (val_feat["timestamp"] <= val_end)
    ].dropna(subset=[TARGET_COL])
    del val_raw, vw_df
    gc.collect()

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
    test_pred = np.array(final_model.predict(test_df[feature_cols])).clip(min=0)
    metrics = {
        "test_rmse": _rmse(test_df[TARGET_COL], test_pred),
        "test_mae": float(mean_absolute_error(test_df[TARGET_COL], test_pred)),
        "best_iteration": total_trees,
        "cv_folds": [],
    }
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
) -> pd.DataFrame:
    cal_pred = early_stop_model.predict(val_df[feature_cols]).clip(min=0)
    cal_resid = pd.DataFrame({
        "building_id": val_df["building_id"].values,
        "primaryspaceusage": val_df["primaryspaceusage"].astype(str).values,
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
    bld_meta = cal_resid[["building_id", "primaryspaceusage"]].drop_duplicates("building_id")
    resid_stats = bld_meta.merge(resid_stats, on="building_id", how="left")

    nan_mask = resid_stats["resid_median"].isna()
    if nan_mask.any():
        group_fb = (
            resid_stats.loc[~nan_mask]
            .groupby("primaryspaceusage")[["resid_median", "resid_mad"]]
            .median()
            .rename(columns={"resid_median": "fb_median", "resid_mad": "fb_mad"})
        )
        resid_stats = resid_stats.merge(group_fb, on="primaryspaceusage", how="left")
        resid_stats.loc[nan_mask, "resid_median"] = resid_stats.loc[nan_mask, "fb_median"]
        resid_stats.loc[nan_mask, "resid_mad"] = resid_stats.loc[nan_mask, "fb_mad"]
        resid_stats.drop(columns=["fb_median", "fb_mad"], inplace=True)

    resid_stats.drop(columns=["primaryspaceusage"], inplace=True)
    return resid_stats
