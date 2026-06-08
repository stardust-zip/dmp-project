from datetime import datetime, timezone
from typing import Literal

import pandas as pd
from fastapi import APIRouter, Query
from src.ml.anomaly_events import (
    SEVERITIES,
    event_records,
    filter_events,
    load_anomaly_events,
    sort_events,
)
from src.schemas import (
    AnomalyEventsResponse,
    AnomalyFacetsResponse,
    AnomalyOverviewResponse,
    AnomalyTimelineResponse,
)

router = APIRouter()


def _query_time(value: datetime | None) -> pd.Timestamp | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return pd.Timestamp(value)


def _filtered(
    site_id: str | None,
    building_id: str | None,
    severity: str | None,
    anomaly_type: str | None,
    start: datetime | None,
    end: datetime | None,
):
    return filter_events(
        site_id=site_id,
        building_id=building_id,
        severity=severity,
        anomaly_type=anomaly_type,
        start=_query_time(start),
        end=_query_time(end),
    )


@router.get("/overview", response_model=AnomalyOverviewResponse)
async def get_anomaly_overview(
    site_id: str | None = Query(None),
    building_id: str | None = Query(None),
    severity: str | None = Query(None),
    type: str | None = Query(None),
    start: datetime | None = Query(None),
    end: datetime | None = Query(None),
):
    events = _filtered(site_id, building_id, severity, type, start, end)
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
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    sort: Literal["severity", "newest", "oldest", "duration"] = Query("severity"),
):
    events = _filtered(site_id, building_id, severity, type, start, end)
    events = sort_events(events, sort)
    page = events.iloc[offset : offset + limit]
    return {
        "total": int(len(events)),
        "limit": limit,
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
):
    events = _filtered(site_id, building_id, severity, type, start, end)
    events = sort_events(events, "newest").head(limit)
    return {"items": event_records(events)}


@router.get("/facets", response_model=AnomalyFacetsResponse)
async def get_anomaly_facets():
    events = load_anomaly_events()
    return {
        "sites": sorted([str(value) for value in events["site_id"].dropna().unique()]),
        "buildings": sorted([str(value) for value in events["building_id"].dropna().unique()]),
        "severities": SEVERITIES,
        "types": sorted([str(value) for value in events["type"].dropna().unique()]),
    }
