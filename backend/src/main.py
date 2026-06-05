from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from src.api.v1.router import api_router
from src.core.config import settings
from src.core.logging import setup_logging
from src.core.exceptions import DMPException

setup_logging()

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Forecasting, Anomaly Detection for Smart City",
    version="1.0.0",
)

# Set up CORS
if settings.BACKEND_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin) for origin in settings.BACKEND_CORS_ORIGINS],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


# Exception Handler
@app.exception_handler(DMPException)
async def dmp_exception_handler(request: Request, exc: DMPException):
    logger.error(f"DMP Error: {exc.message} | Code: {exc.code}")
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "message": exc.message,
                "code": exc.code,
                "details": exc.details,
            }
        },
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled Exception occurred")
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "message": "An unexpected error occurred. Please contact the administrator.",
                "code": "INTERNAL_SERVER_ERROR",
            }
        },
    )


# Include Routers
app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/health")
def health_check():
    """Satisfies the Docker Compose healthcheck"""
    return {"status": "healthy", "service": "dmp-backend"}


@app.get("/")
def root():
    return {
        "message": f"{settings.PROJECT_NAME} is running.",
        "docs": "/docs",
        "redoc": "/redoc",
    }
