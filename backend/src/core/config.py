from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "DMP Smart City AI Platform"
    API_V1_STR: str = "/api/v1"

    # Core Connections
    DATABASE_URL: str = "postgresql://dmp_user:dmp_password@localhost:5432/dmp_db"
    REDIS_URL: str = "redis://localhost:6379/0"
    MLFLOW_TRACKING_URI: str = "http://mlflow:5000"
    DATA_DIR: str = "/app/data/raw/data"

    # Security
    BACKEND_CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:3001",
    ]
    SECRET_KEY: str = "demo_super_secret_key_very_secret_key"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 10080  # 7 days in minutes
    ANOMALY_DATA_DIR: str = "data/processed/anomaly-detection"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
