from fastapi import APIRouter
from src.api.v1.endpoints import (
    alerts,
    anomalies,
    auth,
    consumption,
    export,
    forecast,
    metadata,
    models,
    monitoring,
    prediction,
    system,
    telemetry,
    users,
)

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])

api_router.include_router(telemetry.router, prefix="/telemetry", tags=["telemetry"])
api_router.include_router(models.router, prefix="/models", tags=["models"])
api_router.include_router(alerts.router, prefix="/alerts", tags=["alerts"])
api_router.include_router(anomalies.router, prefix="/anomalies", tags=["anomalies"])
api_router.include_router(forecast.router, prefix="/forecast", tags=["forecast"])
api_router.include_router(prediction.router, prefix="/prediction", tags=["prediction"])
api_router.include_router(
    consumption.router, prefix="/consumption", tags=["consumption"]
)
api_router.include_router(export.router, prefix="/export", tags=["export"])
api_router.include_router(metadata.router, prefix="/metadata", tags=["metadata"])
api_router.include_router(monitoring.router, prefix="/models", tags=["monitoring"])
api_router.include_router(system.router, tags=["system"])
