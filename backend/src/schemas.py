from datetime import datetime
from enum import Enum
from typing import Any, List, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)


class IngestionStatus(Enum):
    Success = "Success"
    Device_Error = "Device_Error"
    Network_Timeout = "Network_Timeout"


class ModelTask(str, Enum):
    Forecasting = "forecasting"
    AnomalyDetection = "anomaly_detection"
    Prediction = "prediction"


class TrainingDataSource(str, Enum):
    CSV = "csv"
    DB = "db"


class MLAlgorithm(str, Enum):
    RandomForest = "random_forest"
    LinearRegression = "linear_regression"
    LightGBM = "lightgbm"


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
    model_task: ModelTask | None = None
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


class ModelTrainingRequest(BaseSchema):
    model_config = ConfigDict(
        from_attributes=True,
        use_enum_values=True,
        extra="forbid",
    )

    site_id: str = Field(..., min_length=1, description="Site/building to train on.")
    metrics: list[str] = Field(..., min_length=1, description="Metrics to include.")
    time_range_start: datetime
    time_range_end: datetime
    model_task: ModelTask = ModelTask.Forecasting
    data_source: TrainingDataSource = TrainingDataSource.CSV
    csv_path: str | None = Field(
        default=None,
        description="Optional CSV path when data_source is csv.",
    )

    @field_validator("metrics")
    @classmethod
    def normalize_metrics(cls, value: list[str]) -> list[str]:
        metrics = [metric.strip().lower() for metric in value if metric.strip()]
        if not metrics:
            raise ValueError("At least one metric is required")
        return metrics

    @model_validator(mode="after")
    def validate_time_range(self) -> "ModelTrainingRequest":
        if self.time_range_end <= self.time_range_start:
            raise ValueError("time_range_end must be after time_range_start")
        return self


class ModelTrainingResponse(BaseSchema):
    message: str
    task_id: str
    model_task: ModelTask
    data_source: TrainingDataSource
    algorithm: MLAlgorithm
    site_id: str
    metrics: list[str]
    triggered_by: str


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


# Forecast
class ForecastDataPoint(BaseModel):
    timestamp: datetime
    predicted_value: float


class ForecastRequest(BaseModel):
    target_building_id: str = Field(..., description="The ID of the building/site")
    metric_type: str = Field(..., description="e.g., electricity, water")
    forecast_horizon_hours: int = Field(
        24, ge=1, le=168, description="Hours to predict"
    )


class ForecastResponse(BaseModel):
    building_id: str
    metric_type: str
    model_version_used: str
    forecast: List[ForecastDataPoint]


# Anomaly
class AlertResponse(BaseModel):
    id: int
    building_id: str
    metric_type: str
    timestamp: datetime
    severity: str
    description: str
    is_resolved: bool


class AnomalyEventResponse(BaseSchema):
    id: str
    site_id: str
    building_id: str
    primary_space_usage: str | None = None
    timestamp: datetime
    start_time: datetime
    end_time: datetime | None = None
    duration_hours: float | None = None
    severity: str
    type: str
    actual_value: float | None = None
    expected_value: float | None = None
    deviation_percent: float | None = None
    reason: str


class AnomalyEventsResponse(BaseSchema):
    total: int
    limit: int
    offset: int
    items: list[AnomalyEventResponse]


class AnomalyOverviewResponse(BaseSchema):
    total_anomalies: int
    critical_anomalies: int
    buildings_affected: int
    most_affected_site: str | None = None
    time_min: datetime | None = None
    time_max: datetime | None = None
    severity_counts: dict[str, int]
    type_counts: dict[str, int]


class AnomalyFacetsResponse(BaseSchema):
    sites: list[str]
    buildings: list[str]
    severities: list[str]
    types: list[str]


class AnomalyTimelineResponse(BaseSchema):
    items: list[AnomalyEventResponse]
