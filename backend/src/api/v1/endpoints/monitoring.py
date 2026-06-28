"""Monitoring API endpoints for model performance and drift detection."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from src.api.v1.deps import get_current_ai_engineer_or_admin
from src.database import get_db
from src.ml.monitoring.drift_detector import DriftDetector
from src.ml.monitoring.health_calculator import HealthCalculator, HealthResult
from src.ml.monitoring.performance_evaluator import PerformanceEvaluator
from src.schemas import (
    DriftReportResponse,
    ModelDriftTimelineResponse,
    ModelMonitoringSummary,
    ModelPerformanceResponse,
    ModelPerformanceTimelineResponse,
    ModelVersionComparisonResponse,
    UserResponse,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def _resolve_model_version(
    db: Session, model_name: str, model_version: str | None = None
) -> str:
    """Resolve model version to a concrete version string."""
    if model_version:
        return model_version

    from mlflow.tracking import MlflowClient
    from src.core.config import settings

    client = MlflowClient(tracking_uri=settings.MLFLOW_TRACKING_URI)
    versions = client.search_model_versions(f"name='{model_name}'")
    if not versions:
        raise HTTPException(
            status_code=404, detail=f"No versions found for model '{model_name}'"
        )

    # Prefer production version
    prod = [v for v in versions if getattr(v, "current_stage", None) == "Production"]
    if prod:
        return prod[0].version

    # Fall back to latest version
    return max(versions, key=lambda v: int(v.version)).version


def _drift_to_response(record: Any) -> DriftReportResponse:
    return DriftReportResponse(
        id=str(record.id),
        model_name=record.model_name,
        model_version=record.model_version,
        mlflow_run_id=record.mlflow_run_id,
        model_task=record.model_task,
        drift_type=record.drift_type,
        feature_name=record.feature_name,
        period_start=record.period_start,
        period_end=record.period_end,
        drift_score=record.drift_score,
        drift_threshold=record.drift_threshold,
        is_drifted=record.is_drifted,
        severity=record.severity,
        reference_stats=record.reference_stats or {},
        current_stats=record.current_stats or {},
        details=record.details,
        computed_at=record.computed_at,
    )


def _perf_to_response(record: Any) -> ModelPerformanceResponse:
    return ModelPerformanceResponse(
        id=str(record.id),
        model_name=record.model_name,
        model_version=record.model_version,
        mlflow_run_id=record.mlflow_run_id,
        model_task=record.model_task,
        building_id=record.building_id,
        metric_type_id=record.metric_type_id,
        period_start=record.period_start,
        period_end=record.period_end,
        sample_count=record.sample_count,
        mae=record.mae,
        rmse=record.rmse,
        mape=record.mape,
        r2_score=record.r2_score,
        mean_error=record.mean_error,
        p10_error=record.p10_error,
        p90_error=record.p90_error,
        baseline_mae=record.baseline_mae,
        baseline_rmse=record.baseline_rmse,
        performance_ratio=record.performance_ratio,
        computed_at=record.computed_at,
    )


@router.get(
    "/{name}/monitoring/performance",
    response_model=ModelPerformanceTimelineResponse,
    summary="Get performance timeline",
)
async def get_performance_timeline(
    name: str,
    db: Session = Depends(get_db),
    current_user: UserResponse = Depends(get_current_ai_engineer_or_admin),
    model_version: str | None = Query(None, description="Filter by specific version"),
    period_start: datetime | None = Query(
        None, description="Start of time window (ISO 8601)"
    ),
    period_end: datetime | None = Query(
        None, description="End of time window (ISO 8601)"
    ),
    granularity: str = Query(
        "daily",
        pattern="^(hourly|daily|weekly)$",
        description="Aggregation granularity",
    ),
) -> Any:
    """Get performance timeline (MAE/RMSE/MAPE over time) for a model.

    When ``period_start`` / ``period_end`` are omitted all stored performance
    records for the model are returned (no implicit 30-day window).  This
    matches the Overview tab which also uses no time filter.
    """
    from src.models import ModelPerformance

    query = db.query(ModelPerformance).filter(
        ModelPerformance.model_name == name,
    )

    # Only apply time-window filter when explicitly requested.
    # ModelPerformance.period_start/period_end reflect the timerange of the
    # *predictions* being evaluated, not when the evaluation ran.  An automatic
    # "last 30 days" default would silently hide evaluations of historical
    # forecasts (e.g. January predictions evaluated in June).
    if period_start is not None:
        query = query.filter(ModelPerformance.period_start >= period_start)
    if period_end is not None:
        query = query.filter(ModelPerformance.period_end <= period_end)

    if model_version:
        query = query.filter(ModelPerformance.model_version == model_version)

    records = query.order_by(ModelPerformance.computed_at.asc()).all()

    metrics = [_perf_to_response(r) for r in records]

    # Resolve version for the response
    resolved_version = model_version
    if not resolved_version and metrics:
        resolved_version = metrics[0].model_version
    elif not resolved_version:
        try:
            resolved_version = _resolve_model_version(db, name)
        except Exception:
            resolved_version = "unknown"

    return ModelPerformanceTimelineResponse(
        model_name=name,
        model_version=resolved_version,
        metrics=metrics,
    )


@router.get(
    "/{name}/monitoring/drift",
    response_model=ModelDriftTimelineResponse,
    summary="Get drift detection results",
)
async def get_drift_timeline(
    name: str,
    db: Session = Depends(get_db),
    current_user: UserResponse = Depends(get_current_ai_engineer_or_admin),
    model_version: str | None = Query(None, description="Filter by specific version"),
    period_start: datetime | None = Query(
        None, description="Start of time window (ISO 8601)"
    ),
    period_end: datetime | None = Query(
        None, description="End of time window (ISO 8601)"
    ),
    drift_type: str = Query(
        "all",
        pattern="^(data_drift|concept_drift|prediction_drift|all)$",
        description="Type of drift to filter",
    ),
) -> Any:
    """Get drift detection results for a model."""
    from src.models import DriftReport

    query = db.query(DriftReport).filter(
        DriftReport.model_name == name,
    )

    # Only apply time-window filter when explicitly requested
    # (same reasoning as get_performance_timeline).
    if period_start is not None:
        query = query.filter(DriftReport.period_start >= period_start)
    if period_end is not None:
        query = query.filter(DriftReport.period_end <= period_end)

    if model_version:
        query = query.filter(DriftReport.model_version == model_version)

    if drift_type != "all":
        query = query.filter(DriftReport.drift_type == drift_type)

    records = query.order_by(DriftReport.computed_at.desc()).all()

    def to_response(record: DriftReport) -> DriftReportResponse:
        return _drift_to_response(record)

    overall = [to_response(r) for r in records if not r.feature_name]
    feature_drift: dict[str, list[DriftReportResponse]] = {}
    for r in records:
        if r.feature_name:
            feature_drift.setdefault(r.feature_name, []).append(to_response(r))

    resolved_version = model_version
    if not resolved_version and overall:
        resolved_version = overall[0].model_version
    elif not resolved_version:
        try:
            resolved_version = _resolve_model_version(db, name)
        except Exception:
            resolved_version = "unknown"

    return ModelDriftTimelineResponse(
        model_name=name,
        model_version=resolved_version,
        overall_drift=overall,
        feature_drift=feature_drift,
    )


@router.get(
    "/{name}/monitoring/summary",
    response_model=ModelMonitoringSummary,
    summary="Get health score + summary",
)
async def get_monitoring_summary(
    name: str,
    db: Session = Depends(get_db),
    current_user: UserResponse = Depends(get_current_ai_engineer_or_admin),
    model_version: str | None = Query(None, description="Filter by specific version"),
) -> Any:
    """Get health score and monitoring summary for a model."""
    try:
        resolved_version = _resolve_model_version(db, name, model_version)
    except Exception:
        resolved_version = model_version or "unknown"

    calculator = HealthCalculator()
    result: HealthResult = calculator.calculate(db, name, resolved_version)

    latest_perf = None
    if result.latest_performance:
        latest_perf = _perf_to_response(result.latest_performance)

    active_drifts = [_drift_to_response(d) for d in (result.active_drifts or [])]

    return ModelMonitoringSummary(
        model_name=name,
        model_version=resolved_version,
        health_score=result.health_score,
        status=result.status,
        last_performance=latest_perf,
        active_drifts=active_drifts,
        total_predictions=result.total_predictions,
        pending_actuals=result.pending_actuals,
    )


@router.get(
    "/{name}/monitoring/alerts",
    summary="Get active alerts",
)
async def get_monitoring_alerts(
    name: str,
    db: Session = Depends(get_db),
    current_user: UserResponse = Depends(get_current_ai_engineer_or_admin),
    model_version: str | None = Query(None, description="Filter by specific version"),
    severity: str | None = Query(
        None,
        pattern="^(low|medium|high|critical)$",
        description="Filter by severity level",
    ),
    limit: int = Query(50, ge=1, le=200, description="Maximum records to return"),
) -> Any:
    """Get active alerts (drift reports with non-none severity) for a model."""
    from src.models import DriftReport

    query = db.query(DriftReport).filter(
        DriftReport.model_name == name,
        DriftReport.severity.notin_(["none"]),
    )

    if model_version:
        query = query.filter(DriftReport.model_version == model_version)

    if severity:
        query = query.filter(DriftReport.severity == severity)

    records = query.order_by(DriftReport.computed_at.desc()).limit(limit).all()

    return {
        "model_name": name,
        "model_version": model_version,
        "alerts": [
            {
                "id": str(r.id),
                "model_name": r.model_name,
                "model_version": r.model_version,
                "drift_type": r.drift_type,
                "feature_name": r.feature_name,
                "severity": r.severity,
                "drift_score": r.drift_score,
                "is_drifted": r.is_drifted,
                "message": (r.details or {}).get("message", ""),
                "computed_at": r.computed_at,
            }
            for r in records
        ],
        "total": len(records),
    }


@router.post(
    "/{name}/monitoring/evaluate",
    summary="Manually trigger evaluation",
)
async def trigger_evaluation(
    name: str,
    db: Session = Depends(get_db),
    current_user: UserResponse = Depends(get_current_ai_engineer_or_admin),
    model_version: str | None = Query(None, description="Specific version to evaluate"),
    period_hours: int = Query(
        24, ge=1, le=720, description="Hours to look back for evaluation"
    ),
) -> Any:
    """Manually trigger performance evaluation for a model."""
    evaluator = PerformanceEvaluator()

    if model_version:
        now = datetime.now(timezone.utc)
        period_start = now - timedelta(hours=period_hours)
        record = evaluator.evaluate(
            db,
            name,
            model_version,
            period_start=period_start,
            period_end=now,
        )
        if record is None:
            # Fall back: try without time filter for predictions older
            # than the lookback window (e.g., historical forecast).
            logger.info(
                "No predictions with actuals for %s v%s in last %dh; "
                "trying all-time fallback.",
                name,
                model_version,
                period_hours,
            )
            record = evaluator.evaluate(
                db,
                name,
                model_version,
            )
        if record is None:
            return {
                "message": "Insufficient prediction logs with actuals for evaluation",
                "model_name": name,
                "model_version": model_version,
            }
        return {
            "message": "Evaluation completed successfully",
            "model_name": record.model_name,
            "model_version": record.model_version,
            "mae": record.mae,
            "rmse": record.rmse,
            "mape": record.mape,
            "sample_count": record.sample_count,
        }
    else:
        records = evaluator.evaluate_all_models(
            db,
            period_hours=period_hours,
            model_name=name,
        )
        return {
            "message": f"Evaluation completed for {len(records)} model/version combinations",
            "evaluated_models": [
                {
                    "model_name": r.model_name,
                    "model_version": r.model_version,
                    "mae": r.mae,
                    "rmse": r.rmse,
                    "sample_count": r.sample_count,
                }
                for r in records
            ],
        }


@router.post(
    "/{name}/monitoring/drift/detect",
    summary="Manually trigger drift detection",
)
async def trigger_drift_detection(
    name: str,
    db: Session = Depends(get_db),
    current_user: UserResponse = Depends(get_current_ai_engineer_or_admin),
    model_version: str | None = Query(None, description="Specific version to check"),
    period_hours: int = Query(
        168, ge=1, le=2160, description="Hours to look back for drift detection"
    ),
    drift_type: str = Query(
        "all",
        pattern="^(data_drift|concept_drift|prediction_drift|all)$",
        description="Type of drift to detect",
    ),
) -> Any:
    """Manually trigger drift detection for a model."""
    try:
        resolved_version = _resolve_model_version(db, name, model_version)
    except Exception:
        resolved_version = model_version or "unknown"

    detector = DriftDetector()
    reports = detector.detect_all_drifts(
        db,
        name,
        resolved_version,
        period_hours=period_hours,
    )

    if drift_type != "all":
        reports = [r for r in reports if r.drift_type == drift_type]

    return {
        "message": f"Drift detection completed: {len(reports)} reports generated",
        "model_name": name,
        "model_version": resolved_version,
        "drift_reports": [
            {
                "drift_type": r.drift_type,
                "feature_name": r.feature_name,
                "severity": r.severity,
                "drift_score": r.drift_score,
                "is_drifted": r.is_drifted,
            }
            for r in reports
        ],
    }


@router.get(
    "/{name}/monitoring/compare",
    response_model=ModelVersionComparisonResponse,
    summary="Compare two versions",
)
async def compare_versions(
    name: str,
    db: Session = Depends(get_db),
    current_user: UserResponse = Depends(get_current_ai_engineer_or_admin),
    version_a: str = Query(..., description="First version to compare"),
    version_b: str = Query(..., description="Second version to compare"),
    period_start: datetime | None = Query(
        None, description="Start of comparison window (ISO 8601)"
    ),
    period_end: datetime | None = Query(
        None, description="End of comparison window (ISO 8601)"
    ),
) -> Any:
    """Compare two model versions side by side."""
    from src.models import ModelPerformance

    end = period_end or datetime.now(timezone.utc)
    start = period_start or (end - timedelta(days=30))

    perf_a = (
        db.query(ModelPerformance)
        .filter(
            ModelPerformance.model_name == name,
            ModelPerformance.model_version == version_a,
            ModelPerformance.period_start >= start,
            ModelPerformance.period_end <= end,
        )
        .order_by(ModelPerformance.computed_at.desc())
        .first()
    )

    perf_b = (
        db.query(ModelPerformance)
        .filter(
            ModelPerformance.model_name == name,
            ModelPerformance.model_version == version_b,
            ModelPerformance.period_start >= start,
            ModelPerformance.period_end <= end,
        )
        .order_by(ModelPerformance.computed_at.desc())
        .first()
    )

    def perf_to_dict(perf) -> dict[str, Any]:
        if perf is None:
            return {}
        return {
            "version": perf.model_version,
            "mae": perf.mae,
            "rmse": perf.rmse,
            "mape": perf.mape,
            "r2_score": perf.r2_score,
            "mean_error": perf.mean_error,
            "sample_count": perf.sample_count,
            "baseline_mae": perf.baseline_mae,
            "baseline_rmse": perf.baseline_rmse,
            "performance_ratio": perf.performance_ratio,
            "computed_at": perf.computed_at,
        }

    versions = [perf_to_dict(perf_a), perf_to_dict(perf_b)]
    # Remove empty entries
    versions = [v for v in versions if v]

    return ModelVersionComparisonResponse(
        model_name=name,
        versions=versions,
        comparison_period_start=start,
        comparison_period_end=end,
    )
