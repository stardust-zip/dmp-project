from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session
from src.api.v1.deps import get_current_user, user_can_access_site
from src.database import get_db
from src.models import Device, ForecastResult, Location, TelemetryData
from src.schemas import (
    ForecastGenerateRequest,
    ForecastVsActualResponse,
    UserResponse,
)

router = APIRouter()
RECOMMENDED_FORECAST_INPUT_HOURS = 14 * 24


def _assert_building_access(
    db: Session, current_user: UserResponse, building_id: str
) -> Location:
    building = db.query(Location).filter(Location.id == building_id).first()
    if building is None:
        raise HTTPException(
            status_code=404, detail=f"Building '{building_id}' not found."
        )
    if not user_can_access_site(current_user, building.parent_id):
        raise HTTPException(
            status_code=403, detail="Not enough permissions for this site."
        )
    return building


def _latest_contiguous_hourly_window(
    timestamps: list[datetime],
    *,
    min_hours: int = RECOMMENDED_FORECAST_INPUT_HOURS,
) -> tuple[datetime | None, datetime | None]:
    if not timestamps:
        return None, None

    ordered = sorted({ts.replace(minute=0, second=0, microsecond=0) for ts in timestamps})
    segments: list[tuple[datetime, datetime, int]] = []
    start = ordered[0]
    previous = ordered[0]
    length = 1

    for current in ordered[1:]:
        if current - previous == timedelta(hours=1):
            length += 1
        else:
            segments.append((start, previous, length))
            start = current
            length = 1
        previous = current
    segments.append((start, previous, length))

    for start, end, length in reversed(segments):
        if length >= min_hours:
            return max(start, end - timedelta(hours=min_hours - 1)), end

    # No segment is long enough. Return the latest contiguous segment so the UI
    # can show truthful coverage instead of recommending a min/max range with gaps.
    start, end, _length = segments[-1]
    return start, end


@router.get("/")
async def get_forecast(
    device_id: str | None = Query(None, description="Filter by a specific device ID"),
    metric_type_id: str | None = Query(
        None, description="Filter by metric (e.g., electricity, water)"
    ),
    start_time: datetime | None = Query(None, description="Start timestamp (ISO 8601)"),
    end_time: datetime | None = Query(None, description="End timestamp (ISO 8601)"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum records to return"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    db: Session = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user),
) -> Any:
    """
    Extract forecasted data series for chart visualization.
    """
    query = db.query(ForecastResult)

    if device_id:
        query = query.filter(ForecastResult.device_id == device_id)
    if metric_type_id:
        query = query.filter(ForecastResult.metric_type_id == metric_type_id)
    if start_time:
        query = query.filter(ForecastResult.timestamp >= start_time)
    if end_time:
        query = query.filter(ForecastResult.timestamp <= end_time)

    query = query.order_by(ForecastResult.timestamp.desc())
    results = query.offset(offset).limit(limit).all()

    formatted_results = [
        {
            "timestamp": row.timestamp,
            "device_id": row.device_id,
            "metric_type_id": row.metric_type_id,
            "predicted_value": row.predicted_value,
        }
        for row in results
    ]

    return {"limit": limit, "offset": offset, "forecast": formatted_results}


@router.get("/availability")
async def get_forecast_availability(
    building_id: str = Query(..., min_length=1),
    metric_type: str = Query("electricity", min_length=1),
    db: Session = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user),
) -> Any:
    """Return telemetry availability for forecast input selection."""
    _assert_building_access(db, current_user, building_id)

    timestamp_rows = (
        db.query(TelemetryData.timestamp)
        .join(Device, TelemetryData.device_id == Device.id)
        .filter(Device.location_id == building_id)
        .filter(TelemetryData.metric_type_id == metric_type)
        .order_by(TelemetryData.timestamp)
        .all()
    )
    timestamps = [row[0] for row in timestamp_rows]
    row_count = len(timestamps)
    first_ts = min(timestamps) if timestamps else None
    last_ts = max(timestamps) if timestamps else None

    recommended_start, recommended_end = _latest_contiguous_hourly_window(timestamps)

    return {
        "building_id": building_id,
        "metric_type": metric_type,
        "first_timestamp": first_ts,
        "last_timestamp": last_ts,
        "row_count": row_count,
        "recommended_input_start": recommended_start,
        "recommended_input_end": recommended_end,
    }


@router.post("/vs-actual", response_model=ForecastVsActualResponse)
async def generate_forecast_vs_actual(
    payload: ForecastGenerateRequest,
    db: Session = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user),
) -> Any:
    """Forecast the future for one building and overlay it on the recent actuals.

    Operator/Admin only. Site access is enforced against the building's parent
    site. Runs synchronously and persists the future forecast to
    ``ForecastResult``.
    """
    from src.ml.forecasting.inference import ForecastError, forecast_for_building

    _assert_building_access(db, current_user, payload.building_id)

    try:
        return forecast_for_building(
            db,
            building_id=payload.building_id,
            metric_type_id=payload.metric_type,
            input_start=payload.input_start,
            input_end=payload.input_end,
            forecast_hours=payload.forecast_hours,
        )
    except ForecastError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Forecast generation failed: {type(exc).__name__}: {exc}",
        ) from exc
