from fastapi import APIRouter, Depends
from src.api.v1.deps import get_current_user
from src.schemas import UserResponse

router = APIRouter()


@router.get("/")
async def get_forecast(current_user: UserResponse = Depends(get_current_user)):
    """
    (Placeholder)
    Extract forecasted data series for chart visualization.
    TODO: Implement
    """
    return {
        "forecast": [
            {"timestamp": "2026-06-07T00:00:00Z", "predicted_value": 150.5},
            {"timestamp": "2026-06-08T00:00:00Z", "predicted_value": 152.1},
        ]
    }
