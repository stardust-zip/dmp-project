from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path

import pandas as pd
from sqlalchemy.orm import Session

from src.ml.anomaly.types import LOOKBACK_HOURS
from src.schemas import ModelTrainingRequest, TrainingDataSource

logger = logging.getLogger(__name__)

TELEMETRY_COLUMNS = [
    "timestamp",
    "consumption",
    "metric_type_id",
    "building_id",
    "site_id",
    "sqm",
    "primaryspaceusage",
    "sub_primaryspaceusage",
    "timezone",
]


def load_telemetry_for_training(db: Session, request: ModelTrainingRequest) -> pd.DataFrame:
    """Load hourly telemetry with lookback for lag warmup."""
    if TrainingDataSource(request.data_source) == TrainingDataSource.CSV:
        return _load_telemetry_from_csv(db, request)
    return _load_telemetry_from_db(db, request)


def query_telemetry_window(
    db: Session,
    start,
    end,
    metrics: list[str] | None = None,
) -> pd.DataFrame:
    from src.models import Device, Location, TelemetryData

    query = (
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
            TelemetryData.timestamp >= start,
            TelemetryData.timestamp <= end,
        )
    )
    if metrics:
        query = query.filter(TelemetryData.metric_type_id.in_(metrics))

    rows = query.all()
    if not rows:
        return pd.DataFrame(columns=TELEMETRY_COLUMNS)

    df = pd.DataFrame(
        rows,
        columns=["timestamp", "consumption", "metric_type_id", "building_id", "site_id"],
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)

    loc_rows = (
        db.query(Location.id, Location.metadata_)
        .filter(Location.id.in_(df["building_id"].unique().tolist()))
        .all()
    )
    loc_meta = {
        loc_id: {
            "sqm": (meta or {}).get("sqm"),
            "primaryspaceusage": (meta or {}).get("primaryspaceusage"),
            "sub_primaryspaceusage": (meta or {}).get("sub_primaryspaceusage"),
            "timezone": (meta or {}).get("timezone"),
        }
        for loc_id, meta in loc_rows
    }
    df["sqm"] = df["building_id"].map(lambda b: loc_meta.get(b, {}).get("sqm"))
    df["primaryspaceusage"] = df["building_id"].map(
        lambda b: loc_meta.get(b, {}).get("primaryspaceusage")
    )
    df["timezone"] = df["building_id"].map(lambda b: loc_meta.get(b, {}).get("timezone"))
    df["sub_primaryspaceusage"] = df["building_id"].map(
        lambda b: loc_meta.get(b, {}).get("sub_primaryspaceusage")
    )
    null_sub = df["sub_primaryspaceusage"].isna()
    df.loc[null_sub, "sub_primaryspaceusage"] = df.loc[null_sub, "primaryspaceusage"]
    df.sort_values(["timestamp", "building_id"], inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df


def _load_telemetry_from_db(db: Session, request: ModelTrainingRequest) -> pd.DataFrame:
    lookback_start = request.time_range_start - timedelta(hours=LOOKBACK_HOURS)
    return query_telemetry_window(
        db,
        lookback_start,
        request.time_range_end,
        metrics=request.metrics,
    )


def _load_telemetry_from_csv(db: Session, request: ModelTrainingRequest) -> pd.DataFrame:
    """Load telemetry from cleaned wide-format meter CSVs, then join location metadata from DB."""
    from src.ml.training import cleaned_meter_csv_path
    from src.models import Location

    empty = pd.DataFrame(columns=TELEMETRY_COLUMNS)

    def _to_utc_ts(dt) -> pd.Timestamp:
        ts = pd.Timestamp(dt)
        return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")

    lookback_start = _to_utc_ts(request.time_range_start - timedelta(hours=LOOKBACK_HOURS))
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
        melted = raw.melt(
            id_vars=["timestamp"],
            value_vars=building_cols,
            var_name="building_id",
            value_name="consumption",
        )
        melted["consumption"] = pd.to_numeric(melted["consumption"], errors="coerce")
        melted["metric_type_id"] = metric
        frames.append(melted)

    if not frames:
        return empty

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
            "sub_primaryspaceusage": (meta or {}).get("sub_primaryspaceusage"),
            "timezone": (meta or {}).get("timezone"),
        }
        for loc_id, parent_id, meta in loc_rows
    }

    df["site_id"] = df["building_id"].map(lambda b: loc_meta.get(b, {}).get("site_id"))
    df["sqm"] = df["building_id"].map(lambda b: loc_meta.get(b, {}).get("sqm"))
    df["primaryspaceusage"] = df["building_id"].map(
        lambda b: loc_meta.get(b, {}).get("primaryspaceusage")
    )
    df["sub_primaryspaceusage"] = df["building_id"].map(
        lambda b: loc_meta.get(b, {}).get("sub_primaryspaceusage")
    )
    null_sub = df["sub_primaryspaceusage"].isna()
    df.loc[null_sub, "sub_primaryspaceusage"] = df.loc[null_sub, "primaryspaceusage"]
    df["timezone"] = df["building_id"].map(lambda b: loc_meta.get(b, {}).get("timezone"))
    return df


def downcast_telemetry_dtypes(df: pd.DataFrame) -> None:
    """Downcast float64->float32 and int64->int32 in-place before feature matrix build."""
    for col in df.columns:
        if df[col].dtype == "float64":
            df[col] = df[col].astype("float32")
        elif df[col].dtype == "int64":
            df[col] = df[col].astype("int32")
