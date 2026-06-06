from fastapi import APIRouter, Depends
from src.api.v1.deps import get_current_user
from src.schemas import UserResponse

router = APIRouter()


@router.get("/")
async def get_alerts(current_user: UserResponse = Depends(get_current_user)):
    """
    (Placeholder)
    Retrieve a list of detected anomaly alerts.
    TODO: Implement
    """
    return {
        "alerts": [
            {
                "id": "1",
                "severity": "Warning",
                "message": "High energy consumption detected on Floor 3",
                "timestamp": "2026-06-06T10:00:00Z",
            }
        ]
    }
