from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
from src.ml.monitoring.health_calculator import HealthResult
from src.ml.training import algorithm_for_task
from src.schemas import MLAlgorithm, ModelTask, ModelTrainingRequest
from src.tasks import (
    _external_task_failure_message,
    _finalize_prediction_training_frame,
    _not_implemented_training_response,
    _prediction_building_ids,
    _registered_model_name,
    check_alerts_task,
    detect_model_drift_task,
    evaluate_model_performance_task,
    fill_prediction_actuals_task,
)


def test_registered_model_name_uses_global_forecasting_model():
    request = ModelTrainingRequest(
        metrics=[" Electricity "],
        time_range_start="2026-06-01T00:00:00Z",
        time_range_end="2026-06-02T00:00:00Z",
    )

    assert _registered_model_name(request) == "dmp_energy_forecasting"


def test_registered_model_name_uses_global_anomaly_model():
    request = ModelTrainingRequest(
        metrics=["electricity"],
        time_range_start="2026-06-01T00:00:00Z",
        time_range_end="2026-06-02T00:00:00Z",
        model_task="anomaly_detection",
    )

    assert _registered_model_name(request) == "dmp_energy_anomaly_detection"


def test_registered_model_name_separates_sites_and_metrics():
    site_1_electricity = ModelTrainingRequest(
        site_id="Site 1",
        metrics=["electricity"],
        time_range_start="2026-06-01T00:00:00Z",
        time_range_end="2026-06-02T00:00:00Z",
        model_task="prediction",
    )
    site_2_steam = ModelTrainingRequest(
        site_id="Site 2",
        metrics=["steam"],
        time_range_start="2026-06-01T00:00:00Z",
        time_range_end="2026-06-02T00:00:00Z",
        model_task="prediction",
    )

    assert _registered_model_name(site_1_electricity) != _registered_model_name(
        site_2_steam
    )


def test_algorithm_for_task_returns_expected_defaults():
    assert algorithm_for_task(ModelTask.Prediction) == MLAlgorithm.RandomForest
    assert algorithm_for_task(ModelTask.Forecasting) == MLAlgorithm.XGBoost
    assert algorithm_for_task(ModelTask.AnomalyDetection) == MLAlgorithm.LightGBM


def test_external_task_failure_message_explains_sigkill_memory_risk():
    message = _external_task_failure_message(
        RuntimeError("Worker exited prematurely: signal 9 (SIGKILL)")
    )

    assert "Pipeline failed outside the task handler" in message
    assert "memory pressure" in message


def test_non_prediction_training_response_is_explicitly_not_implemented():
    request = ModelTrainingRequest(
        site_id="SiteA",
        metrics=["electricity"],
        time_range_start="2026-06-01T00:00:00Z",
        time_range_end="2026-06-02T00:00:00Z",
        model_task="forecasting",
    )

    response = _not_implemented_training_response(
        request,
        MLAlgorithm.RandomForest,
    )

    assert response["implemented"] is False
    assert response["message"] == "forecasting training pipeline is not implemented yet."
    assert response["scores"] == {}
    assert response["mlflow_run_id"] is None


def test_prediction_building_ids_selects_site_children():
    request = ModelTrainingRequest(
        site_id="SiteA",
        metrics=["electricity"],
        time_range_start="2026-06-01T00:00:00Z",
        time_range_end="2026-06-02T00:00:00Z",
        model_task="prediction",
    )
    metadata_df = pd.DataFrame(
        {
            "building_id": ["BuildingA", "BuildingB", "BuildingC"],
            "site_id": ["SiteA", "SiteA", "SiteB"],
            "primaryspaceusage": ["Office", "Education", "Retail"],
            "sqm": [100.0, 200.0, 300.0],
        }
    )

    assert _prediction_building_ids(request, metadata_df) == [
        "BuildingA",
        "BuildingB",
    ]


def test_finalize_prediction_training_frame_adds_model_features():
    readings_df = pd.DataFrame(
        {
            "timestamp": [
                datetime(2026, 6, 1, 8, tzinfo=timezone.utc),
                datetime(2026, 6, 1, 9, tzinfo=timezone.utc),
            ],
            "building_id": ["BuildingA", "BuildingA"],
            "metric_type": ["electricity", "electricity"],
            "meter_reading": ["10.5", "11.5"],
        }
    )
    metadata_df = pd.DataFrame(
        {
            "building_id": ["BuildingA"],
            "primaryspaceusage": ["Office"],
            "sqm": [100.0],
        }
    )

    result = _finalize_prediction_training_frame(readings_df, metadata_df)

    assert list(result["hour"]) == [8, 9]
    assert list(result["day_of_week"]) == [0, 0]
    assert list(result["month"]) == [6, 6]
    assert list(result["closing_hour"]) == [18, 18]
    assert list(result["is_open"]) == [1, 1]
    assert list(result["meter_reading"]) == [10.5, 11.5]
    assert result["primaryspaceusage"].tolist() == ["Office", "Office"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _chainable_query(*all_side_effects) -> tuple[MagicMock, MagicMock]:
    """Return (db_mock, query_chain) where every chaining method loops back to
    the same query_chain object.

    ``db.query(...)`` returns query_chain, so every sub-call
    (.filter / .join / .distinct / .order_by) also returns query_chain.
    ``.all()`` consumes side_effects in order across all query calls.
    """
    chain = MagicMock()
    chain.filter.return_value = chain
    chain.distinct.return_value = chain
    chain.order_by.return_value = chain
    chain.join.return_value = chain
    chain.all.side_effect = list(all_side_effects)

    db = MagicMock()
    db.query.return_value = chain
    return db, chain


# ---------------------------------------------------------------------------
# fill_prediction_actuals_task
# ---------------------------------------------------------------------------


class TestFillPredictionActualsTask:
    def test_no_unfilled_pairs_returns_zero_updated(self):
        mock_db, _ = _chainable_query([])  # pairs query → empty

        with (
            patch("src.tasks.SessionLocal", return_value=mock_db),
            patch("src.tasks.PredictionLogger"),
        ):
            result = fill_prediction_actuals_task.apply(kwargs={"hours_lookback": 24}).get()

        assert result["updated_count"] == 0
        assert result["pairs_checked"] == 0

    def test_pairs_without_matching_telemetry_are_skipped(self):
        mock_db, _ = _chainable_query(
            [("BuildingA", "electricity")],  # first .all() → pairs
            [],                               # second .all() → no telemetry
        )

        mock_logger = MagicMock()
        with (
            patch("src.tasks.SessionLocal", return_value=mock_db),
            patch("src.tasks.PredictionLogger", return_value=mock_logger),
        ):
            result = fill_prediction_actuals_task.apply(kwargs={"hours_lookback": 24}).get()

        assert result["updated_count"] == 0
        assert result["pairs_checked"] == 1
        mock_logger.fill_actuals.assert_not_called()

    def test_pairs_with_telemetry_call_fill_actuals_and_aggregate_count(self):
        telemetry_row = MagicMock()
        telemetry_row.timestamp = datetime(2026, 6, 1, 8, tzinfo=timezone.utc)
        telemetry_row.value = 110.0

        mock_db, _ = _chainable_query(
            [("BuildingA", "electricity")],  # first .all() → pairs
            [telemetry_row],                  # second .all() → telemetry
        )

        mock_logger = MagicMock()
        mock_logger.fill_actuals.return_value = 3

        with (
            patch("src.tasks.SessionLocal", return_value=mock_db),
            patch("src.tasks.PredictionLogger", return_value=mock_logger),
        ):
            result = fill_prediction_actuals_task.apply(kwargs={"hours_lookback": 24}).get()

        assert result["updated_count"] == 3
        mock_logger.fill_actuals.assert_called_once()

    def test_db_session_is_always_closed(self):
        mock_db, _ = _chainable_query([])

        with (
            patch("src.tasks.SessionLocal", return_value=mock_db),
            patch("src.tasks.PredictionLogger"),
        ):
            fill_prediction_actuals_task.apply(kwargs={"hours_lookback": 24}).get()

        mock_db.close.assert_called_once()


# ---------------------------------------------------------------------------
# evaluate_model_performance_task
# ---------------------------------------------------------------------------


class TestEvaluateModelPerformanceTask:
    def test_delegates_to_evaluator_and_returns_count(self):
        mock_db = MagicMock()
        mock_evaluator = MagicMock()
        mock_evaluator.evaluate_all_models.return_value = [MagicMock(), MagicMock()]

        with (
            patch("src.tasks.SessionLocal", return_value=mock_db),
            patch("src.tasks.PerformanceEvaluator", return_value=mock_evaluator),
        ):
            result = evaluate_model_performance_task.apply(kwargs={"period_hours": 24}).get()

        assert result["evaluated_models"] == 2
        assert result["period_hours"] == 24
        mock_evaluator.evaluate_all_models.assert_called_once_with(mock_db, period_hours=24)

    def test_zero_records_when_evaluator_finds_nothing(self):
        mock_db = MagicMock()
        mock_evaluator = MagicMock()
        mock_evaluator.evaluate_all_models.return_value = []

        with (
            patch("src.tasks.SessionLocal", return_value=mock_db),
            patch("src.tasks.PerformanceEvaluator", return_value=mock_evaluator),
        ):
            result = evaluate_model_performance_task.apply(kwargs={"period_hours": 12}).get()

        assert result["evaluated_models"] == 0

    def test_db_session_is_always_closed(self):
        mock_db = MagicMock()
        mock_evaluator = MagicMock()
        mock_evaluator.evaluate_all_models.return_value = []

        with (
            patch("src.tasks.SessionLocal", return_value=mock_db),
            patch("src.tasks.PerformanceEvaluator", return_value=mock_evaluator),
        ):
            evaluate_model_performance_task.apply().get()

        mock_db.close.assert_called_once()


# ---------------------------------------------------------------------------
# detect_model_drift_task
# ---------------------------------------------------------------------------


class TestDetectModelDriftTask:
    def test_no_model_pairs_returns_zero_reports_and_scores(self):
        mock_db, _ = _chainable_query([])  # distinct pairs query → empty

        mock_calculator = MagicMock()
        mock_calculator.calculate_all_models.return_value = {}

        with (
            patch("src.tasks.SessionLocal", return_value=mock_db),
            patch("src.tasks.DriftDetector"),
            patch("src.tasks.HealthCalculator", return_value=mock_calculator),
        ):
            result = detect_model_drift_task.apply(kwargs={"period_hours": 168}).get()

        assert result["drift_reports"] == 0
        assert result["health_scores"] == 0
        assert result["period_hours"] == 168

    def test_drift_detector_is_called_per_model_pair(self):
        pairs = [
            ("model_a", "1", "forecasting", "run-001"),
            ("model_b", "2", "forecasting", "run-002"),
        ]
        mock_db, _ = _chainable_query(pairs)

        mock_detector = MagicMock()
        mock_detector.detect_all_drifts.return_value = [MagicMock()]

        mock_calculator = MagicMock()
        mock_calculator.calculate_all_models.return_value = {}

        with (
            patch("src.tasks.SessionLocal", return_value=mock_db),
            patch("src.tasks.DriftDetector", return_value=mock_detector),
            patch("src.tasks.HealthCalculator", return_value=mock_calculator),
        ):
            result = detect_model_drift_task.apply(kwargs={"period_hours": 168}).get()

        assert mock_detector.detect_all_drifts.call_count == 2
        assert result["drift_reports"] == 2  # 1 report per pair × 2 pairs

    def test_health_scores_reflect_calculate_all_models_result(self):
        mock_db, _ = _chainable_query([])

        mock_calculator = MagicMock()
        mock_calculator.calculate_all_models.return_value = {"m:1": MagicMock(), "m:2": MagicMock()}

        with (
            patch("src.tasks.SessionLocal", return_value=mock_db),
            patch("src.tasks.DriftDetector"),
            patch("src.tasks.HealthCalculator", return_value=mock_calculator),
        ):
            result = detect_model_drift_task.apply().get()

        assert result["health_scores"] == 2

    def test_drift_detection_error_per_model_does_not_abort_task(self):
        """A failure on one model pair must not prevent processing remaining pairs."""
        pairs = [
            ("model_ok", "1", "forecasting", "run-ok"),
            ("model_bad", "2", "forecasting", "run-bad"),
        ]
        mock_db, _ = _chainable_query(pairs)

        mock_detector = MagicMock()
        mock_detector.detect_all_drifts.side_effect = [
            RuntimeError("MLflow unreachable"),  # first pair fails
            [MagicMock()],                        # second pair succeeds
        ]

        mock_calculator = MagicMock()
        mock_calculator.calculate_all_models.return_value = {}

        with (
            patch("src.tasks.SessionLocal", return_value=mock_db),
            patch("src.tasks.DriftDetector", return_value=mock_detector),
            patch("src.tasks.HealthCalculator", return_value=mock_calculator),
        ):
            result = detect_model_drift_task.apply().get()

        assert result["drift_reports"] == 1  # only the successful pair counted


# ---------------------------------------------------------------------------
# check_alerts_task
# ---------------------------------------------------------------------------


class TestCheckAlertsTask:
    def _make_health_result(self, status: str, score: float, active_drifts=None):
        result = MagicMock()
        result.status = status
        result.health_score = score
        result.active_drifts = active_drifts or []
        return result

    def test_no_models_returns_zero_alerts(self):
        mock_db = MagicMock()
        mock_calculator = MagicMock()
        mock_calculator.calculate_all_models.return_value = {}

        with (
            patch("src.tasks.SessionLocal", return_value=mock_db),
            patch("src.tasks.HealthCalculator", return_value=mock_calculator),
        ):
            result = check_alerts_task.apply().get()

        assert result["total_alerts"] == 0
        assert result["alerts"] == []
        assert result["models_checked"] == 0

    def test_critical_model_generates_an_alert(self):
        mock_db = MagicMock()
        mock_calculator = MagicMock()
        mock_calculator.calculate_all_models.return_value = {
            "dmp_model:1": self._make_health_result("critical", 35.0),
        }

        with (
            patch("src.tasks.SessionLocal", return_value=mock_db),
            patch("src.tasks.HealthCalculator", return_value=mock_calculator),
        ):
            result = check_alerts_task.apply().get()

        assert result["total_alerts"] == 1
        assert result["alerts"][0]["status"] == "critical"
        assert result["models_checked"] == 1

    def test_degraded_model_generates_an_alert(self):
        mock_db = MagicMock()
        mock_calculator = MagicMock()
        mock_calculator.calculate_all_models.return_value = {
            "dmp_model:2": self._make_health_result("degraded", 65.0),
        }

        with (
            patch("src.tasks.SessionLocal", return_value=mock_db),
            patch("src.tasks.HealthCalculator", return_value=mock_calculator),
        ):
            result = check_alerts_task.apply().get()

        assert result["total_alerts"] == 1
        assert result["alerts"][0]["status"] == "degraded"

    def test_healthy_model_generates_no_alert(self):
        mock_db = MagicMock()
        mock_calculator = MagicMock()
        mock_calculator.calculate_all_models.return_value = {
            "dmp_model:3": self._make_health_result("healthy", 90.0),
        }

        with (
            patch("src.tasks.SessionLocal", return_value=mock_db),
            patch("src.tasks.HealthCalculator", return_value=mock_calculator),
        ):
            result = check_alerts_task.apply().get()

        assert result["total_alerts"] == 0

    def test_active_high_severity_drift_generates_additional_alert(self):
        drift = MagicMock()
        drift.severity = "high"
        drift.drift_type = "prediction_drift"
        drift.drift_score = 0.35

        mock_db = MagicMock()
        mock_calculator = MagicMock()
        mock_calculator.calculate_all_models.return_value = {
            "dmp_model:1": self._make_health_result("healthy", 80.0, active_drifts=[drift]),
        }

        with (
            patch("src.tasks.SessionLocal", return_value=mock_db),
            patch("src.tasks.HealthCalculator", return_value=mock_calculator),
        ):
            result = check_alerts_task.apply().get()

        drift_alerts = [a for a in result["alerts"] if "drift_type" in a]
        assert len(drift_alerts) == 1
        assert drift_alerts[0]["status"] == "high"

    def test_db_session_is_always_closed(self):
        mock_db = MagicMock()
        mock_calculator = MagicMock()
        mock_calculator.calculate_all_models.return_value = {}

        with (
            patch("src.tasks.SessionLocal", return_value=mock_db),
            patch("src.tasks.HealthCalculator", return_value=mock_calculator),
        ):
            check_alerts_task.apply().get()

        mock_db.close.assert_called_once()


# ---------------------------------------------------------------------------
# Supplementary function-based tests (use .run() and real HealthResult objects)
# ---------------------------------------------------------------------------


def test_fill_prediction_actuals_task_matches_telemetry_and_closes_session():
    session = MagicMock()
    pairs_query = MagicMock()
    telemetry_query = MagicMock()
    session.query.side_effect = [pairs_query, telemetry_query]
    pairs_query.filter.return_value.distinct.return_value.all.return_value = [
        ("building-1", "electricity")
    ]
    telemetry_query.join.return_value.filter.return_value.all.return_value = [
        SimpleNamespace(
            timestamp=datetime(2026, 6, 1, 12, 34, tzinfo=timezone.utc),
            value=25.5,
        )
    ]
    prediction_logger = MagicMock()
    prediction_logger.fill_actuals.return_value = 1

    with (
        patch("src.tasks.SessionLocal", return_value=session),
        patch("src.tasks.PredictionLogger", return_value=prediction_logger),
    ):
        result = fill_prediction_actuals_task.run(hours_lookback=12)

    assert result == {"updated_count": 1, "pairs_checked": 1}
    prediction_logger.fill_actuals.assert_called_once()
    _, building_id, metric_type_id, actuals = prediction_logger.fill_actuals.call_args[0]
    assert building_id == "building-1"
    assert metric_type_id == "electricity"
    assert actuals == {datetime(2026, 6, 1, 12, tzinfo=timezone.utc): 25.5}
    session.close.assert_called_once()


def test_evaluate_model_performance_task_delegates_to_evaluator_and_closes_session():
    session = MagicMock()
    evaluator = MagicMock()
    evaluator.evaluate_all_models.return_value = [SimpleNamespace(), SimpleNamespace()]

    with (
        patch("src.tasks.SessionLocal", return_value=session),
        patch("src.tasks.PerformanceEvaluator", return_value=evaluator),
    ):
        result = evaluate_model_performance_task.run(period_hours=48)

    assert result == {"evaluated_models": 2, "period_hours": 48}
    evaluator.evaluate_all_models.assert_called_once_with(session, period_hours=48)
    session.close.assert_called_once()


def test_detect_model_drift_task_runs_detector_for_each_pair_and_health_scores():
    session = MagicMock()
    pairs_query = MagicMock()
    session.query.return_value = pairs_query
    pairs_query.distinct.return_value.all.return_value = [
        ("model-a", "1", "forecasting", "run-1"),
        ("model-b", "2", "prediction", "run-2"),
    ]
    detector = MagicMock()
    detector.detect_all_drifts.side_effect = [
        [SimpleNamespace(), SimpleNamespace()],
        [SimpleNamespace()],
    ]
    calculator = MagicMock()
    calculator.calculate_all_models.return_value = {
        "model-a:1": SimpleNamespace(),
        "model-b:2": SimpleNamespace(),
    }

    with (
        patch("src.tasks.SessionLocal", return_value=session),
        patch("src.tasks.DriftDetector", return_value=detector),
        patch("src.tasks.HealthCalculator", return_value=calculator),
    ):
        result = detect_model_drift_task.run(period_hours=168)

    assert result == {
        "drift_reports": 3,
        "health_scores": 2,
        "period_hours": 168,
    }
    assert detector.detect_all_drifts.call_count == 2
    detector.detect_all_drifts.assert_any_call(
        session,
        "model-a",
        "1",
        period_hours=168,
        mlflow_run_id="run-1",
        model_task="forecasting",
    )
    calculator.calculate_all_models.assert_called_once_with(session)
    session.close.assert_called_once()


def test_detect_model_drift_task_continues_when_one_model_fails():
    session = MagicMock()
    pairs_query = MagicMock()
    session.query.return_value = pairs_query
    pairs_query.distinct.return_value.all.return_value = [
        ("model-a", "1", "forecasting", "run-1"),
        ("model-b", "2", "forecasting", "run-2"),
    ]
    detector = MagicMock()
    detector.detect_all_drifts.side_effect = [RuntimeError("boom"), [SimpleNamespace()]]
    calculator = MagicMock()
    calculator.calculate_all_models.return_value = {"model-b:2": SimpleNamespace()}

    with (
        patch("src.tasks.SessionLocal", return_value=session),
        patch("src.tasks.DriftDetector", return_value=detector),
        patch("src.tasks.HealthCalculator", return_value=calculator),
    ):
        result = detect_model_drift_task.run(period_hours=24)

    assert result["drift_reports"] == 1
    assert result["health_scores"] == 1
    assert detector.detect_all_drifts.call_count == 2
    session.close.assert_called_once()


def test_check_alerts_task_reports_degraded_models_and_high_drifts():
    session = MagicMock()
    high_drift = SimpleNamespace(
        severity="high",
        drift_type="prediction_drift",
        drift_score=0.42,
    )
    calculator = MagicMock()
    calculator.calculate_all_models.return_value = {
        "model-a:1": HealthResult(
            health_score=65.0,
            status="degraded",
            performance_score=50.0,
            data_drift_score=100.0,
            concept_drift_score=100.0,
            prediction_drift_score=80.0,
            active_drifts=[],
        ),
        "model-b:2": HealthResult(
            health_score=85.0,
            status="healthy",
            performance_score=100.0,
            data_drift_score=100.0,
            concept_drift_score=100.0,
            prediction_drift_score=20.0,
            active_drifts=[high_drift],
        ),
    }

    with (
        patch("src.tasks.SessionLocal", return_value=session),
        patch("src.tasks.HealthCalculator", return_value=calculator),
    ):
        result = check_alerts_task.run()

    assert result["total_alerts"] == 2
    assert result["models_checked"] == 2
    assert {
        "model": "model-a:1",
        "status": "degraded",
        "health_score": 65.0,
        "reason": "Health score below 70",
    } in result["alerts"]
    assert {
        "model": "model-b:2",
        "status": "high",
        "drift_type": "prediction_drift",
        "drift_score": 0.42,
        "reason": "Active high prediction_drift",
    } in result["alerts"]
    session.close.assert_called_once()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _chainable_query(*all_side_effects) -> tuple[MagicMock, MagicMock]:
    """Return (db_mock, query_chain) where every chaining method loops back to
    the same query_chain object.

    ``db.query(...)`` returns query_chain, so every sub-call
    (.filter / .join / .distinct / .order_by) also returns query_chain.
    ``.all()`` consumes side_effects in order across all query calls.
    """
    chain = MagicMock()
    chain.filter.return_value = chain
    chain.distinct.return_value = chain
    chain.order_by.return_value = chain
    chain.join.return_value = chain
    chain.all.side_effect = list(all_side_effects)

    db = MagicMock()
    db.query.return_value = chain
    return db, chain


# ---------------------------------------------------------------------------
# fill_prediction_actuals_task
# ---------------------------------------------------------------------------


class TestFillPredictionActualsTask:
    def test_no_unfilled_pairs_returns_zero_updated(self):
        mock_db, _ = _chainable_query([])  # pairs query → empty

        with (
            patch("src.tasks.SessionLocal", return_value=mock_db),
            patch("src.tasks.PredictionLogger"),
        ):
            result = fill_prediction_actuals_task.apply(kwargs={"hours_lookback": 24}).get()

        assert result["updated_count"] == 0
        assert result["pairs_checked"] == 0

    def test_pairs_without_matching_telemetry_are_skipped(self):
        mock_db, _ = _chainable_query(
            [("BuildingA", "electricity")],  # first .all() → pairs
            [],                               # second .all() → no telemetry
        )

        mock_logger = MagicMock()
        with (
            patch("src.tasks.SessionLocal", return_value=mock_db),
            patch("src.tasks.PredictionLogger", return_value=mock_logger),
        ):
            result = fill_prediction_actuals_task.apply(kwargs={"hours_lookback": 24}).get()

        assert result["updated_count"] == 0
        assert result["pairs_checked"] == 1
        mock_logger.fill_actuals.assert_not_called()

    def test_pairs_with_telemetry_call_fill_actuals_and_aggregate_count(self):
        telemetry_row = MagicMock()
        telemetry_row.timestamp = datetime(2026, 6, 1, 8, tzinfo=timezone.utc)
        telemetry_row.value = 110.0

        mock_db, _ = _chainable_query(
            [("BuildingA", "electricity")],  # first .all() → pairs
            [telemetry_row],                  # second .all() → telemetry
        )

        mock_logger = MagicMock()
        mock_logger.fill_actuals.return_value = 3

        with (
            patch("src.tasks.SessionLocal", return_value=mock_db),
            patch("src.tasks.PredictionLogger", return_value=mock_logger),
        ):
            result = fill_prediction_actuals_task.apply(kwargs={"hours_lookback": 24}).get()

        assert result["updated_count"] == 3
        mock_logger.fill_actuals.assert_called_once()

    def test_db_session_is_always_closed(self):
        mock_db, _ = _chainable_query([])

        with (
            patch("src.tasks.SessionLocal", return_value=mock_db),
            patch("src.tasks.PredictionLogger"),
        ):
            fill_prediction_actuals_task.apply(kwargs={"hours_lookback": 24}).get()

        mock_db.close.assert_called_once()


# ---------------------------------------------------------------------------
# evaluate_model_performance_task
# ---------------------------------------------------------------------------


class TestEvaluateModelPerformanceTask:
    def test_delegates_to_evaluator_and_returns_count(self):
        mock_db = MagicMock()
        mock_evaluator = MagicMock()
        mock_evaluator.evaluate_all_models.return_value = [MagicMock(), MagicMock()]

        with (
            patch("src.tasks.SessionLocal", return_value=mock_db),
            patch("src.tasks.PerformanceEvaluator", return_value=mock_evaluator),
        ):
            result = evaluate_model_performance_task.apply(kwargs={"period_hours": 24}).get()

        assert result["evaluated_models"] == 2
        assert result["period_hours"] == 24
        mock_evaluator.evaluate_all_models.assert_called_once_with(mock_db, period_hours=24)

    def test_zero_records_when_evaluator_finds_nothing(self):
        mock_db = MagicMock()
        mock_evaluator = MagicMock()
        mock_evaluator.evaluate_all_models.return_value = []

        with (
            patch("src.tasks.SessionLocal", return_value=mock_db),
            patch("src.tasks.PerformanceEvaluator", return_value=mock_evaluator),
        ):
            result = evaluate_model_performance_task.apply(kwargs={"period_hours": 12}).get()

        assert result["evaluated_models"] == 0

    def test_db_session_is_always_closed(self):
        mock_db = MagicMock()
        mock_evaluator = MagicMock()
        mock_evaluator.evaluate_all_models.return_value = []

        with (
            patch("src.tasks.SessionLocal", return_value=mock_db),
            patch("src.tasks.PerformanceEvaluator", return_value=mock_evaluator),
        ):
            evaluate_model_performance_task.apply().get()

        mock_db.close.assert_called_once()


# ---------------------------------------------------------------------------
# detect_model_drift_task
# ---------------------------------------------------------------------------


class TestDetectModelDriftTask:
    def test_no_model_pairs_returns_zero_reports_and_scores(self):
        mock_db, _ = _chainable_query([])  # distinct pairs query → empty

        mock_calculator = MagicMock()
        mock_calculator.calculate_all_models.return_value = {}

        with (
            patch("src.tasks.SessionLocal", return_value=mock_db),
            patch("src.tasks.DriftDetector"),
            patch("src.tasks.HealthCalculator", return_value=mock_calculator),
        ):
            result = detect_model_drift_task.apply(kwargs={"period_hours": 168}).get()

        assert result["drift_reports"] == 0
        assert result["health_scores"] == 0
        assert result["period_hours"] == 168

    def test_drift_detector_is_called_per_model_pair(self):
        pairs = [
            ("model_a", "1", "forecasting", "run-001"),
            ("model_b", "2", "forecasting", "run-002"),
        ]
        mock_db, _ = _chainable_query(pairs)

        mock_detector = MagicMock()
        mock_detector.detect_all_drifts.return_value = [MagicMock()]

        mock_calculator = MagicMock()
        mock_calculator.calculate_all_models.return_value = {}

        with (
            patch("src.tasks.SessionLocal", return_value=mock_db),
            patch("src.tasks.DriftDetector", return_value=mock_detector),
            patch("src.tasks.HealthCalculator", return_value=mock_calculator),
        ):
            result = detect_model_drift_task.apply(kwargs={"period_hours": 168}).get()

        assert mock_detector.detect_all_drifts.call_count == 2
        assert result["drift_reports"] == 2  # 1 report per pair × 2 pairs

    def test_health_scores_reflect_calculate_all_models_result(self):
        mock_db, _ = _chainable_query([])

        mock_calculator = MagicMock()
        mock_calculator.calculate_all_models.return_value = {"m:1": MagicMock(), "m:2": MagicMock()}

        with (
            patch("src.tasks.SessionLocal", return_value=mock_db),
            patch("src.tasks.DriftDetector"),
            patch("src.tasks.HealthCalculator", return_value=mock_calculator),
        ):
            result = detect_model_drift_task.apply().get()

        assert result["health_scores"] == 2

    def test_drift_detection_error_per_model_does_not_abort_task(self):
        """A failure on one model pair must not prevent processing remaining pairs."""
        pairs = [
            ("model_ok", "1", "forecasting", "run-ok"),
            ("model_bad", "2", "forecasting", "run-bad"),
        ]
        mock_db, _ = _chainable_query(pairs)

        mock_detector = MagicMock()
        mock_detector.detect_all_drifts.side_effect = [
            RuntimeError("MLflow unreachable"),  # first pair fails
            [MagicMock()],                        # second pair succeeds
        ]

        mock_calculator = MagicMock()
        mock_calculator.calculate_all_models.return_value = {}

        with (
            patch("src.tasks.SessionLocal", return_value=mock_db),
            patch("src.tasks.DriftDetector", return_value=mock_detector),
            patch("src.tasks.HealthCalculator", return_value=mock_calculator),
        ):
            result = detect_model_drift_task.apply().get()

        assert result["drift_reports"] == 1  # only the successful pair counted


# ---------------------------------------------------------------------------
# check_alerts_task
# ---------------------------------------------------------------------------


class TestCheckAlertsTask:
    def _make_health_result(self, status: str, score: float, active_drifts=None):
        result = MagicMock()
        result.status = status
        result.health_score = score
        result.active_drifts = active_drifts or []
        return result

    def test_no_models_returns_zero_alerts(self):
        mock_db = MagicMock()
        mock_calculator = MagicMock()
        mock_calculator.calculate_all_models.return_value = {}

        with (
            patch("src.tasks.SessionLocal", return_value=mock_db),
            patch("src.tasks.HealthCalculator", return_value=mock_calculator),
        ):
            result = check_alerts_task.apply().get()

        assert result["total_alerts"] == 0
        assert result["alerts"] == []
        assert result["models_checked"] == 0

    def test_critical_model_generates_an_alert(self):
        mock_db = MagicMock()
        mock_calculator = MagicMock()
        mock_calculator.calculate_all_models.return_value = {
            "dmp_model:1": self._make_health_result("critical", 35.0),
        }

        with (
            patch("src.tasks.SessionLocal", return_value=mock_db),
            patch("src.tasks.HealthCalculator", return_value=mock_calculator),
        ):
            result = check_alerts_task.apply().get()

        assert result["total_alerts"] == 1
        assert result["alerts"][0]["status"] == "critical"
        assert result["models_checked"] == 1

    def test_degraded_model_generates_an_alert(self):
        mock_db = MagicMock()
        mock_calculator = MagicMock()
        mock_calculator.calculate_all_models.return_value = {
            "dmp_model:2": self._make_health_result("degraded", 65.0),
        }

        with (
            patch("src.tasks.SessionLocal", return_value=mock_db),
            patch("src.tasks.HealthCalculator", return_value=mock_calculator),
        ):
            result = check_alerts_task.apply().get()

        assert result["total_alerts"] == 1
        assert result["alerts"][0]["status"] == "degraded"

    def test_healthy_model_generates_no_alert(self):
        mock_db = MagicMock()
        mock_calculator = MagicMock()
        mock_calculator.calculate_all_models.return_value = {
            "dmp_model:3": self._make_health_result("healthy", 90.0),
        }

        with (
            patch("src.tasks.SessionLocal", return_value=mock_db),
            patch("src.tasks.HealthCalculator", return_value=mock_calculator),
        ):
            result = check_alerts_task.apply().get()

        assert result["total_alerts"] == 0

    def test_active_high_severity_drift_generates_additional_alert(self):
        drift = MagicMock()
        drift.severity = "high"
        drift.drift_type = "prediction_drift"
        drift.drift_score = 0.35

        mock_db = MagicMock()
        mock_calculator = MagicMock()
        mock_calculator.calculate_all_models.return_value = {
            "dmp_model:1": self._make_health_result("healthy", 80.0, active_drifts=[drift]),
        }

        with (
            patch("src.tasks.SessionLocal", return_value=mock_db),
            patch("src.tasks.HealthCalculator", return_value=mock_calculator),
        ):
            result = check_alerts_task.apply().get()

        drift_alerts = [a for a in result["alerts"] if "drift_type" in a]
        assert len(drift_alerts) == 1
        assert drift_alerts[0]["status"] == "high"

    def test_db_session_is_always_closed(self):
        mock_db = MagicMock()
        mock_calculator = MagicMock()
        mock_calculator.calculate_all_models.return_value = {}

        with (
            patch("src.tasks.SessionLocal", return_value=mock_db),
            patch("src.tasks.HealthCalculator", return_value=mock_calculator),
        ):
            check_alerts_task.apply().get()

        mock_db.close.assert_called_once()
