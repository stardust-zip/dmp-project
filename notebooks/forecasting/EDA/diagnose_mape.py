"""Diagnostic: có phải MAPE cao do giá trị actual (y_true) gần 0 bị nổ?

Dùng các HÀM THẬT của pipeline forecasting (cleaning + feature build + _mape)
trên một mẫu building đa dạng, train nhanh LightGBM rồi phân tích test set.
Chạy:  cd backend && python ../notebooks/forecasting/EDA/diagnose_mape.py
"""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, "C:/Users/letung373/Desktop/dmp-project/backend")

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, root_mean_squared_error

from src.ml.forecasting.feature_engineering import build_forecast_feature_matrix
from src.ml.forecasting.preprocessing import clean_telemetry_for_forecasting
from src.ml.forecasting.training import (
    TARGET_COLUMN,
    _build_preprocessor,
    _make_estimator,
    _mape,
)
from src.ml.forecasting.types import DEFAULT_FORECAST_HORIZON
from src.schemas import MLAlgorithm

CSV = "C:/Users/letung373/Desktop/dmp-project/data/raw/data/meters/cleaned/electricity_cleaned.csv"
META = "C:/Users/letung373/Desktop/dmp-project/data/raw/data/metadata/metadata.csv"
N_BUILDINGS = 60  # mẫu đa dạng (global-style training)

# 1) Load wide CSV -> long, lấy mẫu N building ngẫu nhiên cố định
raw = pd.read_csv(CSV)
raw["timestamp"] = pd.to_datetime(raw["timestamp"], utc=True, errors="coerce")
all_b = [c for c in raw.columns if c != "timestamp"]
rng = np.random.default_rng(42)
chosen = list(rng.choice(all_b, size=min(N_BUILDINGS, len(all_b)), replace=False))
sub = raw[["timestamp"] + chosen]
melted = sub.melt(id_vars=["timestamp"], var_name="building_id", value_name="consumption")
melted["consumption"] = pd.to_numeric(melted["consumption"], errors="coerce")
melted = melted.dropna(subset=["consumption"])
melted["metric_type_id"] = "electricity"

# 2) Join metadata (sqm, primaryspaceusage, timezone, site_id) như loader
meta = pd.read_csv(META).set_index("building_id")
for col in ["site_id", "sqm", "primaryspaceusage", "timezone"]:
    melted[col] = melted["building_id"].map(meta[col])

# 3) Clean + build feature matrix (hàm thật)
df, stats = clean_telemetry_for_forecasting(melted, drop_high_missing=True, return_stats=True)
print("clean stats:", stats, "| buildings:", df["building_id"].nunique())
fdf, feat_cols, cat = build_forecast_feature_matrix(df, DEFAULT_FORECAST_HORIZON, "none")
print(f"feature matrix: {len(fdf):,} rows x {len(feat_cols)} features")

# 4) Temporal split 70/15/15 theo đúng training.py
start, end = fdf["timestamp"].min(), fdf["timestamp"].max()
total = end - start
train_end, test_start = start + total * 0.70, end - total * 0.15


def sp(d, s, e):
    return d[(d["timestamp"] >= s) & (d["timestamp"] <= e)].copy()


train_df, val_df, test_df = sp(fdf, start, train_end), sp(fdf, train_end, test_start), sp(fdf, test_start, end)
print(f"split -> train={len(train_df):,} val={len(val_df):,} test={len(test_df):,}")

# 5) Fit (reproduce _fit_and_evaluate nhưng giữ lại y_test/pred)
num_features = [c for c in feat_cols if c not in cat]
pre = _build_preprocessor(cat, num_features)
pre.fit(train_df[feat_cols])
x_train = pre.transform(train_df[feat_cols])
x_val = pre.transform(val_df[feat_cols])
x_test = pre.transform(test_df[feat_cols])
y_train = train_df[TARGET_COLUMN].to_numpy(float)
y_val = val_df[TARGET_COLUMN].to_numpy(float)
y_test = test_df[TARGET_COLUMN].to_numpy(float)

est = _make_estimator(MLAlgorithm.LightGBM)
est.fit(
    x_train,
    y_train,
    eval_set=[(x_val, y_val)],
    callbacks=[
        lgb.early_stopping(100, first_metric_only=True, verbose=False),
        lgb.log_evaluation(0),
    ],
)
pred = np.clip(est.predict(x_test), 0.0, None)

# 6) Phân tích MAPE
print("\n=== KẾT QUẢ TEST SET ===")
print(f"MAE  = {mean_absolute_error(y_test, pred):.4f}")
print(f"RMSE = {root_mean_squared_error(y_test, pred):.4f}")
from src.ml.forecasting.training import MAPE_MIN_ACTUAL

print(f"MAPE (hàm _mape thật, mask y<={MAPE_MIN_ACTUAL} kWh) = {_mape(y_test, pred):.4f}%")

print("\n--- Phân phối y_test (actual) ---")
print("  percentiles [1,5,10,25,50]:", np.round(np.percentile(y_test, [1, 5, 10, 25, 50]), 3))
for thr in [0.1, 1, 5, 10]:
    print(f"  y_test < {thr:>4}: {(y_test < thr).mean() * 100:5.1f}%  (n={int((y_test < thr).sum())})")

mask0 = np.abs(y_test) > 1e-9
ape = np.abs((y_test[mask0] - pred[mask0]) / y_test[mask0]) * 100
print("\n--- APE từng điểm (chỉ 式中 y_true khác 0) ---")
print("  percentiles [50,90,95,99,99.9]:", np.round(np.percentile(ape, [50, 90, 95, 99, 99.9]), 2))
print(f"  số điểm APE > 100%  : {int((ape > 100).sum())} ({(ape > 100).mean() * 100:.1f}%)")
print(f"  số điểm APE > 1000% : {int((ape > 1000).sum())} ({(ape > 1000).mean() * 100:.1f}%)")
print(f"  số điểm APE > 10000%: {int((ape > 10000).sum())}")

print("\n--- MAPE nếu mask actual nhỏ (loại điểm |y_true|<=thr) ---")
for thr in [0.1, 1, 5, 10]:
    m = y_test > thr
    if m.any():
        v = np.mean(np.abs((y_test[m] - pred[m]) / y_test[m])) * 100
        print(f"  mask y_true <= {thr:>4}: MAPE = {v:7.2f}%  (giữ {m.sum()} / {len(y_test)} điểm)")

den = (np.abs(y_test) + np.abs(pred)) / 2.0
den = np.where(den == 0, np.nan, den)
smape = np.nanmean(np.abs(y_test - pred) / den) * 100
print(f"\nsMAPE (đối xứng, bị chặn 0-200%) = {smape:.2f}%")
