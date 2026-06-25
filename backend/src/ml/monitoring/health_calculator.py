"""Health Score Calculator.

Computes a 0-100 health score per model version based on
performance ratio, data drift, concept drift, and prediction drift.
"""

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session
from src.ml.monitoring.performance_evaluator import (
    MAE_RATIO_CRITICAL,
    MAE_RATIO_WARNING,
)
from src.models import DriftReport, ModelPerformance, PredictionLog

logger = logging.getLogger(__name__)

# Health score weights
WEIGHT_PERFORMANCE = 0.40
WEIGHT_DATA_DRIFT = 0.25
WEIGHT_CONCEPT_DRIFT = 0.25
WEIGHT_PREDICTION_DRIFT = 0.10


def _performance_score(ratio: float | None) -> float:
    """Score based on performance ratio (current MAE / baseline MAE).

    Ratio of 1.0 = perfect (score 100).
    Ratio of 1.2 = warning (score 50).
    Ratio of 1.5+ = critical (score 0).
    """
    if ratio is None:
        return 50.0  # Unknown performance
    if ratio <= 1.0:
        return 100.0
    if ratio >= MAE_RATIO_CRITICAL:
        return 0.0
    if ratio >= MAE_RATIO_WARNING:
        # Linear interpolation from 50 to 0 between 1.2 and 1.5
        return 50.0 * (
            1.0 - (ratio - MAE_RATIO_WARNING) / (MAE_RATIO_CRITICAL - MAE_RATIO_WARNING)
        )
    # Linear interpolation from 100 to 50 between 1.0 and 1.2
    return 100.0 - 50.0 * (ratio - 1.0) / (MAE_RATIO_WARNING - 1.0)


# Severity to score mapping
_DRIFT_SEVERITY_SCORE = {
    "none": 100.0,
    "low": 80.0,
    "medium": 50.0,
    "high": 20.0,
    "critical": 0.0,
}


def _drift_score_from_severity(severity: str) -> float:
    return _DRIFT_SEVERITY_SCORE.get(severity, 50.0)


def _latest_drift_severity(drifts: list[DriftReport], drift_type: str) -> str | None:
    """Get the severity of the most recent drift report of a given type."""
    relevant = [d for d in drifts if d.drift_type == drift_type]
    if not relevant:
        return None
    latest = max(relevant, key=lambda d: d.computed_at)
    return latest.severity


@dataclass
class HealthResult:
    """Result of a health score calculation."""

    health_score: float  # 0-100
    status: str  # "healthy", "degraded", "critical"
    performance_score: float
    data_drift_score: float
    concept_drift_score: float
    prediction_drift_score: float
    total_predictions: int = 0
    pending_actuals: int = 0
    latest_performance: ModelPerformance | None = None
    active_drifts: list[DriftReport] | None = None


class HealthCalculator:
    """Computes model health scores based on performance and drift metrics."""

    def calculate(
        self,
        db: Session,
        model_name: str,
        model_version: str,
    ) -> HealthResult:
        """Calculate health score for a specific model version.

        Args:
            db: Active database session.
            model_name: Registered model name.
            model_version: Model version string.

        Returns:
            HealthResult with score and component breakdown.
        """
        # Get latest performance record
        latest_perf = (
            db.query(ModelPerformance)
            .filter(
                ModelPerformance.model_name == model_name,
                ModelPerformance.model_version == model_version,
            )
            .order_by(ModelPerformance.computed_at.desc())
            .first()
        )

        # Get recent drift reports
        recent_drifts = (
            db.query(DriftReport)
            .filter(
                DriftReport.model_name == model_name,
                DriftReport.model_version == model_version,
            )
            .order_by(DriftReport.computed_at.desc())
            .limit(50)
            .all()
        )

        # Count predictions
        total_predictions = (
            db.query(PredictionLog)
            .filter(
                PredictionLog.model_name == model_name,
                PredictionLog.model_version == model_version,
            )
            .count()
        )

        pending_actuals = (
            db.query(PredictionLog)
            .filter(
                PredictionLog.model_name == model_name,
                PredictionLog.model_version == model_version,
                PredictionLog.actual_value.is_(None),
            )
            .count()
        )

        # Component scores
        perf_ratio = latest_perf.performance_ratio if latest_perf else None
        perf_score = _performance_score(perf_ratio)

        data_drift_severity = _latest_drift_severity(recent_drifts, "data_drift")
        data_drift_score = (
            _drift_score_from_severity(data_drift_severity)
            if data_drift_severity
            else 100.0
        )

        concept_drift_severity = _latest_drift_severity(recent_drifts, "concept_drift")
        concept_drift_score = (
            _drift_score_from_severity(concept_drift_severity)
            if concept_drift_severity
            else 100.0
        )

        pred_drift_severity = _latest_drift_severity(recent_drifts, "prediction_drift")
        pred_drift_score = (
            _drift_score_from_severity(pred_drift_severity)
            if pred_drift_severity
            else 100.0
        )

        # Weighted score
        health_score = (
            perf_score * WEIGHT_PERFORMANCE
            + data_drift_score * WEIGHT_DATA_DRIFT
            + concept_drift_score * WEIGHT_CONCEPT_DRIFT
            + pred_drift_score * WEIGHT_PREDICTION_DRIFT
        )
        health_score = round(max(0.0, min(100.0, health_score)), 1)

        # Status mapping
        if health_score >= 70:
            status = "healthy"
        elif health_score >= 40:
            status = "degraded"
        else:
            status = "critical"

        # Active drifts: non-none severity from recent reports
        active_drifts = [d for d in recent_drifts if d.severity not in ("none",)]

        result = HealthResult(
            health_score=health_score,
            status=status,
            performance_score=round(perf_score, 1),
            data_drift_score=round(data_drift_score, 1),
            concept_drift_score=round(concept_drift_score, 1),
            prediction_drift_score=round(pred_drift_score, 1),
            total_predictions=total_predictions,
            pending_actuals=pending_actuals,
            latest_performance=latest_perf,
            active_drifts=active_drifts,
        )

        logger.info(
            "Health score for %s v%s: %.1f (%s) perf=%.1f drift_data=%.1f drift_concept=%.1f drift_pred=%.1f",
            model_name,
            model_version,
            health_score,
            status,
            perf_score,
            data_drift_score,
            concept_drift_score,
            pred_drift_score,
        )
        return result

    def calculate_all_models(
        self,
        db: Session,
    ) -> dict[str, HealthResult]:
        """Calculate health scores for all model/version combinations.

        Returns:
            Dict mapping "model_name:version" to HealthResult.
        """
        pairs = (
            db.query(
                PredictionLog.model_name,
                PredictionLog.model_version,
            )
            .distinct()
            .all()
        )

        results: dict[str, HealthResult] = {}
        for model_name, model_version in pairs:
            key = f"{model_name}:{model_version}"
            try:
                results[key] = self.calculate(db, model_name, model_version)
            except Exception:
                logger.exception(
                    "Failed to calculate health for %s v%s", model_name, model_version
                )

        return results
