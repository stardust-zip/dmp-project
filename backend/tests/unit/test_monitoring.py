"""Tests for monitoring services: PredictionLogger, PerformanceEvaluator, DriftDetector, HealthCalculator."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import numpy as np

from src.ml.monitoring.drift_detector import DriftDetector, _classify_psi_severity, _compute_psi
from src.ml.monitoring.health_calculator import (
    HealthCalculator,
    _drift_score_from_severity,
    _performance_score,
)
from src.ml.monitoring.performance_evaluator import PerformanceEvaluator, MAE_RATIO_WARNING, MAE_RATIO_CRITICAL
from src.ml.monitoring.prediction_logger import PredictionLogger


class FakeDB:
    def __init__(self):
        self.added = []
        self.commits = 0
        self.refreshed = []
        self.query_result = []

    def add(self, value):
        self.added.append(value)

    def commit(self):
        self.commits += 1

    def refresh(self, value):
        self.refreshed.append(value)

    def query(self, *args):
        query = MagicMock()
        query.filter.return_value.all.return_value = self.query_result
        return query


class TestComputePSI:
    def test_identical_distributions(self):
        ref = np.random.normal(0, 1, 1000)
        cur = ref.copy()
        psi = _compute_psi(ref, cur)
        assert psi < 0.01

    def test_different_distributions(self):
        ref = np.random.normal(0, 1, 1000)
        cur = np.random.normal(5, 1, 1000)
        psi = _compute_psi(ref, cur)
        assert psi > 0.1

    def test_empty_arrays(self):
        ref = np.array([1.0] * 10)
        cur = np.array([1.0] * 10)
        psi = _compute_psi(ref, cur)
        assert psi >= 0.0


class TestClassifyPSISeverity:
    def test_none(self):
        sev, msg = _classify_psi_severity(0.05)
        assert sev == "none"

    def test_low(self):
        sev, msg = _classify_psi_severity(0.15)
        assert sev == "low"

    def test_medium(self):
        sev, msg = _classify_psi_severity(0.22)
        assert sev == "medium"

    def test_high(self):
        sev, msg = _classify_psi_severity(0.3)
        assert sev == "high"


class TestPerformanceScore:
    def test_perfect(self):
        assert _performance_score(1.0) == 100.0

    def test_good(self):
        score = _performance_score(1.1)
        assert 50.0 < score < 100.0

    def test_warning(self):
        score = _performance_score(MAE_RATIO_WARNING)
        assert score == 50.0

    def test_critical(self):
        score = _performance_score(MAE_RATIO_CRITICAL)
        assert score == 0.0

    def test_unknown(self):
        assert _performance_score(None) == 50.0


class TestDriftScoreFromSeverity:
    def test_none(self):
        assert _drift_score_from_severity("none") == 100.0

    def test_low(self):
        assert _drift_score_from_severity("low") == 80.0

    def test_medium(self):
        assert _drift_score_from_severity("medium") == 50.0

    def test_high(self):
        assert _drift_score_from_severity("high") == 20.0

    def test_unknown(self):
        assert _drift_score_from_severity("unknown") == 50.0


class TestDriftDetector:
    def test_detect_data_drift_insufficient_data(self):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = []
        detector = DriftDetector()
        result = detector.detect_data_drift(
            mock_db, "test_model", "1",
            period_start=datetime.now(timezone.utc) - timedelta(hours=24),
            period_end=datetime.now(timezone.utc),
            feature_name="temp",
            reference_values=[1.0] * 5,
        )
        assert result is None

    def test_detect_prediction_drift(self):
        mock_db = MagicMock()
        now = datetime.now(timezone.utc)
        logs = []
        for i in range(20):
            log = MagicMock()
            log.predicted_value = 100.0 + i
            log.model_name = "test_model"
            log.model_version = "1"
            log.timestamp = now - timedelta(hours=i)
            logs.append(log)
        mock_db.query.return_value.filter.return_value.all.return_value = logs

        detector = DriftDetector()
        result = detector.detect_prediction_drift(
            mock_db, "test_model", "1",
            period_start=now - timedelta(hours=24),
            period_end=now,
            reference_predictions=[100.0 + i for i in range(20)],
        )
        assert result is not None
        assert result.drift_type == "prediction_drift"
        assert result.severity in ("none", "low", "medium", "high")


class TestHealthCalculator:
    def test_calculate_no_data(self):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
        mock_db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
        mock_db.query.return_value.filter.return_value.count.return_value = 0

        calc = HealthCalculator()
        result = calc.calculate(mock_db, "test_model", "1")
        assert result.health_score >= 0
        assert result.health_score <= 100
        assert result.status in ("healthy", "degraded", "critical")

    def test_calculate_healthy(self):
        mock_db = MagicMock()
        perf = MagicMock()
        perf.performance_ratio = 1.0
        perf.mae = 0.5
        perf.rmse = 0.7
        mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = perf
        mock_db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
        mock_db.query.return_value.filter.return_value.count.return_value = 10

        calc = HealthCalculator()
        result = calc.calculate(mock_db, "test_model", "1")
        assert result.health_score >= 70
        assert result.status == "healthy"


class TestPerformanceEvaluator:
    def test_safe_mape_no_zeros(self):
        actuals = np.array([10.0, 20.0, 30.0])
        predictions = np.array([11.0, 19.0, 31.0])
        mape = PerformanceEvaluator._safe_mape(actuals, predictions)
        assert mape is not None
        assert mape > 0

    def test_safe_mape_all_zeros(self):
        actuals = np.array([0.0, 0.0, 0.0])
        predictions = np.array([1.0, 2.0, 3.0])
        mape = PerformanceEvaluator._safe_mape(actuals, predictions)
        assert mape is None

    def test_evaluate_insufficient_data(self):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = []
        evaluator = PerformanceEvaluator()
        result = evaluator.evaluate(
            mock_db, "test_model", "1",
            period_start=datetime.now(timezone.utc) - timedelta(hours=24),
            period_end=datetime.now(timezone.utc),
        )
        assert result is None


class TestPredictionLogger:
    def test_log_prediction_persists_single_prediction_with_utc_timestamp(self):
        db = FakeDB()
        timestamp = datetime(2026, 6, 1, 12, 0)

        result = PredictionLogger().log_prediction(
            db,
            timestamp=timestamp,
            building_id="building-1",
            metric_type_id="electricity",
            predicted_value=42.5,
            mlflow_run_id="run-1",
            model_name="model-a",
            model_version="3",
            model_task="forecasting",
            feature_values={"hour": 12},
            prediction_context={"source": "unit-test"},
        )

        assert result is db.added[0]
        assert result.timestamp.tzinfo == timezone.utc
        assert result.building_id == "building-1"
        assert result.metric_type_id == "electricity"
        assert result.predicted_value == 42.5
        assert result.feature_values == {"hour": 12}
        assert result.prediction_context == {"source": "unit-test"}
        assert db.commits == 1
        assert db.refreshed == [result]

    def test_log_batch_persists_predictions_and_preserves_prefilled_actual_errors(self):
        db = FakeDB()
        timestamp = datetime(2026, 6, 1, 12, 0)

        logs = PredictionLogger().log_batch(
            db,
            [
                {
                    "timestamp": timestamp,
                    "building_id": "building-1",
                    "metric_type_id": "electricity",
                    "predicted_value": 40.0,
                    "actual_value": 42.0,
                    "error": 2.0,
                    "mlflow_run_id": "run-1",
                    "model_name": "model-a",
                    "model_version": "3",
                    "model_task": "forecasting",
                },
                {
                    "timestamp": timestamp.replace(hour=13, tzinfo=timezone.utc),
                    "building_id": "building-1",
                    "metric_type_id": "electricity",
                    "predicted_value": 41.0,
                    "mlflow_run_id": "run-1",
                    "model_name": "model-a",
                    "model_version": "3",
                    "model_task": "forecasting",
                    "prediction_context": {"source": "future"},
                },
            ],
        )

        assert logs == db.added
        assert len(logs) == 2
        assert logs[0].timestamp.tzinfo == timezone.utc
        assert logs[0].actual_value == 42.0
        assert logs[0].error == 2.0
        assert logs[1].actual_value is None
        assert logs[1].error is None
        assert logs[1].prediction_context == {"source": "future"}
        assert db.commits == 1
        assert db.refreshed == logs

    def test_log_batch_returns_empty_without_commit_when_no_predictions(self):
        db = FakeDB()

        assert PredictionLogger().log_batch(db, []) == []
        assert db.added == []
        assert db.commits == 0

    def test_fill_actuals_updates_matching_logs_and_computes_error(self):
        db = FakeDB()
        timestamp = datetime(2026, 6, 1, 12, 34, tzinfo=timezone.utc)
        log = MagicMock()
        log.timestamp = timestamp
        log.predicted_value = 10.0
        log.actual_value = None
        log.error = None
        db.query_result = [log]

        updated = PredictionLogger().fill_actuals(
            db,
            "building-1",
            "electricity",
            {datetime(2026, 6, 1, 12, tzinfo=timezone.utc): 12.5},
        )

        assert updated == 1
        assert log.actual_value == 12.5
        assert log.error == 2.5
        assert db.commits == 1

    def test_fill_actuals_does_not_commit_when_no_actuals_match(self):
        db = FakeDB()
        log = MagicMock()
        log.timestamp = datetime(2026, 6, 1, 13, tzinfo=timezone.utc)
        log.predicted_value = 10.0
        db.query_result = [log]

        updated = PredictionLogger().fill_actuals(
            db,
            "building-1",
            "electricity",
            {datetime(2026, 6, 1, 12, tzinfo=timezone.utc): 12.5},
        )

        assert updated == 0
        assert db.commits == 0
