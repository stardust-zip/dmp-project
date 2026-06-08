from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session
from src.api.v1.deps import get_current_user
from src.database import get_db
from src.models import Location, MetricType
from src.schemas import UserResponse

router = APIRouter()


@router.get("/locations")
async def list_locations(
    q: str | None = Query(
        None,
        description="Search by location ID or display name.",
    ),
    location_type: str | None = Query(
        None,
        description="Filter by location type ID.",
    ),
    parent_id: str | None = Query(
        None,
        description="Filter buildings by parent site ID.",
    ),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user),
) -> Any:
    """
    Retrieve searchable locations for UI dropdowns.
    """
    query = db.query(Location)
    if q:
        term = f"%{q.strip()}%"
        query = query.filter(or_(Location.id.ilike(term), Location.name.ilike(term)))
    if location_type:
        query = query.filter(Location.location_type_id == location_type)
    if parent_id:
        query = query.filter(Location.parent_id == parent_id)

    locations = query.limit(limit).all()
    return {
        "locations": [
            {
                "id": loc.id,
                "parent_id": loc.parent_id,
                "name": loc.name,
                "location_type": loc.location_type_id,
                "metadata": getattr(loc, "metadata_", {}),
            }
            for loc in locations
        ]
    }


@router.get("/metrics")
async def list_metrics(
    db: Session = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user),
) -> Any:
    """
    Retrieve all available metric types (utilities) for UI dropdowns.
    """
    metrics = db.query(MetricType).all()
    return {
        "metrics": [
            {"id": m.id, "unit": m.unit, "description": m.description} for m in metrics
        ]
    }
