import pandas as pd
import pytest
from src import seeder, models

# ==========================================
# Fixtures for Fake Data
# ==========================================


@pytest.fixture
def mock_data_dir(tmp_path, monkeypatch):
    """
    Creates a temporary directory structure mimicking the real data folder
    and patches seeder.DATA_DIR to point to it.
    """
    # Create the folder structure
    meta_dir = tmp_path / "metadata"
    meta_dir.mkdir()

    meters_dir = tmp_path / "meters" / "cleaned"
    meters_dir.mkdir(parents=True)

    # Override the DATA_DIR in the seeder module
    monkeypatch.setattr(seeder, "DATA_DIR", str(tmp_path))

    return tmp_path


@pytest.fixture
def create_fake_metadata_csv(mock_data_dir):
    """Generates a minimal metadata.csv for testing."""
    csv_path = mock_data_dir / "metadata" / "metadata.csv"
    data = {
        "building_id": ["Panther_lodging_Cora", "Panther_office_Hannah"],
        "primaryspaceusage": ["Lodging/Residential", "Office"],
        "sqm": [1000.5, 2500.0],
        "timezone": ["US/Eastern", "US/Eastern"],
        "yearbuilt": [1990, 2005],
    }
    pd.DataFrame(data).to_csv(csv_path, index=False)
    return csv_path


@pytest.fixture
def create_fake_telemetry_csv(mock_data_dir):
    """Generates a minimal electricity_cleaned.csv for testing."""
    csv_path = mock_data_dir / "meters" / "cleaned" / "electricity_cleaned.csv"
    data = {
        "timestamp": ["2016-01-01 00:00:00", "2016-01-01 01:00:00"],
        "Panther_lodging_Cora": [150.5, 155.2],
        "Panther_office_Hannah": [300.0, 290.5],
    }
    pd.DataFrame(data).to_csv(csv_path, index=False)
    return csv_path


# ==========================================
# Integration Tests
# ==========================================


def test_seed_lookups(db_session):
    """Test that static lookup tables (DeviceType, MetricType) are seeded correctly."""
    # Run the seeder
    seeder.seed_lookups(db_session)

    # Assert Device Types
    virtual_meter = (
        db_session.query(models.DeviceType).filter_by(id="virtual_meter").first()
    )
    assert virtual_meter is not None

    # Assert Metric Types
    electricity = (
        db_session.query(models.MetricType).filter_by(id="electricity").first()
    )
    assert electricity is not None
    assert electricity.unit == "kWh"


@pytest.mark.usefixtures("create_fake_metadata_csv")
def test_seed_metadata(db_session):
    """Test that Locations and LocationTypes are parsed and saved correctly."""
    seeder.seed_metadata(db_session)

    # Verify Location Types were extracted
    loc_types = db_session.query(models.LocationType).all()
    loc_type_ids = [lt.id for lt in loc_types]
    assert "Lodging/Residential" in loc_type_ids
    assert "Office" in loc_type_ids

    # Verify Locations were created with proper JSONB metadata
    cora = (
        db_session.query(models.Location).filter_by(id="Panther_lodging_Cora").first()
    )
    assert cora is not None
    assert cora.location_type_id == "Lodging/Residential"
    assert cora.metadata_["sqm"] == 1000.5
    assert cora.metadata_["yearbuilt"] == 1990.0


@pytest.mark.usefixtures("create_fake_telemetry_csv")
def test_seed_telemetry(db_session):
    """Test that telemetry melting, device creation, and timeseries insertion work."""
    # We must seed lookups and metadata first because Devices depend on them via Foreign Keys
    seeder.seed_lookups(db_session)
    # Create fake locations manually for the test to satisfy Foreign Key constraints
    db_session.add(models.LocationType(id="Unknown"))
    db_session.add(
        models.Location(
            id="Panther_lodging_Cora", location_type_id="Unknown", name="Cora"
        )
    )
    db_session.add(
        models.Location(
            id="Panther_office_Hannah", location_type_id="Unknown", name="Hannah"
        )
    )
    db_session.commit()

    # Run the telemetry seeder
    seeder.seed_telemetry(db_session, limit=10)

    # 1. Verify Devices were auto-created
    cora_meter = (
        db_session.query(models.Device)
        .filter_by(id="meter_electricity_Panther_lodging_Cora")
        .first()
    )
    assert cora_meter is not None
    assert cora_meter.device_type_id == "virtual_meter"

    # 2. Verify Telemetry Data was inserted
    telemetry = db_session.query(models.TelemetryData).all()

    # 2 timestamps * 2 buildings = 4 records
    assert len(telemetry) == 4

    # Verify specific value
    cora_reading = (
        db_session.query(models.TelemetryData)
        .filter_by(device_id="meter_electricity_Panther_lodging_Cora")
        .first()
    )
    assert cora_reading.value in [150.5, 155.2]
    assert cora_reading.ingestion_status == "Success"
