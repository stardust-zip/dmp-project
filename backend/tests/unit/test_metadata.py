from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from src.api.v1.deps import get_current_user
from src.database import get_db
from src.main import app

client = TestClient(app)


class MockUser:
    email = "admin@vinsmart.com"
    role = "Admin"


@pytest.fixture(autouse=True)
def override_auth_dependencies():
    app.dependency_overrides[get_current_user] = lambda: MockUser()

    yield

    app.dependency_overrides.clear()


def _override_db_with_query_results(results_by_model):
    db = Mock()

    def query(model):
        query_mock = Mock()
        query_mock.filter.return_value = query_mock
        query_mock.order_by.return_value = query_mock
        query_mock.limit.return_value = query_mock
        query_mock.all.return_value = results_by_model[model]
        return query_mock

    db.query.side_effect = query

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    return db


def test_list_locations_returns_dropdown_metadata():
    from src.models import Location

    _override_db_with_query_results(
        {
            Location: [
                SimpleNamespace(
                    id="Panther_lodging_Cora",
                    parent_id="Panther",
                    name="Cora",
                    location_type_id="lodging",
                    metadata_={"sqm": 1000.5, "timezone": "UTC"},
                ),
                SimpleNamespace(
                    id="Panther_parking_Lorriane",
                    parent_id="Panther",
                    name="Lorriane",
                    location_type_id="parking",
                    metadata_=None,
                ),
            ]
        }
    )

    response = client.get("/api/v1/metadata/locations")

    assert response.status_code == 200
    assert response.json() == {
        "locations": [
            {
                "id": "Panther_lodging_Cora",
                "parent_id": "Panther",
                "name": "Cora",
                "location_type": "lodging",
                "metadata": {"sqm": 1000.5, "timezone": "UTC"},
                "archived": False,
            },
            {
                "id": "Panther_parking_Lorriane",
                "parent_id": "Panther",
                "name": "Lorriane",
                "location_type": "parking",
                "metadata": {},
                "archived": False,
            },
        ]
    }


def test_list_metrics_returns_dropdown_options():
    from src.models import MetricType

    _override_db_with_query_results(
        {
            MetricType: [
                SimpleNamespace(
                    id="electricity",
                    unit="kWh",
                    description="Electricity consumption",
                ),
                SimpleNamespace(
                    id="water",
                    unit="m3",
                    description="Water consumption",
                ),
            ]
        }
    )

    response = client.get("/api/v1/metadata/metrics")

    assert response.status_code == 200
    assert response.json() == {
        "metrics": [
            {
                "id": "electricity",
                "unit": "kWh",
                "description": "Electricity consumption",
            },
            {
                "id": "water",
                "unit": "m3",
                "description": "Water consumption",
            },
        ]
    }
