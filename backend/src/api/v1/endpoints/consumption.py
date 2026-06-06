from fastapi import APIRouter, Depends
from src.api.v1.deps import get_current_user
from src.schemas import UserResponse

router = APIRouter()


@router.get("/")
async def get_consumption(current_user: UserResponse = Depends(get_current_user)):
    """
    (Placeholder)
    Extract past energy consumption data for the Dashboard.
    TODO: Implement
    """
    return {
        "consumption": [
            {"timestamp": "2026-06-05T00:00:00Z", "actual_value": 145.2},
            {"timestamp": "2026-06-06T00:00:00Z", "actual_value": 148.9},
        ]
    }
