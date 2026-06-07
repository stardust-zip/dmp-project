from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from src.api.v1.deps import get_current_user
from src.database import get_db
from src.models import TelemetryData
from src.schemas import ConsumptionPaginatedResponse, UserResponse

router = APIRouter()


@router.get("/", response_model=ConsumptionPaginatedResponse)
async def get_consumption(
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
    query = db.query(TelemetryData)

    if device_id:
        query = query.filter(TelemetryData.device_id == device_id)
    if metric_type_id:
        query = query.filter(TelemetryData.metric_type_id == metric_type_id)
    if start_time:
        query = query.filter(TelemetryData.timestamp >= start_time)
    if end_time:
        query = query.filter(TelemetryData.timestamp <= end_time)

    query = query.order_by(TelemetryData.timestamp.desc())

    results = query.offset(offset).limit(limit).all()

    formatted_results = [
        {
            "timestamp": row.timestamp,
            "device_id": row.device_id,
            "metric_type_id": row.metric_type_id,
            "actual_value": row.value,
            "ingestion_status": row.ingestion_status.name
            if hasattr(row.ingestion_status, "name")
            else row.ingestion_status,
        }
        for row in results
    ]

    return {"limit": limit, "offset": offset, "consumption": formatted_results}
