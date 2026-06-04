import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    String,
    DateTime,
    ForeignKey,
    Enum,
    Integer,
    Double,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def get_utc_now():
    return datetime.now(timezone.utc)


# ------
# Enums
# ------

user_role_enum = Enum(
    "Admin", "AI_Engineer", "Operator", "PO", "Developer", name="user_role"
)

alert_severity_enum = Enum("Warning", "Critical", "Emergency", name="alert_severity")

alert_status_enum = Enum("Open", "Acknowledged", "Resolved", name="alert_status")

job_type_enum = Enum("Training", "Inference", name="job_type")

job_status_enum = Enum("Success", "Failed", "Running", name="job_status")

ingestion_status_enum = Enum(
    "Success", "Device_Error", "Network_Timeout", name="ingestion_status"
)


# -----------------------------------------
# Lookup Tables
# -----------------------------------------
class LocationType(Base):
    __tablename__ = "location_type"
    id = Column(String, primary_key=True)
    description = Column(String, nullable=True)


class MetricType(Base):
    __tablename__ = "metric_type"
    id = Column(String, primary_key=True)
    unit = Column(String, nullable=True)
    description = Column(String, nullable=True)


class DeviceType(Base):
    __tablename__ = "device_type"
    id = Column(String, primary_key=True)
    manufacturer = Column(String, nullable=True)
    description = Column(String, nullable=True)


class ContextType(Base):
    __tablename__ = "context_type"
    id = Column(String, primary_key=True)
    unit = Column(String, nullable=True)
    description = Column(String, nullable=True)


# -----------------------------------------
# Core Application Tables
# -----------------------------------------
class User(Base):
    __tablename__ = "users"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    full_name = Column(String, nullable=False)
    email = Column(String, nullable=False, unique=True)
    password_hash = Column(String, nullable=False)
    role = Column(user_role_enum, nullable=False)
    created_at = Column(DateTime(timezone=True), default=get_utc_now)


class Location(Base):
    __tablename__ = "location"
    id = Column(String, primary_key=True)
    parent_id = Column(String, ForeignKey("location.id"), nullable=True)
    location_type_id = Column(String, ForeignKey("location_type.id"), nullable=False)
    name = Column(String, nullable=False)
    metadata_ = Column(
        "metadata", JSONB, nullable=True
    )  # Using metadata_ to avoid conflict with SQLAlchemy Base.metadata

    # Relationships
    type = relationship("LocationType")
    devices = relationship("Device", back_populates="location")


class Device(Base):
    __tablename__ = "device"
    id = Column(String, primary_key=True)
    location_id = Column(String, ForeignKey("location.id"), nullable=False)
    device_type_id = Column(String, ForeignKey("device_type.id"), nullable=False)
    status = Column(String, default="Active")
    installed_at = Column(DateTime(timezone=True), default=get_utc_now)

    # Relationships
    location = relationship("Location", back_populates="devices")
    type = relationship("DeviceType")


# -----------------------------------------
# Configuration & Alerting
# -----------------------------------------
class ThresholdConfig(Base):
    __tablename__ = "threshold_config"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id = Column(String, ForeignKey("device.id"), nullable=False)
    metric_type_id = Column(String, ForeignKey("metric_type.id"), nullable=False)
    baseline_value = Column(Double, nullable=True)
    upper_limit = Column(Double, nullable=True)
    lower_limit = Column(Double, nullable=True)
    updated_at = Column(
        DateTime(timezone=True), default=get_utc_now, onupdate=get_utc_now
    )


class AnomalyAlert(Base):
    __tablename__ = "anomaly_alert"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id = Column(String, ForeignKey("device.id"), nullable=False)
    metric_type_id = Column(String, ForeignKey("metric_type.id"), nullable=False)
    severity = Column(alert_severity_enum, nullable=False)
    message = Column(String, nullable=False)
    status = Column(alert_status_enum, default="Open")
    mlflow_run_id = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=get_utc_now)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolved_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)


# -----------------------------------------
# Time-Series (Hypertables)
# -----------------------------------------
class TelemetryData(Base):
    __tablename__ = "telemetry_data"
    # Composite Primary Key for TimescaleDB / Time-Series optimization
    timestamp = Column(DateTime(timezone=True), primary_key=True)
    device_id = Column(String, ForeignKey("device.id"), primary_key=True)
    metric_type_id = Column(String, ForeignKey("metric_type.id"), primary_key=True)

    value = Column(Double, nullable=False)
    ingestion_status = Column(ingestion_status_enum, default="Success")


class ForecastResult(Base):
    __tablename__ = "forecast_result"
    timestamp = Column(DateTime(timezone=True), primary_key=True)
    device_id = Column(String, ForeignKey("device.id"), primary_key=True)
    metric_type_id = Column(String, ForeignKey("metric_type.id"), primary_key=True)

    predicted_value = Column(Double, nullable=False)
    mlflow_run_id = Column(String, nullable=False)
    generated_at = Column(DateTime(timezone=True), default=get_utc_now)


class ContextData(Base):
    __tablename__ = "context_data"
    timestamp = Column(DateTime(timezone=True), primary_key=True)
    location_id = Column(String, ForeignKey("location.id"), primary_key=True)
    context_type_id = Column(String, ForeignKey("context_type.id"), primary_key=True)
    value = Column(Double, nullable=False)


# -----------------------------------------
# System & ML Logging
# -----------------------------------------
class AIPipelineLog(Base):
    __tablename__ = "ai_pipeline_log"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    type = Column(job_type_enum, nullable=False)
    mlflow_run_id = Column(String, nullable=False)
    datasource_used = Column(String, nullable=True)
    execution_time_ms = Column(Integer, nullable=False)
    status = Column(job_status_enum, nullable=False)
    created_at = Column(DateTime(timezone=True), default=get_utc_now)


class SystemLog(Base):
    __tablename__ = "system_log"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_type = Column(String, nullable=False)
    actor = Column(String, nullable=False)
    details = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), default=get_utc_now)
