from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class IngestionStatus(Enum):
    Success = "Success"
    Device_Error = "Device_Error"
    Network_Timeout = "Network_Timeout"


class BaseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


# Auth Schemas


class Token(BaseSchema):
    access_token: str
    token_type: str


class TokenPayload(BaseSchema):
    sub: Optional[str] = None
    role: Optional[str] = None


class UserResponse(BaseSchema):
    id: str
    email: EmailStr
    full_name: str
    role: str


class ModelVersionResponse(BaseSchema):
    name: str
    version: str
    run_id: str
    metrics: dict[str, float]
    tags: dict[str, str] = Field(default_factory=dict)
    current_stage: str | None = None
    creation_timestamp: int | None = None
    last_updated_timestamp: int | None = None


class ModelVersionsResponse(BaseSchema):
    model_name: str
    versions: list[ModelVersionResponse]


class ModelRollbackRequest(BaseSchema):
    mlflow_run_id: str = Field(..., min_length=1)
    model_name: str | None = Field(
        default=None,
        description="Optional registered model name to disambiguate duplicate run IDs.",
    )


class ModelRollbackResponse(BaseSchema):
    message: str
    model_name: str
    version: str
    run_id: str
    promoted_by: str


# -----------------------------------------
# Payloads for Seeding Asset Data (from metadata.csv)
# -----------------------------------------


class LocationCreate(BaseSchema):
    """Payload for creating a new building/location."""

    id: str = Field(
        ..., description="Unique building ID (e.g., 'Panther_lodging_Cora')"
    )
    location_type_id: str = Field(..., description="E.g., 'education', 'lodging'")
    name: str
    metadata: Optional[dict[str, Any]] = Field(
        default=None,
        description="To store extra Kaggle data like sqm, yearbuilt, timezone",
    )


class DeviceCreate(BaseSchema):
    """Payload for registering a new virtual sensor/meter for a building."""

    id: str = Field(
        ...,
        description="Unique device ID (e.g., 'meter_electricity_Panther_lodging_Cora')",
    )
    location_id: str = Field(..., description="Must match a Location ID")
    device_type_id: str = Field(default="virtual_meter")
    status: str = Field(default="Active")


# -----------------------------------------
# Payload for Seeding Time-Series Data (from telemetry CSVs)
# -----------------------------------------


class TelemetryDataPayload(BaseSchema):
    """Payload for ingesting sensor readings."""

    timestamp: datetime
    device_id: str = Field(..., min_length=1)
    metric_type_id: str = Field(
        ...,
        description="electricity, chilledwater, steam, hotwater, gas, water, solar, irrigation",
    )
    value: Optional[float] = Field(None, ge=0.0)
    # Replaced quality with ingestion_status
    ingestion_status: IngestionStatus = Field(default=IngestionStatus.Success)

    @field_validator("timestamp")
    @classmethod
    def enforce_utc_timezone(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("Timestamp must be timezone-aware (ISO 8601).")
        from datetime import timezone

        return v.astimezone(timezone.utc)


# Consumptions


class ConsumptionRecord(BaseSchema):
    timestamp: datetime
    device_id: str
    metric_type_id: str
    actual_value: float
    ingestion_status: str


class ConsumptionPaginatedResponse(BaseSchema):
    limit: int
    offset: int
    consumption: list[ConsumptionRecord]
