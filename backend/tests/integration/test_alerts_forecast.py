from datetime import datetime, timezone

import pytest
from src import models
from src.database import get_db
from src.main import app


@pytest.fixture
def api_db_client(admin_client, db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    yield admin_client
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def alert_forecast_prerequisites(db_session):
    db_session.add_all(
        [
            models.MetricType(id="electricity", unit="kWh"),
            models.MetricType(id="water", unit="m3"),
            models.LocationType(id="building"),
            models.DeviceType(id="virtual_meter"),
            models.Location(
                id="loc-1", location_type_id="building", name="Test Building"
            ),
            models.Device(
                id="meter-1", location_id="loc-1", device_type_id="virtual_meter"
            ),
            models.Device(
                id="meter-2", location_id="loc-1", device_type_id="virtual_meter"
            ),
        ]
    )
    db_session.commit()


def _utc_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


@pytest.mark.usefixtures("alert_forecast_prerequisites")
def test_get_alerts_returns_filtered_paginated_alerts(api_db_client, db_session):
    db_session.add_all(
        [
            models.AnomalyAlert(
                device_id="meter-1",
                metric_type_id="electricity",
                severity="Warning",
                message="Older electricity warning",
                status="Open",
                created_at=_utc_timestamp("2026-06-05T10:00:00"),
            ),
            models.AnomalyAlert(
                device_id="meter-1",
                metric_type_id="electricity",
                severity="Critical",
                message="Newest electricity alert",
                status="Acknowledged",
                created_at=_utc_timestamp("2026-06-07T10:00:00"),
            ),
            models.AnomalyAlert(
                device_id="meter-2",
                metric_type_id="water",
                severity="Emergency",
                message="Different device alert",
                status="Open",
                created_at=_utc_timestamp("2026-06-08T10:00:00"),
            ),
        ]
    )
    db_session.commit()

    response = api_db_client.get(
        "/api/v1/alerts/",
        params={
            "device_id": "meter-1",
            "metric_type_id": "electricity",
            "start_time": "2026-06-05T00:00:00Z",
            "end_time": "2026-06-08T00:00:00Z",
            "limit": 1,
            "offset": 0,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["limit"] == 1
    assert data["offset"] == 0
    assert len(data["alerts"]) == 1
    assert data["alerts"][0]["device_id"] == "meter-1"
    assert data["alerts"][0]["metric_type_id"] == "electricity"
    assert data["alerts"][0]["severity"] == "Critical"
    assert data["alerts"][0]["status"] == "Acknowledged"
    assert data["alerts"][0]["message"] == "Newest electricity alert"
    assert data["alerts"][0]["timestamp"].startswith("2026-06-07T10:00:00")


def test_get_alerts_returns_empty_page(api_db_client):
    response = api_db_client.get(
        "/api/v1/alerts/", params={"device_id": "missing-device"}
    )

    assert response.status_code == 200
    assert response.json() == {"limit": 100, "offset": 0, "alerts": []}


@pytest.mark.usefixtures("alert_forecast_prerequisites")
def test_get_forecast_returns_filtered_paginated_forecast(api_db_client, db_session):
    db_session.add_all(
        [
            models.ForecastResult(
                timestamp=_utc_timestamp("2026-06-05T00:00:00"),
                device_id="meter-1",
                metric_type_id="electricity",
                predicted_value=150.5,
                mlflow_run_id="run-old",
            ),
            models.ForecastResult(
                timestamp=_utc_timestamp("2026-06-06T00:00:00"),
                device_id="meter-1",
                metric_type_id="electricity",
                predicted_value=152.1,
                mlflow_run_id="run-new",
            ),
            models.ForecastResult(
                timestamp=_utc_timestamp("2026-06-07T00:00:00"),
                device_id="meter-2",
                metric_type_id="water",
                predicted_value=88.0,
                mlflow_run_id="run-other",
            ),
        ]
    )
    db_session.commit()

    response = api_db_client.get(
        "/api/v1/forecast/",
        params={
            "device_id": "meter-1",
            "metric_type_id": "electricity",
            "start_time": "2026-06-05T00:00:00Z",
            "end_time": "2026-06-07T00:00:00Z",
            "limit": 1,
            "offset": 1,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["limit"] == 1
    assert data["offset"] == 1
    assert data["forecast"] == [
        {
            "timestamp": data["forecast"][0]["timestamp"],
            "device_id": "meter-1",
            "metric_type_id": "electricity",
            "predicted_value": 150.5,
        }
    ]
    assert data["forecast"][0]["timestamp"].startswith("2026-06-05T00:00:00")


@pytest.mark.usefixtures("alert_forecast_prerequisites")
def test_get_forecast_availability_returns_building_metric_window(api_db_client, db_session):
    db_session.add_all(
        [
            models.TelemetryData(
                timestamp=_utc_timestamp("2026-06-05T00:00:00"),
                device_id="meter-1",
                metric_type_id="electricity",
                value=150.5,
            ),
            models.TelemetryData(
                timestamp=_utc_timestamp("2026-06-06T00:00:00"),
                device_id="meter-1",
                metric_type_id="electricity",
                value=152.1,
            ),
            models.TelemetryData(
                timestamp=_utc_timestamp("2026-06-07T00:00:00"),
                device_id="meter-2",
                metric_type_id="water",
                value=88.0,
            ),
        ]
    )
    db_session.commit()

    response = api_db_client.get(
        "/api/v1/forecast/availability",
        params={"building_id": "loc-1", "metric_type": "electricity"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["building_id"] == "loc-1"
    assert data["metric_type"] == "electricity"
    assert data["row_count"] == 2
    assert data["first_timestamp"].startswith("2026-06-05T00:00:00")
    assert data["last_timestamp"].startswith("2026-06-06T00:00:00")
    assert data["recommended_input_start"].startswith("2026-06-05T00:00:00")
    assert data["recommended_input_end"].startswith("2026-06-06T00:00:00")


def test_get_forecast_returns_empty_page(api_db_client):
    response = api_db_client.get(
        "/api/v1/forecast/", params={"metric_type_id": "unknown"}
    )

    assert response.status_code == 200
    assert response.json() == {"limit": 100, "offset": 0, "forecast": []}


@pytest.mark.parametrize("path", ["/api/v1/alerts/", "/api/v1/forecast/"])
@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 1001},
        {"offset": -1},
        {"start_time": "not-a-date"},
    ],
)
def test_alert_and_forecast_query_validation(api_db_client, path, params):
    response = api_db_client.get(path, params=params)

    assert response.status_code == 422
