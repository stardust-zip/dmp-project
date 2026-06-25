"""Drift Detection Service.

Detects data drift, concept drift, and prediction drift using
statistical tests (PSI, KS test) on production prediction logs.
"""

import logging
from datetime import datetime, timedelta, timezone

import numpy as np
from scipy import stats
from sqlalchemy.orm import Session
from src.models import DriftReport, PredictionLog

logger = logging.getLogger(__name__)

# PSI severity thresholds
PSI_LOW = 0.1
PSI_MEDIUM = 0.2
PSI_HIGH = 0.25


def _compute_psi(
    reference: np.ndarray, current: np.ndarray, buckets: int = 10
) -> float:
    """Compute Population Stability Index between two distributions.

    Args:
        reference: Reference (training) distribution.
        current: Current (production) distribution.
        buckets: Number of bins for discretization.

    Returns:
        PSI value. Lower = more stable.
    """
    # Use reference percentiles as bin edges to ensure equal expected counts
    edges = np.percentile(reference, np.linspace(0, 100, buckets + 1))
    # Add small epsilon to avoid duplicate edges
    edges = np.unique(edges)
    if len(edges) < 2:
        return 0.0

    # Clip current values to reference range
    clipped_current = np.clip(current, edges[0], edges[-1])

    ref_counts = np.histogram(reference, bins=edges)[0]
    cur_counts = np.histogram(clipped_current, bins=edges)[0]

    # Add small epsilon to avoid log(0)
    ref_pct = (ref_counts + 0.0001) / (len(reference) + 0.0001 * buckets)
    cur_pct = (cur_counts + 0.0001) / (len(current) + 0.0001 * buckets)

    psi = float(np.sum((cur_pct - ref_pct) * np.log(cur_pct / ref_pct)))
    return max(psi, 0.0)


def _classify_psi_severity(psi: float) -> tuple[str, str]:
    """Map PSI value to severity level."""
    if psi < PSI_LOW:
        return "none", "No significant drift"
    if psi < PSI_MEDIUM:
        return "low", "Minor drift detected - monitor"
    if psi < PSI_HIGH:
        return "medium", "Moderate drift - investigate"
    return "high", "Significant drift - retrain recommended"


def _compute_distribution_stats(values: np.ndarray) -> dict:
    """Compute summary statistics for a distribution."""
    return {
        "mean": float(np.mean(values)),
        "std": float(np.std(values)),
        "median": float(np.median(values)),
        "min": float(np.min(values)),
        "max": float(np.max(values)),
        "p25": float(np.percentile(values, 25)),
        "p50": float(np.percentile(values, 50)),
        "p75": float(np.percentile(values, 75)),
        "p90": float(np.percentile(values, 90)),
        "p95": float(np.percentile(values, 95)),
        "sample_count": len(values),
    }


class DriftDetector:
    """Detects various types of model drift using statistical tests."""

    def detect_data_drift(
        self,
        db: Session,
        model_name: str,
        model_version: str,
        *,
        period_start: datetime,
        period_end: datetime,
        feature_name: str,
        reference_values: list[float],
        mlflow_run_id: str = "",
        model_task: str = "forecasting",
    ) -> DriftReport | None:
        """Detect feature-level data drift using PSI.

        Args:
            db: Active database session.
            model_name: Registered model name.
            model_version: Model version string.
            period_start: Start of evaluation window.
            period_end: End of evaluation window.
            feature_name: Name of the feature to check.
            reference_values: Reference distribution values (from training).
            mlflow_run_id: MLflow run ID.
            model_task: Task type.

        Returns:
            DriftReport or None if insufficient data.
        """
        if len(reference_values) < 10:
            logger.debug("Insufficient reference values for %s", feature_name)
            return None

        ref_array = np.array(reference_values)

        # Get current values from feature_values JSONB
        logs = (
            db.query(PredictionLog)
            .filter(
                PredictionLog.model_name == model_name,
                PredictionLog.model_version == model_version,
                PredictionLog.timestamp >= period_start,
                PredictionLog.timestamp <= period_end,
                PredictionLog.feature_values.isnot(None),
            )
            .all()
        )

        current_values = []
        for log in logs:
            fv = log.feature_values or {}
            if feature_name in fv and fv[feature_name] is not None:
                try:
                    current_values.append(float(fv[feature_name]))
                except (ValueError, TypeError):
                    pass

        if len(current_values) < 10:
            logger.debug(
                "Insufficient current values for %s (%d samples)",
                feature_name,
                len(current_values),
            )
            return None

        cur_array = np.array(current_values)
        psi = _compute_psi(ref_array, cur_array)
        severity, details_msg = _classify_psi_severity(psi)

        report = DriftReport(
            model_name=model_name,
            model_version=model_version,
            mlflow_run_id=mlflow_run_id,
            model_task=model_task,
            drift_type="data_drift",
            feature_name=feature_name,
            period_start=period_start,
            period_end=period_end,
            drift_score=psi,
            drift_threshold=PSI_MEDIUM,
            is_drifted=psi >= PSI_LOW,
            severity=severity,
            reference_stats=_compute_distribution_stats(ref_array),
            current_stats=_compute_distribution_stats(cur_array),
            details={"message": details_msg, "method": "PSI", "buckets": 10},
        )
        db.add(report)
        db.commit()
        db.refresh(report)

        logger.info("Data drift %s: PSI=%.4f severity=%s", feature_name, psi, severity)
        return report

    def detect_concept_drift(
        self,
        db: Session,
        model_name: str,
        model_version: str,
        *,
        period_start: datetime,
        period_end: datetime,
        reference_errors: list[float] | None = None,
        mlflow_run_id: str = "",
        model_task: str = "forecasting",
    ) -> DriftReport | None:
        """Detect concept drift via error distribution analysis.

        Uses KS test to compare current error distribution against
        a reference (training-time) error distribution.

        Args:
            db: Active database session.
            model_name: Registered model name.
            model_version: Model version string.
            period_start: Start of evaluation window.
            period_end: End of evaluation window.
            reference_errors: Reference error distribution (training).
            mlflow_run_id: MLflow run ID.
            model_task: Task type.

        Returns:
            DriftReport or None if insufficient data.
        """
        logs = (
            db.query(PredictionLog)
            .filter(
                PredictionLog.model_name == model_name,
                PredictionLog.model_version == model_version,
                PredictionLog.error.isnot(None),
                PredictionLog.timestamp >= period_start,
                PredictionLog.timestamp <= period_end,
            )
            .all()
        )

        if len(logs) < 10:
            logger.debug(
                "Insufficient error logs for concept drift (%d samples)", len(logs)
            )
            return None

        current_errors = np.array([log.error for log in logs])

        # If no reference errors provided, use first half of logs as reference
        if reference_errors is None or len(reference_errors) < 10:
            midpoint = len(logs) // 2
            if midpoint < 10:
                return None
            ref_errors = np.array([logs[i].error for i in range(midpoint)])
        else:
            ref_errors = np.array(reference_errors)

        # KS test
        ks_stat, p_value = stats.ks_2samp(ref_errors, current_errors)
        ks_stat = float(ks_stat)
        p_value = float(p_value)

        # Map p-value to severity
        if p_value >= 0.05:
            severity = "none"
        elif p_value >= 0.01:
            severity = "low"
        elif p_value >= 0.001:
            severity = "medium"
        else:
            severity = "high"

        is_drifted = p_value < 0.05

        report = DriftReport(
            model_name=model_name,
            model_version=model_version,
            mlflow_run_id=mlflow_run_id,
            model_task=model_task,
            drift_type="concept_drift",
            feature_name=None,
            period_start=period_start,
            period_end=period_end,
            drift_score=ks_stat,
            drift_threshold=0.05,
            is_drifted=is_drifted,
            severity=severity,
            reference_stats=_compute_distribution_stats(ref_errors),
            current_stats=_compute_distribution_stats(current_errors),
            details={
                "message": f"KS test p-value={p_value:.6f}",
                "method": "KS_2samp",
                "ks_statistic": ks_stat,
                "p_value": p_value,
            },
        )
        db.add(report)
        db.commit()
        db.refresh(report)

        logger.info(
            "Concept drift: KS=%.4f p=%.4f severity=%s",
            ks_stat,
            p_value,
            severity,
        )
        return report

    def detect_prediction_drift(
        self,
        db: Session,
        model_name: str,
        model_version: str,
        *,
        period_start: datetime,
        period_end: datetime,
        reference_predictions: list[float],
        mlflow_run_id: str = "",
        model_task: str = "forecasting",
    ) -> DriftReport | None:
        """Detect prediction drift via PSI on model outputs.

        Args:
            db: Active database session.
            model_name: Registered model name.
            model_version: Model version string.
            period_start: Start of evaluation window.
            period_end: End of evaluation window.
            reference_predictions: Reference prediction distribution.
            mlflow_run_id: MLflow run ID.
            model_task: Task type.

        Returns:
            DriftReport or None if insufficient data.
        """
        if len(reference_predictions) < 10:
            return None

        ref_array = np.array(reference_predictions)

        logs = (
            db.query(PredictionLog)
            .filter(
                PredictionLog.model_name == model_name,
                PredictionLog.model_version == model_version,
                PredictionLog.timestamp >= period_start,
                PredictionLog.timestamp <= period_end,
            )
            .all()
        )

        if len(logs) < 10:
            return None

        cur_array = np.array([log.predicted_value for log in logs])
        psi = _compute_psi(ref_array, cur_array)
        severity, details_msg = _classify_psi_severity(psi)

        report = DriftReport(
            model_name=model_name,
            model_version=model_version,
            mlflow_run_id=mlflow_run_id,
            model_task=model_task,
            drift_type="prediction_drift",
            feature_name=None,
            period_start=period_start,
            period_end=period_end,
            drift_score=psi,
            drift_threshold=PSI_MEDIUM,
            is_drifted=psi >= PSI_LOW,
            severity=severity,
            reference_stats=_compute_distribution_stats(ref_array),
            current_stats=_compute_distribution_stats(cur_array),
            details={"message": details_msg, "method": "PSI", "buckets": 10},
        )
        db.add(report)
        db.commit()
        db.refresh(report)

        logger.info("Prediction drift: PSI=%.4f severity=%s", psi, severity)
        return report

    def detect_all_drifts(
        self,
        db: Session,
        model_name: str,
        model_version: str,
        *,
        period_hours: int = 168,
        reference_features: dict[str, list[float]] | None = None,
        reference_predictions: list[float] | None = None,
        reference_errors: list[float] | None = None,
        mlflow_run_id: str = "",
        model_task: str = "forecasting",
    ) -> list[DriftReport]:
        """Run all drift detection types for a model.

        Args:
            db: Active database session.
            model_name: Registered model name.
            model_version: Model version string.
            period_hours: Hours to look back.
            reference_features: Dict of feature_name -> reference values.
            reference_predictions: Reference prediction distribution.
            reference_errors: Reference error distribution.
            mlflow_run_id: MLflow run ID.
            model_task: Task type.

        Returns:
            List of DriftReport records.
        """
        now = datetime.now(timezone.utc)
        period_start = now - timedelta(hours=period_hours)
        reports: list[DriftReport] = []

        # Data drift per feature (requires reference_features from MLflow)
        if reference_features:
            for feature_name, ref_values in reference_features.items():
                try:
                    report = self.detect_data_drift(
                        db,
                        model_name,
                        model_version,
                        period_start=period_start,
                        period_end=now,
                        feature_name=feature_name,
                        reference_values=ref_values,
                        mlflow_run_id=mlflow_run_id,
                        model_task=model_task,
                    )
                    if report:
                        reports.append(report)
                except Exception:
                    logger.exception("Failed to detect data drift for %s", feature_name)

        # Concept drift (auto-reference if none provided)
        try:
            report = self._detect_concept_drift_with_fallback(
                db,
                model_name,
                model_version,
                period_start=period_start,
                period_end=now,
                reference_errors=reference_errors,
                mlflow_run_id=mlflow_run_id,
                model_task=model_task,
            )
            if report:
                reports.append(report)
        except Exception:
            logger.exception("Failed to detect concept drift")

        # Prediction drift (auto-reference from first half of predictions)
        try:
            report = self._detect_prediction_drift_with_fallback(
                db,
                model_name,
                model_version,
                period_start=period_start,
                period_end=now,
                reference_predictions=reference_predictions,
                mlflow_run_id=mlflow_run_id,
                model_task=model_task,
            )
            if report:
                reports.append(report)
        except Exception:
            logger.exception("Failed to detect prediction drift")

        return reports

    def _detect_concept_drift_with_fallback(
        self,
        db: Session,
        model_name: str,
        model_version: str,
        *,
        period_start: datetime,
        period_end: datetime,
        reference_errors: list[float] | None = None,
        mlflow_run_id: str = "",
        model_task: str = "forecasting",
    ) -> DriftReport | None:
        # First try with time filter
        report = self.detect_concept_drift(
            db,
            model_name,
            model_version,
            period_start=period_start,
            period_end=period_end,
            reference_errors=reference_errors,
            mlflow_run_id=mlflow_run_id,
            model_task=model_task,
        )
        if report is not None:
            return report
        # Fall back: all-time (no time filter on error logs)
        logger.info("Concept drift: insufficient logs in time window; trying all-time.")
        # Query the full timerange
        all_logs = (
            db.query(PredictionLog)
            .filter(
                PredictionLog.model_name == model_name,
                PredictionLog.model_version == model_version,
                PredictionLog.error.isnot(None),
            )
            .order_by(PredictionLog.timestamp)
            .all()
        )
        if len(all_logs) < 10:
            return None
        return self.detect_concept_drift(
            db,
            model_name,
            model_version,
            period_start=all_logs[0].timestamp,
            period_end=all_logs[-1].timestamp,
            reference_errors=reference_errors,
            mlflow_run_id=mlflow_run_id,
            model_task=model_task,
        )

    def _detect_prediction_drift_with_fallback(
        self,
        db: Session,
        model_name: str,
        model_version: str,
        *,
        period_start: datetime,
        period_end: datetime,
        reference_predictions: list[float] | None = None,
        mlflow_run_id: str = "",
        model_task: str = "forecasting",
    ) -> DriftReport | None:
        # Auto-compute reference predictions from first half of the data
        # if none provided (same approach as concept drift)
        if reference_predictions is None or len(reference_predictions) < 10:
            all_preds = (
                db.query(PredictionLog.predicted_value, PredictionLog.timestamp)
                .filter(
                    PredictionLog.model_name == model_name,
                    PredictionLog.model_version == model_version,
                )
                .order_by(PredictionLog.timestamp)
                .all()
            )
            if len(all_preds) < 20:
                return None
            midpoint = len(all_preds) // 2
            reference_predictions = [float(row[0]) for row in all_preds[:midpoint]]
            # Use full range for the current window
            period_start = all_preds[0][1]
            period_end = all_preds[-1][1]

        return self.detect_prediction_drift(
            db,
            model_name,
            model_version,
            period_start=period_start,
            period_end=period_end,
            reference_predictions=reference_predictions,
            mlflow_run_id=mlflow_run_id,
            model_task=model_task,
        )
