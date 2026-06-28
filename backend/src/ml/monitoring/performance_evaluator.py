"""Performance Evaluator Service.

Computes aggregated performance metrics from prediction logs
and stores them in the model_performance table.
"""

import logging
from datetime import datetime, timedelta, timezone

import numpy as np
from mlflow.tracking import MlflowClient
from sqlalchemy.orm import Session
from src.core.config import settings
from src.models import ModelPerformance, PredictionLog

logger = logging.getLogger(__name__)

# Thresholds for performance degradation
MAE_RATIO_WARNING = 1.2  # 20% worse than baseline
MAE_RATIO_CRITICAL = 1.5  # 50% worse than baseline


class PerformanceEvaluator:
    """Evaluates model performance by computing metrics from production prediction logs."""

    def __init__(self, mlflow_client: MlflowClient | None = None):
        mlflow_client = mlflow_client or MlflowClient(
            tracking_uri=settings.MLFLOW_TRACKING_URI
        )
        self.mlflow_client = mlflow_client

    def evaluate(
        self,
        db: Session,
        model_name: str,
        model_version: str,
        *,
        period_start: datetime | None = None,
        period_end: datetime | None = None,
        building_id: str | None = None,
        metric_type_id: str | None = None,
        mlflow_run_id: str | None = None,
        model_task: str = "forecasting",
    ) -> ModelPerformance | None:
        """Compute performance metrics for a model over a time window.

        Args:
            db: Active database session.
            model_name: Registered model name.
            model_version: Model version string.
            period_start: Start of evaluation window (None = no lower bound).
            period_end: End of evaluation window (None = no upper bound).
            building_id: Optional building filter.
            metric_type_id: Optional metric type filter.
            mlflow_run_id: Optional MLflow run ID filter.
            model_task: Task type (forecasting/anomaly_detection).

        Returns:
            ModelPerformance record or None if insufficient data.
        """
        query = db.query(PredictionLog).filter(
            PredictionLog.model_name == model_name,
            PredictionLog.model_version == model_version,
            PredictionLog.actual_value.isnot(None),
        )
        if period_start is not None:
            query = query.filter(PredictionLog.timestamp >= period_start)
        if period_end is not None:
            query = query.filter(PredictionLog.timestamp <= period_end)
        if building_id:
            query = query.filter(PredictionLog.building_id == building_id)
        if metric_type_id:
            query = query.filter(PredictionLog.metric_type_id == metric_type_id)
        if mlflow_run_id:
            query = query.filter(PredictionLog.mlflow_run_id == mlflow_run_id)

        logs = query.all()
        if len(logs) < 5:
            logger.debug(
                "Insufficient prediction logs for %s v%s (%d samples)",
                model_name,
                model_version,
                len(logs),
            )
            return None

        actuals = np.array([log.actual_value for log in logs])
        predictions = np.array([log.predicted_value for log in logs])
        errors = actuals - predictions

        mae = float(np.mean(np.abs(errors)))
        rmse = float(np.sqrt(np.mean(errors**2)))
        mape = self._safe_mape(actuals, predictions)
        r2 = float(1.0 - np.sum(errors**2) / np.sum((actuals - np.mean(actuals)) ** 2))
        mean_err = float(np.mean(errors))
        p10 = float(np.percentile(np.abs(errors), 10))
        p90 = float(np.percentile(np.abs(errors), 90))

        # Get baseline from MLflow
        baseline_mae, baseline_rmse = self._get_baseline_metrics(
            model_name, model_version
        )

        performance_ratio = (
            mae / baseline_mae if baseline_mae and baseline_mae > 0 else None
        )

        computed_at = datetime.now(timezone.utc)
        record = ModelPerformance(
            model_name=model_name,
            model_version=model_version,
            mlflow_run_id=mlflow_run_id or logs[0].mlflow_run_id,
            model_task=model_task,
            building_id=building_id,
            metric_type_id=metric_type_id,
            period_start=period_start or logs[0].timestamp,
            period_end=period_end or logs[-1].timestamp,
            sample_count=len(logs),
            mae=mae,
            rmse=rmse,
            mape=mape,
            r2_score=r2 if not np.isinf(r2) and not np.isnan(r2) else None,
            mean_error=mean_err,
            p10_error=p10,
            p90_error=p90,
            baseline_mae=baseline_mae,
            baseline_rmse=baseline_rmse,
            performance_ratio=performance_ratio,
            computed_at=computed_at,
        )
        db.add(record)
        db.commit()
        db.refresh(record)

        logger.info(
            "Evaluated %s v%s: MAE=%.4f RMSE=%.4f ratio=%.2f (%d samples)",
            model_name,
            model_version,
            mae,
            rmse,
            performance_ratio or 0,
            len(logs),
        )
        return record

    def evaluate_all_models(
        self,
        db: Session,
        *,
        period_hours: int = 24,
        model_name: str | None = None,
    ) -> list[ModelPerformance]:
        """Evaluate performance for all model/version combinations that have prediction logs.

        Args:
            db: Active database session.
            period_hours: Number of hours to look back.
            model_name: Optional filter for a specific model.

        Returns:
            List of newly created ModelPerformance records.
        """
        now = datetime.now(timezone.utc)
        period_start = now - timedelta(hours=period_hours)

        base_query = db.query(
            PredictionLog.model_name,
            PredictionLog.model_version,
            PredictionLog.model_task,
        ).filter(
            PredictionLog.actual_value.isnot(None),
        )
        if model_name:
            base_query = base_query.filter(PredictionLog.model_name == model_name)

        # First attempt: use the time window
        windowed_pairs = (
            base_query.filter(PredictionLog.timestamp >= period_start).distinct().all()
        )

        # If nothing found in the time window, fall back to all-time
        # (e.g., when evaluating predictions from a historical forecast).
        if not windowed_pairs:
            logger.info(
                "No prediction logs with actuals found in the last %dh%s; "
                "falling back to all-time.",
                period_hours,
                f" for model '{model_name}'" if model_name else "",
            )
            all_pairs = base_query.distinct().all()
            if not all_pairs:
                return []
            # Use the full timerange of the found predictions for the
            # period_start/end parameters so the stored record is honest.
            if model_name:
                full_range = (
                    db.query(PredictionLog.timestamp)
                    .filter(
                        PredictionLog.model_name == model_name,
                        PredictionLog.actual_value.isnot(None),
                    )
                    .order_by(PredictionLog.timestamp)
                    .all()
                )
            else:
                full_range = (
                    db.query(PredictionLog.timestamp)
                    .filter(PredictionLog.actual_value.isnot(None))
                    .order_by(PredictionLog.timestamp)
                    .all()
                )
            if full_range:
                period_start = full_range[0][0]
                now = full_range[-1][0]
            pairs = all_pairs
        else:
            pairs = windowed_pairs

        records: list[ModelPerformance] = []
        for mn, mv, mt in pairs:
            try:
                record = self.evaluate(
                    db,
                    mn,
                    mv,
                    period_start=period_start,
                    period_end=now,
                    model_task=mt,
                )
                if record:
                    records.append(record)
            except Exception:
                logger.exception("Failed to evaluate %s v%s", mn, mv)
        return records

    def _get_baseline_metrics(
        self, model_name: str, model_version: str
    ) -> tuple[float | None, float | None]:
        """Retrieve baseline MAE and RMSE from MLflow run metrics."""
        try:
            versions = self.mlflow_client.search_model_versions(f"name='{model_name}'")
            matching = [v for v in versions if v.version == str(model_version)]
            if not matching:
                return None, None

            run_id = matching[0].run_id
            if not run_id:
                return None, None

            run = self.mlflow_client.get_run(run_id)
            metrics = run.data.metrics or {}
            baseline_mae = (
                metrics.get("mae") or metrics.get("val_mae") or metrics.get("test_mae")
            )
            baseline_rmse = (
                metrics.get("rmse")
                or metrics.get("val_rmse")
                or metrics.get("test_rmse")
            )
            return (
                float(baseline_mae) if baseline_mae is not None else None,
                float(baseline_rmse) if baseline_rmse is not None else None,
            )
        except Exception:
            logger.warning(
                "Failed to get baseline metrics for %s v%s",
                model_name,
                model_version,
                exc_info=True,
            )
            return None, None

    @staticmethod
    def _safe_mape(actuals: np.ndarray, predictions: np.ndarray) -> float | None:
        """Compute MAPE safely, returning None if actuals contain zeros."""
        mask = actuals != 0
        if not mask.any():
            return None
        return float(
            np.mean(np.abs((actuals[mask] - predictions[mask]) / actuals[mask])) * 100
        )
