from datetime import datetime, timezone

import pandas as pd
import pytest
from src import models
from src.ml.anomaly.telemetry_loaders import query_telemetry_window
from src.seeders.metadata import seed_reference_data
from src.seeders.telemetry import seed_telemetry_data
from src.seeders.weather import seed_weather_data

# ==========================================
# Fixtures for Fake Data
# ==========================================


@pytest.fixture
def mock_data_dir(tmp_path):
    """
    Creates a temporary directory structure mimicking the real data folder.
    """
    meta_dir = tmp_path / "metadata"
    meta_dir.mkdir()

    meters_dir = tmp_path / "meters" / "cleaned"
    meters_dir.mkdir(parents=True)

    return tmp_path


@pytest.fixture
def create_fake_metadata_csv(mock_data_dir):
    """Generates a minimal metadata.csv for testing."""
    csv_path = mock_data_dir / "metadata" / "metadata.csv"
    data = {
        "building_id": ["Panther_lodging_Cora", "Panther_office_Hannah"],
        "site_id": ["site_001", "site_001"],
        "primaryspaceusage": ["Lodging/Residential", "Office"],
        "electricity": ["Yes", "Yes"],
        "sqm": [1000.5, 2500.0],
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


@pytest.fixture
def create_fake_weather_csv(mock_data_dir):
    """Generates a minimal weather.csv for testing."""
    weather_dir = mock_data_dir / "weather"
    weather_dir.mkdir()
    csv_path = weather_dir / "weather.csv"
    data = {
        "timestamp": ["2016-01-01 00:00:00", "2016-01-01 01:00:00"],
        "site_id": ["site_001", "site_001"],
        "airTemperature": [12.5, 13.0],
        "windSpeed": [3.2, 3.5],
    }
    pd.DataFrame(data).to_csv(csv_path, index=False)
    return csv_path


# ==========================================
# Integration Tests
# ==========================================


def test_seed_lookups(db_session, create_fake_metadata_csv):
    """Test that static lookup tables (DeviceType, MetricType) are seeded correctly."""
    seed_reference_data(db_session, csv_path=create_fake_metadata_csv)

    virtual_meter = (
        db_session.query(models.DeviceType).filter_by(id="virtual_meter").first()
    )
    assert virtual_meter is not None

    electricity = (
        db_session.query(models.MetricType).filter_by(id="electricity").first()
    )
    assert electricity is not None
    assert electricity.unit == "kWh"


def test_seed_metadata(db_session, create_fake_metadata_csv):
    """Test that Locations and LocationTypes are parsed and saved correctly."""
    seed_reference_data(db_session, csv_path=create_fake_metadata_csv)

    loc_types = db_session.query(models.LocationType).all()
    loc_type_ids = [lt.id for lt in loc_types]
    assert "Lodging/Residential" in loc_type_ids
    assert "Office" in loc_type_ids

    cora = (
        db_session.query(models.Location).filter_by(id="Panther_lodging_Cora").first()
    )
    assert cora is not None
    assert cora.location_type_id == "Lodging/Residential"
    assert cora.parent_id == "site_001"
    assert cora.metadata_["sqm"] == 1000.5
    assert cora.metadata_["yearbuilt"] == 1990


def test_seed_telemetry(
    db_session,
    create_fake_metadata_csv,
    create_fake_telemetry_csv,
    mock_data_dir,
):
    """Test that telemetry melting, device creation, and timeseries insertion work."""
    seed_reference_data(db_session, csv_path=create_fake_metadata_csv)

    meter_dir = mock_data_dir / "meters" / "cleaned"
    seed_telemetry_data(
        db_session,
        meter_dir=str(meter_dir),
        metrics=("electricity",),
        limit=10,
    )

    cora_meter = (
        db_session.query(models.Device)
        .filter_by(id="meter_electricity_Panther_lodging_Cora")
        .first()
    )
    assert cora_meter is not None
    assert cora_meter.device_type_id == "virtual_meter"

    telemetry = db_session.query(models.TelemetryData).all()

    assert len(telemetry) == 4

    cora_reading = (
        db_session.query(models.TelemetryData)
        .filter_by(device_id="meter_electricity_Panther_lodging_Cora")
        .first()
    )
    assert cora_reading.value in [150.5, 155.2]
    assert cora_reading.ingestion_status == "Success"


def test_seed_weather(db_session, create_fake_metadata_csv, create_fake_weather_csv):
    """Test that weather CSV rows are seeded into context_data for ML weather loaders."""
    seed_reference_data(db_session, csv_path=create_fake_metadata_csv)

    summary = seed_weather_data(db_session, csv_path=create_fake_weather_csv)

    assert summary["context_types"] == 8
    assert summary["context_rows"] == 4
    air_temp = (
        db_session.query(models.ContextData)
        .filter_by(location_id="site_001", context_type_id="airTemperature")
        .first()
    )
    assert air_temp is not None
    assert air_temp.value in [12.5, 13.0]


def test_seeded_db_telemetry_matches_csv_loader_metadata_fallback(
    db_session,
    create_fake_metadata_csv,
    create_fake_telemetry_csv,
    mock_data_dir,
):
    """DB telemetry loader should expose the same sub-PSU fallback as the CSV path."""
    seed_reference_data(db_session, csv_path=create_fake_metadata_csv)
    seed_telemetry_data(
        db_session,
        meter_dir=str(mock_data_dir / "meters" / "cleaned"),
        metrics=("electricity",),
        limit=10,
    )

    df = query_telemetry_window(
        db_session,
        datetime(2016, 1, 1, tzinfo=timezone.utc),
        datetime(2016, 1, 1, 1, tzinfo=timezone.utc),
        metrics=["electricity"],
    )

    assert not df.empty
    assert df["metric_type_id"].unique().tolist() == ["electricity"]
    assert df["sub_primaryspaceusage"].notna().all()
    assert (
        df.loc[df["building_id"] == "Panther_office_Hannah", "sub_primaryspaceusage"]
        == "Office"
    ).all()
