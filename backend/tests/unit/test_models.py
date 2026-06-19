import io
import os
import zipfile
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from mlflow.exceptions import MlflowException
from src.api.v1.deps import (
    get_current_admin,
    get_current_ai_engineer_or_admin,
    get_current_user,
)
from src.api.v1.endpoints.models import _sync_running_pipeline_log_with_celery
from src.database import get_db
from src.main import app
from src.models import Location, MetricType

client = TestClient(app)


class MockAdminUser:
    email = "admin@vinsmart.com"
    role = "Admin"


def get_mock_admin():
    return MockAdminUser()


def _override_training_validation_db(
    *,
    locations: set[str] | None = None,
    metrics: set[str] | None = None,
):
    known_locations = locations or {"TestBuilding", "SiteA", "BuildingA"}
    known_metrics = metrics or {"electricity", "water"}
    db = Mock()

    def query(column):
        query_mock = Mock()
        query_mock.filter.return_value = query_mock
        query_mock.order_by.return_value = query_mock
        if column is Location.id:
            query_mock.all.return_value = [(location,) for location in known_locations]
            query_mock.one_or_none.side_effect = lambda: (
                ("location",)
                if _query_filter_contains(query_mock, known_locations)
                else None
            )
        elif column is MetricType.id:
            query_mock.all.return_value = [(metric,) for metric in known_metrics]
        else:
            query_mock.one_or_none.return_value = None
            query_mock.all.return_value = []
        return query_mock

    db.query.side_effect = query

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    return db


def _query_filter_contains(query_mock: Mock, values: set[str]) -> bool:
    filter_arg = query_mock.filter.call_args.args[0]
    compared_value = getattr(getattr(filter_arg, "right", None), "value", None)
    return compared_value in values


@pytest.fixture(autouse=True)
def override_auth_dependencies():
    app.dependency_overrides[get_current_admin] = get_mock_admin
    app.dependency_overrides[get_current_user] = get_mock_admin
    _override_training_validation_db()

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
    assert training_request["building_id"] == "TestBuilding"
    assert training_request["metrics"] == ["water"]
    assert training_request["data_source"] == "csv"
    assert training_request["model_task"] == "forecasting"
    assert "algorithm" not in training_request
    assert response.json()["algorithm"] == "xgboost"


@patch("src.api.v1.endpoints.models.train_model_task.delay")
def test_trigger_training_queues_anomaly_training(mock_delay):
    class MockTask:
        id = "mock-anomaly-task-456"

    mock_delay.return_value = MockTask()

    response = client.post(
        "/api/v1/models/train"
        "?building_id=TestBuilding&metric_type=water"
        "&model_task=anomaly_detection&data_source=db"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["task_id"] == "mock-anomaly-task-456"
    assert body["model_task"] == "anomaly_detection"
    assert body["algorithm"] == "lightgbm"
    assert body["message"] == "anomaly_detection training job queued using db data."
    training_request = mock_delay.call_args.kwargs["training_request"]
    assert training_request["model_task"] == "anomaly_detection"
    assert training_request["data_source"] == "db"
    mock_delay.assert_called_once()


@patch("src.api.v1.endpoints.models.train_model_task.delay")
def test_trigger_training_accepts_global_forecasting_payload(mock_delay):
    class MockTask:
        id = "mock-task-uuid-789"

    mock_delay.return_value = MockTask()

    payload = {
        "metrics": [" electricity "],
        "time_range_start": "2026-06-01T00:00:00Z",
        "time_range_end": "2026-06-07T00:00:00Z",
        "model_task": "forecasting",
        "data_source": "csv",
        "csv_path": "/tmp/site-a.csv",
    }

    response = client.post("/api/v1/models/train", json=payload)

    assert response.status_code == 200
    assert response.json()["model_task"] == "forecasting"
    assert response.json()["site_id"] is None
    assert response.json()["building_id"] is None
    assert response.json()["metrics"] == ["electricity"]
    assert response.json()["algorithm"] == "xgboost"
    training_request = mock_delay.call_args.kwargs["training_request"]
    assert training_request["csv_path"] == "/tmp/site-a.csv"
    assert "algorithm" not in training_request


@patch("src.api.v1.endpoints.models.train_model_task.delay")
def test_trigger_training_rejects_multi_metric_forecasting(mock_delay):
    payload = {
        "metrics": ["electricity", "water"],
        "time_range_start": "2026-06-01T00:00:00Z",
        "time_range_end": "2026-06-07T00:00:00Z",
        "model_task": "forecasting",
        "data_source": "csv",
    }

    response = client.post("/api/v1/models/train", json=payload)

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "forecasting training requires exactly one metric per model."
    )
    mock_delay.assert_not_called()


@patch("src.api.v1.endpoints.models.train_model_task.delay")
def test_trigger_training_forecasting_accepts_algorithm_selection(mock_delay):
    class MockTask:
        id = "mock-fc-task-001"

    mock_delay.return_value = MockTask()

    payload = {
        "metrics": ["electricity"],
        "time_range_start": "2026-06-01T00:00:00Z",
        "time_range_end": "2026-06-07T00:00:00Z",
        "model_task": "forecasting",
        "data_source": "csv",
        "algorithm": "lightgbm",
    }

    response = client.post("/api/v1/models/train", json=payload)

    assert response.status_code == 200
    assert response.json()["model_task"] == "forecasting"
    assert response.json()["algorithm"] == "lightgbm"
    training_request = mock_delay.call_args.kwargs["training_request"]
    assert training_request["algorithm"] == "lightgbm"
    assert training_request["model_task"] == "forecasting"


@patch("src.api.v1.endpoints.models.train_model_task.delay")
def test_trigger_training_rejects_unknown_location(mock_delay):
    _override_training_validation_db(locations={"KnownBuilding"})

    payload = {
        "site_id": "MissingBuilding",
        "metrics": ["electricity"],
        "time_range_start": "2026-06-01T00:00:00Z",
        "time_range_end": "2026-06-07T00:00:00Z",
        "model_task": "forecasting",
        "data_source": "csv",
    }

    response = client.post("/api/v1/models/train", json=payload)

    assert response.status_code == 422
    assert response.json()["detail"] == "Unknown site/building: MissingBuilding"
    mock_delay.assert_not_called()


@patch("src.api.v1.endpoints.models.train_model_task.delay")
def test_trigger_training_rejects_unknown_metrics(mock_delay):
    _override_training_validation_db(metrics={"electricity"})

    payload = {
        "site_id": "SiteA",
        "metrics": ["electricity", "steam"],
        "time_range_start": "2026-06-01T00:00:00Z",
        "time_range_end": "2026-06-07T00:00:00Z",
        "model_task": "forecasting",
        "data_source": "csv",
    }

    response = client.post("/api/v1/models/train", json=payload)

    assert response.status_code == 422
    assert response.json()["detail"] == "Unknown metric(s): steam"
    mock_delay.assert_not_called()


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
    production_version = SimpleNamespace(
        version=2,
        run_id="run-2",
        current_stage="None",
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
    client_mock.get_model_version_by_alias.return_value = production_version
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
                "production_version": {
                    "version": "2",
                    "run_id": "run-2",
                    "current_stage": "None",
                    "status": "READY",
                },
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
def test_update_model_description_updates_registered_model(mock_mlflow_client):
    updated_model = SimpleNamespace(
        name="forecasting_v1",
        description="Business-facing description",
    )
    client_mock = Mock()
    client_mock.update_registered_model.return_value = updated_model
    mock_mlflow_client.return_value = client_mock

    response = client.patch(
        "/api/v1/models/forecasting_v1/description",
        json={"description": "  Business-facing description  "},
    )

    assert response.status_code == 200
    assert response.json() == {
        "name": "forecasting_v1",
        "description": "Business-facing description",
        "updated_by": "admin@vinsmart.com",
    }
    client_mock.update_registered_model.assert_called_once_with(
        name="forecasting_v1",
        description="Business-facing description",
    )


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


@patch("src.api.v1.endpoints.models.mark_pipeline_log_external_failure")
@patch("src.api.v1.endpoints.models.AsyncResult")
def test_sync_running_pipeline_log_marks_failed_celery_task(
    mock_async_result,
    mock_mark_failure,
):
    task_result = Mock()
    task_result.status = "FAILURE"
    task_result.result = RuntimeError("Worker exited prematurely: signal 9 (SIGKILL)")
    mock_async_result.return_value = task_result
    mock_mark_failure.return_value = True
    pipeline_log = SimpleNamespace(
        status="Running",
        celery_task_id="task-123",
    )

    synced = _sync_running_pipeline_log_with_celery(pipeline_log)

    assert synced is True
    mock_async_result.assert_called_once()
    mock_mark_failure.assert_called_once()
    assert mock_mark_failure.call_args.args[0] == "task-123"
    assert "SIGKILL" in str(mock_mark_failure.call_args.args[1])
    assert mock_mark_failure.call_args.kwargs["task_state"] == "FAILURE"


def test_get_pipeline_logs_returns_paginated_logs():
    created_at = datetime(2026, 6, 8, 12, 0, tzinfo=timezone.utc)
    log_id = UUID("11111111-1111-1111-1111-111111111111")
    pipeline_log = SimpleNamespace(
        id=log_id,
        type=SimpleNamespace(name="Training"),
        status=SimpleNamespace(name="Success"),
        model_task="forecasting",
        mlflow_run_id="run-123",
        celery_task_id="task-123",
        datasource_used="db",
        execution_time_ms=2400,
        created_at=created_at,
        terminal_log="[2026-06-08T12:00:00+00:00] Pipeline finished successfully.",
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
                "celery_task_id": "task-123",
                "datasource_used": "db",
                "execution_time_ms": 2400,
                "timestamp": data["logs"][0]["timestamp"],
                "terminal_log": "[2026-06-08T12:00:00+00:00] Pipeline finished successfully.",
            }
        ],
    }
    assert data["logs"][0]["timestamp"].startswith("2026-06-08T12:00:00")
    query.offset.assert_called_once_with(5)
    query.limit.assert_called_once_with(10)


# ---------------------------------------------------------------------------
# download_model
# ---------------------------------------------------------------------------


def _fake_run_artifacts(run_id: str, path: str, dst_path: str) -> str:
    """Side-effect that creates dummy run artifacts under dst_path."""
    artifacts_dir = os.path.join(dst_path, "artifacts")
    os.makedirs(artifacts_dir, exist_ok=True)
    with open(os.path.join(artifacts_dir, "resid_stats.parquet"), "wb") as f:
        f.write(b"parquet data")
    return dst_path


def _fake_model_artifacts(artifact_uri: str = "", dst_path: str = "") -> str:
    """Side-effect that creates dummy registered model files under dst_path."""
    with open(os.path.join(dst_path, "MLmodel"), "w") as f:
        f.write("mlflow artifact metadata")
    model_dir = os.path.join(dst_path, "model")
    os.makedirs(model_dir, exist_ok=True)
    with open(os.path.join(model_dir, "model.pkl"), "w") as f:
        f.write("dummy model binary")
    return dst_path


@patch("src.api.v1.endpoints.models._mlflow_client")
@patch("mlflow.artifacts.download_artifacts")
def test_download_model_returns_zip_with_all_artifacts(mock_model_artifacts, mock_mlflow_client):
    """Successful download returns a valid zip containing both run and model artifacts."""
    client_mock = Mock()
    client_mock.get_model_version.return_value = SimpleNamespace(
        name="energy_forecast",
        version="3",
        run_id="run-def456",
    )
    client_mock.download_artifacts.side_effect = _fake_run_artifacts
    mock_model_artifacts.side_effect = _fake_model_artifacts
    mock_mlflow_client.return_value = client_mock

    response = client.get("/api/v1/models/energy_forecast/versions/3/download")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    expected_disposition = 'attachment; filename="energy_forecast_v3.zip"'
    assert response.headers["content-disposition"] == expected_disposition

    zip_buf = io.BytesIO(response.content)
    with zipfile.ZipFile(zip_buf) as zf:
        names = sorted(zf.namelist())
        assert names == [
            "MLmodel",
            "artifacts/",
            "artifacts/resid_stats.parquet",
            "model/",
            "model/model.pkl",
        ]
        with zf.open("MLmodel") as f:
            assert f.read().decode() == "mlflow artifact metadata"

    client_mock.get_model_version.assert_called_once_with("energy_forecast", "3")
    client_mock.download_artifacts.assert_called_once()
    assert client_mock.download_artifacts.call_args.args[0] == "run-def456"
    mock_model_artifacts.assert_called_once()
    assert mock_model_artifacts.call_args.kwargs["artifact_uri"] == "models:/energy_forecast/3"


@patch("src.api.v1.endpoints.models._mlflow_client")
def test_download_model_404_when_version_not_in_registry(mock_mlflow_client):
    """Returns 404 when MLflow has no such model version."""
    client_mock = Mock()
    client_mock.get_model_version.side_effect = MlflowException(
        "Model version 99 not found"
    )
    mock_mlflow_client.return_value = client_mock

    response = client.get("/api/v1/models/nonexistent/versions/99/download")

    assert response.status_code == 404
    assert "Model version not found" in response.json()["detail"]


@patch("src.api.v1.endpoints.models._mlflow_client")
def test_download_model_404_when_version_has_no_run_id(mock_mlflow_client):
    """Returns 404 when the model version has no associated run ID."""
    client_mock = Mock()
    client_mock.get_model_version.return_value = SimpleNamespace(
        name="orphan",
        version="1",
        run_id=None,
    )
    mock_mlflow_client.return_value = client_mock

    response = client.get("/api/v1/models/orphan/versions/1/download")

    assert response.status_code == 404
    assert "no associated run id" in response.json()["detail"].lower()


def test_download_model_403_for_operator_user():
    """Operators cannot download models."""

    class MockOperator:
        email = "operator@vinsmart.com"
        role = "Operator"

    app.dependency_overrides[get_current_user] = lambda: MockOperator()
    app.dependency_overrides.pop(get_current_admin, None)
    app.dependency_overrides.pop(get_current_ai_engineer_or_admin, None)
    try:
        response = client.get("/api/v1/models/some_model/versions/1/download")
    finally:
        app.dependency_overrides.clear()
        # Restore auth overrides that the autouse fixture provides
        app.dependency_overrides[get_current_admin] = get_mock_admin
        app.dependency_overrides[get_current_user] = get_mock_admin
        _override_training_validation_db()

    assert response.status_code == 403
