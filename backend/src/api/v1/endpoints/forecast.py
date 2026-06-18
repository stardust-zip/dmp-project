from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from src.api.v1.deps import get_current_operator, get_current_user, user_can_access_site
from src.database import get_db
from src.models import ForecastResult, Location
from src.schemas import (
    ForecastGenerateRequest,
    ForecastVsActualResponse,
    UserResponse,
)

router = APIRouter()


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


@router.post("/vs-actual", response_model=ForecastVsActualResponse)
async def generate_forecast_vs_actual(
    payload: ForecastGenerateRequest,
    db: Session = Depends(get_db),
    current_user: UserResponse = Depends(get_current_operator),
) -> Any:
    """Forecast the future for one building and overlay it on the recent actuals.

    Operator/Admin only. Site access is enforced against the building's parent
    site. Runs synchronously and persists the future forecast to
    ``ForecastResult``.
    """
    from src.ml.forecasting.inference import ForecastError, forecast_for_building

    building = db.query(Location).filter(Location.id == payload.building_id).first()
    if building is None:
        raise HTTPException(
            status_code=404, detail=f"Building '{payload.building_id}' not found."
        )
    if not user_can_access_site(current_user, building.parent_id):
        raise HTTPException(
            status_code=403, detail="Not enough permissions for this site."
        )

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
