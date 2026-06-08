from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from src.api.v1.deps import get_current_admin, get_current_user
from src.database import get_db
from src.main import app

client = TestClient(app)


class MockAdminUser:
    email = "admin@vinsmart.com"
    role = "Admin"


def get_mock_admin():
    return MockAdminUser()


@pytest.fixture(autouse=True)
def override_auth_dependencies():
    app.dependency_overrides[get_current_admin] = get_mock_admin
    app.dependency_overrides[get_current_user] = get_mock_admin

    yield

    app.dependency_overrides.clear()


@patch("src.api.v1.endpoints.models.train_model_task.delay")
def test_trigger_training_success(mock_delay):
    class MockTask:
        id = "mock-task-uuid-123"

    mock_delay.return_value = MockTask()

    response = client.post(
        "/api/v1/models/train?building_id=TestBuilding&metric_type=water"
    )

    assert response.status_code == 200
    assert response.json()["task_id"] == "mock-task-uuid-123"
    assert (
        response.json()["message"] == "forecasting training job queued using csv data."
    )
    assert response.json()["model_task"] == "forecasting"
    training_request = mock_delay.call_args.kwargs["training_request"]
    assert training_request["site_id"] == "TestBuilding"
    assert training_request["metrics"] == ["water"]
    assert training_request["data_source"] == "csv"
    assert training_request["model_task"] == "forecasting"
    assert "algorithm" not in training_request
    assert response.json()["algorithm"] == "random_forest"


@patch("src.api.v1.endpoints.models.train_model_task.delay")
def test_trigger_training_accepts_anomaly_training(mock_delay):
    class MockTask:
        id = "mock-task-uuid-456"

    mock_delay.return_value = MockTask()

    response = client.post(
        "/api/v1/models/train"
        "?building_id=TestBuilding&metric_type=water"
        "&model_task=anomaly_detection&data_source=db"
    )

    assert response.status_code == 200
    assert response.json()["message"] == (
        "anomaly_detection training job queued using db data."
    )
    training_request = mock_delay.call_args.kwargs["training_request"]
    assert training_request["model_task"] == "anomaly_detection"
    assert training_request["data_source"] == "db"
    assert "algorithm" not in training_request
    assert response.json()["algorithm"] == "lightgbm"


@patch("src.api.v1.endpoints.models.train_model_task.delay")
def test_trigger_training_accepts_popup_payload(mock_delay):
    class MockTask:
        id = "mock-task-uuid-789"

    mock_delay.return_value = MockTask()

    payload = {
        "site_id": "SiteA",
        "metrics": [" electricity ", "Water"],
        "time_range_start": "2026-06-01T00:00:00Z",
        "time_range_end": "2026-06-07T00:00:00Z",
        "model_task": "prediction",
        "data_source": "csv",
        "csv_path": "/tmp/site-a.csv",
    }

    response = client.post("/api/v1/models/train", json=payload)

    assert response.status_code == 200
    assert response.json()["model_task"] == "prediction"
    assert response.json()["site_id"] == "SiteA"
    assert response.json()["metrics"] == ["electricity", "water"]
    assert response.json()["algorithm"] == "linear_regression"
    training_request = mock_delay.call_args.kwargs["training_request"]
    assert training_request["csv_path"] == "/tmp/site-a.csv"
    assert "algorithm" not in training_request


def test_trigger_training_rejects_client_selected_algorithm():
    payload = {
        "site_id": "SiteA",
        "metrics": ["electricity"],
        "time_range_start": "2026-06-01T00:00:00Z",
        "time_range_end": "2026-06-07T00:00:00Z",
        "model_task": "forecasting",
        "data_source": "csv",
        "algorithm": "lightgbm",
    }

    response = client.post("/api/v1/models/train", json=payload)

    assert response.status_code == 422


@patch("src.api.v1.endpoints.models._mlflow_client")
def test_get_model_versions_returns_run_ids_and_metrics(mock_mlflow_client):
    client_mock = Mock()
    client_mock.search_model_versions.return_value = [
        SimpleNamespace(
            name="forecasting_v1",
            version="1",
            run_id="run-1",
            tags={"active": "false", "model_task": "forecasting"},
            current_stage="None",
            creation_timestamp=100,
            last_updated_timestamp=200,
        ),
        SimpleNamespace(
            name="forecasting_v1",
            version="2",
            run_id="run-2",
            tags={"active": "true"},
            current_stage="Production",
            creation_timestamp=300,
            last_updated_timestamp=400,
        ),
    ]
    client_mock.get_run.side_effect = [
        SimpleNamespace(data=SimpleNamespace(metrics={"mae": 0.2, "rmse": 0.4})),
        SimpleNamespace(data=SimpleNamespace(metrics={"mae": 0.1, "rmse": 0.3})),
    ]
    mock_mlflow_client.return_value = client_mock

    response = client.get("/api/v1/models/forecasting_v1/versions")

    assert response.status_code == 200
    assert response.json() == {
        "model_name": "forecasting_v1",
        "versions": [
            {
                "name": "forecasting_v1",
                "version": "2",
                "run_id": "run-2",
                "model_task": None,
                "metrics": {"mae": 0.2, "rmse": 0.4},
                "tags": {"active": "true"},
                "current_stage": "Production",
                "creation_timestamp": 300,
                "last_updated_timestamp": 400,
            },
            {
                "name": "forecasting_v1",
                "version": "1",
                "run_id": "run-1",
                "model_task": "forecasting",
                "metrics": {"mae": 0.1, "rmse": 0.3},
                "tags": {"active": "false", "model_task": "forecasting"},
                "current_stage": "None",
                "creation_timestamp": 100,
                "last_updated_timestamp": 200,
            },
        ],
    }
    client_mock.search_model_versions.assert_called_once_with("name = 'forecasting_v1'")
    client_mock.get_run.assert_any_call("run-1")
    client_mock.get_run.assert_any_call("run-2")


@patch("src.api.v1.endpoints.models._mlflow_client")
def test_get_model_versions_returns_404_when_none_registered(mock_mlflow_client):
    client_mock = Mock()
    client_mock.search_model_versions.return_value = []
    mock_mlflow_client.return_value = client_mock

    response = client.get("/api/v1/models/missing_model/versions")

    assert response.status_code == 404
    assert "No registered versions found" in response.json()["detail"]


@patch("src.api.v1.endpoints.models._mlflow_client")
def test_rollback_promotes_run_model_version(mock_mlflow_client):
    target_version = SimpleNamespace(
        name="forecasting_v1",
        version="2",
        run_id="run-2",
    )
    sibling_version = SimpleNamespace(
        name="forecasting_v1",
        version="1",
        run_id="run-1",
    )
    client_mock = Mock()
    client_mock.search_model_versions.side_effect = [
        [target_version],
        [sibling_version, target_version],
    ]
    mock_mlflow_client.return_value = client_mock

    response = client.post(
        "/api/v1/models/rollback",
        json={"mlflow_run_id": "run-2", "model_name": "forecasting_v1"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "message": "Model version promoted to production.",
        "model_name": "forecasting_v1",
        "version": "2",
        "run_id": "run-2",
        "promoted_by": "admin@vinsmart.com",
    }
    assert client_mock.search_model_versions.call_args_list[0].args == (
        "name = 'forecasting_v1' and run_id = 'run-2'",
    )
    client_mock.set_model_version_tag.assert_any_call(
        "forecasting_v1", "1", "active", "false"
    )
    client_mock.set_model_version_tag.assert_any_call(
        "forecasting_v1", "2", "active", "false"
    )
    client_mock.set_model_version_tag.assert_any_call(
        "forecasting_v1", "2", "active", "true"
    )
    client_mock.set_model_version_tag.assert_any_call(
        "forecasting_v1", "2", "stage", "production"
    )
    client_mock.set_registered_model_alias.assert_called_once_with(
        "forecasting_v1", "production", "2"
    )


@patch("src.api.v1.endpoints.models._mlflow_client")
def test_rollback_returns_404_for_unknown_run_id(mock_mlflow_client):
    client_mock = Mock()
    client_mock.search_model_versions.return_value = []
    mock_mlflow_client.return_value = client_mock

    response = client.post(
        "/api/v1/models/rollback",
        json={"mlflow_run_id": "missing-run"},
    )

    assert response.status_code == 404
    assert "No registered model version found" in response.json()["detail"]


@patch("src.api.v1.endpoints.models._mlflow_client")
def test_list_models_returns_registered_models(mock_mlflow_client):
    latest_version = SimpleNamespace(
        version=3,
        current_stage="Production",
        status="READY",
    )
    registered_model = SimpleNamespace(
        name="forecasting_v1",
        description="Forecast energy consumption",
        creation_timestamp=100,
        last_updated_timestamp=200,
        tags={"domain": "forecasting"},
        latest_versions=[latest_version],
    )
    client_mock = Mock()
    client_mock.search_registered_models.return_value = [registered_model]
    mock_mlflow_client.return_value = client_mock

    response = client.get("/api/v1/models/")

    assert response.status_code == 200
    assert response.json() == {
        "models": [
            {
                "name": "forecasting_v1",
                "description": "Forecast energy consumption",
                "creation_timestamp": 100,
                "last_updated_timestamp": 200,
                "tags": {"domain": "forecasting"},
                "latest_versions": [
                    {
                        "version": "3",
                        "current_stage": "Production",
                        "status": "READY",
                    }
                ],
            }
        ]
    }


@patch("src.api.v1.endpoints.models._mlflow_client")
def test_rollback_returns_409_when_run_id_matches_multiple_versions(
    mock_mlflow_client,
):
    client_mock = Mock()
    client_mock.search_model_versions.return_value = [
        SimpleNamespace(name="forecasting_v1", version="1", run_id="run-2"),
        SimpleNamespace(name="forecasting_v2", version="4", run_id="run-2"),
    ]
    mock_mlflow_client.return_value = client_mock

    response = client.post(
        "/api/v1/models/rollback",
        json={"mlflow_run_id": "run-2"},
    )

    assert response.status_code == 409
    assert "Retry with model_name" in response.json()["detail"]
    client_mock.set_model_version_tag.assert_not_called()


@patch("src.api.v1.endpoints.models._mlflow_client")
def test_rollback_returns_502_when_target_version_has_no_run_id(mock_mlflow_client):
    target_version = SimpleNamespace(
        name="forecasting_v1",
        version="2",
        run_id=None,
    )
    client_mock = Mock()
    client_mock.search_model_versions.side_effect = [
        [target_version],
        [target_version],
    ]
    mock_mlflow_client.return_value = client_mock

    response = client.post(
        "/api/v1/models/rollback",
        json={"mlflow_run_id": "run-2", "model_name": "forecasting_v1"},
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "Model version has no associated run ID."


@patch("src.api.v1.endpoints.models.AsyncResult")
def test_get_task_status_returns_ready_result(mock_async_result):
    task_result = Mock()
    task_result.status = "SUCCESS"
    task_result.result = {"model": "forecasting_v1"}
    task_result.ready.return_value = True
    mock_async_result.return_value = task_result

    response = client.get("/api/v1/models/tasks/task-123")

    assert response.status_code == 200
    assert response.json() == {
        "task_id": "task-123",
        "status": "SUCCESS",
        "result": {"model": "forecasting_v1"},
    }
    mock_async_result.assert_called_once()
    assert mock_async_result.call_args.args == ("task-123",)


@patch("src.api.v1.endpoints.models.AsyncResult")
def test_get_task_status_hides_result_until_task_is_ready(mock_async_result):
    task_result = Mock()
    task_result.status = "PENDING"
    task_result.result = RuntimeError("worker unavailable")
    task_result.ready.return_value = False
    mock_async_result.return_value = task_result

    response = client.get("/api/v1/models/tasks/task-456")

    assert response.status_code == 200
    assert response.json() == {
        "task_id": "task-456",
        "status": "PENDING",
        "result": None,
    }


def test_get_pipeline_logs_returns_paginated_logs():
    created_at = datetime(2026, 6, 8, 12, 0, tzinfo=timezone.utc)
    log_id = UUID("11111111-1111-1111-1111-111111111111")
    pipeline_log = SimpleNamespace(
        id=log_id,
        type=SimpleNamespace(name="Training"),
        status=SimpleNamespace(name="Success"),
        model_task="forecasting",
        mlflow_run_id="run-123",
        datasource_used="db",
        execution_time_ms=2400,
        created_at=created_at,
    )

    query = Mock()
    query.order_by.return_value = query
    query.offset.return_value = query
    query.limit.return_value = query
    query.all.return_value = [pipeline_log]

    db = Mock()
    db.query.return_value = query

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = client.get("/api/v1/models/logs/pipeline?limit=10&offset=5")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    data = response.json()
    assert data == {
        "limit": 10,
        "offset": 5,
        "logs": [
            {
                "id": str(log_id),
                "type": "Training",
                "model_task": "forecasting",
                "status": "Success",
                "mlflow_run_id": "run-123",
                "datasource_used": "db",
                "execution_time_ms": 2400,
                "timestamp": data["logs"][0]["timestamp"],
            }
        ],
    }
    assert data["logs"][0]["timestamp"].startswith("2026-06-08T12:00:00")
    query.offset.assert_called_once_with(5)
    query.limit.assert_called_once_with(10)
