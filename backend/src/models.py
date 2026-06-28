import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Double,
    Enum,
    ForeignKey,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, declarative_base, mapped_column, relationship


class ModelBase:
    if TYPE_CHECKING:

        def __init__(self, **kwargs: object) -> None: ...


Base = declarative_base(cls=ModelBase)


def get_utc_now():
    return datetime.now(timezone.utc)


class SQLAlchemyKwargsMixin:
    if TYPE_CHECKING:

        def __init__(self, **kwargs: object) -> None: ...


class StringIDMixin(SQLAlchemyKwargsMixin):
    id: Mapped[str] = mapped_column(String, primary_key=True)


class UUIDMixin(SQLAlchemyKwargsMixin):
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=get_utc_now
    )


class UpdateTimestampMixin(TimestampMixin):
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=get_utc_now, onupdate=get_utc_now
    )


# ------
# Enums
# ------

user_role_enum = Enum("Admin", "AI_Engineer", "Operator", name="user_role")

user_status_enum = Enum(
    "Available",
    "In_Shift",
    "Busy",
    "On_Break",
    "Off_Duty",
    "On_Leave",
    "Suspended",
    name="user_status",
)

alert_severity_enum = Enum("Warning", "Critical", "Emergency", name="alert_severity")

alert_status_enum = Enum("Open", "Acknowledged", "Resolved", name="alert_status")

job_type_enum = Enum("Training", "Inference", name="job_type")

model_task_enum = Enum(
    "forecasting", "anomaly_detection", "prediction", name="model_task"
)

drift_severity_enum = Enum(
    "none", "low", "medium", "high", "critical", name="drift_severity"
)
drift_type_enum = Enum(
    "data_drift", "concept_drift", "prediction_drift", name="drift_type"
)

job_status_enum = Enum("Success", "Failed", "Running", "Cancelled", name="job_status")

ingestion_status_enum = Enum(
    "Success", "Device_Error", "Network_Timeout", name="ingestion_status"
)


# -----------------------------------------
# Lookup Tables
# -----------------------------------------
class LocationType(StringIDMixin, Base):
    __tablename__ = "location_type"
    description: Mapped[str | None] = mapped_column(String, nullable=True)


class MetricType(StringIDMixin, Base):
    __tablename__ = "metric_type"
    unit: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str | None] = mapped_column(String, nullable=True)


class DeviceType(StringIDMixin, Base):
    __tablename__ = "device_type"
    manufacturer: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str | None] = mapped_column(String, nullable=True)


class ContextType(StringIDMixin, Base):
    __tablename__ = "context_type"
    unit: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str | None] = mapped_column(String, nullable=True)


# -----------------------------------------
# Core Application Tables
# -----------------------------------------
class User(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "users"
    full_name: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(user_role_enum, nullable=False)
    status: Mapped[str] = mapped_column(
        user_status_enum, default="Off_Duty", nullable=False
    )
    contact_number: Mapped[str | None] = mapped_column(String, nullable=True)
    assigned_site_ids: Mapped[list[str]] = mapped_column(
        JSONB, default=list, nullable=False
    )
    is_global_admin: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )


class Location(StringIDMixin, Base):
    __tablename__ = "location"
    parent_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("location.id"), nullable=True
    )
    location_type_id: Mapped[str] = mapped_column(
        String, ForeignKey("location_type.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSONB, nullable=True
    )  # Using metadata_ to avoid conflict with SQLAlchemy Base.metadata

    # Relationships
    type = relationship("LocationType")
    devices = relationship("Device", back_populates="location")


class Device(StringIDMixin, Base):
    __tablename__ = "device"
    location_id: Mapped[str] = mapped_column(
        String, ForeignKey("location.id"), nullable=False
    )
    device_type_id: Mapped[str] = mapped_column(
        String, ForeignKey("device_type.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String, default="Active")
    installed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=get_utc_now
    )

    # Relationships
    location = relationship("Location", back_populates="devices")
    type = relationship("DeviceType")
    metric_capabilities = relationship(
        "DeviceMetricCapability",
        cascade="all, delete-orphan",
        back_populates="device",
    )


class DeviceMetricCapability(SQLAlchemyKwargsMixin, Base):
    __tablename__ = "device_metric_capability"
    device_id: Mapped[str] = mapped_column(
        String, ForeignKey("device.id"), nullable=False
    )
    metric_type_id: Mapped[str] = mapped_column(
        String, ForeignKey("metric_type.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=get_utc_now
    )

    __table_args__ = (PrimaryKeyConstraint("device_id", "metric_type_id"),)

    device = relationship("Device", back_populates="metric_capabilities")
    metric_type = relationship("MetricType")


# -----------------------------------------
# Configuration & Alerting
# -----------------------------------------
class ThresholdConfig(UUIDMixin, UpdateTimestampMixin, Base):
    __tablename__ = "threshold_config"
    device_id: Mapped[str] = mapped_column(
        String, ForeignKey("device.id"), nullable=False
    )
    metric_type_id: Mapped[str] = mapped_column(
        String, ForeignKey("metric_type.id"), nullable=False
    )
    baseline_value: Mapped[float | None] = mapped_column(Double, nullable=True)
    upper_limit: Mapped[float | None] = mapped_column(Double, nullable=True)
    lower_limit: Mapped[float | None] = mapped_column(Double, nullable=True)


class AnomalyAlert(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "anomaly_alert"
    device_id: Mapped[str] = mapped_column(
        String, ForeignKey("device.id"), nullable=False
    )
    metric_type_id: Mapped[str] = mapped_column(
        String, ForeignKey("metric_type.id"), nullable=False
    )
    severity: Mapped[str] = mapped_column(alert_severity_enum, nullable=False)
    message: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(alert_status_enum, default="Open")
    mlflow_run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )


# -----------------------------------------
# Time-Series (Hypertables)
# -----------------------------------------
class TelemetryData(SQLAlchemyKwargsMixin, Base):
    __tablename__ = "telemetry_data"
    # Composite Primary Key for TimescaleDB / Time-Series optimization
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True
    )
    device_id: Mapped[str] = mapped_column(
        String, ForeignKey("device.id"), primary_key=True
    )
    metric_type_id: Mapped[str] = mapped_column(
        String, ForeignKey("metric_type.id"), primary_key=True
    )

    value: Mapped[float] = mapped_column(Double, nullable=False)
    ingestion_status: Mapped[str] = mapped_column(
        ingestion_status_enum, default="Success"
    )


class ForecastResult(SQLAlchemyKwargsMixin, Base):
    __tablename__ = "forecast_result"
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True
    )
    device_id: Mapped[str] = mapped_column(
        String, ForeignKey("device.id"), primary_key=True
    )
    metric_type_id: Mapped[str] = mapped_column(
        String, ForeignKey("metric_type.id"), primary_key=True
    )

    predicted_value: Mapped[float] = mapped_column(Double, nullable=False)
    mlflow_run_id: Mapped[str] = mapped_column(String, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=get_utc_now
    )


class ContextData(SQLAlchemyKwargsMixin, Base):
    __tablename__ = "context_data"
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True
    )
    location_id: Mapped[str] = mapped_column(
        String, ForeignKey("location.id"), primary_key=True
    )
    context_type_id: Mapped[str] = mapped_column(
        String, ForeignKey("context_type.id"), primary_key=True
    )
    value: Mapped[float] = mapped_column(Double, nullable=False)


# -----------------------------------------
# System & ML Logging
# -----------------------------------------
class AIPipelineLog(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "ai_pipeline_log"
    type: Mapped[str] = mapped_column(job_type_enum, nullable=False)
    model_task: Mapped[str] = mapped_column(
        model_task_enum,
        nullable=False,
        default="forecasting",
        server_default="forecasting",
    )
    mlflow_run_id: Mapped[str] = mapped_column(String, nullable=False)
    celery_task_id: Mapped[str | None] = mapped_column(String, nullable=True)
    datasource_used: Mapped[str | None] = mapped_column(String, nullable=True)
    execution_time_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(job_status_enum, nullable=False)
    terminal_log: Mapped[str | None] = mapped_column(Text, nullable=True)


class SystemLog(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "system_log"
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    actor: Mapped[str] = mapped_column(String, nullable=False)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


class AnomalyDetectedEvent(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "anomaly_detected_event"

    building_id: Mapped[str] = mapped_column(
        String, ForeignKey("location.id"), nullable=False
    )
    site_id: Mapped[str] = mapped_column(String, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metric_type_id: Mapped[str] = mapped_column(
        String, ForeignKey("metric_type.id"), nullable=False
    )
    primary_space_usage: Mapped[str | None] = mapped_column(String, nullable=True)
    actual_value: Mapped[float | None] = mapped_column(Double, nullable=True)
    predicted_value: Mapped[float | None] = mapped_column(Double, nullable=True)
    residual: Mapped[float | None] = mapped_column(Double, nullable=True)
    residual_z: Mapped[float | None] = mapped_column(Double, nullable=True)
    anomaly_score: Mapped[float | None] = mapped_column(Double, nullable=True)
    is_anomaly: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    direction: Mapped[str | None] = mapped_column(String, nullable=True)
    severity: Mapped[str] = mapped_column(String, nullable=False, default="normal")
    source: Mapped[str] = mapped_column(String, nullable=False)  # "rule_based" / "lgbm"
    anomaly_type: Mapped[str | None] = mapped_column(String, nullable=True)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    mlflow_run_id: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "building_id",
            "timestamp",
            "metric_type_id",
            "source",
            name="uq_anomaly_detected_event",
        ),
    )


# -----------------------------------------
# Monitoring & Drift Detection
# -----------------------------------------
class PredictionLog(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "prediction_log"

    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    building_id: Mapped[str] = mapped_column(
        String, ForeignKey("location.id"), nullable=False
    )
    metric_type_id: Mapped[str] = mapped_column(
        String, ForeignKey("metric_type.id"), nullable=False
    )
    predicted_value: Mapped[float] = mapped_column(Double, nullable=False)
    actual_value: Mapped[float | None] = mapped_column(Double, nullable=True)
    error: Mapped[float | None] = mapped_column(Double, nullable=True)
    mlflow_run_id: Mapped[str] = mapped_column(String, nullable=False)
    model_name: Mapped[str] = mapped_column(String, nullable=False)
    model_version: Mapped[str] = mapped_column(String, nullable=False)
    model_task: Mapped[str] = mapped_column(model_task_enum, nullable=False)
    feature_values: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    prediction_context: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )


class ModelPerformance(UUIDMixin, Base):
    __tablename__ = "model_performance"

    model_name: Mapped[str] = mapped_column(String, nullable=False)
    model_version: Mapped[str] = mapped_column(String, nullable=False)
    mlflow_run_id: Mapped[str] = mapped_column(String, nullable=False)
    model_task: Mapped[str] = mapped_column(model_task_enum, nullable=False)
    building_id: Mapped[str | None] = mapped_column(String, nullable=True)
    metric_type_id: Mapped[str | None] = mapped_column(String, nullable=True)
    period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    period_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    mae: Mapped[float | None] = mapped_column(Double, nullable=True)
    rmse: Mapped[float | None] = mapped_column(Double, nullable=True)
    mape: Mapped[float | None] = mapped_column(Double, nullable=True)
    r2_score: Mapped[float | None] = mapped_column(Double, nullable=True)
    mean_error: Mapped[float | None] = mapped_column(Double, nullable=True)
    p10_error: Mapped[float | None] = mapped_column(Double, nullable=True)
    p90_error: Mapped[float | None] = mapped_column(Double, nullable=True)
    baseline_mae: Mapped[float | None] = mapped_column(Double, nullable=True)
    baseline_rmse: Mapped[float | None] = mapped_column(Double, nullable=True)
    performance_ratio: Mapped[float | None] = mapped_column(Double, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=get_utc_now
    )


class DriftReport(UUIDMixin, Base):
    __tablename__ = "drift_report"

    model_name: Mapped[str] = mapped_column(String, nullable=False)
    model_version: Mapped[str] = mapped_column(String, nullable=False)
    mlflow_run_id: Mapped[str] = mapped_column(String, nullable=False)
    model_task: Mapped[str] = mapped_column(model_task_enum, nullable=False)
    drift_type: Mapped[str] = mapped_column(drift_type_enum, nullable=False)
    feature_name: Mapped[str | None] = mapped_column(String, nullable=True)
    period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    period_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    drift_score: Mapped[float] = mapped_column(Double, nullable=False)
    drift_threshold: Mapped[float] = mapped_column(Double, nullable=False)
    is_drifted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    severity: Mapped[str] = mapped_column(drift_severity_enum, nullable=False)
    reference_stats: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    current_stats: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=get_utc_now
    )
