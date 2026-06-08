from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from src.api.v1.deps import get_current_user
from src.database import get_db
from src.models import AnomalyAlert
from src.schemas import UserResponse

router = APIRouter()


@router.get("/")
async def get_alerts(
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
    Retrieve a paginated list of detected anomaly alerts.
    """
    query = db.query(AnomalyAlert)

    if device_id:
        query = query.filter(AnomalyAlert.device_id == device_id)
    if metric_type_id:
        query = query.filter(AnomalyAlert.metric_type_id == metric_type_id)
    if start_time:
        query = query.filter(AnomalyAlert.created_at >= start_time)
    if end_time:
        query = query.filter(AnomalyAlert.created_at <= end_time)

    query = query.order_by(AnomalyAlert.created_at.desc())
    results = query.offset(offset).limit(limit).all()

    formatted_results = [
        {
            "id": str(row.id),
            "device_id": row.device_id,
            "metric_type_id": row.metric_type_id,
            "severity": row.severity.name
            if hasattr(row.severity, "name")
            else row.severity,
            "message": row.message,
            "status": row.status.name if hasattr(row.status, "name") else row.status,
            "timestamp": row.created_at,
        }
        for row in results
    ]

    return {"limit": limit, "offset": offset, "alerts": formatted_results}
