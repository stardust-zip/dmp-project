"""
Feature engineering and LightGBM training for anomaly detection.

Split boundaries are computed from the user-supplied date range:
  train_end  = start + 50% of total range
  test_start = end   - 10% of total range
  val_window = [train_end+1h, test_start-1h]  (40% middle)

CV: 4 expanding-window folds over val_window (diagnostic only).
Final: early_stop_model on [start, train_end] -> best_iteration ->
       final_model on [start, test_start-1h] for best_iteration trees.
Calibration: early_stop_model predictions on val_window (out-of-sample).
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING

import holidays as holidays_lib
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sqlalchemy.orm import Session

from src.schemas import ModelTrainingRequest, TrainingDataSource

if TYPE_CHECKING:
    pass

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

DIRECT_LEAKAGE_COLS = {
    "delta_1h", "delta_24h", "pct_change_1h", "pct_change_24h", "consumption_per_sqm",
}
FULL_HISTORY_REFERENCE_COLS = {
    "building_mean", "building_median", "building_std", "building_p95", "building_p99",
}
CAT_FEATURES = ["building_id", "site_id", "primaryspaceusage"]

TIMEZONE_TO_COUNTRY = {
    "US/Pacific": "US",
    "US/Mountain": "US",
    "US/Central": "US",
    "US/Eastern": "US",
    "Europe/London": "GB",
    "Europe/Dublin": "IE",
}
HOLIDAY_MAX_DAYS = 3
MAD_SCALE = 1.4826
MAD_FLOOR = 1e-3
ANOMALY_Z = 3.0
SEV_THRESHOLDS = [(10.0, "Critical"), (6.0, "High"), (4.0, "Medium"), (3.0, "Low")]

# Weather CSV fallback location (mirrors the raw data layout used in tasks.py).
RAW_DATA_DIR = "/app/data/raw/data"


# ---------------------------------------------------------------------------
# Telemetry loading
# ---------------------------------------------------------------------------

def load_telemetry_for_training(db: Session, request: ModelTrainingRequest) -> pd.DataFrame:
    """Load hourly telemetry with 168h lookback for lag warmup."""
    if TrainingDataSource(request.data_source) == TrainingDataSource.CSV:
        return _load_telemetry_from_csv(db, request)
    return _load_telemetry_from_db(db, request)


def _load_telemetry_from_db(db: Session, request: ModelTrainingRequest) -> pd.DataFrame:
    from src.models import Device, Location, TelemetryData

    lookback_start = request.time_range_start - timedelta(hours=168)

    rows = (
        db.query(
            TelemetryData.timestamp,
            TelemetryData.value.label("consumption"),
            TelemetryData.metric_type_id,
            Device.location_id.label("building_id"),
            Location.parent_id.label("site_id"),
        )
        .join(Device, TelemetryData.device_id == Device.id)
        .join(Location, Device.location_id == Location.id)
        .filter(
            TelemetryData.timestamp >= lookback_start,
            TelemetryData.timestamp <= request.time_range_end,
        )
        .all()
    )

    if not rows:
        return pd.DataFrame(columns=["timestamp", "building_id", "site_id", "metric_type_id", "consumption"])

    df = pd.DataFrame(rows, columns=["timestamp", "consumption", "metric_type_id", "building_id", "site_id"])
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df.sort_values(["timestamp", "building_id"], inplace=True)
    df.reset_index(drop=True, inplace=True)

    # Also fetch sqm and primaryspaceusage from Location metadata
    loc_rows = (
        db.query(Location.id, Location.metadata_)
        .filter(Location.id.in_(df["building_id"].unique().tolist()))
        .all()
    )
    loc_meta = {}
    for loc_id, meta in loc_rows:
        if meta:
            loc_meta[loc_id] = {
                "sqm": meta.get("sqm"),
                "primaryspaceusage": meta.get("primaryspaceusage"),
                "timezone": meta.get("timezone"),
            }

    df["sqm"] = df["building_id"].map(lambda b: loc_meta.get(b, {}).get("sqm"))
    df["primaryspaceusage"] = df["building_id"].map(lambda b: loc_meta.get(b, {}).get("primaryspaceusage"))
    df["timezone"] = df["building_id"].map(lambda b: loc_meta.get(b, {}).get("timezone"))

    return df


def _load_telemetry_from_csv(db: Session, request: ModelTrainingRequest) -> pd.DataFrame:
    """Load telemetry from cleaned wide-format meter CSVs, then join location metadata from DB."""
    from pathlib import Path

    from src.ml.training import cleaned_meter_csv_path
    from src.models import Location

    _EMPTY = pd.DataFrame(
        columns=["timestamp", "consumption", "metric_type_id", "building_id", "site_id", "sqm", "primaryspaceusage", "timezone"]
    )

    def _to_utc_ts(dt) -> pd.Timestamp:
        ts = pd.Timestamp(dt)
        return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")

    lookback_start = _to_utc_ts(request.time_range_start - timedelta(hours=168))
    range_end = _to_utc_ts(request.time_range_end)

    frames = []
    for metric in request.metrics:
        csv_path = Path(request.csv_path) if request.csv_path else cleaned_meter_csv_path(metric)
        if not csv_path.exists():
            logger.warning("Meter CSV not found: %s", csv_path)
            continue

        raw = pd.read_csv(csv_path)
        if "timestamp" not in raw.columns:
            logger.warning("No timestamp column in %s", csv_path)
            continue

        raw["timestamp"] = pd.to_datetime(raw["timestamp"], utc=True, errors="coerce")
        raw = raw[(raw["timestamp"] >= lookback_start) & (raw["timestamp"] <= range_end)]
        if raw.empty:
            continue

        building_cols = [c for c in raw.columns if c != "timestamp"]
        melted = raw.melt(id_vars=["timestamp"], value_vars=building_cols, var_name="building_id", value_name="consumption")
        melted["consumption"] = pd.to_numeric(melted["consumption"], errors="coerce")
        melted = melted.dropna(subset=["consumption"])
        melted["metric_type_id"] = metric
        frames.append(melted)

    if not frames:
        return _EMPTY

    df = pd.concat(frames, ignore_index=True)
    df.sort_values(["timestamp", "building_id"], inplace=True)
    df.reset_index(drop=True, inplace=True)

    loc_rows = (
        db.query(Location.id, Location.parent_id, Location.metadata_)
        .filter(Location.id.in_(df["building_id"].unique().tolist()))
        .all()
    )
    loc_meta = {
        loc_id: {
            "site_id": parent_id,
            "sqm": (meta or {}).get("sqm"),
            "primaryspaceusage": (meta or {}).get("primaryspaceusage"),
            "timezone": (meta or {}).get("timezone"),
        }
        for loc_id, parent_id, meta in loc_rows
    }

    df["site_id"] = df["building_id"].map(lambda b: loc_meta.get(b, {}).get("site_id"))
    df["sqm"] = df["building_id"].map(lambda b: loc_meta.get(b, {}).get("sqm"))
    df["primaryspaceusage"] = df["building_id"].map(lambda b: loc_meta.get(b, {}).get("primaryspaceusage"))
    df["timezone"] = df["building_id"].map(lambda b: loc_meta.get(b, {}).get("timezone"))

    return df


# ---------------------------------------------------------------------------
# Weather loading
# ---------------------------------------------------------------------------

def load_weather_for_range(
    db: Session,
    site_ids: list[str],
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> tuple[pd.DataFrame, list[str]]:
    """Load weather features from DB (falls back to CSV)."""
    from pathlib import Path

    from src.models import ContextData

    WEATHER_CONTEXT_TYPES = {"airTemperature", "windSpeed", "dewTemperature"}

    rows = (
        db.query(
            ContextData.timestamp,
            ContextData.location_id.label("site_id"),
            ContextData.context_type_id,
            ContextData.value,
        )
        .filter(
            ContextData.location_id.in_(site_ids),
            ContextData.context_type_id.in_(WEATHER_CONTEXT_TYPES),
            ContextData.timestamp >= start,
            ContextData.timestamp <= end,
        )
        .all()
    )

    if rows:
        raw = pd.DataFrame(rows, columns=["timestamp", "site_id", "context_type_id", "value"])
        weather = raw.pivot_table(index=["timestamp", "site_id"], columns="context_type_id", values="value").reset_index()
        weather.columns.name = None
    else:
        # Fallback to CSV
        csv_path = Path(RAW_DATA_DIR) / "weather" / "weather.csv"
        if not csv_path.exists():
            logger.warning("No weather data in DB and no CSV fallback found.")
            return pd.DataFrame(), []
        weather = pd.read_csv(csv_path)
        weather["timestamp"] = pd.to_datetime(weather["timestamp"])
        for col in ["airTemperature", "dewTemperature", "windSpeed"]:
            if col in weather.columns:
                weather[col] = pd.to_numeric(weather[col], errors="coerce")

    weather["timestamp"] = pd.to_datetime(weather["timestamp"])

    if {"airTemperature", "dewTemperature"}.issubset(weather.columns):
        weather["temp_dew_spread"] = weather["airTemperature"] - weather["dewTemperature"]

    for col, window in [("airTemperature", 24), ("airTemperature", 168)]:
        out_col = f"{col}_roll{window}h"
        weather[out_col] = (
            weather.sort_values(["site_id", "timestamp"])
            .groupby("site_id")[col]
            .transform(lambda s: s.rolling(window, min_periods=1).mean())
        )

    feature_cols = [
        c for c in [
            "airTemperature", "windSpeed", "temp_dew_spread",
            "airTemperature_roll24h", "airTemperature_roll168h",
        ]
        if c in weather.columns
    ]

    return weather[["timestamp", "site_id"] + feature_cols], feature_cols


# ---------------------------------------------------------------------------
# Feature engineering
# ---------------------------------------------------------------------------

def _build_holiday_lookup(df: pd.DataFrame, years: list[int]) -> pd.DataFrame:
    site_tz = (
        df[["site_id", "timezone"]].dropna(subset=["timezone"])
        .drop_duplicates()
        .set_index("site_id")["timezone"]
        .to_dict()
    )
    records = []
    for site, tz in site_tz.items():
        country = TIMEZONE_TO_COUNTRY.get(tz)
        if not country:
            continue
        cal = holidays_lib.country_holidays(country, years=years)
        for date in cal.keys():
            records.append({"site_id": site, "date": pd.Timestamp(date)})
    return pd.DataFrame(records) if records else pd.DataFrame(columns=["site_id", "date"])


def build_feature_matrix(
    df: pd.DataFrame,
    use_weather: bool,
    weather_df: pd.DataFrame,
    weather_feature_cols: list[str],
) -> tuple[pd.DataFrame, list[str], list[str]]:
    """Build the full feature matrix. df must include a 168h lookback prefix for lag warmup."""
    out = df.copy()
    out.sort_values(["building_id", "timestamp"], inplace=True)

    grp = out.groupby("building_id")["consumption"]

    # Lag features
    out["lag_1h"] = grp.transform(lambda s: s.shift(1)).astype("float32")
    out["lag_24h"] = grp.transform(lambda s: s.shift(24)).astype("float32")
    out["lag_168h"] = grp.transform(lambda s: s.shift(168)).astype("float32")

    # Rolling stats (shift(1) first to avoid leakage)
    def shifted_rolling(s, window):
        return s.shift(1).rolling(window, min_periods=1).mean()

    def shifted_rolling_std(s, window):
        return s.shift(1).rolling(window, min_periods=1).std()

    out["rolling_mean_6h"] = grp.transform(lambda s: shifted_rolling(s, 6)).astype("float32")
    out["rolling_mean_24h"] = grp.transform(lambda s: shifted_rolling(s, 24)).astype("float32")
    out["rolling_std_24h"] = grp.transform(lambda s: shifted_rolling_std(s, 24)).astype("float32")
    out["rolling_mean_168h"] = grp.transform(lambda s: shifted_rolling(s, 168)).astype("float32")
    out["rolling_std_168h"] = grp.transform(lambda s: shifted_rolling_std(s, 168)).astype("float32")

    # Historical baselines (computed per building×hour from training data — no leakage because
    # we compute on the whole passed-in df, which is the training slice at call time)
    out["hour"] = out["timestamp"].dt.hour.astype("int32")
    out["day_of_week"] = out["timestamp"].dt.dayofweek.astype("int32")

    hist = (
        out.groupby(["building_id", "hour"])["consumption"]
        .agg(historical_hour_median="median", historical_hour_std="std")
        .reset_index()
    )
    out = out.merge(hist, on=["building_id", "hour"], how="left")

    out["is_weekday"] = (out["day_of_week"] < 5).astype("int8")
    hist_daytype = (
        out.groupby(["building_id", "hour", "is_weekday"])["consumption"]
        .median()
        .reset_index()
        .rename(columns={"consumption": "historical_hour_daytype_median"})
    )
    out = out.merge(hist_daytype, on=["building_id", "hour", "is_weekday"], how="left")
    out.drop(columns=["is_weekday"], inplace=True)

    # Calendar
    out["month"] = out["timestamp"].dt.month.astype("int32")
    out["day_of_year"] = out["timestamp"].dt.dayofyear.astype("int32")
    out["week_of_year"] = out["timestamp"].dt.isocalendar().week.astype("int32")

    # Holiday features
    years = sorted(out["timestamp"].dt.year.unique().tolist())
    holiday_lookup = _build_holiday_lookup(out, years)
    if not holiday_lookup.empty:
        base = pd.DataFrame({"site_id": out["site_id"].values, "date": out["timestamp"].dt.normalize().values})
        hl = holiday_lookup.assign(is_holiday=np.int8(1))
        out["is_holiday"] = (
            base.merge(hl, on=["site_id", "date"], how="left")["is_holiday"]
            .fillna(0).astype("int8").values
        )
        days_to = np.full(len(out), HOLIDAY_MAX_DAYS, dtype="int8")
        days_from = np.full(len(out), HOLIDAY_MAX_DAYS, dtype="int8")
        for d in range(HOLIDAY_MAX_DAYS, 0, -1):
            sb = holiday_lookup[["site_id", "date"]].copy()
            sb["date"] -= pd.Timedelta(days=d)
            sb = sb.drop_duplicates().assign(v=np.int8(1))
            days_to[base.merge(sb, on=["site_id", "date"], how="left")["v"].notna().values] = d
            sf = holiday_lookup[["site_id", "date"]].copy()
            sf["date"] += pd.Timedelta(days=d)
            sf = sf.drop_duplicates().assign(v=np.int8(1))
            days_from[base.merge(sf, on=["site_id", "date"], how="left")["v"].notna().values] = d
        out["days_to_next_holiday"] = days_to
        out["days_from_last_holiday"] = days_from
    else:
        out["is_holiday"] = np.int8(0)
        out["days_to_next_holiday"] = np.int8(HOLIDAY_MAX_DAYS)
        out["days_from_last_holiday"] = np.int8(HOLIDAY_MAX_DAYS)

    # Numeric metadata
    out["sqm"] = out["sqm"].astype("float32")

    # Weather merge
    if use_weather and not weather_df.empty:
        out = out.merge(weather_df, on=["timestamp", "site_id"], how="left")
        for col in weather_feature_cols:
            if col in out.columns:
                out[col] = out[col].astype("float32")
    else:
        weather_feature_cols = []

    # Categorical dtypes
    for col in CAT_FEATURES:
        if col in out.columns:
            out[col] = out[col].astype("category")

    EXCLUDED = DIRECT_LEAKAGE_COLS | FULL_HISTORY_REFERENCE_COLS
    base_features = [
        "hour", "day_of_week", "month", "day_of_year", "week_of_year",
        "is_holiday", "days_to_next_holiday", "days_from_last_holiday",
        "lag_1h", "lag_24h", "lag_168h",
        "rolling_mean_6h", "rolling_mean_24h", "rolling_std_24h",
        "rolling_mean_168h", "rolling_std_168h",
        "historical_hour_median", "historical_hour_std", "historical_hour_daytype_median",
        "sqm",
        "building_id", "site_id", "primaryspaceusage",
    ] + list(weather_feature_cols)

    feature_cols = [c for c in base_features if c in out.columns and c not in EXCLUDED]
    cat_present = [c for c in CAT_FEATURES if c in feature_cols]

    out.sort_values(["timestamp", "building_id"], inplace=True)
    out.reset_index(drop=True, inplace=True)

    return out, feature_cols, cat_present


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def _rmse(y_true, y_pred) -> float:
    return float(np.sqrt(mean_squared_error(y_true, y_pred)))


def _split_by_dates(df: pd.DataFrame, start, end) -> pd.DataFrame:
    return df[(df["timestamp"] >= start) & (df["timestamp"] <= end)].copy()


def train_lgbm(
    df: pd.DataFrame,
    feature_cols: list[str],
    cat_features: list[str],
    train_end: pd.Timestamp,
    test_start: pd.Timestamp,
) -> tuple[lgb.LGBMRegressor, lgb.LGBMRegressor, pd.DataFrame, dict]:
    """
    Returns (final_model, early_stop_model, val_df, metrics).
    CV folds are diagnostic only. The final model uses best_iteration from
    early_stop_model trained on [start, train_end] vs full val window.
    """
    df_start = df["timestamp"].min()

    val_duration = test_start - train_end
    val_chunk = val_duration / 4

    # --- 4-fold expanding-window CV (diagnostic) ---
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
            tr[feature_cols], tr[TARGET_COL],
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
        logger.info(
            "Fold %d: RMSE=%.3f MAE=%.3f best_iter=%d",
            i + 1, fold_metrics[-1]["val_rmse"], fold_metrics[-1]["val_mae"],
            fold_metrics[-1]["best_iteration"],
        )
        del fold_model

    # --- Final early-stop model on [start, train_end] vs full val window ---
    val_start = train_end + timedelta(hours=1)
    val_end = test_start - timedelta(hours=1)

    final_train_df = _split_by_dates(df, df_start, train_end).dropna(subset=[TARGET_COL])
    val_df = _split_by_dates(df, val_start, val_end).dropna(subset=[TARGET_COL])
    fit_df = _split_by_dates(df, df_start, val_end).dropna(subset=[TARGET_COL])
    test_df = _split_by_dates(df, test_start, df["timestamp"].max()).dropna(subset=[TARGET_COL])

    early_stop_model = lgb.LGBMRegressor(**LGB_PARAMS)
    early_stop_model.fit(
        final_train_df[feature_cols], final_train_df[TARGET_COL],
        eval_set=[(val_df[feature_cols], val_df[TARGET_COL])],
        eval_metric="rmse",
        categorical_feature=cat_features,
        callbacks=[
            lgb.early_stopping(EARLY_STOPPING_ROUNDS, first_metric_only=True, verbose=False),
            lgb.log_evaluation(100),
        ],
    )
    best_iteration = early_stop_model.best_iteration_ or LGB_PARAMS["n_estimators"]
    logger.info("Early-stop model best_iteration: %d", best_iteration)

    # --- Final model on [start, val_end] for best_iteration trees ---
    final_params = {**LGB_PARAMS, "n_estimators": best_iteration}
    final_model = lgb.LGBMRegressor(**final_params)
    final_model.fit(
        fit_df[feature_cols], fit_df[TARGET_COL],
        categorical_feature=cat_features,
    )

    # Test evaluation
    test_pred = final_model.predict(test_df[feature_cols]).clip(min=0)
    test_rmse = _rmse(test_df[TARGET_COL], test_pred)
    test_mae = float(mean_absolute_error(test_df[TARGET_COL], test_pred))
    logger.info("Test RMSE=%.3f MAE=%.3f", test_rmse, test_mae)

    metrics = {
        "test_rmse": test_rmse,
        "test_mae": test_mae,
        "best_iteration": best_iteration,
        "cv_folds": fold_metrics,
    }

    return final_model, early_stop_model, val_df, metrics


def compute_residual_stats(
    early_stop_model: lgb.LGBMRegressor,
    val_df: pd.DataFrame,
    feature_cols: list[str],
) -> pd.DataFrame:
    """
    Calibrate per-building residual stats from early_stop_model on the val window
    (out-of-sample for early_stop_model — trained only on the 50% train slice).
    """
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

    # Group fallback for buildings not in val window
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


def score_anomalies(
    model: lgb.LGBMRegressor,
    resid_stats: pd.DataFrame,
    df: pd.DataFrame,
    feature_cols: list[str],
) -> pd.DataFrame:
    """Score df rows; returns df with anomaly columns appended."""
    out = df.copy()
    pred = model.predict(out[feature_cols]).clip(min=0)
    out["predicted_value"] = pred
    out["residual"] = out[TARGET_COL].values - pred

    out = out.merge(resid_stats[["building_id", "resid_median", "resid_mad"]], on="building_id", how="left")
    safe_mad = (out["resid_mad"] * MAD_SCALE).clip(lower=MAD_FLOOR)
    out["residual_z"] = (out["residual"] - out["resid_median"]) / safe_mad
    out["anomaly_score"] = out["residual_z"].abs()
    out["is_anomaly"] = out["anomaly_score"] > ANOMALY_Z
    out["direction"] = np.where(
        out["residual_z"] > ANOMALY_Z, "over",
        np.where(out["residual_z"] < -ANOMALY_Z, "under", "normal"),
    )
    out["severity"] = np.select(
        [out["anomaly_score"] >= t for t, _ in SEV_THRESHOLDS],
        [s for _, s in SEV_THRESHOLDS],
        default="normal",
    )
    return out
