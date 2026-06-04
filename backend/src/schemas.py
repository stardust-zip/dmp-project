from datetime import datetime
from typing import Optional, Any
from pydantic import BaseModel, Field, ConfigDict, field_validator
from enum import Enum


class QualityFlag(str, Enum):
    Good = "Good"
    Suspect = "Suspect"
    Bad = "Bad"
    Missing = "Missing"


class BaseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


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
        description="eletricity, chilledwater, steam, hotwater, gas, water, solar, irrigation",
    )
    value: Optional[float] = Field(None, ge=0.0)
    quality: QualityFlag = Field(default=QualityFlag.Good)

    @field_validator("timestamp")
    @classmethod
    def enforce_utc_timezone(cls, v: datetime) -> datetime:
        """Ensures the seeder localized the naive CSV timestamp before validation."""
        if v.tzinfo is None:
            raise ValueError("Timestamp must be timezone-aware (ISO 8601).")
        from datetime import timezone

        return v.astimezone(timezone.utc)
