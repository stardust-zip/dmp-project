"""Initial application schema.

Revision ID: 20260611_0001
Revises:
Create Date: 2026-06-11 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260611_0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

user_role = sa.Enum("Admin", "AI_Engineer", "Operator", name="user_role")
user_status = sa.Enum(
    "Available",
    "In_Shift",
    "Busy",
    "On_Break",
    "Off_Duty",
    "On_Leave",
    "Suspended",
    name="user_status",
)
alert_severity = sa.Enum("Warning", "Critical", "Emergency", name="alert_severity")
alert_status = sa.Enum("Open", "Acknowledged", "Resolved", name="alert_status")
job_type = sa.Enum("Training", "Inference", name="job_type")
model_task = sa.Enum(
    "forecasting",
    "anomaly_detection",
    "prediction",
    name="model_task",
)
job_status = sa.Enum("Success", "Failed", "Running", name="job_status")
ingestion_status = sa.Enum(
    "Success",
    "Device_Error",
    "Network_Timeout",
    name="ingestion_status",
)


def upgrade() -> None:
    op.create_table(
        "context_type",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("unit", sa.String(), nullable=True),
        sa.Column("description", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "device_type",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("manufacturer", sa.String(), nullable=True),
        sa.Column("description", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "location_type",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "metric_type",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("unit", sa.String(), nullable=True),
        sa.Column("description", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "system_log",
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("actor", sa.String(), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "users",
        sa.Column("full_name", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("role", user_role, nullable=False),
        sa.Column("status", user_status, nullable=False),
        sa.Column("contact_number", sa.String(), nullable=True),
        sa.Column(
            "assigned_site_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("is_global_admin", sa.Boolean(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_table(
        "ai_pipeline_log",
        sa.Column("type", job_type, nullable=False),
        sa.Column(
            "model_task",
            model_task,
            server_default="forecasting",
            nullable=False,
        ),
        sa.Column("mlflow_run_id", sa.String(), nullable=False),
        sa.Column("datasource_used", sa.String(), nullable=True),
        sa.Column("execution_time_ms", sa.Integer(), nullable=False),
        sa.Column("status", job_status, nullable=False),
        sa.Column("terminal_log", sa.Text(), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "location",
        sa.Column("parent_id", sa.String(), nullable=True),
        sa.Column("location_type_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("id", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["location_type_id"], ["location_type.id"]),
        sa.ForeignKeyConstraint(["parent_id"], ["location.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "context_data",
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("location_id", sa.String(), nullable=False),
        sa.Column("context_type_id", sa.String(), nullable=False),
        sa.Column("value", sa.Double(), nullable=False),
        sa.ForeignKeyConstraint(["context_type_id"], ["context_type.id"]),
        sa.ForeignKeyConstraint(["location_id"], ["location.id"]),
        sa.PrimaryKeyConstraint("timestamp", "location_id", "context_type_id"),
    )
    op.create_table(
        "device",
        sa.Column("location_id", sa.String(), nullable=False),
        sa.Column("device_type_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("installed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["device_type_id"], ["device_type.id"]),
        sa.ForeignKeyConstraint(["location_id"], ["location.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "anomaly_alert",
        sa.Column("device_id", sa.String(), nullable=False),
        sa.Column("metric_type_id", sa.String(), nullable=False),
        sa.Column("severity", alert_severity, nullable=False),
        sa.Column("message", sa.String(), nullable=False),
        sa.Column("status", alert_status, nullable=False),
        sa.Column("mlflow_run_id", sa.String(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["device.id"]),
        sa.ForeignKeyConstraint(["metric_type_id"], ["metric_type.id"]),
        sa.ForeignKeyConstraint(["resolved_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "device_metric_capability",
        sa.Column("device_id", sa.String(), nullable=False),
        sa.Column("metric_type_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["device.id"]),
        sa.ForeignKeyConstraint(["metric_type_id"], ["metric_type.id"]),
        sa.PrimaryKeyConstraint("device_id", "metric_type_id"),
    )
    op.create_table(
        "forecast_result",
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("device_id", sa.String(), nullable=False),
        sa.Column("metric_type_id", sa.String(), nullable=False),
        sa.Column("predicted_value", sa.Double(), nullable=False),
        sa.Column("mlflow_run_id", sa.String(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["device.id"]),
        sa.ForeignKeyConstraint(["metric_type_id"], ["metric_type.id"]),
        sa.PrimaryKeyConstraint("timestamp", "device_id", "metric_type_id"),
    )
    op.create_table(
        "telemetry_data",
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("device_id", sa.String(), nullable=False),
        sa.Column("metric_type_id", sa.String(), nullable=False),
        sa.Column("value", sa.Double(), nullable=False),
        sa.Column("ingestion_status", ingestion_status, nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["device.id"]),
        sa.ForeignKeyConstraint(["metric_type_id"], ["metric_type.id"]),
        sa.PrimaryKeyConstraint("timestamp", "device_id", "metric_type_id"),
    )
    op.create_table(
        "threshold_config",
        sa.Column("device_id", sa.String(), nullable=False),
        sa.Column("metric_type_id", sa.String(), nullable=False),
        sa.Column("baseline_value", sa.Double(), nullable=True),
        sa.Column("upper_limit", sa.Double(), nullable=True),
        sa.Column("lower_limit", sa.Double(), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["device.id"]),
        sa.ForeignKeyConstraint(["metric_type_id"], ["metric_type.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("threshold_config")
    op.drop_table("telemetry_data")
    op.drop_table("forecast_result")
    op.drop_table("device_metric_capability")
    op.drop_table("anomaly_alert")
    op.drop_table("device")
    op.drop_table("context_data")
    op.drop_table("location")
    op.drop_table("ai_pipeline_log")
    op.drop_table("users")
    op.drop_table("system_log")
    op.drop_table("metric_type")
    op.drop_table("location_type")
    op.drop_table("device_type")
    op.drop_table("context_type")

    for enum_name in (
        "ingestion_status",
        "job_status",
        "model_task",
        "job_type",
        "alert_status",
        "alert_severity",
        "user_status",
        "user_role",
    ):
        op.execute(sa.text(f"DROP TYPE IF EXISTS {enum_name}"))
