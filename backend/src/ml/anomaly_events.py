from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

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

_DIRECTION_TYPE_LABELS = {
    "under": "Unusual low consumption",
    "over": "Unusual high consumption",
}


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


def _event_type(row) -> str:
    if row["source"] == "rule_based" and row["anomaly_type"]:
        return STAGE1_TYPE_LABELS.get(row["anomaly_type"], "Meter data anomaly")
    direction = str(row["direction"]).lower() if row["direction"] is not None else ""
    return _DIRECTION_TYPE_LABELS.get(direction, "Unusual consumption")


def load_anomaly_facets(db: Session, site_id: str | None = None) -> dict:
    from src.models import AnomalyDetectedEvent

    base = [AnomalyDetectedEvent.is_anomaly.is_(True)]
    scoped = base + ([AnomalyDetectedEvent.site_id == site_id] if site_id else [])

    site_rows = (
        db.query(AnomalyDetectedEvent.site_id)
        .filter(*base, AnomalyDetectedEvent.site_id.isnot(None))
        .distinct()
        .all()
    )
    building_rows = (
        db.query(AnomalyDetectedEvent.building_id)
        .filter(*scoped, AnomalyDetectedEvent.building_id.isnot(None))
        .distinct()
        .all()
    )
    usage_rows = (
        db.query(AnomalyDetectedEvent.primary_space_usage)
        .filter(*scoped, AnomalyDetectedEvent.primary_space_usage.isnot(None))
        .distinct()
        .all()
    )
    type_rows = (
        db.query(
            AnomalyDetectedEvent.source,
            AnomalyDetectedEvent.anomaly_type,
            AnomalyDetectedEvent.direction,
        )
        .filter(*scoped)
        .distinct()
        .all()
    )
    types = sorted({
        _event_type({"source": r.source, "anomaly_type": r.anomaly_type, "direction": r.direction})
        for r in type_rows
    })
    return {
        "sites": sorted(str(r.site_id) for r in site_rows),
        "buildings": sorted(str(r.building_id) for r in building_rows),
        "severities": SEVERITIES,
        "types": types,
        "primary_usage_types": sorted(str(r.primary_space_usage) for r in usage_rows),
    }


def _rows_to_events_df(rows) -> pd.DataFrame:
    if not rows:
        events = pd.DataFrame(columns=_event_columns())
        events["severity_rank"] = pd.Series(dtype=int)
        return events

    records = []
    for row in rows:
        predicted = row.predicted_value
        actual = row.actual_value
        deviation = ((actual - predicted) / predicted) * 100 if predicted not in (None, 0) and actual is not None else np.nan
        records.append(
            {
                "id": str(row.id),
                "site_id": _safe_str(row.site_id),
                "building_id": _safe_str(row.building_id),
                "primary_space_usage": row.primary_space_usage,
                "timestamp": row.timestamp,
                "start_time": row.timestamp,
                "end_time": row.timestamp,
                "duration_hours": 1.0,
                "severity": _safe_str(row.severity),
                "type": _event_type({"source": row.source, "anomaly_type": row.anomaly_type, "direction": row.direction}),
                "actual_value": actual,
                "expected_value": predicted,
                "deviation_percent": deviation,
                "reason": row.reason if row.reason else "Meter data did not match expected quality checks.",
            }
        )

    events = pd.DataFrame(records, columns=_event_columns())
    for col in ["timestamp", "start_time", "end_time"]:
        events[col] = pd.to_datetime(events[col], errors="coerce")
    events["severity_rank"] = events["severity"].map(SEVERITY_ORDER).fillna(0).astype(int)
    events = events.sort_values(["severity_rank", "timestamp"], ascending=[False, False])
    return events.reset_index(drop=True)


def load_anomaly_events(db: Session) -> pd.DataFrame:
    from src.models import AnomalyDetectedEvent

    rows = db.query(AnomalyDetectedEvent).filter(AnomalyDetectedEvent.is_anomaly.is_(True)).all()
    return _rows_to_events_df(rows)


def load_anomaly_series(db: Session) -> pd.DataFrame:
    from src.models import AnomalyDetectedEvent

    columns = [
        "site_id",
        "building_id",
        "primary_space_usage",
        "timestamp",
        "actual_value",
        "expected_value",
        "severity",
        "is_anomaly",
    ]

    rows = (
        db.query(AnomalyDetectedEvent)
        .filter(AnomalyDetectedEvent.source == "lgbm")
        .all()
    )

    if not rows:
        return pd.DataFrame(columns=columns)

    series = pd.DataFrame(
        [
            {
                "site_id": _safe_str(row.site_id),
                "building_id": _safe_str(row.building_id),
                "primary_space_usage": row.primary_space_usage,
                "timestamp": row.timestamp,
                "actual_value": row.actual_value,
                "expected_value": row.predicted_value,
                "severity": _safe_str(row.severity),
                "is_anomaly": bool(row.is_anomaly),
            }
            for row in rows
        ],
        columns=columns,
    )
    series["timestamp"] = pd.to_datetime(series["timestamp"], errors="coerce")
    return series.sort_values(["building_id", "timestamp"]).reset_index(drop=True)


def filter_events(
    db: Session,
    *,
    site_id: str | None = None,
    building_id: str | None = None,
    severity: str | None = None,
    anomaly_type: str | None = None,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> pd.DataFrame:
    from src.models import AnomalyDetectedEvent

    q = db.query(AnomalyDetectedEvent).filter(AnomalyDetectedEvent.is_anomaly.is_(True))
    if site_id:
        q = q.filter(AnomalyDetectedEvent.site_id == site_id)
    if building_id:
        q = q.filter(AnomalyDetectedEvent.building_id == building_id)
    if severity:
        q = q.filter(AnomalyDetectedEvent.severity == severity)
    if start is not None:
        q = q.filter(AnomalyDetectedEvent.timestamp >= start)
    if end is not None:
        q = q.filter(AnomalyDetectedEvent.timestamp <= end)

    events = _rows_to_events_df(q.all())

    if anomaly_type:
        events = events[events["type"] == anomaly_type].copy()

    return events


def filter_series(
    db: Session,
    *,
    site_id: str | None = None,
    building_id: str | None = None,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> pd.DataFrame:
    from src.models import AnomalyDetectedEvent

    columns = ["site_id", "building_id", "primary_space_usage", "timestamp", "actual_value", "expected_value", "severity", "is_anomaly"]

    q = db.query(AnomalyDetectedEvent).filter(AnomalyDetectedEvent.source == "lgbm")
    if site_id:
        q = q.filter(AnomalyDetectedEvent.site_id == site_id)
    if building_id:
        q = q.filter(AnomalyDetectedEvent.building_id == building_id)
    if start is not None:
        q = q.filter(AnomalyDetectedEvent.timestamp >= start)
    if end is not None:
        q = q.filter(AnomalyDetectedEvent.timestamp <= end)

    rows = q.all()
    if not rows:
        return pd.DataFrame(columns=columns)

    series = pd.DataFrame(
        [
            {
                "site_id": _safe_str(row.site_id),
                "building_id": _safe_str(row.building_id),
                "primary_space_usage": row.primary_space_usage,
                "timestamp": row.timestamp,
                "actual_value": row.actual_value,
                "expected_value": row.predicted_value,
                "severity": _safe_str(row.severity),
                "is_anomaly": bool(row.is_anomaly),
            }
            for row in rows
        ],
        columns=columns,
    )
    series["timestamp"] = pd.to_datetime(series["timestamp"], errors="coerce")
    return series.sort_values(["building_id", "timestamp"]).reset_index(drop=True)


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
