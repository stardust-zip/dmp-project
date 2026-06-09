from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd

from src.core.config import settings
from src.core.exceptions import NotFoundException

SEVERITY_ORDER = {"Critical": 4, "High": 3, "Medium": 2, "Low": 1}
SEVERITIES = ["Critical", "High", "Medium", "Low"]

STAGE1_TYPE_LABELS = {
    "missing_reading": "Missing meter data",
    "long_missing_run": "Missing meter data",
    "no_data_building": "No usable meter data",
    "flatline": "Flatline reading",
    "near_zero_flatline": "Near-zero flatline",
    "spike_extreme_reading": "Extreme spike",
}


def _project_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").exists():
            return parent
    return Path(__file__).resolve().parents[3]


def _data_dir() -> Path:
    configured = Path(settings.ANOMALY_DATA_DIR)
    if configured.is_absolute():
        return configured
    return _project_root() / configured


def _safe_float(value) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _safe_str(value, fallback: str = "Unknown") -> str:
    if value is None or pd.isna(value):
        return fallback
    return str(value)


def _safe_datetime(value):
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(value).to_pydatetime()


def _normalize_stage1(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise NotFoundException(
            "Stage 1 anomaly export was not found.",
            {"path": str(path)},
        )

    df = pd.read_parquet(path)
    if df.empty:
        return pd.DataFrame(columns=_event_columns())

    records = pd.DataFrame(
        {
            "id": df["anomaly_id"].astype(str),
            "site_id": df["site_id"].astype(object).fillna("Unknown").astype(str),
            "building_id": df["building_id"].astype(str),
            "primary_space_usage": df["primaryspaceusage"].astype(object),
            "timestamp": df["timestamp"].where(df["timestamp"].notna(), df["start_time"]),
            "start_time": df["start_time"].where(df["start_time"].notna(), df["timestamp"]),
            "end_time": df["end_time"].where(df["end_time"].notna(), df["timestamp"]),
            "duration_hours": df["duration_hours"].fillna(1.0),
            "severity": df["severity"].astype(str),
            "type": df["anomaly_type"].map(STAGE1_TYPE_LABELS).fillna("Meter data anomaly"),
            "actual_value": df["actual_value"],
            "expected_value": np.nan,
            "deviation_percent": np.nan,
            "reason": df["reason"].fillna("Meter data did not match expected quality checks."),
        }
    )
    return records[_event_columns()]


def _normalize_stage3(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise NotFoundException(
            "Residual anomaly export was not found.",
            {"path": str(path)},
        )

    df = pd.read_parquet(path)
    if df.empty:
        return pd.DataFrame(columns=_event_columns())

    df = df[df["is_anomaly"]].copy()
    if df.empty:
        return pd.DataFrame(columns=_event_columns())

    predicted = df["predicted"].replace(0, np.nan)
    deviation = ((df["consumption"] - df["predicted"]) / predicted) * 100
    direction_label = np.where(
        df["direction"].astype(str).str.lower() == "under",
        "Unusual low consumption",
        "Unusual high consumption",
    )
    reason = np.where(
        df["direction"].astype(str).str.lower() == "under",
        "Consumption was lower than the expected building baseline.",
        "Consumption was higher than the expected building baseline.",
    )

    records = pd.DataFrame(
        {
            "id": (
                "R-"
                + df["building_id"].astype(str)
                + "-"
                + pd.to_datetime(df["timestamp"]).dt.strftime("%Y%m%d%H")
            ),
            "site_id": df["site_id"].astype(object).fillna("Unknown").astype(str),
            "building_id": df["building_id"].astype(str),
            "primary_space_usage": df["primaryspaceusage"].astype(object),
            "timestamp": df["timestamp"],
            "start_time": df["timestamp"],
            "end_time": df["timestamp"],
            "duration_hours": 1.0,
            "severity": df["severity"].astype(str),
            "type": direction_label,
            "actual_value": df["consumption"],
            "expected_value": df["predicted"],
            "deviation_percent": deviation,
            "reason": reason,
        }
    )
    return records[_event_columns()]


def _event_columns() -> list[str]:
    return [
        "id",
        "site_id",
        "building_id",
        "primary_space_usage",
        "timestamp",
        "start_time",
        "end_time",
        "duration_hours",
        "severity",
        "type",
        "actual_value",
        "expected_value",
        "deviation_percent",
        "reason",
    ]


@lru_cache(maxsize=1)
def load_anomaly_events() -> pd.DataFrame:
    data_dir = _data_dir()
    stage1 = _normalize_stage1(data_dir / "stage1_anomalies.parquet")
    stage3 = _normalize_stage3(data_dir / "stage3_residual_anomalies.parquet")
    events = pd.concat([stage1, stage3], ignore_index=True)

    for col in ["timestamp", "start_time", "end_time"]:
        events[col] = pd.to_datetime(events[col], errors="coerce")

    events["severity_rank"] = events["severity"].map(SEVERITY_ORDER).fillna(0).astype(int)
    events = events.sort_values(["severity_rank", "timestamp"], ascending=[False, False])
    return events.reset_index(drop=True)


@lru_cache(maxsize=1)
def load_anomaly_series() -> pd.DataFrame:
    path = _data_dir() / "stage3_residual_anomalies.parquet"
    if not path.exists():
        raise NotFoundException(
            "Residual anomaly export was not found.",
            {"path": str(path)},
        )

    df = pd.read_parquet(
        path,
        columns=[
            "building_id",
            "timestamp",
            "consumption",
            "predicted",
            "severity",
            "is_anomaly",
            "site_id",
            "primaryspaceusage",
        ],
    )
    if df.empty:
        return pd.DataFrame(
            columns=[
                "site_id",
                "building_id",
                "primary_space_usage",
                "timestamp",
                "actual_value",
                "expected_value",
                "severity",
                "is_anomaly",
            ]
        )

    series = pd.DataFrame(
        {
            "site_id": df["site_id"].astype(object).fillna("Unknown").astype(str),
            "building_id": df["building_id"].astype(str),
            "primary_space_usage": df["primaryspaceusage"].astype(object),
            "timestamp": pd.to_datetime(df["timestamp"], errors="coerce"),
            "actual_value": df["consumption"],
            "expected_value": df["predicted"],
            "severity": df["severity"].astype(str),
            "is_anomaly": df["is_anomaly"].astype(bool),
        }
    )
    return series.sort_values(["building_id", "timestamp"]).reset_index(drop=True)


def filter_events(
    *,
    site_id: str | None = None,
    building_id: str | None = None,
    severity: str | None = None,
    anomaly_type: str | None = None,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> pd.DataFrame:
    events = load_anomaly_events()
    mask = pd.Series(True, index=events.index)

    if site_id:
        mask &= events["site_id"] == site_id
    if building_id:
        mask &= events["building_id"] == building_id
    if severity:
        mask &= events["severity"] == severity
    if anomaly_type:
        mask &= events["type"] == anomaly_type
    if start is not None:
        mask &= events["end_time"] >= start
    if end is not None:
        mask &= events["start_time"] <= end

    return events[mask].copy()


def filter_series(
    *,
    site_id: str | None = None,
    building_id: str | None = None,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> pd.DataFrame:
    series = load_anomaly_series()
    mask = pd.Series(True, index=series.index)

    if site_id:
        mask &= series["site_id"] == site_id
    if building_id:
        mask &= series["building_id"] == building_id
    if start is not None:
        mask &= series["timestamp"] >= start
    if end is not None:
        mask &= series["timestamp"] <= end

    return series[mask].copy()


def event_records(events: pd.DataFrame) -> list[dict]:
    records: list[dict] = []
    public_cols = _event_columns()
    for row in events[public_cols].itertuples(index=False):
        record = {
            "id": _safe_str(row.id),
            "site_id": _safe_str(row.site_id),
            "building_id": _safe_str(row.building_id),
            "primary_space_usage": _safe_str(row.primary_space_usage, fallback=None),
            "timestamp": _safe_datetime(row.timestamp),
            "start_time": _safe_datetime(row.start_time),
            "end_time": _safe_datetime(row.end_time),
            "duration_hours": _safe_float(row.duration_hours),
            "severity": _safe_str(row.severity),
            "type": _safe_str(row.type),
            "actual_value": _safe_float(row.actual_value),
            "expected_value": _safe_float(row.expected_value),
            "deviation_percent": _safe_float(row.deviation_percent),
            "reason": _safe_str(row.reason, fallback="An anomaly was detected."),
        }
        records.append(record)
    return records


def sort_events(
    events: pd.DataFrame,
    sort: Literal["severity", "newest", "oldest", "duration"],
) -> pd.DataFrame:
    if sort == "newest":
        return events.sort_values("timestamp", ascending=False)
    if sort == "oldest":
        return events.sort_values("timestamp", ascending=True)
    if sort == "duration":
        return events.sort_values(["duration_hours", "severity_rank"], ascending=[False, False])
    return events.sort_values(["severity_rank", "timestamp"], ascending=[False, False])
