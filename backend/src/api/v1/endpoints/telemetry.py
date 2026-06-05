from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from src.database import get_db
from src.schemas import TelemetryDataPayload

router = APIRouter()

@router.post("/", response_model=dict)
async def create_telemetry_data(
    payload: TelemetryDataPayload,
    db: Session = Depends(get_db)
):
    """
    Placeholder for ingesting telemetry data.
    AI Engineers will use this to feed their models.
    """
    return {"message": "Telemetry data received", "data": payload}
