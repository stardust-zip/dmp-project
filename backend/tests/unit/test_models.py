from unittest.mock import patch

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
