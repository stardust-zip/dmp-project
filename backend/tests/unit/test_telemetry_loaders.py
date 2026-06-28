from datetime import datetime, timezone

import pandas as pd

from src.ml.anomaly import telemetry_loaders
from src.schemas import ModelTrainingRequest, ModelTask, TrainingDataSource


def test_db_training_loader_filters_requested_metrics(monkeypatch):
    captured = {}

    def fake_query_telemetry_window(db, start, end, metrics=None):
        captured["metrics"] = metrics
        return pd.DataFrame(columns=telemetry_loaders.TELEMETRY_COLUMNS)

    monkeypatch.setattr(
        telemetry_loaders,
        "query_telemetry_window",
        fake_query_telemetry_window,
    )
    request = ModelTrainingRequest(
        metrics=["electricity"],
        time_range_start=datetime(2017, 1, 1, tzinfo=timezone.utc),
        time_range_end=datetime(2017, 1, 2, tzinfo=timezone.utc),
        model_task=ModelTask.AnomalyDetection,
        data_source=TrainingDataSource.DB,
    )

    telemetry_loaders.load_telemetry_for_training(db=object(), request=request)

    assert captured["metrics"] == ["electricity"]
