from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from src.database import get_db
from src.schemas import TelemetryDataPayload

router = APIRouter()


@router.post("/", response_model=dict)
async def create_telemetry_data(
    payload: TelemetryDataPayload,
    _db: Session = Depends(get_db)
):
    """
    Placeholder for ingesting telemetry data.
    Use this to feed models.
    """
    return {"message": "Telemetry data received", "data": payload}
