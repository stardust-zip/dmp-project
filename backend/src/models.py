import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import (
    Column,
    DateTime,
    Double,
    Enum,
    ForeignKey,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import declarative_base, relationship


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
    id = Column(String, primary_key=True)


class UUIDMixin(SQLAlchemyKwargsMixin):
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at = Column(DateTime(timezone=True), default=get_utc_now)


class UpdateTimestampMixin(TimestampMixin):
    updated_at = Column(
        DateTime(timezone=True), default=get_utc_now, onupdate=get_utc_now
    )


# ------
# Enums
# ------

user_role_enum = Enum(
    "Admin", "AI_Engineer", "Operator", "PO", "Developer", name="user_role"
)

alert_severity_enum = Enum("Warning", "Critical", "Emergency", name="alert_severity")

alert_status_enum = Enum("Open", "Acknowledged", "Resolved", name="alert_status")

job_type_enum = Enum("Training", "Inference", name="job_type")

model_task_enum = Enum(
    "forecasting", "anomaly_detection", "prediction", name="model_task"
)

job_status_enum = Enum("Success", "Failed", "Running", name="job_status")

ingestion_status_enum = Enum(
    "Success", "Device_Error", "Network_Timeout", name="ingestion_status"
)


# -----------------------------------------
# Lookup Tables
# -----------------------------------------
class LocationType(StringIDMixin, Base):
    __tablename__ = "location_type"
    description = Column(String, nullable=True)


class MetricType(StringIDMixin, Base):
    __tablename__ = "metric_type"
    unit = Column(String, nullable=True)
    description = Column(String, nullable=True)


class DeviceType(StringIDMixin, Base):
    __tablename__ = "device_type"
    manufacturer = Column(String, nullable=True)
    description = Column(String, nullable=True)


class ContextType(StringIDMixin, Base):
    __tablename__ = "context_type"
    unit = Column(String, nullable=True)
    description = Column(String, nullable=True)


# -----------------------------------------
# Core Application Tables
# -----------------------------------------
class User(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "users"
    full_name = Column(String, nullable=False)
    email = Column(String, nullable=False, unique=True)
    password_hash = Column(String, nullable=False)
    role = Column(user_role_enum, nullable=False)


class Location(StringIDMixin, Base):
    __tablename__ = "location"
    parent_id = Column(String, ForeignKey("location.id"), nullable=True)
    location_type_id = Column(String, ForeignKey("location_type.id"), nullable=False)
    name = Column(String, nullable=False)
    metadata_ = Column(
        "metadata", JSONB, nullable=True
    )  # Using metadata_ to avoid conflict with SQLAlchemy Base.metadata

    # Relationships
    type = relationship("LocationType")
    devices = relationship("Device", back_populates="location")


class Device(StringIDMixin, Base):
    __tablename__ = "device"
    location_id = Column(String, ForeignKey("location.id"), nullable=False)
    device_type_id = Column(String, ForeignKey("device_type.id"), nullable=False)
    status = Column(String, default="Active")
    installed_at = Column(DateTime(timezone=True), default=get_utc_now)

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
    device_id = Column(String, ForeignKey("device.id"), nullable=False)
    metric_type_id = Column(String, ForeignKey("metric_type.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=get_utc_now)

    __table_args__ = (PrimaryKeyConstraint("device_id", "metric_type_id"),)

    device = relationship("Device", back_populates="metric_capabilities")
    metric_type = relationship("MetricType")


# -----------------------------------------
# Configuration & Alerting
# -----------------------------------------
class ThresholdConfig(UUIDMixin, UpdateTimestampMixin, Base):
    __tablename__ = "threshold_config"
    device_id = Column(String, ForeignKey("device.id"), nullable=False)
    metric_type_id = Column(String, ForeignKey("metric_type.id"), nullable=False)
    baseline_value = Column(Double, nullable=True)
    upper_limit = Column(Double, nullable=True)
    lower_limit = Column(Double, nullable=True)


class AnomalyAlert(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "anomaly_alert"
    device_id = Column(String, ForeignKey("device.id"), nullable=False)
    metric_type_id = Column(String, ForeignKey("metric_type.id"), nullable=False)
    severity = Column(alert_severity_enum, nullable=False)
    message = Column(String, nullable=False)
    status = Column(alert_status_enum, default="Open")
    mlflow_run_id = Column(String, nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolved_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)


# -----------------------------------------
# Time-Series (Hypertables)
# -----------------------------------------
class TelemetryData(SQLAlchemyKwargsMixin, Base):
    __tablename__ = "telemetry_data"
    # Composite Primary Key for TimescaleDB / Time-Series optimization
    timestamp = Column(DateTime(timezone=True), primary_key=True)
    device_id = Column(String, ForeignKey("device.id"), primary_key=True)
    metric_type_id = Column(String, ForeignKey("metric_type.id"), primary_key=True)

    value = Column(Double, nullable=False)
    ingestion_status = Column(ingestion_status_enum, default="Success")


class ForecastResult(SQLAlchemyKwargsMixin, Base):
    __tablename__ = "forecast_result"
    timestamp = Column(DateTime(timezone=True), primary_key=True)
    device_id = Column(String, ForeignKey("device.id"), primary_key=True)
    metric_type_id = Column(String, ForeignKey("metric_type.id"), primary_key=True)

    predicted_value = Column(Double, nullable=False)
    mlflow_run_id = Column(String, nullable=False)
    generated_at = Column(DateTime(timezone=True), default=get_utc_now)


class ContextData(SQLAlchemyKwargsMixin, Base):
    __tablename__ = "context_data"
    timestamp = Column(DateTime(timezone=True), primary_key=True)
    location_id = Column(String, ForeignKey("location.id"), primary_key=True)
    context_type_id = Column(String, ForeignKey("context_type.id"), primary_key=True)
    value = Column(Double, nullable=False)


# -----------------------------------------
# System & ML Logging
# -----------------------------------------
class AIPipelineLog(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "ai_pipeline_log"
    type = Column(job_type_enum, nullable=False)
    model_task = Column(
        model_task_enum,
        nullable=False,
        default="forecasting",
        server_default="forecasting",
    )
    mlflow_run_id = Column(String, nullable=False)
    datasource_used = Column(String, nullable=True)
    execution_time_ms = Column(Integer, nullable=False)
    status = Column(job_status_enum, nullable=False)
    terminal_log = Column(Text, nullable=True)


class SystemLog(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "system_log"
    event_type = Column(String, nullable=False)
    actor = Column(String, nullable=False)
    details = Column(JSONB, nullable=True)
