from fastapi import APIRouter, Depends
from src.api.v1.deps import get_current_admin, get_current_user
from src.schemas import UserResponse
from src.tasks import train_model_task

router = APIRouter()


@router.get("/")
async def list_models(current_user: UserResponse = Depends(get_current_user)):
    """
    (Placeholder)
    Listing AI models (forecasting, anomaly detection).
    TODO: Implement
    """
    return {"models": ["forecasting_v1", "anomaly_detection_v1"]}


@router.post("/train")
async def trigger_training(
    building_id: str = "Panther_parking_Lorriane",
    metric_type: str = "electricity",
    current_admin: UserResponse = Depends(get_current_admin),
):
    """
    Trigger training job for the forecasting model via Celery.
    """
    task = train_model_task.delay(  # type: ignore
        target_building_id=building_id,
        metric_type=metric_type,
    )

    return {
        "message": "Training job queued successfully.",
        "task_id": task.id,
        "triggered_by": current_admin.email,
    }
