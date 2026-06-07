from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient
from src.api.v1.deps import get_current_admin, get_current_user
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
    assert response.json()["message"] == "Training job queued successfully."
    mock_delay.assert_called_once_with(
        target_building_id="TestBuilding",
        metric_type="water",
    )


@patch("src.api.v1.endpoints.models._mlflow_client")
def test_get_model_versions_returns_run_ids_and_metrics(mock_mlflow_client):
    client_mock = Mock()
    client_mock.search_model_versions.return_value = [
        SimpleNamespace(
            name="forecasting_v1",
            version="1",
            run_id="run-1",
            tags={"active": "false"},
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
                "metrics": {"mae": 0.1, "rmse": 0.3},
                "tags": {"active": "false"},
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
