"""Tests for monitoring API endpoints."""

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from src.api.v1.deps import get_current_ai_engineer_or_admin
from src.database import get_db
from src.main import app
from src.schemas import UserResponse

MOCK_VERSION = "1"


def performance_record(**overrides):
    values = {
        "id": uuid.uuid4(),
        "model_name": "test-model",
        "model_version": "1",
        "mlflow_run_id": "run-1",
        "model_task": "forecasting",
        "building_id": "building-1",
        "metric_type_id": "electricity",
        "period_start": datetime(2026, 6, 1, tzinfo=timezone.utc),
        "period_end": datetime(2026, 6, 2, tzinfo=timezone.utc),
        "sample_count": 12,
        "mae": 1.25,
        "rmse": 1.5,
        "mape": 2.5,
        "r2_score": 0.9,
        "mean_error": 0.1,
        "p10_error": 0.2,
        "p90_error": 2.0,
        "baseline_mae": 1.0,
        "baseline_rmse": 1.3,
        "performance_ratio": 1.25,
        "computed_at": datetime(2026, 6, 3, tzinfo=timezone.utc),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def drift_record(**overrides):
    values = {
        "id": uuid.uuid4(),
        "model_name": "test-model",
        "model_version": "1",
        "mlflow_run_id": "run-1",
        "model_task": "forecasting",
        "drift_type": "prediction_drift",
        "feature_name": None,
        "period_start": datetime(2026, 6, 1, tzinfo=timezone.utc),
        "period_end": datetime(2026, 6, 2, tzinfo=timezone.utc),
        "drift_score": 0.22,
        "drift_threshold": 0.2,
        "is_drifted": True,
        "severity": "medium",
        "reference_stats": {"mean": 10.0},
        "current_stats": {"mean": 12.0},
        "details": {"message": "Moderate drift"},
        "computed_at": datetime(2026, 6, 3, tzinfo=timezone.utc),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def chain_query(records):
    query = MagicMock()
    query.filter.return_value = query
    query.order_by.return_value = query
    query.limit.return_value = query
    query.all.return_value = records
    return query


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

    def test_get_performance_timeline_returns_records_and_applies_filters(
        self, client, mock_db
    ):
        query = chain_query([performance_record()])
        mock_db.query.return_value = query

        response = client.get(
            "/api/v1/models/test-model/monitoring/performance"
            "?model_version=1&period_start=2026-06-01T00:00:00Z"
            "&period_end=2026-06-30T00:00:00Z"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["model_name"] == "test-model"
        assert data["model_version"] == "1"
        assert len(data["metrics"]) == 1
        assert data["metrics"][0]["mae"] == 1.25
        assert data["metrics"][0]["performance_ratio"] == 1.25
        assert query.filter.call_count == 4


class TestDriftTimeline:
    def test_get_drift_timeline_empty(self, client, mock_db):
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
        response = client.get("/api/v1/models/test-model/monitoring/drift")
        assert response.status_code == 200
        data = response.json()
        assert data["model_name"] == "test-model"

    def test_get_drift_timeline_groups_overall_and_feature_drift(
        self, client, mock_db
    ):
        overall = drift_record()
        feature = drift_record(
            id=uuid.uuid4(),
            drift_type="data_drift",
            feature_name="temperature",
            drift_score=0.31,
            severity="high",
        )
        query = chain_query([overall, feature])
        mock_db.query.return_value = query

        response = client.get(
            "/api/v1/models/test-model/monitoring/drift"
            "?model_version=1&drift_type=data_drift"
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["overall_drift"]) == 1
        assert data["overall_drift"][0]["drift_type"] == "prediction_drift"
        assert list(data["feature_drift"]) == ["temperature"]
        assert data["feature_drift"]["temperature"][0]["severity"] == "high"
        assert query.filter.call_count == 3


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

    def test_get_alerts_returns_filtered_alert_payload(self, client, mock_db):
        query = chain_query([drift_record(severity="high", drift_score=0.44)])
        mock_db.query.return_value = query

        response = client.get(
            "/api/v1/models/test-model/monitoring/alerts"
            "?model_version=1&severity=high&limit=10"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["alerts"][0]["severity"] == "high"
        assert data["alerts"][0]["message"] == "Moderate drift"
        assert query.filter.call_count == 3
        query.limit.assert_called_once_with(10)


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

    @patch("src.api.v1.endpoints.monitoring.PerformanceEvaluator")
    def test_trigger_evaluation_with_version_falls_back_to_all_time(
        self, mock_evaluator_cls, client, mock_db
    ):
        record = performance_record()
        mock_evaluator = MagicMock()
        mock_evaluator.evaluate.side_effect = [None, record]
        mock_evaluator_cls.return_value = mock_evaluator

        response = client.post(
            "/api/v1/models/test-model/monitoring/evaluate"
            "?model_version=1&period_hours=24"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Evaluation completed successfully"
        assert data["mae"] == 1.25
        assert mock_evaluator.evaluate.call_count == 2
        assert "period_start" in mock_evaluator.evaluate.call_args_list[0].kwargs
        assert mock_evaluator.evaluate.call_args_list[1].kwargs == {}


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

    @patch("src.ml.monitoring.drift_detector.DriftDetector.detect_all_drifts")
    def test_trigger_drift_detection_filters_requested_type(
        self, mock_detect, client, mock_db
    ):
        mock_detect.return_value = [
            drift_record(drift_type="concept_drift", feature_name=None),
            drift_record(drift_type="prediction_drift", feature_name=None),
        ]

        response = client.post(
            "/api/v1/models/test-model/monitoring/drift/detect"
            "?model_version=1&drift_type=prediction_drift"
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["drift_reports"]) == 1
        assert data["drift_reports"][0]["drift_type"] == "prediction_drift"


class TestCompareVersions:
    def test_compare_versions_returns_available_version_metrics(self, client, mock_db):
        query_a = MagicMock()
        query_b = MagicMock()
        query_a.filter.return_value.order_by.return_value.first.return_value = (
            performance_record(model_version="1", mae=1.0)
        )
        query_b.filter.return_value.order_by.return_value.first.return_value = (
            performance_record(model_version="2", mae=0.8)
        )
        mock_db.query.side_effect = [query_a, query_b]

        response = client.get(
            "/api/v1/models/test-model/monitoring/compare"
            "?version_a=1&version_b=2"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["model_name"] == "test-model"
        assert [version["version"] for version in data["versions"]] == ["1", "2"]
        assert [version["mae"] for version in data["versions"]] == [1.0, 0.8]
        assert data["metrics"] == ["mae", "rmse", "mape", "r2_score"]
