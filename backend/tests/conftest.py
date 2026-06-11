import uuid

import pytest
from fastapi.testclient import TestClient
from src.api.v1.deps import get_current_admin, get_current_user
from src.main import app
from src.schemas import UserResponse


@pytest.fixture
def client():
    """A standard unauthenticated client."""
    return TestClient(app)


@pytest.fixture
def mock_admin_user():
    return UserResponse(
        id=str(uuid.uuid4()),
        email="admin_test@dmp.com",
        full_name="Test Admin",
        role="Admin",
        is_global_admin=True,
    )


@pytest.fixture
def mock_operator_user():
    return UserResponse(
        id=str(uuid.uuid4()),
        email="operator_test@dmp.com",
        full_name="Test Operator",
        role="Operator",
        assigned_site_ids=["site-a"],
    )


@pytest.fixture
def admin_client(client, mock_admin_user):
    app.dependency_overrides[get_current_user] = lambda: mock_admin_user
    app.dependency_overrides[get_current_admin] = lambda: mock_admin_user

    yield client

    app.dependency_overrides.clear()


@pytest.fixture
def operator_client(client, mock_operator_user):
    app.dependency_overrides[get_current_user] = lambda: mock_operator_user
    yield client
    app.dependency_overrides.clear()
