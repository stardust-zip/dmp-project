"""Tests for monitoring API endpoints."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from src.api.v1.deps import get_current_ai_engineer_or_admin
from src.database import get_db
from src.main import app
from src.schemas import UserResponse

MOCK_VERSION = "1"


@pytest.fixture
def mock_user():
    return UserResponse(
        id=str(uuid.uuid4()),
        email="test@example.com",
        full_name="Test User",
        role="AI_Engineer",
        status="active",
        contact_number=None,
        assigned_site_ids=[],
        is_global_admin=False,
    )


@pytest.fixture
def mock_db():
    return MagicMock()


@pytest.fixture(autouse=True)
def mock_mlflow():
    """Prevent any real MLflow network calls during tests.

    _resolve_model_version creates a real MlflowClient and calls
    search_model_versions, which hangs when the MLflow server is
    unreachable.  This autouse fixture patches it globally so no test
    accidentally makes a live connection.
    """
    with patch(
        "src.api.v1.endpoints.monitoring._resolve_model_version",
        return_value=MOCK_VERSION,
    ):
        yield


@pytest.fixture
def client(mock_db, mock_user):
    def override_get_db():
        yield mock_db

    def override_get_user():
        return mock_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_ai_engineer_or_admin] = override_get_user
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


class TestPerformanceTimeline:
    def test_get_performance_timeline_empty(self, client, mock_db):
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
        response = client.get("/api/v1/models/test-model/monitoring/performance")
        assert response.status_code == 200
        data = response.json()
        assert data["model_name"] == "test-model"
        assert data["metrics"] == []


class TestDriftTimeline:
    def test_get_drift_timeline_empty(self, client, mock_db):
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
        response = client.get("/api/v1/models/test-model/monitoring/drift")
        assert response.status_code == 200
        data = response.json()
        assert data["model_name"] == "test-model"


class TestMonitoringSummary:
    @patch("src.ml.monitoring.health_calculator.HealthCalculator.calculate")
    def test_get_summary(self, mock_calculate, client, mock_db):
        from src.ml.monitoring.health_calculator import HealthResult

        mock_calculate.return_value = HealthResult(
            health_score=85.0,
            status="healthy",
            performance_score=90.0,
            data_drift_score=100.0,
            concept_drift_score=100.0,
            prediction_drift_score=100.0,
            total_predictions=100,
            pending_actuals=10,
            latest_performance=None,
            active_drifts=[],
        )
        response = client.get("/api/v1/models/test-model/monitoring/summary")
        assert response.status_code == 200
        data = response.json()
        assert data["health_score"] == 85.0
        assert data["status"] == "healthy"


class TestMonitoringAlerts:
    def test_get_alerts_empty(self, client, mock_db):
        mock_db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
        response = client.get("/api/v1/models/test-model/monitoring/alerts")
        assert response.status_code == 200
        data = response.json()
        assert data["alerts"] == []
        assert data["total"] == 0


class TestTriggerEvaluation:
    @patch("src.api.v1.endpoints.monitoring.PerformanceEvaluator")
    def test_trigger_evaluation_no_model_version(
        self, mock_evaluator_cls, client, mock_db
    ):
        mock_evaluator = MagicMock()
        mock_evaluator.evaluate_all_models.return_value = []
        mock_evaluator_cls.return_value = mock_evaluator
        response = client.post("/api/v1/models/test-model/monitoring/evaluate")
        assert response.status_code == 200
        data = response.json()
        assert "message" in data


class TestTriggerDriftDetection:
    @patch("src.ml.monitoring.drift_detector.DriftDetector.detect_all_drifts")
    def test_trigger_drift_detection(self, mock_detect, client, mock_db):
        mock_detect.return_value = []
        response = client.post(
            "/api/v1/models/test-model/monitoring/drift/detect?model_version=1"
        )
        assert response.status_code == 200
        data = response.json()
        assert "message" in data
