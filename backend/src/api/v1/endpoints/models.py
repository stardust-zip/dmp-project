from fastapi import APIRouter, Depends
from src.api.v1.deps import get_current_admin, get_current_user
from src.schemas import UserResponse

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
async def trigger_training(current_admin: UserResponse = Depends(get_current_admin)):
    """
    (Placeholder)
    Trigger training job for the forecasting model.
    TODO: Implement
    """
    return {
        "message": "Training job queued successfully.",
        "triggered_by": current_admin.email,
    }


@router.post("/rollback")
async def rollback_model(current_admin: UserResponse = Depends(get_current_admin)):
    """
    (Placeholder)
    Update the active flag to reload the previous AI model version.
    TODO: Implement
    """
    return {
        "message": "Model rolled back to the previous stable version successfully.",
        "triggered_by": current_admin.email,
    }
