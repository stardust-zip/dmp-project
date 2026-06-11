from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from src.api.v1.deps import get_current_user
from src.database import get_db
from src.ml.prediction import PredictionService
from src.schemas import (
    ExpectedActualReportRequest,
    ExpectedActualReportResponse,
    PredictionScenarioRequest,
    PredictionScenarioResponse,
    UserResponse,
)

router = APIRouter()


def get_prediction_service() -> PredictionService:
    return PredictionService()


@router.post("/scenario", response_model=PredictionScenarioResponse)
async def predict_scenario(
    payload: PredictionScenarioRequest,
    db: Session = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user),
    service: PredictionService = Depends(get_prediction_service),
):
    """
    Estimate expected usage for an operator-supplied what-if scenario.
    """
    try:
        return service.predict_scenario(db, payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.post("/expected-vs-actual", response_model=ExpectedActualReportResponse)
async def expected_vs_actual(
    payload: ExpectedActualReportRequest,
    db: Session = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user),
    service: PredictionService = Depends(get_prediction_service),
):
    """
    Compare actual telemetry against model-expected usage for a historical period.
    """
    try:
        return service.expected_vs_actual(db, payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
