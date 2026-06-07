from unittest.mock import patch

import pandas as pd
from src.ml.dummy_randomforest import (
    RandomForestAlarmClassifier,
    RandomForestTrainer,
)


@patch("src.ml.base.mlflow")
def test_random_forest_trainer(mock_mlflow):
    X = pd.DataFrame(
        {"hour": [1, 2, 3, 4], "dayofweek": [0, 0, 0, 0], "month": [6, 6, 6, 6]}
    )
    y = pd.Series([100, 110, 105, 115])

    trainer = RandomForestTrainer(n_estimators=5)

    metrics = trainer.train_and_evaluate(X, y)

    assert "mae" in metrics
    assert "rmse" in metrics
    assert "execution_time_ms" in metrics

    mock_mlflow.log_metrics.assert_called_once()
    mock_mlflow.sklearn.log_model.assert_called_once()


@patch("src.ml.base.mlflow")
def test_random_forest_alarm_classifier(mock_mlflow):
    X = pd.DataFrame(
        {
            "hour": [1, 2, 3, 4, 5, 6],
            "dayofweek": [0, 0, 0, 0, 0, 0],
            "month": [6, 6, 6, 6, 6, 6],
        }
    )
    y = pd.Series(["normal", "alarm", "normal", "alarm", "normal", "alarm"])

    trainer = RandomForestAlarmClassifier(n_estimators=5)

    metrics = trainer.train_and_evaluate(X, y)

    assert "accuracy" in metrics
    assert "execution_time_ms" in metrics

    mock_mlflow.log_metrics.assert_called_once_with({"accuracy": metrics["accuracy"]})
    mock_mlflow.sklearn.log_model.assert_called_once()
