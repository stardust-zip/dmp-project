"""
Experiment comparison endpoint.

GET /api/v1/models/{model_name}/experiments/compare
  Fetches hyperparameters, training metrics, evaluation metrics, and
  training-data statistics for 2–10 registered model versions and returns
  a structured side-by-side comparison payload.

Design notes:
  - All pure helpers (_parse*, _resolve*, _infer*, _strip*, _compute*, _build*)
    are free of I/O so they can be unit-tested without any mocks.
  - The two DB helpers (_fetch_*) are the only functions that touch the
    database session — I/O isolated to the edge.
  - mlflow.tracking.MlflowClient is accessed via the module reference (not a
    from-import) so that test patches on "mlflow.tracking.MlflowClient" are
    correctly intercepted at call time.
"""

from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

import mlflow.tracking
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from src import models
from src.api.v1.deps import get_current_ai_engineer_or_admin
from src.database import get_db
from src.schemas import (
    ExperimentComparisonResponse,
    ExperimentVersionDetail,
    UserResponse,
)

router = APIRouter()

_MAX_COMPARABLE_VERSIONS = 10
_DEFAULT_EVALUATION_WINDOW_DAYS = 30


# ---------------------------------------------------------------------------
# Pure helpers — no I/O, fully unit-testable without mocks
# ---------------------------------------------------------------------------


def _parse_and_validate_versions(versions_csv: str) -> list[str]:
    """Split a comma-separated version string and enforce the 2–10 range."""
    parsed = [v.strip() for v in versions_csv.split(",") if v.strip()]
    if not (2 <= len(parsed) <= _MAX_COMPARABLE_VERSIONS):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Provide between 2 and {_MAX_COMPARABLE_VERSIONS} comma-separated "
                f"versions. Received {len(parsed)}."
            ),
        )
    return parsed


def _resolve_evaluation_window(
    start: datetime | None, end: datetime | None
) -> tuple[datetime, datetime]:
    """Default evaluation window: last 30 days ending at the current moment."""
    resolved_end = end or datetime.now(timezone.utc)
    resolved_start = start or (resolved_end - timedelta(days=_DEFAULT_EVALUATION_WINDOW_DAYS))
    return resolved_start, resolved_end


def _infer_training_data_attrs(run_tags: dict, run_params: dict) -> dict:
    """
    Extract training-data provenance from MLflow run tags and params.
    run_params takes priority over run_tags for feature_count.
    """
    feature_count_raw = run_params.get("feature_count") or run_tags.get("feature_count")
    try:
        feature_count: int | None = int(float(feature_count_raw)) if feature_count_raw else None
    except (ValueError, TypeError):
        feature_count = None

    return {
        "data_source": run_tags.get("data_source") or run_tags.get("datasource_used"),
        "training_start": run_tags.get("training_start"),
        "training_end": run_tags.get("training_end"),
        "feature_count": feature_count,
    }


def _strip_system_tags(tags: dict) -> dict:
    """Remove MLflow internal tags (prefixed 'mlflow.') — not useful for UI comparison."""
    return {key: value for key, value in tags.items() if not key.startswith("mlflow.")}


def _compute_common_keys(details: list[ExperimentVersionDetail], field: str) -> list[str]:
    """Return sorted keys that appear in *all* version details for the given dict field."""
    if not details:
        return []
    key_sets = [set(getattr(detail, field, {}).keys()) for detail in details]
    return sorted(key_sets[0].intersection(*key_sets[1:]))


def _build_version_detail(
    version: str,
    run_detail: dict,
    eval_metrics: dict,
    training_stats: dict,
    current_stage: str | None,
) -> ExperimentVersionDetail:
    """Assemble a single ExperimentVersionDetail from raw MLflow + DB data."""
    raw_tags = run_detail.get("tags", {})
    training_data_attrs = _infer_training_data_attrs(raw_tags, run_detail.get("params", {}))

    started_at: datetime | None = None
    if run_detail.get("start_time"):
        started_at = datetime.fromtimestamp(
            run_detail["start_time"] / 1000, tz=timezone.utc
        )

    ended_at: datetime | None = None
    if run_detail.get("end_time"):
        ended_at = datetime.fromtimestamp(
            run_detail["end_time"] / 1000, tz=timezone.utc
        )

    return ExperimentVersionDetail(
        version=version,
        run_id=run_detail["run_id"],
        algorithm=raw_tags.get("algorithm"),
        current_stage=current_stage,
        status=run_detail.get("status"),
        started_at=started_at,
        ended_at=ended_at,
        hyperparameters=run_detail.get("params", {}),
        training_metrics={k: float(v) for k, v in run_detail.get("metrics", {}).items()},
        evaluation_metrics=eval_metrics,
        tags=_strip_system_tags(raw_tags),
        training_building_count=training_stats.get("building_count"),
        training_metric_count=training_stats.get("metric_count"),
        training_row_count=training_stats.get("row_count"),
        **training_data_attrs,
    )


# ---------------------------------------------------------------------------
# DB helpers — I/O isolated to the edge, injected as dependencies in the endpoint
# ---------------------------------------------------------------------------


def _to_optional_int(value: Any) -> int | None:
    """Safe coercion to int — returns None for anything that can't be converted."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _fetch_evaluation_metrics(
    db: Session,
    model_name: str,
    version: str,
    period_start: datetime,
    period_end: datetime,
) -> dict[str, float]:
    """Query the most recent ModelPerformance record within the evaluation window."""
    record = (
        db.query(models.ModelPerformance)
        .filter(
            models.ModelPerformance.model_name == model_name,
            models.ModelPerformance.model_version == version,
            models.ModelPerformance.period_end >= period_start,
            models.ModelPerformance.period_start <= period_end,
        )
        .order_by(models.ModelPerformance.computed_at.desc())
        .first()
    )
    if record is None:
        return {}
    return {
        key: val
        for key, val in {
            "mae": record.mae,
            "rmse": record.rmse,
            "mape": record.mape,
            "r2_score": record.r2_score,
            "mean_error": record.mean_error,
            "performance_ratio": record.performance_ratio,
        }.items()
        if val is not None
    }


def _fetch_training_data_stats(
    db: Session, model_name: str, version: str
) -> dict[str, int | None]:
    """
    Fetch training run statistics from the most recent ModelPerformance record.
    sample_count is the closest available DB proxy for total training rows.
    """
    record = (
        db.query(models.ModelPerformance)
        .filter(
            models.ModelPerformance.model_name == model_name,
            models.ModelPerformance.model_version == version,
        )
        .one_or_none()
    )
    if record is None:
        return {"building_count": None, "metric_count": None, "row_count": None}
    return {
        "building_count": _to_optional_int(getattr(record, "building_count", None)),
        "metric_count": _to_optional_int(getattr(record, "metric_count", None)),
        "row_count": _to_optional_int(getattr(record, "sample_count", None)),
    }


# ---------------------------------------------------------------------------
# MLflow extraction helper
# ---------------------------------------------------------------------------


def _extract_run_detail(run: Any) -> dict:
    """Convert a raw MLflow Run object to the flat dict format _build_version_detail expects."""
    return {
        "run_id": run.info.run_id,
        "params": dict(run.data.params),
        "metrics": dict(run.data.metrics),
        "tags": dict(run.data.tags),
        "start_time": run.info.start_time,
        "end_time": run.info.end_time,
        "status": run.info.status,
    }


def _assemble_version_detail(
    client: Any,
    db: Session,
    model_name: str,
    version: str,
    eval_start: datetime,
    eval_end: datetime,
) -> ExperimentVersionDetail:
    """Orchestrate all MLflow + DB calls for a single model version."""
    model_version = client.get_model_version(model_name, version)
    run_detail = _extract_run_detail(client.get_run(model_version.run_id))
    return _build_version_detail(
        version=version,
        run_detail=run_detail,
        eval_metrics=_fetch_evaluation_metrics(db, model_name, version, eval_start, eval_end),
        training_stats=_fetch_training_data_stats(db, model_name, version),
        current_stage=model_version.current_stage,
    )


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.get("/{model_name}/experiments/compare", response_model=ExperimentComparisonResponse)
def compare_experiment_versions(
    model_name: str,
    versions: Annotated[
        str,
        Query(description="Comma-separated list of 2–10 model versions to compare"),
    ],
    period_start: Annotated[datetime | None, Query(description="Evaluation window start (inclusive)")] = None,
    period_end: Annotated[datetime | None, Query(description="Evaluation window end (inclusive)")] = None,
    db: Session = Depends(get_db),
    _current_user: UserResponse = Depends(get_current_ai_engineer_or_admin),
) -> ExperimentComparisonResponse:
    parsed_versions = _parse_and_validate_versions(versions)
    eval_start, eval_end = _resolve_evaluation_window(period_start, period_end)
    client = mlflow.tracking.MlflowClient()

    version_details = [
        _assemble_version_detail(client, db, model_name, v, eval_start, eval_end)
        for v in parsed_versions
    ]

    return ExperimentComparisonResponse(
        model_name=model_name,
        versions=version_details,
        common_hyperparameters=_compute_common_keys(version_details, "hyperparameters"),
        common_evaluation_metrics=_compute_common_keys(version_details, "evaluation_metrics"),
        comparison_period_start=eval_start,
        comparison_period_end=eval_end,
    )
