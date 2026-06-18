from datetime import datetime
from enum import Enum
from typing import Any, List, Optional

from pydantic import (
    AliasChoices,
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
    XGBoost = "xgboost"


class BaseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


# Auth Schemas


class Token(BaseSchema):
    access_token: str
    token_type: str


class TokenPayload(BaseSchema):
    sub: Optional[str] = None
    role: Optional[str] = None


class UserRole(str, Enum):
    Admin = "Admin"
    AIEngineer = "AI_Engineer"
    Operator = "Operator"


class UserStatus(str, Enum):
    Available = "Available"
    InShift = "In_Shift"
    Busy = "Busy"
    OnBreak = "On_Break"
    OffDuty = "Off_Duty"
    OnLeave = "On_Leave"
    Suspended = "Suspended"


class UserCreate(BaseSchema):
    email: EmailStr
    full_name: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)
    role: UserRole
    status: UserStatus = UserStatus.OffDuty
    contact_number: str | None = Field(default=None, min_length=1)
    assigned_site_ids: list[str] = Field(default_factory=list)
    is_global_admin: bool = False

    @field_validator("assigned_site_ids")
    @classmethod
    def normalize_assigned_site_ids(cls, value: list[str]) -> list[str]:
        normalized = [site_id.strip() for site_id in value if site_id.strip()]
        return sorted(set(normalized))

    @model_validator(mode="after")
    def validate_access_scope(self) -> "UserCreate":
        if self.role != UserRole.Admin and self.is_global_admin:
            raise ValueError("Only Admin users can be global admins")
        if self.role in {UserRole.Admin, UserRole.Operator} and not self.is_global_admin and not self.assigned_site_ids:
            raise ValueError("Assigned sites are required for scoped Admin and Operator users")
        if self.role == UserRole.AIEngineer:
            self.assigned_site_ids = []
            self.is_global_admin = False
        return self


class UserRoleUpdate(BaseSchema):
    full_name: str | None = Field(default=None, min_length=1)
    email: EmailStr | None = None
    role: UserRole | None = None
    status: UserStatus | None = None
    contact_number: str | None = Field(default=None, min_length=1)
    assigned_site_ids: list[str] | None = None
    is_global_admin: bool | None = None

    @field_validator("assigned_site_ids")
    @classmethod
    def normalize_assigned_site_ids(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized = [site_id.strip() for site_id in value if site_id.strip()]
        return sorted(set(normalized))


class UserResponse(BaseSchema):
    id: str
    email: EmailStr
    full_name: str
    role: str
    status: str = UserStatus.OffDuty.value
    contact_number: str | None = None
    assigned_site_ids: list[str] = Field(default_factory=list)
    is_global_admin: bool = False


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

    site_id: str | None = Field(
        default=None,
        min_length=1,
        description="Site to train on. Required for prediction/forecasting; omit for anomaly_detection (trains across all buildings).",
    )
    building_id: str | None = Field(
        default=None,
        min_length=1,
        description="Optional building to train on inside the selected site.",
    )
    metrics: list[str] = Field(..., min_length=1, description="Metrics to include.")
    time_range_start: datetime
    time_range_end: datetime
    model_task: ModelTask = ModelTask.Prediction
    data_source: TrainingDataSource = TrainingDataSource.CSV
    csv_path: str | None = Field(
        default=None,
        description="Optional CSV path when data_source is csv.",
    )
    algorithm: Optional[MLAlgorithm] = Field(
        default=None,
        description="Forecasting: algorithm to train (linear_regression/xgboost/lightgbm). "
        "Ignored by other tasks. Defaults to xgboost when omitted.",
    )
    forecast_horizon_hours: int = Field(
        default=24,
        ge=1,
        le=168,
        description="Forecasting: direct forecast horizon in hours. "
        "A forecasting model is horizon-specific; this value is logged to MLflow.",
    )
    weather_mode: str = Field(
        default="none",
        description="Forecasting: weather feature mode. MVP supports 'none' only.",
    )

    @field_validator("metrics")
    @classmethod
    def normalize_metrics(cls, value: list[str]) -> list[str]:
        metrics = [metric.strip().lower() for metric in value if metric.strip()]
        if not metrics:
            raise ValueError("At least one metric is required")
        return metrics

    @model_validator(mode="after")
    def site_id_required_for_non_anomaly(self) -> "ModelTrainingRequest":
        if ModelTask(self.model_task) != ModelTask.AnomalyDetection and not self.site_id:
            raise ValueError("site_id is required for prediction and forecasting tasks")
        return self

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
    site_id: str | None
    building_id: str | None = None
    metrics: list[str]
    triggered_by: str


class ModelTrainingValidationMetric(BaseSchema):
    metric: str
    known_metric: bool
    db_rows: int = 0
    csv_rows: int = 0
    available_in_db: bool = False
    available_in_csv: bool = False
    enough_rows: bool = False
    required_rows: int
    messages: list[str] = Field(default_factory=list)


class ModelTrainingValidationResponse(BaseSchema):
    valid: bool
    data_source: TrainingDataSource
    site_id: str | None
    building_id: str | None = None
    target_building_ids: list[str] = Field(default_factory=list)
    required_rows_per_metric: int
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    metrics: list[ModelTrainingValidationMetric] = Field(default_factory=list)


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


class SiteCreate(BaseSchema):
    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    metadata: dict[str, Any] | None = None


class BuildingCreate(BaseSchema):
    id: str = Field(..., min_length=1)
    site_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    location_type_id: str = Field(default="building", min_length=1)
    metadata: dict[str, Any] | None = None


class LocationUpdate(BaseSchema):
    name: str | None = Field(default=None, min_length=1)
    parent_id: str | None = Field(default=None, min_length=1)
    location_type_id: str | None = Field(default=None, min_length=1)
    metadata: dict[str, Any] | None = None
    archived: bool | None = None


class LocationResponse(BaseSchema):
    id: str
    parent_id: str | None = None
    name: str
    location_type: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    archived: bool = False


class MetricTypeCreate(BaseSchema):
    id: str = Field(..., min_length=1)
    unit: str | None = None
    description: str | None = None


class MetricTypeUpdate(BaseSchema):
    unit: str | None = None
    description: str | None = None


class MetricTypeResponse(BaseSchema):
    id: str
    unit: str | None = None
    description: str | None = None


class DeviceCreate(BaseSchema):
    """Payload for registering a new virtual sensor/meter for a building."""

    id: str = Field(
        ...,
        description="Unique device ID (e.g., 'meter_electricity_Panther_lodging_Cora')",
    )
    location_id: str = Field(..., description="Must match a Location ID")
    device_type_id: str = Field(default="virtual_meter")
    status: str = Field(default="Active")


class DeviceRegisterRequest(BaseSchema):
    id: str = Field(..., min_length=1)
    building_id: str = Field(..., min_length=1)
    device_type_id: str = Field(default="virtual_meter", min_length=1)
    status: str = Field(default="Active", min_length=1)
    metric_type_ids: list[str] = Field(default_factory=list)


class DeviceUpdate(BaseSchema):
    building_id: str | None = Field(default=None, min_length=1)
    device_type_id: str | None = Field(default=None, min_length=1)
    status: str | None = Field(default=None, min_length=1)
    metric_type_ids: list[str] | None = None


class DeviceResponse(BaseSchema):
    id: str
    building_id: str
    device_type_id: str
    status: str
    metric_type_ids: list[str] = Field(default_factory=list)


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


class ForecastGenerateRequest(BaseSchema):
    """Operator request: forecast the FUTURE for one building.

    ``input_start``/``input_end`` bound a window of *actual* telemetry (>= 168h,
    needed for lag/rolling-168h features). ``forecast_hours`` is how many hours
    of the future (after ``input_end``) to predict.
    """

    building_id: str = Field(..., min_length=1)
    metric_type: str = Field("electricity", min_length=1)
    input_start: datetime
    input_end: datetime
    forecast_hours: int = Field(24, ge=1, le=168)


class ForecastVsActualPoint(BaseModel):
    """One timestamp on the merged actual-vs-forecast timeline.

    Either side may be null: the recent-past tail has only ``actual`` before the
    overlay starts, the far future has only ``forecast``.
    """

    timestamp: datetime
    actual: Optional[float] = None
    forecast: Optional[float] = None


class ForecastVsActualResponse(BaseSchema):
    building_id: str
    site_id: Optional[str] = None
    metric_type: str
    horizon_hours: int
    model_run_id: str
    input_start: datetime
    input_end: datetime
    forecast_hours: int
    divider_timestamp: datetime
    points: List[ForecastVsActualPoint]


# Prediction
class PredictionScenarioRequest(BaseSchema):
    site_id: str = Field(..., min_length=1)
    building_id: str = Field(..., min_length=1)
    metric_type: str = Field(default="electricity", min_length=1)
    scenario_date: datetime
    opening_time: str = Field(default="06:00", pattern=r"^\d{2}:\d{2}$")
    closing_time: str = Field(default="18:00", pattern=r"^\d{2}:\d{2}$")
    unit_rate: float | None = Field(
        default=None,
        ge=0.0,
        validation_alias=AliasChoices("unit_rate", "energy_rate_per_kwh"),
        description="Optional cost per response unit, e.g. dollars per kWh or per m3.",
    )
    model_name: str | None = Field(default=None, min_length=1)


class PredictionHourlyPoint(BaseSchema):
    timestamp: datetime
    expected_value: float


class PredictionScenarioResponse(BaseSchema):
    site_id: str
    building_id: str
    metric_type: str
    model_name: str
    model_version: str
    estimated_value: float
    estimated_cost: float | None = None
    unit: str
    points: list[PredictionHourlyPoint]


class ExpectedActualReportRequest(BaseSchema):
    site_id: str = Field(..., min_length=1)
    building_id: str = Field(..., min_length=1)
    metric_type: str = Field(default="electricity", min_length=1)
    start_time: datetime
    end_time: datetime
    opening_time: str = Field(default="06:00", pattern=r"^\d{2}:\d{2}$")
    closing_time: str = Field(default="18:00", pattern=r"^\d{2}:\d{2}$")
    model_name: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_report_range(self) -> "ExpectedActualReportRequest":
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        return self


class ExpectedActualPoint(BaseSchema):
    timestamp: datetime
    expected_value: float
    actual_value: float | None = None
    variance: float | None = None
    variance_percent: float | None = None


class ExpectedActualReportResponse(BaseSchema):
    site_id: str
    building_id: str
    metric_type: str
    model_name: str
    model_version: str
    expected_total: float
    actual_total: float | None = None
    variance_total: float | None = None
    variance_percent: float | None = None
    unit: str
    points: list[ExpectedActualPoint]


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
    primary_usage_types: list[str]


class AnomalyTimelinePointResponse(BaseSchema):
    timestamp: datetime
    actual_value: float | None = None
    expected_value: float | None = None


class AnomalyTimelineGapResponse(BaseSchema):
    start_time: datetime
    end_time: datetime
    reason: str = "Missing actual data"


class AnomalyTimelineResponse(BaseSchema):
    items: list[AnomalyEventResponse]
    points: list[AnomalyTimelinePointResponse] = Field(default_factory=list)
    gaps: list[AnomalyTimelineGapResponse] = Field(default_factory=list)
