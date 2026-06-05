from fastapi import APIRouter

router = APIRouter()

@router.get("/")
async def list_models():
    """
    Placeholder for listing AI models (forecasting, anomaly detection).
    """
    return {"models": ["forecasting_v1", "anomaly_detection_v1"]}
