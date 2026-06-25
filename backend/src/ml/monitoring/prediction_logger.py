import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session
from src.models import PredictionLog

logger = logging.getLogger(__name__)


class PredictionLogger:
    """Service for logging prediction events to the database.

    This service records every prediction made in production, enabling
    later accuracy calculation and drift analysis.
    """

    def log_prediction(
        self,
        db: Session,
        *,
        timestamp: datetime,
        building_id: str,
        metric_type_id: str,
        predicted_value: float,
        mlflow_run_id: str,
        model_name: str,
        model_version: str,
        model_task: str,
        feature_values: dict[str, Any] | None = None,
        prediction_context: dict[str, Any] | None = None,
    ) -> PredictionLog:
        """Log a single prediction to the database.

        Args:
            db: Active database session.
            timestamp: Prediction timestamp (should be UTC).
            building_id: ID of the building being predicted.
            metric_type_id: Metric type (e.g., electricity, water).
            predicted_value: The model's predicted value.
            mlflow_run_id: MLflow run ID of the model used.
            model_name: Registered model name in MLflow.
            model_version: MLflow model version string.
            model_task: Task type (forecasting/anomaly_detection).
            feature_values: Snapshot of input features for drift analysis.
            prediction_context: Additional context (scenario params, etc.).

        Returns:
            The created PredictionLog instance.
        """
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)

        log = PredictionLog(
            timestamp=timestamp,
            building_id=building_id,
            metric_type_id=metric_type_id,
            predicted_value=predicted_value,
            mlflow_run_id=mlflow_run_id,
            model_name=model_name,
            model_version=model_version,
            model_task=model_task,
            feature_values=feature_values,
            prediction_context=prediction_context,
        )
        db.add(log)
        db.commit()
        db.refresh(log)
        logger.debug(
            "Logged prediction: model=%s v%s building=%s metric=%s",
            model_name,
            model_version,
            building_id,
            metric_type_id,
        )
        return log

    def log_batch(
        self,
        db: Session,
        predictions: list[dict[str, Any]],
    ) -> list[PredictionLog]:
        """Bulk insert multiple prediction logs for efficiency.

        Args:
            db: Active database session.
            predictions: List of prediction data dicts. Each dict should contain:
                - timestamp, building_id, metric_type_id, predicted_value
                - mlflow_run_id, model_name, model_version, model_task
                - feature_values (optional), prediction_context (optional)

        Returns:
            List of created PredictionLog instances.
        """
        if not predictions:
            return []

        logs: list[PredictionLog] = []
        for pred in predictions:
            timestamp = pred["timestamp"]
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)

            actual = pred.get("actual_value")
            log = PredictionLog(
                timestamp=timestamp,
                building_id=pred["building_id"],
                metric_type_id=pred["metric_type_id"],
                predicted_value=pred["predicted_value"],
                actual_value=actual,
                error=pred.get("error") if actual is not None else None,
                mlflow_run_id=pred["mlflow_run_id"],
                model_name=pred["model_name"],
                model_version=pred["model_version"],
                model_task=pred["model_task"],
                feature_values=pred.get("feature_values"),
                prediction_context=pred.get("prediction_context"),
            )
            db.add(log)
            logs.append(log)

        db.commit()
        for log in logs:
            db.refresh(log)

        logger.info("Batch logged %d predictions", len(logs))
        return logs

    def fill_actuals(
        self,
        db: Session,
        building_id: str,
        metric_type_id: str,
        actuals: dict[datetime, float],
    ) -> int:
        """Match logged predictions with actual telemetry values.

        Updates PredictionLog entries where actual_value is NULL,
        populating both actual_value and computed error.

        Args:
            db: Active database session.
            building_id: Building ID to match.
            metric_type_id: Metric type to match.
            actuals: Mapping of timestamp -> actual value.

        Returns:
            Number of prediction logs updated.
        """
        if not actuals:
            return 0

        updated_count = 0
        logs = (
            db.query(PredictionLog)
            .filter(
                PredictionLog.building_id == building_id,
                PredictionLog.metric_type_id == metric_type_id,
                PredictionLog.actual_value.is_(None),
                PredictionLog.timestamp.in_(actuals.keys()),
            )
            .all()
        )

        for log in logs:
            ts = log.timestamp
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            else:
                ts = ts.astimezone(timezone.utc)

            # Normalize timestamp to match actuals keys
            ts_key = ts.replace(minute=0, second=0, microsecond=0)
            if ts_key in actuals:
                actual = actuals[ts_key]
                log.actual_value = actual
                log.error = actual - log.predicted_value
                updated_count += 1

        if updated_count > 0:
            db.commit()
            logger.info(
                "Filled actuals for %d predictions (building=%s, metric=%s)",
                updated_count,
                building_id,
                metric_type_id,
            )

        return updated_count
