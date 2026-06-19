from datetime import datetime, timezone

import pandas as pd
from src.ml.training import algorithm_for_task
from src.schemas import MLAlgorithm, ModelTask, ModelTrainingRequest
from src.tasks import (
    _external_task_failure_message,
    _finalize_prediction_training_frame,
    _not_implemented_training_response,
    _prediction_building_ids,
    _registered_model_name,
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
