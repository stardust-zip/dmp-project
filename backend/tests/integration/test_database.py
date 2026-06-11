from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError
from src import models


def test_user_unique_email_constraint(db_session):
    """Ensure that two users cannot be registered with the same email."""
    user1 = models.User(
        full_name="User One",
        email="duplicate@example.com",
        password_hash="hash1",
        role="Operator",
    )
    db_session.add(user1)
    db_session.commit()

    user2 = models.User(
        full_name="User Two",
        email="duplicate@example.com",
        password_hash="hash2",
        role="Operator",
    )
    db_session.add(user2)

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_device_foreign_key_violation(db_session):
    """Ensure a device cannot be created with a non-existent location_id."""
    device = models.Device(
        id="orphan_device",
        location_id="non_existent_loc",
        device_type_id="virtual_meter",
    )
    db_session.add(device)

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_telemetry_composite_primary_key(db_session):
    """
    Ensure the same (timestamp, device_id, metric_type_id) triplet
    cannot be inserted twice (Database-level deduplication).
    """
    # 1. Setup prerequisites
    db_session.add(models.MetricType(id="electricity"))
    db_session.add(models.LocationType(id="test_loc_type"))
    db_session.add(models.DeviceType(id="virtual_meter"))
    db_session.add(
        models.Location(id="loc1", location_type_id="test_loc_type", name="Loc 1")
    )
    db_session.add(
        models.Device(id="dev1", location_id="loc1", device_type_id="virtual_meter")
    )
    db_session.commit()

    ts = datetime.now(timezone.utc)

    # First insertion
    read1 = models.TelemetryData(
        timestamp=ts, device_id="dev1", metric_type_id="electricity", value=100.0
    )
    db_session.add(read1)
    db_session.commit()

    # Clear session to avoid SAWarning about conflicting identity map
    db_session.expunge_all()

    # Duplicate insertion (same PK)
    read2 = models.TelemetryData(
        timestamp=ts,
        device_id="dev1",
        metric_type_id="electricity",
        value=200.0,  # Different value, same PK
    )
    db_session.add(read2)

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_telemetry_null_value_rejected(db_session):
    """Ensure that telemetry 'value' cannot be null in the DB."""
    # Prerequisites
    db_session.add(models.MetricType(id="water"))
    db_session.add(models.LocationType(id="test_loc_type"))
    db_session.add(models.DeviceType(id="virtual_meter"))
    db_session.add(
        models.Location(id="loc2", location_type_id="test_loc_type", name="Loc 2")
    )
    db_session.add(
        models.Device(id="dev2", location_id="loc2", device_type_id="virtual_meter")
    )
    db_session.commit()

    bad_read = models.TelemetryData(
        timestamp=datetime.now(timezone.utc),
        device_id="dev2",
        metric_type_id="water",
        value=None,  # NOT NULL constraint violation
    )
    db_session.add(bad_read)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_enum_valid_values(db_session):
    """Ensure only predefined enums can be used."""
    # 'role' is an Enum in User
    bad_user = models.User(
        full_name="Bad Enum",
        email="bad@enum.com",
        password_hash="pw",
        role="SuperAdmin",  # Not in ('Admin', 'AI_Engineer', 'Operator')
    )
    db_session.add(bad_user)
    # Note: SQLAlchemy might catch this before the DB, or the DB will.
    # Either way, it should fail.
    with pytest.raises((IntegrityError, ValueError, Exception)):
        db_session.commit()
    db_session.rollback()
