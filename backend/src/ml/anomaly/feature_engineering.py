from __future__ import annotations

import holidays as holidays_lib
import numpy as np
import pandas as pd

from src.ml.anomaly.types import LOOKBACK_HOURS

DIRECT_LEAKAGE_COLS = {
    "delta_1h",
    "delta_24h",
    "pct_change_1h",
    "pct_change_24h",
    "consumption_per_sqm",
}
FULL_HISTORY_REFERENCE_COLS = {
    "building_mean",
    "building_median",
    "building_std",
    "building_p95",
    "building_p99",
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


def _build_holiday_lookup(df: pd.DataFrame, years: list[int]) -> pd.DataFrame:
    site_tz = (
        df[["site_id", "timezone"]]
        .dropna(subset=["timezone"])
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


def _add_lag_features(out: pd.DataFrame) -> pd.DataFrame:
    grp = out.groupby("building_id")["consumption"]
    out["lag_1h"] = grp.transform(lambda s: s.shift(1)).astype("float32")
    out["lag_24h"] = grp.transform(lambda s: s.shift(24)).astype("float32")
    out["lag_168h"] = grp.transform(lambda s: s.shift(LOOKBACK_HOURS)).astype("float32")
    return out


def _add_rolling_features(out: pd.DataFrame) -> pd.DataFrame:
    grp = out.groupby("building_id")["consumption"]

    def shifted_rolling(s, window):
        return s.shift(1).rolling(window, min_periods=1).mean()

    def shifted_rolling_std(s, window):
        return s.shift(1).rolling(window, min_periods=1).std()

    out["rolling_mean_6h"] = grp.transform(lambda s: shifted_rolling(s, 6)).astype("float32")
    out["rolling_mean_24h"] = grp.transform(lambda s: shifted_rolling(s, 24)).astype("float32")
    out["rolling_std_24h"] = grp.transform(lambda s: shifted_rolling_std(s, 24)).astype("float32")
    out["rolling_mean_168h"] = grp.transform(lambda s: shifted_rolling(s, LOOKBACK_HOURS)).astype("float32")
    out["rolling_std_168h"] = grp.transform(lambda s: shifted_rolling_std(s, LOOKBACK_HOURS)).astype("float32")
    return out


def _add_historical_baselines(out: pd.DataFrame) -> pd.DataFrame:
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
    return out.drop(columns=["is_weekday"])


def _add_calendar_features(out: pd.DataFrame) -> pd.DataFrame:
    out["month"] = out["timestamp"].dt.month.astype("int32")
    out["day_of_year"] = out["timestamp"].dt.dayofyear.astype("int32")
    out["week_of_year"] = out["timestamp"].dt.isocalendar().week.astype("int32")
    return out


def _add_holiday_features(out: pd.DataFrame) -> pd.DataFrame:
    years = sorted(out["timestamp"].dt.year.unique().tolist())
    holiday_lookup = _build_holiday_lookup(out, years)
    if holiday_lookup.empty:
        out["is_holiday"] = np.int8(0)
        out["days_to_next_holiday"] = np.int8(HOLIDAY_MAX_DAYS)
        out["days_from_last_holiday"] = np.int8(HOLIDAY_MAX_DAYS)
        return out

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
    return out


def _merge_weather(
    out: pd.DataFrame,
    use_weather: bool,
    weather_df: pd.DataFrame,
    weather_feature_cols: list[str],
) -> tuple[pd.DataFrame, list[str]]:
    if use_weather and not weather_df.empty:
        weather_df = weather_df.copy()
        weather_df["timestamp"] = pd.to_datetime(weather_df["timestamp"], utc=True)
        out = out.merge(weather_df, on=["timestamp", "site_id"], how="left")
        for col in weather_feature_cols:
            if col in out.columns:
                out[col] = out[col].astype("float32")
        return out, weather_feature_cols
    return out, []


def _select_features(
    out: pd.DataFrame,
    weather_feature_cols: list[str],
) -> tuple[pd.DataFrame, list[str], list[str]]:
    for col in CAT_FEATURES:
        if col in out.columns:
            out[col] = out[col].astype("category")

    excluded = DIRECT_LEAKAGE_COLS | FULL_HISTORY_REFERENCE_COLS
    base_features = [
        "hour", "day_of_week", "month", "day_of_year", "week_of_year",
        "is_holiday", "days_to_next_holiday", "days_from_last_holiday",
        "lag_1h", "lag_24h", "lag_168h",
        "rolling_mean_6h", "rolling_mean_24h", "rolling_std_24h",
        "rolling_mean_168h", "rolling_std_168h",
        "historical_hour_median", "historical_hour_std", "historical_hour_daytype_median",
        "sqm", "building_id", "site_id", "primaryspaceusage",
    ] + list(weather_feature_cols)
    feature_cols = [c for c in base_features if c in out.columns and c not in excluded]
    cat_present = [c for c in CAT_FEATURES if c in feature_cols]
    out.sort_values(["timestamp", "building_id"], inplace=True)
    out.reset_index(drop=True, inplace=True)
    return out, feature_cols, cat_present


def build_feature_matrix(
    df: pd.DataFrame,
    use_weather: bool,
    weather_df: pd.DataFrame,
    weather_feature_cols: list[str],
) -> tuple[pd.DataFrame, list[str], list[str]]:
    """Build the full feature matrix. df must include a lookback prefix for lag warmup."""
    out = df.copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True)
    out.sort_values(["building_id", "timestamp"], inplace=True)
    out = _add_lag_features(out)
    out = _add_rolling_features(out)
    out = _add_historical_baselines(out)
    out = _add_calendar_features(out)
    out = _add_holiday_features(out)
    out["sqm"] = out["sqm"].astype("float32")
    out, weather_feature_cols = _merge_weather(out, use_weather, weather_df, weather_feature_cols)
    return _select_features(out, weather_feature_cols)
