"""
Infrastructure tests: database schema portability.

These tests verify that the ORM-declared schema (src/models.py) can be
created, destroyed, and re-created against a live PostgreSQL instance that
matches the production version.  They use Base.metadata directly — not the
module-level engine in database.py — so they are fully isolated from any
runtime connection strings and portable across environments.
"""

from sqlalchemy import inspect

from src.models import Base


# ---------------------------------------------------------------------------
# Canonical list of the most business-critical tables.
# Add to this set whenever a new domain table is introduced.
# ---------------------------------------------------------------------------
_CRITICAL_TABLES = frozenset(
    {
        "users",
        "location",
        "location_type",
        "device",
        "device_type",
        "metric_type",
        "context_type",
        "telemetry_data",
        "forecast_result",
        "context_data",
        "anomaly_alert",
        "anomaly_detected_event",
        "ai_pipeline_log",
        "system_log",
        "prediction_log",
        "model_performance",
        "drift_report",
        "threshold_config",
        "device_metric_capability",
    }
)


# ---------------------------------------------------------------------------
# Schema creation portability
# ---------------------------------------------------------------------------


def test_all_orm_models_create_their_tables_without_error(pg_engine):
    """Every model registered with Base must produce a valid DDL statement."""
    Base.metadata.create_all(bind=pg_engine)
    inspector = inspect(pg_engine)
    created_tables = set(inspector.get_table_names())
    expected_tables = set(Base.metadata.tables.keys())

    missing = expected_tables - created_tables
    assert not missing, f"ORM models without a created table: {missing}"


def test_all_critical_domain_tables_are_present_after_creation(pg_engine):
    """Spot-check: the most important tables must always be in the schema."""
    Base.metadata.create_all(bind=pg_engine)
    inspector = inspect(pg_engine)
    created_tables = set(inspector.get_table_names())

    missing = _CRITICAL_TABLES - created_tables
    assert not missing, f"Critical domain tables missing from schema: {missing}"


# ---------------------------------------------------------------------------
# Idempotency — the deployment model for this project is create_all on boot
# ---------------------------------------------------------------------------


def test_schema_creation_is_idempotent(pg_engine):
    """
    Calling create_all twice on the same database must not raise.
    This mirrors the production boot sequence where init_db() is called
    every time the container starts, regardless of existing state.
    """
    Base.metadata.create_all(bind=pg_engine)
    Base.metadata.create_all(bind=pg_engine)  # second call — must be a silent no-op


# ---------------------------------------------------------------------------
# Teardown and recreation — validates portability across fresh environments
# ---------------------------------------------------------------------------


def test_full_teardown_and_recreation_produces_a_valid_schema(pg_engine):
    """
    drop_all followed by create_all must produce a fully usable schema.
    This simulates a fresh deployment or a CI environment with a clean DB.
    """
    Base.metadata.create_all(bind=pg_engine)
    Base.metadata.drop_all(bind=pg_engine)
    Base.metadata.create_all(bind=pg_engine)

    inspector = inspect(pg_engine)
    created_tables = set(inspector.get_table_names())
    expected_tables = set(Base.metadata.tables.keys())

    missing = expected_tables - created_tables
    assert not missing, f"Tables missing after teardown + recreation: {missing}"


# ---------------------------------------------------------------------------
# Schema contract assertions — catch accidental model changes early
# ---------------------------------------------------------------------------


def test_telemetry_data_has_the_correct_composite_primary_key(pg_engine):
    """
    The time-series table PK must be (timestamp, device_id, metric_type_id).
    Changing this would silently break TimescaleDB hypertable compatibility.
    """
    Base.metadata.create_all(bind=pg_engine)
    inspector = inspect(pg_engine)

    pk_columns = set(
        inspector.get_pk_constraint("telemetry_data")["constrained_columns"]
    )
    assert pk_columns == {"timestamp", "device_id", "metric_type_id"}


def test_users_table_has_a_unique_constraint_on_email(pg_engine):
    """
    The unique constraint on users.email must exist at the DB level, not
    just in application code.  Auth login queries rely on this guarantee.
    """
    Base.metadata.create_all(bind=pg_engine)
    inspector = inspect(pg_engine)

    constrained_columns = {
        col
        for constraint in inspector.get_unique_constraints("users")
        for col in constraint["column_names"]
    }
    assert "email" in constrained_columns


def test_anomaly_detected_event_has_composite_unique_constraint(pg_engine):
    """
    The uq_anomaly_detected_event constraint prevents duplicate anomaly
    records for the same (building, timestamp, metric, source) combination.
    """
    Base.metadata.create_all(bind=pg_engine)
    inspector = inspect(pg_engine)

    unique_constraints = inspector.get_unique_constraints("anomaly_detected_event")
    constrained_column_sets = [
        frozenset(c["column_names"]) for c in unique_constraints
    ]
    expected_key = frozenset({"building_id", "timestamp", "metric_type_id", "source"})
    assert expected_key in constrained_column_sets
