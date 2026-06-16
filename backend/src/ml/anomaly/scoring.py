from __future__ import annotations

import logging
from collections.abc import Callable

import lightgbm as lgb
import numpy as np
import pandas as pd

from src.ml.anomaly.feature_engineering import CAT_FEATURES

logger = logging.getLogger(__name__)

TARGET_COL = "consumption"
MAD_SCALE = 1.4826
MAD_FLOOR = 1e-3
ANOMALY_Z = 3.0
SEV_THRESHOLDS = [(10.0, "Critical"), (6.0, "High"), (4.0, "Medium"), (3.0, "Low")]


def _encode_categoricals(
    model: lgb.LGBMRegressor,
    predict_input: pd.DataFrame,
    feature_cols: list[str],
    missing_features: list[str],
    diagnostic_cb: Callable[[str], None] | None,
) -> pd.DataFrame | np.ndarray:
    booster = getattr(model, "booster_", None) or getattr(model, "_Booster", None)
    stored_cats = getattr(booster, "pandas_categorical", None) if booster else None
    if not stored_cats:
        return predict_input

    expected_cat_cols = [col for col in feature_cols if col in CAT_FEATURES]
    actual_cat_cols = [
        col for col in predict_input.columns
        if isinstance(predict_input[col].dtype, pd.CategoricalDtype)
    ]
    dtype_mismatch_cols = [
        col for col in expected_cat_cols
        if col in predict_input.columns
        and not isinstance(predict_input[col].dtype, pd.CategoricalDtype)
    ]
    unexpected_cat_cols = [col for col in actual_cat_cols if col not in expected_cat_cols]

    if len(actual_cat_cols) != len(stored_cats) or dtype_mismatch_cols or unexpected_cat_cols:
        cat_details = []
        for col in expected_cat_cols:
            if col not in predict_input.columns:
                cat_details.append(f"{col}: missing")
                continue
            series = predict_input[col]
            cat_details.append(f"{col}: dtype={series.dtype}, nulls={int(series.isna().sum())}")
        message = (
            "LightGBM categorical dtype diagnostic: "
            f"model_saved_category_count={len(stored_cats)}; "
            f"expected_categorical_columns={expected_cat_cols}; "
            f"input_categorical_columns={actual_cat_cols}; "
            f"dtype_mismatch_columns={dtype_mismatch_cols}; "
            f"unexpected_categorical_columns={unexpected_cat_cols}; "
            f"missing_features={missing_features}; "
            f"category_details={cat_details}"
        )
        logger.warning(message)
        if diagnostic_cb:
            diagnostic_cb(message)

    for col, training_cats in zip(expected_cat_cols, stored_cats):
        predict_input[col] = pd.Categorical(
            predict_input[col].astype(object), categories=training_cats
        ).codes.astype("float32")
        predict_input.loc[predict_input[col] < 0, col] = np.nan

    for col in predict_input.columns:
        if isinstance(predict_input[col].dtype, pd.CategoricalDtype):
            codes = predict_input[col].cat.codes.astype("float32")
            predict_input[col] = codes.mask(codes < 0, np.nan)

    return predict_input.apply(pd.to_numeric, errors="coerce").to_numpy(dtype=np.float32, copy=False)


def score_anomalies(
    model: lgb.LGBMRegressor,
    resid_stats: pd.DataFrame,
    df: pd.DataFrame,
    feature_cols: list[str],
    diagnostic_cb: Callable[[str], None] | None = None,
) -> pd.DataFrame:
    """Pure scoring: append prediction, residual, residual_z, and anomaly_score."""
    out = df.copy()
    missing_features = [col for col in feature_cols if col not in out.columns]
    for col in missing_features:
        out[col] = np.nan

    predict_input = out[feature_cols].copy()
    pred_input = _encode_categoricals(
        model, predict_input, feature_cols, missing_features, diagnostic_cb
    )
    pred = model.predict(pred_input).clip(min=0)
    out["predicted_value"] = pred
    out["residual"] = out[TARGET_COL].values - pred
    out = out.merge(
        resid_stats[["building_id", "resid_median", "resid_mad"]],
        on="building_id",
        how="left",
    )
    safe_mad = (out["resid_mad"] * MAD_SCALE).clip(lower=MAD_FLOOR)
    out["residual_z"] = (out["residual"] - out["resid_median"]) / safe_mad
    out["anomaly_score"] = out["residual_z"].abs()
    return out


def classify_severity(
    scored_df: pd.DataFrame,
    anomaly_z: float = ANOMALY_Z,
    thresholds: list[tuple[float, str]] = SEV_THRESHOLDS,
) -> pd.DataFrame:
    """Policy layer: add anomaly flag, direction, and severity."""
    out = scored_df.copy()
    out["is_anomaly"] = out["anomaly_score"] > anomaly_z
    out["direction"] = np.where(
        out["residual_z"] > anomaly_z,
        "over",
        np.where(out["residual_z"] < -anomaly_z, "under", "normal"),
    )
    out["severity"] = np.select(
        [out["anomaly_score"] >= threshold for threshold, _ in thresholds],
        [severity for _, severity in thresholds],
        default="normal",
    )
    return out
