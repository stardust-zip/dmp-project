from fastapi import APIRouter
from src.api.v1.endpoints import telemetry, models

api_router = APIRouter()

api_router.include_router(telemetry.router, prefix="/telemetry", tags=["telemetry"])
api_router.include_router(models.router, prefix="/models", tags=["models"])
