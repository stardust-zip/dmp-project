from datetime import datetime, timezone
from typing import Literal

import pandas as pd
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from src.api.v1.deps import get_current_user, user_has_global_read_access
from src.database import get_db
from src.ml.anomaly.events import (
    event_records,
    filter_events,
    filter_series,
    load_anomaly_facets,
    sort_events,
)
from src.ml.anomaly.types import SEVERITIES
from loguru import logger
from src.schemas import (
    AnomalyEventsResponse,
    AnomalyFacetsResponse,
    AnomalyOverviewResponse,
    AnomalyTimelineResponse,
    UserResponse,
)

router = APIRouter()


def _query_time(value: datetime | None) -> pd.Timestamp | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        return pd.Timestamp(value.astimezone(timezone.utc))
    return pd.Timestamp(value, tz="UTC")


def _allowed_sites(current_user: UserResponse) -> list[str] | None:
    if user_has_global_read_access(current_user):
        return None
    return list(current_user.assigned_site_ids)


def _filtered(
    db: Session,
    site_id: str | None,
    building_id: str | None,
    severity: str | None,
    anomaly_type: str | None,
    start: datetime | None,
    end: datetime | None,
    allowed_site_ids: list[str] | None,
):
    return filter_events(
        db,
        site_id=site_id,
        building_id=building_id,
        severity=severity,
        anomaly_type=anomaly_type,
        start=_query_time(start),
        end=_query_time(end),
        allowed_site_ids=allowed_site_ids,
    )


def _clip_interval(
    interval_start: pd.Timestamp,
    interval_end: pd.Timestamp,
    window_start: pd.Timestamp | None,
    window_end: pd.Timestamp | None,
) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    if pd.isna(interval_start) or pd.isna(interval_end):
        return None
    start_value = max(interval_start, window_start) if window_start is not None else interval_start
    end_value = min(interval_end, window_end) if window_end is not None else interval_end
    if end_value < start_value:
        return None
    return start_value, end_value


def _merge_gaps(
    gaps: list[tuple[pd.Timestamp, pd.Timestamp]],
) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    if not gaps:
        return []

    merged: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    for start_value, end_value in sorted(gaps, key=lambda item: item[0]):
        if not merged or start_value > merged[-1][1]:
            merged.append((start_value, end_value))
            continue
        merged[-1] = (merged[-1][0], max(merged[-1][1], end_value))
    return merged


def _timeline_points_and_gaps(
    db: Session,
    *,
    site_id: str | None,
    building_id: str | None,
    events: pd.DataFrame,
    start: datetime | None,
    end: datetime | None,
    allowed_site_ids: list[str] | None,
) -> tuple[list[dict], list[dict]]:
    if not building_id:
        return [], []

    window_start = _query_time(start)
    window_end = _query_time(end)
    series = filter_series(
        db,
        site_id=site_id,
        building_id=building_id,
        start=window_start,
        end=window_end,
        allowed_site_ids=allowed_site_ids,
    )

    points: list[dict] = []
    raw_gaps: list[tuple[pd.Timestamp, pd.Timestamp]] = []

    if not series.empty:
        series = (
            series.dropna(subset=["timestamp"])
            .sort_values("timestamp")
            .groupby("timestamp", as_index=True)
            .agg({"actual_value": "last", "expected_value": "last"})
        )
        first_ts = window_start if window_start is not None else series.index.min()
        last_ts = window_end if window_end is not None else series.index.max()
        if first_ts is not None and last_ts is not None and last_ts >= first_ts:
            hourly_index = pd.date_range(
                first_ts.floor("h"),
                last_ts.floor("h"),
                freq="h",
            )
            dense = series.reindex(hourly_index)
            missing_start: pd.Timestamp | None = None
            missing_end: pd.Timestamp | None = None

            for ts, row in dense.iterrows():
                actual = row["actual_value"]
                expected = row["expected_value"]
                points.append(
                    {
                        "timestamp": ts.to_pydatetime(),
                        "actual_value": None if pd.isna(actual) else float(actual),
                        "expected_value": None if pd.isna(expected) else float(expected),
                    }
                )

                if pd.isna(actual):
                    missing_start = ts if missing_start is None else missing_start
                    missing_end = ts + pd.Timedelta(hours=1)
                elif missing_start is not None and missing_end is not None:
                    raw_gaps.append((missing_start, missing_end))
                    missing_start = None
                    missing_end = None

            if missing_start is not None and missing_end is not None:
                raw_gaps.append((missing_start, missing_end))

    missing_events = events[events["actual_value"].isna()]
    for row in missing_events.itertuples(index=False):
        start_value = pd.Timestamp(row.start_time)
        end_source = row.end_time if row.end_time is not None and not pd.isna(row.end_time) else row.start_time
        end_value = pd.Timestamp(end_source)
        clipped = _clip_interval(start_value, end_value, window_start, window_end)
        if clipped is not None:
            raw_gaps.append(clipped)

    gaps = [
        {
            "start_time": start_value.to_pydatetime(),
            "end_time": end_value.to_pydatetime(),
            "reason": "Missing actual data",
        }
        for start_value, end_value in _merge_gaps(raw_gaps)
    ]
    return points, gaps


@router.get("/overview", response_model=AnomalyOverviewResponse)
async def get_anomaly_overview(
    site_id: str | None = Query(None),
    building_id: str | None = Query(None),
    severity: str | None = Query(None),
    type: str | None = Query(None),
    start: datetime | None = Query(None),
    end: datetime | None = Query(None),
    db: Session = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user),
):
    logger.info("Anomaly overview requested — site={} building={} severity={} type={} start={} end={}", site_id, building_id, severity, type, start, end)
    events = _filtered(db, site_id, building_id, severity, type, start, end, _allowed_sites(current_user))
    logger.info("Anomaly overview — {} events matched", len(events))
    severity_counts = {key: int((events["severity"] == key).sum()) for key in SEVERITIES}
    type_counts = events["type"].value_counts().head(12).astype(int).to_dict()
    site_counts = events["site_id"].value_counts()

    return {
        "total_anomalies": int(len(events)),
        "critical_anomalies": severity_counts["Critical"],
        "buildings_affected": int(events["building_id"].nunique()),
        "most_affected_site": None if site_counts.empty else str(site_counts.index[0]),
        "time_min": None if events.empty else events["start_time"].min().to_pydatetime(),
        "time_max": None if events.empty else events["end_time"].max().to_pydatetime(),
        "severity_counts": severity_counts,
        "type_counts": type_counts,
    }


@router.get("/events", response_model=AnomalyEventsResponse)
async def get_anomaly_events(
    site_id: str | None = Query(None),
    building_id: str | None = Query(None),
    severity: str | None = Query(None),
    type: str | None = Query(None),
    start: datetime | None = Query(None),
    end: datetime | None = Query(None),
    limit: int | None = Query(None, ge=1),
    offset: int = Query(0, ge=0),
    sort: Literal["severity", "newest", "oldest", "duration"] = Query("severity"),
    db: Session = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user),
):
    logger.info("Anomaly events requested — site={} building={} severity={} type={} start={} end={} limit={} offset={} sort={}", site_id, building_id, severity, type, start, end, limit, offset, sort)
    events = _filtered(db, site_id, building_id, severity, type, start, end, _allowed_sites(current_user))
    logger.info("Anomaly events — {} events matched", len(events))
    events = sort_events(events, sort)
    page = events.iloc[offset:] if limit is None else events.iloc[offset : offset + limit]
    return {
        "total": int(len(events)),
        "limit": len(page) if limit is None else limit,
        "offset": offset,
        "items": event_records(page),
    }


@router.get("/timeline", response_model=AnomalyTimelineResponse)
async def get_anomaly_timeline(
    site_id: str | None = Query(None),
    building_id: str | None = Query(None),
    severity: str | None = Query(None),
    type: str | None = Query(None),
    start: datetime | None = Query(None),
    end: datetime | None = Query(None),
    limit: int = Query(1000, ge=1, le=5000),
    db: Session = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user),
):
    logger.info("Anomaly timeline requested — site={} building={} severity={} type={} start={} end={} limit={}", site_id, building_id, severity, type, start, end, limit)
    allowed = _allowed_sites(current_user)
    events = _filtered(db, site_id, building_id, severity, type, start, end, allowed)
    logger.info("Anomaly timeline — {} events matched, building series fetched: {}", len(events), bool(building_id))
    timeline_events = sort_events(events, "newest").head(limit)
    points, gaps = _timeline_points_and_gaps(
        db,
        site_id=site_id,
        building_id=building_id,
        events=events,
        start=start,
        end=end,
        allowed_site_ids=allowed,
    )
    return {"items": event_records(timeline_events), "points": points, "gaps": gaps}


@router.get("/facets", response_model=AnomalyFacetsResponse)
async def get_anomaly_facets(
    site_id: str | None = Query(None),
    db: Session = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user),
):
    logger.info("Anomaly detection tab opened — facets requested (site={})", site_id)
    response = load_anomaly_facets(db, site_id=site_id, allowed_site_ids=_allowed_sites(current_user))
    logger.info(
        "Anomaly facets loaded - sites={} primary_usage_types={} buildings={} site_sample={} primary_usage_sample={} building_sample={}",
        len(response["sites"]),
        len(response["primary_usage_types"]),
        len(response["buildings"]),
        response["sites"][:5],
        response["primary_usage_types"][:5],
        response["buildings"][:5],
    )
    return response
