from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from src.api.v1.deps import get_current_user
from src.database import get_db
from src.models import Location, MetricType
from src.schemas import UserResponse

router = APIRouter()


@router.get("/locations")
async def list_locations(
    db: Session = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user),
) -> Any:
    """
    Retrieve all available locations (buildings) for UI dropdowns.
    """
    locations = db.query(Location).all()
    return {
        "locations": [
            {
                "id": loc.id,
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
