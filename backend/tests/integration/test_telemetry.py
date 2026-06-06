import pytest

def test_create_telemetry_data(client):
    payload = {
        "timestamp": "2026-06-05T10:00:00Z",
        "device_id": "test_device",
        "metric_type_id": "electricity",
        "value": 123.45
    }
    response = client.post("/api/v1/telemetry/", json=payload)
    assert response.status_code == 200
    assert response.json()["message"] == "Telemetry data received"
    assert response.json()["data"]["device_id"] == "test_device"

def test_create_telemetry_invalid_timestamp(client):
    payload = {
        "timestamp": "2026-06-05 10:00:00", # No timezone
        "device_id": "test_device",
        "metric_type_id": "electricity",
        "value": 123.45
    }
    response = client.post("/api/v1/telemetry/", json=payload)
    assert response.status_code == 422 # Pydantic validation error
