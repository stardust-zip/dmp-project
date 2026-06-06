from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from src.api.v1.deps import get_current_admin
from src.database import get_db
from src.schemas import TelemetryDataPayload, UserResponse

router = APIRouter()


@router.post("/", response_model=dict)
async def create_telemetry_data(
    payload: TelemetryDataPayload,
    _db: Session = Depends(get_db),
    current_user: UserResponse = Depends(get_current_admin),
):
    """
    Placeholder for ingesting telemetry data.
    Use this to feed models.
    """
    return {"message": "Telemetry data received", "data": payload}
