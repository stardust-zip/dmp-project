import pytest
from datetime import datetime, timezone
from pydantic import ValidationError
from src.schemas import (
    IngestionStatus,
    ModelTrainingRequest,
    PredictionScenarioRequest,
    TelemetryDataPayload,
)


def test_telemetry_payload_enforces_utc():
    """Test that timestamp correctly converts or requires timezone awareness."""

    # 1. Valid UTC datetime
    valid_dt = datetime.now(timezone.utc)
    payload = TelemetryDataPayload(
        timestamp=valid_dt,
        device_id="meter_electricity_Panther_1",
        metric_type_id="electricity",
        value=150.5,
    )
    assert payload.timestamp.tzinfo == timezone.utc
    assert payload.ingestion_status == IngestionStatus.Success

    # 2. Naive datetime should raise ValueError
    naive_dt = datetime.now()
    with pytest.raises(ValidationError) as exc_info:
        TelemetryDataPayload(
            timestamp=naive_dt,
            device_id="meter_electricity_Panther_1",
            metric_type_id="electricity",
            value=150.5,
        )
    assert "Timestamp must be timezone-aware" in str(exc_info.value)


def test_telemetry_payload_negative_value_rejected():
    """Test the ge=0.0 constraint on the value field."""
    valid_dt = datetime.now(timezone.utc)

    with pytest.raises(ValidationError) as exc_info:
        TelemetryDataPayload(
            timestamp=valid_dt,
            device_id="meter_electricity_Panther_1",
            metric_type_id="electricity",
            value=-10.0,  # Invalid negative consumption
        )
    assert "Input should be greater than or equal to 0" in str(exc_info.value)

def test_telemetry_payload_empty_id_rejected():
    """Test that device_id cannot be empty."""
    valid_dt = datetime.now(timezone.utc)
    with pytest.raises(ValidationError):
        TelemetryDataPayload(
            timestamp=valid_dt,
            device_id="", # Empty
            metric_type_id="electricity",
            value=10.0
        )

def test_location_create_metadata_optional():
    """Test that location metadata is truly optional."""
    from src.schemas import LocationCreate
    loc = LocationCreate(id="B1", location_type_id="office", name="Building 1")
    assert loc.metadata is None


def test_model_training_request_normalizes_metrics():
    payload = ModelTrainingRequest(
        site_id="SiteA",
        metrics=[" Electricity ", "WATER"],
        time_range_start="2026-06-01T00:00:00Z",
        time_range_end="2026-06-02T00:00:00Z",
    )

    assert payload.metrics == ["electricity", "water"]
    assert payload.building_id is None
    assert payload.model_task == "prediction"
    assert payload.data_source == "csv"


def test_model_training_request_rejects_invalid_time_range():
    with pytest.raises(ValidationError, match="time_range_end must be after"):
        ModelTrainingRequest(
            site_id="SiteA",
            metrics=["electricity"],
            time_range_start="2026-06-02T00:00:00Z",
            time_range_end="2026-06-01T00:00:00Z",
        )


def test_model_training_request_rejects_algorithm_selection():
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ModelTrainingRequest(
            site_id="SiteA",
            metrics=["electricity"],
            time_range_start="2026-06-01T00:00:00Z",
            time_range_end="2026-06-02T00:00:00Z",
            algorithm="lightgbm",
        )


def test_prediction_scenario_accepts_legacy_energy_rate_alias():
    payload = PredictionScenarioRequest(
        site_id="SiteA",
        building_id="BuildingA",
        metric_type="water",
        scenario_date="2026-06-10T00:00:00Z",
        energy_rate_per_kwh=2.5,
    )

    assert payload.unit_rate == 2.5
