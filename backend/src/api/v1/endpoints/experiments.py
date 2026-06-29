"""
Experiment comparison endpoint.

GET /api/v1/models/{model_name}/experiments/compare
  Fetches hyperparameters, training metrics, evaluation metrics, and
  training-data statistics for 2-10 registered model versions and returns
  a structured side-by-side comparison payload.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from functools import partial
from typing import Annotated, Any

import mlflow.tracking
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.api.v1.deps import get_current_ai_engineer_or_admin
from src.core.config import settings
from src.database import get_db
from src.schemas import (
    ExperimentComparisonResponse,
    ExperimentVersionDetail,
    UserResponse,
)

router = APIRouter()

_MIN_COMPARABLE_VERSIONS = 2
_MAX_COMPARABLE_VERSIONS = 10
_DEFAULT_EVALUATION_WINDOW_DAYS = 30
_DEFAULT_COMMON_METRICS = ["mae", "rmse", "mape", "r2_score"]


# ---------------------------------------------------------------------------
# Pure helpers - no I/O, fully unit-testable without mocks
# ---------------------------------------------------------------------------


def _parse_and_validate_versions(versions_csv: str) -> list[str]:
    """Split a comma-separated version string and enforce the 2-10 range."""
    parsed = [v.strip() for v in versions_csv.split(",") if v.strip()]
    if len(parsed) < _MIN_COMPARABLE_VERSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Provide between {_MIN_COMPARABLE_VERSIONS} and "
                f"{_MAX_COMPARABLE_VERSIONS} comma-separated versions. "
                f"Received {len(parsed)}."
            ),
        )
    if len(parsed) > _MAX_COMPARABLE_VERSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Provide between {_MIN_COMPARABLE_VERSIONS} and "
                f"{_MAX_COMPARABLE_VERSIONS} comma-separated versions. "
                f"Received {len(parsed)}."
            ),
        )
    return parsed


def _resolve_evaluation_window(
    start: datetime | None, end: datetime | None
) -> tuple[datetime, datetime]:
    """Default evaluation window: last 30 days ending at the current moment."""
    resolved_end = end or datetime.now(timezone.utc)
    resolved_start = start or (
        resolved_end - timedelta(days=_DEFAULT_EVALUATION_WINDOW_DAYS)
    )
    return resolved_start, resolved_end


def _infer_training_data_attrs(
    run_tags: dict[str, str], run_params: dict[str, str]
) -> dict[str, Any]:
    """Extract training-data provenance from MLflow run tags and params."""
    feature_count_raw = run_params.get("feature_count") or run_tags.get("feature_count")
    feature_count: int | None = None
    if feature_count_raw is not None:
        try:
            feature_count = int(float(feature_count_raw))
        except (ValueError, TypeError):
            pass

    return {
        "data_source": run_tags.get("data_source") or run_tags.get("datasource_used"),
        "training_start": run_tags.get("training_start")
        or run_tags.get("time_range_start"),
        "training_end": run_tags.get("training_end") or run_tags.get("time_range_end"),
        "feature_count": feature_count,
    }


def _strip_system_tags(tags: dict[str, str]) -> dict[str, str]:
    """Remove MLflow internal tags; they are not useful for UI comparison."""
    return {key: value for key, value in tags.items() if not key.startswith("mlflow.")}


def _compute_common_keys(
    details: list[ExperimentVersionDetail], field: str
) -> list[str]:
    """Return sorted keys that appear in all version details for a dict field."""
    if not details:
        return []
    key_sets = [set(getattr(detail, field, {}).keys()) for detail in details]
    return sorted(key_sets[0].intersection(*key_sets[1:]))


def _ms_to_datetime(value: int | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc)


def _build_version_detail(
    version: str,
    run_detail: dict[str, Any],
    eval_metrics: dict[str, float | None],
    training_stats: dict[str, int | None],
    current_stage: str | None,
) -> ExperimentVersionDetail:
    """Assemble a single ExperimentVersionDetail from raw MLflow and DB data."""
    raw_tags = run_detail.get("tags", {})
    params = run_detail.get("params", {})
    training_data_attrs = _infer_training_data_attrs(raw_tags, params)
    start_time = run_detail.get("start_time")
    end_time = run_detail.get("end_time")
    algorithm = (
        raw_tags.get("algorithm")
        or raw_tags.get("mlflow.runName", "").split("_")[0]
        or None
    )

    return ExperimentVersionDetail(
        version=version,
        run_id=run_detail["run_id"],
        model_task=raw_tags.get("model_task") or raw_tags.get("task"),
        algorithm=algorithm,
        current_stage=current_stage,
        status=run_detail.get("status"),
        started_at=_ms_to_datetime(start_time),
        ended_at=_ms_to_datetime(end_time),
        hyperparameters=params,
        training_metrics={
            key: float(value)
            for key, value in run_detail.get("metrics", {}).items()
            if isinstance(value, (int, float))
        },
        evaluation_metrics=eval_metrics,
        tags=_strip_system_tags(raw_tags),
        training_building_count=training_stats.get("building_count"),
        training_metric_count=training_stats.get("metric_count"),
        training_row_count=training_stats.get("row_count"),
        data_source=training_data_attrs["data_source"],
        training_data_source=training_data_attrs["data_source"],
        training_start=training_data_attrs["training_start"],
        training_end=training_data_attrs["training_end"],
        feature_count=training_data_attrs["feature_count"],
        run_start_time=start_time,
        run_end_time=end_time,
        run_status=run_detail.get("status"),
    )


# ---------------------------------------------------------------------------
# MLflow helpers
# ---------------------------------------------------------------------------


def _get_model_version_info(
    client: Any,
    model_name: str,
    version: str,
) -> tuple[str, str | None]:
    """Return (run_id, current_stage) for a registered model version."""
    try:
        model_version = client.get_model_version(model_name, version)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model '{model_name}' version '{version}' not found in MLflow: {exc}",
        ) from exc
    return model_version.run_id, getattr(model_version, "current_stage", None)


def _fetch_mlflow_run_detail(client: Any, run_id: str) -> dict[str, Any]:
    """Retrieve params, metrics, tags, and run info for a single MLflow run."""
    try:
        run = client.get_run(run_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"MLflow unreachable while fetching run '{run_id}': {exc}",
        ) from exc

    return {
        "run_id": run.info.run_id,
        "params": dict(run.data.params or {}),
        "metrics": dict(run.data.metrics or {}),
        "tags": dict(run.data.tags or {}),
        "start_time": run.info.start_time,
        "end_time": run.info.end_time,
        "status": run.info.status,
    }


# ---------------------------------------------------------------------------
# DB helpers - I/O isolated to the edge
# ---------------------------------------------------------------------------


def _fetch_evaluation_metrics(
    db: Session,
    model_name: str,
    version: str,
    period_start: datetime,
    period_end: datetime,
) -> dict[str, float | None]:
    """
    Query the most recent ModelPerformance record that overlaps the window.

    Falls back to the latest row for historical models whose evaluations predate
    the default 30-day window.
    """
    from src.models import ModelPerformance

    base_query = db.query(ModelPerformance).filter(
        ModelPerformance.model_name == model_name,
        ModelPerformance.model_version == version,
    )
    record = (
        base_query.filter(
            ModelPerformance.period_end >= period_start,
            ModelPerformance.period_start <= period_end,
        )
        .order_by(ModelPerformance.computed_at.desc())
        .first()
    )
    if record is None:
        record = base_query.order_by(ModelPerformance.computed_at.desc()).first()
    if record is None:
        return {}

    return {
        key: value
        for key, value in {
            "mae": record.mae,
            "rmse": record.rmse,
            "mape": record.mape,
            "r2_score": record.r2_score,
            "mean_error": record.mean_error,
            "p10_error": record.p10_error,
            "p90_error": record.p90_error,
            "baseline_mae": record.baseline_mae,
            "baseline_rmse": record.baseline_rmse,
            "performance_ratio": record.performance_ratio,
        }.items()
        if value is not None
    }


def _fetch_training_data_stats(
    db: Session,
    model_name: str,
    version: str,
) -> dict[str, int | None]:
    """
    Aggregate prediction_log to infer training-data footprint.

    Returns distinct building count, distinct metric count, and total logged rows
    for the requested model/version. All values are None when no rows exist.
    """
    from src.models import PredictionLog

    row = (
        db.query(
            func.count(func.distinct(PredictionLog.building_id)).label(
                "building_count"
            ),
            func.count(func.distinct(PredictionLog.metric_type_id)).label(
                "metric_count"
            ),
            func.count(PredictionLog.id).label("row_count"),
        )
        .filter(
            PredictionLog.model_name == model_name,
            PredictionLog.model_version == version,
        )
        .one_or_none()
    )

    if row is None or row.row_count == 0:
        return {"building_count": None, "metric_count": None, "row_count": None}
    return {
        "building_count": int(row.building_count),
        "metric_count": int(row.metric_count),
        "row_count": int(row.row_count),
    }


# ---------------------------------------------------------------------------
# Data-gathering orchestrator
# ---------------------------------------------------------------------------


async def _gather_version_details(
    client: Any,
    model_name: str,
    versions: list[str],
    db: Session,
    period_start: datetime,
    period_end: datetime,
) -> list[ExperimentVersionDetail]:
    """
    Fan out synchronous MLflow calls through the executor.

    DB calls stay sequential because the injected SQLAlchemy Session is not
    thread-safe.
    """
    loop = asyncio.get_running_loop()

    version_infos: list[tuple[str, str | None]] = await asyncio.gather(
        *[
            loop.run_in_executor(
                None, partial(_get_model_version_info, client, model_name, version)
            )
            for version in versions
        ]
    )
    run_details: list[dict[str, Any]] = await asyncio.gather(
        *[
            loop.run_in_executor(
                None, partial(_fetch_mlflow_run_detail, client, run_id)
            )
            for run_id, _ in version_infos
        ]
    )

    results: list[ExperimentVersionDetail] = []
    for version, (_run_id, current_stage), run_detail in zip(
        versions, version_infos, run_details
    ):
        results.append(
            _build_version_detail(
                version=version,
                run_detail=run_detail,
                eval_metrics=_fetch_evaluation_metrics(
                    db, model_name, version, period_start, period_end
                ),
                training_stats=_fetch_training_data_stats(db, model_name, version),
                current_stage=current_stage,
            )
        )
    return results


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.get(
    "/{model_name}/experiments/compare",
    response_model=ExperimentComparisonResponse,
    summary="Compare 2-10 model versions",
)
async def compare_experiment_versions(
    model_name: str,
    versions: Annotated[
        str,
        Query(description="Comma-separated list of 2-10 model versions to compare"),
    ],
    period_start: Annotated[
        datetime | None,
        Query(description="Evaluation window start (inclusive)"),
    ] = None,
    period_end: Annotated[
        datetime | None,
        Query(description="Evaluation window end (inclusive)"),
    ] = None,
    db: Session = Depends(get_db),
    _current_user: UserResponse = Depends(get_current_ai_engineer_or_admin),
) -> ExperimentComparisonResponse:
    parsed_versions = _parse_and_validate_versions(versions)
    eval_start, eval_end = _resolve_evaluation_window(period_start, period_end)
    client = mlflow.tracking.MlflowClient(tracking_uri=settings.MLFLOW_TRACKING_URI)

    version_details = await _gather_version_details(
        client=client,
        model_name=model_name,
        versions=parsed_versions,
        db=db,
        period_start=eval_start,
        period_end=eval_end,
    )
    common_metrics = _compute_common_keys(version_details, "evaluation_metrics")

    return ExperimentComparisonResponse(
        model_name=model_name,
        versions=version_details,
        common_hyperparameters=_compute_common_keys(
            version_details, "hyperparameters"
        ),
        common_evaluation_metrics=common_metrics,
        common_metrics=common_metrics or _DEFAULT_COMMON_METRICS,
        comparison_period_start=eval_start,
        comparison_period_end=eval_end,
    )
