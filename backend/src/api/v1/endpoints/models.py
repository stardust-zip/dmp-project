import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

from celery.result import AsyncResult
from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from mlflow.exceptions import MlflowException
from mlflow.tracking import MlflowClient
from sqlalchemy import func
from sqlalchemy.orm import Session
from src.api.v1.deps import get_current_ai_engineer_or_admin, get_current_user
from src.core.config import settings
from src.database import get_db
from src.models import AIPipelineLog, Device, Location, MetricType, TelemetryData
from src.schemas import (
    MLAlgorithm,
    ModelRollbackRequest,
    ModelRollbackResponse,
    ModelTask,
    ModelTrainingRequest,
    ModelTrainingResponse,
    ModelTrainingValidationMetric,
    ModelTrainingValidationResponse,
    ModelVersionResponse,
    ModelVersionsResponse,
    TrainingDataSource,
    UserResponse,
)
from src.tasks import celery_app, train_model_task

from mlflow import set_tracking_uri

router = APIRouter()
PRODUCTION_ALIAS = "production"
ACTIVE_TAG = "active"
STAGE_TAG = "stage"
MODEL_TASK_TAG = "model_task"
MIN_TRAINING_ROWS_PER_METRIC = 24
METER_DATA_DIR = Path("/app/data/raw/data/meters/cleaned")


def _mlflow_client() -> MlflowClient:
    set_tracking_uri(settings.MLFLOW_TRACKING_URI)
    return MlflowClient()


def _model_version_response(
    client: MlflowClient, model_version
) -> ModelVersionResponse:
    run_id = model_version.run_id
    if run_id is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Model version has no associated run ID.",
        )
    run = client.get_run(run_id)
    tags = dict(getattr(model_version, "tags", {}) or {})
    run_tags = dict(getattr(run.data, "tags", {}) or {})
    model_task = tags.get(MODEL_TASK_TAG) or run_tags.get(MODEL_TASK_TAG)
    return ModelVersionResponse(
        name=model_version.name,
        version=str(model_version.version),
        run_id=run_id,
        model_task=model_task,
        metrics=dict(run.data.metrics),
        tags=tags,
        current_stage=getattr(model_version, "current_stage", None),
        creation_timestamp=getattr(model_version, "creation_timestamp", None),
        last_updated_timestamp=getattr(model_version, "last_updated_timestamp", None),
    )


def _search_model_versions(client: MlflowClient, filter_string: str):
    try:
        return list(client.search_model_versions(filter_string))
    except MlflowException as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"MLflow registry query failed: {exc}",
        ) from exc


def _find_model_version_by_run_id(
    client: MlflowClient, mlflow_run_id: str, model_name: str | None
):
    filter_parts = [f"run_id = '{mlflow_run_id}'"]
    if model_name:
        filter_parts.insert(0, f"name = '{model_name}'")

    matches = _search_model_versions(client, " and ".join(filter_parts))
    if not matches:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No registered model version found for the supplied MLflow run ID.",
        )

    if len(matches) > 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Multiple registered model versions matched this MLflow run ID. "
                "Retry with model_name."
            ),
        )

    return matches[0]


def _set_optional_production_alias(
    client: MlflowClient, model_name: str, version: str
) -> None:
    try:
        client.set_registered_model_alias(model_name, PRODUCTION_ALIAS, version)
    except AttributeError:
        return


def _delete_optional_production_alias(client: MlflowClient, model_name: str) -> None:
    try:
        client.delete_registered_model_alias(model_name, PRODUCTION_ALIAS)
    except AttributeError:
        return
    except MlflowException:
        return


def _promote_model_version(client: MlflowClient, model_version) -> None:
    model_name = model_version.name
    version = str(model_version.version)

    for sibling in _search_model_versions(client, f"name = '{model_name}'"):
        client.set_model_version_tag(
            model_name, str(sibling.version), ACTIVE_TAG, "false"
        )

    client.set_model_version_tag(model_name, version, ACTIVE_TAG, "true")
    client.set_model_version_tag(model_name, version, STAGE_TAG, "production")
    _set_optional_production_alias(client, model_name, version)


def _demote_model_version(client: MlflowClient, model_version) -> None:
    model_name = model_version.name
    version = str(model_version.version)

    client.set_model_version_tag(model_name, version, ACTIVE_TAG, "false")
    client.set_model_version_tag(model_name, version, STAGE_TAG, "archived")

    production_version = _production_model_version(client, model_name)
    if production_version is not None and str(production_version.version) == version:
        _delete_optional_production_alias(client, model_name)


def _production_model_version(client: MlflowClient, model_name: str):
    try:
        return client.get_model_version_by_alias(model_name, PRODUCTION_ALIAS)
    except AttributeError:
        pass
    except MlflowException:
        pass

    versions = _search_model_versions(client, f"name = '{model_name}'")
    production_versions = [
        version
        for version in versions
        if (getattr(version, "tags", {}) or {}).get(ACTIVE_TAG) == "true"
        or (getattr(version, "tags", {}) or {}).get(STAGE_TAG) == "production"
        or getattr(version, "current_stage", None) == "Production"
    ]
    if not production_versions:
        return None

    return max(
        production_versions,
        key=lambda version: getattr(version, "last_updated_timestamp", 0) or 0,
    )


@router.get("/")
async def list_models(current_user: UserResponse = Depends(get_current_user)):
    """
    List all registered AI models (e.g., forecasting, anomaly detection) from MLflow.
    """
    client = _mlflow_client()
    try:
        registered_models = client.search_registered_models()
    except MlflowException as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"MLflow registry query failed: {exc}",
        ) from exc

    models_data = []
    for rm in registered_models:
        production_version = _production_model_version(client, rm.name)
        models_data.append(
            {
                "name": rm.name,
                "description": rm.description,
                "creation_timestamp": rm.creation_timestamp,
                "last_updated_timestamp": rm.last_updated_timestamp,
                "tags": dict(getattr(rm, "tags", {}) or {}),
                "production_version": (
                    {
                        "version": str(production_version.version),
                        "run_id": getattr(production_version, "run_id", None),
                        "current_stage": getattr(
                            production_version, "current_stage", None
                        ),
                        "status": getattr(production_version, "status", None),
                    }
                    if production_version is not None
                    else None
                ),
                "latest_versions": [
                    {
                        "version": str(v.version),
                        "current_stage": v.current_stage,
                        "status": v.status,
                    }
                    for v in (rm.latest_versions or [])
                ],
            }
        )

    return {"models": models_data}


@router.get("/{model_name}/versions", response_model=ModelVersionsResponse)
async def get_model_versions(
    model_name: str,
    current_user: UserResponse = Depends(get_current_user),
):
    """
    Return all registered MLflow versions for a model with their run IDs and metrics.
    """
    client = _mlflow_client()
    versions = _search_model_versions(client, f"name = '{model_name}'")

    if not versions:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No registered versions found for model '{model_name}'.",
        )

    return ModelVersionsResponse(
        model_name=model_name,
        versions=[
            _model_version_response(client, model_version)
            for model_version in sorted(
                versions, key=lambda item: int(item.version), reverse=True
            )
        ],
    )


@router.post("/train", response_model=ModelTrainingResponse)
async def trigger_training(
    payload: ModelTrainingRequest | None = Body(default=None),
    building_id: str = Query("Panther_parking_Lorriane"),
    site_id: str | None = Query(
        None,
        description="Optional site ID. Defaults to building_id for legacy callers.",
    ),
    metric_type: str = Query("electricity"),
    model_task: ModelTask = Query(
        ModelTask.Prediction,
        description="ML task to train.",
    ),
    data_source: TrainingDataSource = Query(
        "csv", description="Choose 'csv' for baseline or 'db' for live data"
    ),
    db: Session = Depends(get_db),
    current_user: UserResponse = Depends(get_current_ai_engineer_or_admin),
):
    """
    Trigger a configurable training job via Celery.
    """
    request = payload or _legacy_training_request(
        building_id=building_id,
        site_id=site_id,
        metric_type=metric_type,
        model_task=model_task,
        data_source=data_source,
    )
    validation = _validate_training_request(
        request, db, enforce_data_availability=False
    )
    if not validation.valid:
        raise HTTPException(
            status_code=422,
            detail=_training_error_detail(validation),
        )

    selected_algorithm = _algorithm_for_task(ModelTask(request.model_task))
    if ModelTask(request.model_task) != ModelTask.Prediction:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=(
                f"{ModelTask(request.model_task).value} training pipeline is not "
                "implemented yet."
            ),
        )
    if len(request.metrics) != 1:
        raise HTTPException(
            status_code=422,
            detail="Prediction training requires exactly one metric per model.",
        )

    task = train_model_task.delay(
        training_request=request.model_dump(mode="json", exclude_none=True)
    )

    return ModelTrainingResponse(
        message=(
            f"{ModelTask(request.model_task).value} training job queued using "
            f"{TrainingDataSource(request.data_source).value} data."
        ),
        task_id=task.id,
        model_task=request.model_task,
        data_source=request.data_source,
        algorithm=selected_algorithm,
        site_id=request.site_id,
        building_id=request.building_id,
        metrics=request.metrics,
        triggered_by=current_user.email,
    )


@router.post(
    "/train/validate",
    response_model=ModelTrainingValidationResponse,
)
async def validate_training(
    payload: ModelTrainingRequest,
    db: Session = Depends(get_db),
    current_user: UserResponse = Depends(get_current_ai_engineer_or_admin),
):
    """
    Validate a training request without queueing a training job.
    """
    return _validate_training_request(payload, db)


def _validate_training_request(
    request: ModelTrainingRequest,
    db: Session,
    *,
    enforce_data_availability: bool = True,
) -> ModelTrainingValidationResponse:
    errors: list[str] = []
    warnings: list[str] = []
    source = TrainingDataSource(request.data_source)
    start = _to_utc(request.time_range_start)
    end = _to_utc(request.time_range_end)

    site = _get_location_ref(db, request.site_id)
    building = (
        _get_location_ref(db, request.building_id) if request.building_id else None
    )
    if site is None:
        errors.append(f"Unknown site/building: {request.site_id}")
    if request.building_id and building is None:
        errors.append(f"Unknown building: {request.building_id}")

    target_building_ids: list[str] = []
    if site and building:
        if building.id == site.id or building.parent_id in (None, site.id):
            target_building_ids = [building.id]
        else:
            errors.append(
                f"Building '{building.id}' does not belong to site '{site.id}'."
            )
    elif building:
        target_building_ids = [building.id]
    elif site:
        child_rows = _safe_all(
            db.query(Location.id)
            .filter(Location.parent_id == site.id)
            .order_by(Location.id)
        )
        child_ids = [row[0] for row in child_rows]
        target_building_ids = child_ids or [site.id]

    known_metrics = {
        row[0]
        for row in db.query(MetricType.id)
        .filter(MetricType.id.in_(request.metrics))
        .all()
    }
    db_counts = (
        _count_db_training_rows(
            db=db,
            building_ids=target_building_ids,
            metrics=request.metrics,
            start=start,
            end=end,
        )
        if enforce_data_availability
        else {}
    )
    csv_counts = (
        _count_csv_training_rows(
            building_ids=target_building_ids,
            metrics=request.metrics,
            start=start,
            end=end,
            explicit_csv_path=request.csv_path,
        )
        if source == TrainingDataSource.CSV and enforce_data_availability
        else {}
    )

    if not target_building_ids and site is not None and building is None:
        errors.append(f"No buildings found for site/building '{request.site_id}'.")

    missing_metrics = sorted(set(request.metrics).difference(known_metrics))
    if missing_metrics:
        errors.append(f"Unknown metric(s): {', '.join(missing_metrics)}")

    metric_results: list[ModelTrainingValidationMetric] = []
    for metric in request.metrics:
        db_rows = db_counts.get(metric, 0)
        csv_rows = csv_counts.get(metric, 0)
        source_rows = csv_rows if source == TrainingDataSource.CSV else db_rows
        messages: list[str] = []

        if metric not in known_metrics:
            messages.append("Metric is not registered in metadata.")
        if (
            enforce_data_availability
            and source == TrainingDataSource.DB
            and db_rows == 0
        ):
            messages.append(
                "No database telemetry exists for this location and time range."
            )
        if (
            enforce_data_availability
            and source == TrainingDataSource.CSV
            and csv_rows == 0
        ):
            messages.append(
                "No cleaned CSV rows exist for this location and time range."
            )
        if enforce_data_availability and source_rows < MIN_TRAINING_ROWS_PER_METRIC:
            messages.append(
                f"Needs at least {MIN_TRAINING_ROWS_PER_METRIC} rows from the selected data source."
            )

        result = ModelTrainingValidationMetric(
            metric=metric,
            known_metric=metric in known_metrics,
            db_rows=db_rows,
            csv_rows=csv_rows,
            available_in_db=db_rows > 0,
            available_in_csv=csv_rows > 0,
            enough_rows=source_rows >= MIN_TRAINING_ROWS_PER_METRIC,
            required_rows=MIN_TRAINING_ROWS_PER_METRIC,
            messages=messages,
        )
        metric_results.append(result)

        if messages:
            errors.extend(f"{metric}: {message}" for message in messages)

    if source == TrainingDataSource.DB:
        csv_missing = [
            metric.metric for metric in metric_results if not metric.available_in_csv
        ]
        if csv_missing:
            warnings.append(
                "Cleaned CSV data is unavailable for: " + ", ".join(csv_missing)
            )

    deduped_errors = list(dict.fromkeys(errors))
    return ModelTrainingValidationResponse(
        valid=not deduped_errors,
        data_source=request.data_source,
        site_id=request.site_id,
        building_id=request.building_id,
        target_building_ids=target_building_ids,
        required_rows_per_metric=MIN_TRAINING_ROWS_PER_METRIC,
        errors=deduped_errors,
        warnings=warnings,
        metrics=metric_results,
    )


def _training_error_detail(
    validation: ModelTrainingValidationResponse,
) -> str | list[str]:
    metric_detail_errors = {
        f"{metric.metric}: {message}"
        for metric in validation.metrics
        for message in metric.messages
    }
    primary_errors = [
        error for error in validation.errors if error not in metric_detail_errors
    ]
    errors = primary_errors or validation.errors
    return errors[0] if len(errors) == 1 else errors


def _get_location_ref(db: Session, location_id: str):
    location = db.query(Location).filter(Location.id == location_id).one_or_none()
    if location is not None:
        return location

    id_row = db.query(Location.id).filter(Location.id == location_id).one_or_none()
    if id_row is None:
        return None

    class LocationRef:
        id = location_id
        parent_id = None

    return LocationRef()


def _safe_all(query) -> list:
    try:
        rows = query.all()
        iter(rows)
    except TypeError:
        return []
    return list(rows)


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _count_db_training_rows(
    *,
    db: Session,
    building_ids: list[str],
    metrics: list[str],
    start: datetime,
    end: datetime,
) -> dict[str, int]:
    if not building_ids or not metrics:
        return {}

    rows = (
        db.query(TelemetryData.metric_type_id, func.count().label("row_count"))
        .join(Device, Device.id == TelemetryData.device_id)
        .filter(Device.location_id.in_(building_ids))
        .filter(TelemetryData.metric_type_id.in_(metrics))
        .filter(TelemetryData.timestamp >= start)
        .filter(TelemetryData.timestamp <= end)
        .group_by(TelemetryData.metric_type_id)
        .all()
    )
    return {str(metric): int(row_count) for metric, row_count in rows}


def _count_csv_training_rows(
    *,
    building_ids: list[str],
    metrics: list[str],
    start: datetime,
    end: datetime,
    explicit_csv_path: str | None,
) -> dict[str, int]:
    if not building_ids or not metrics:
        return {}

    return {
        metric: _count_csv_metric_rows(
            metric=metric,
            building_ids=building_ids,
            start=start,
            end=end,
            explicit_csv_path=explicit_csv_path if len(metrics) == 1 else None,
        )
        for metric in metrics
    }


def _count_csv_metric_rows(
    *,
    metric: str,
    building_ids: list[str],
    start: datetime,
    end: datetime,
    explicit_csv_path: str | None,
) -> int:
    csv_path = (
        Path(explicit_csv_path)
        if explicit_csv_path
        else _cleaned_meter_csv_path(metric)
    )
    if not csv_path.exists() or not csv_path.is_file():
        return 0

    count = 0
    with csv_path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "timestamp" not in reader.fieldnames:
            return 0

        available_buildings = [
            building_id
            for building_id in building_ids
            if building_id in reader.fieldnames
        ]
        if not available_buildings:
            return 0

        for row in reader:
            timestamp = _parse_csv_timestamp(row.get("timestamp"))
            if timestamp is None or timestamp < start or timestamp > end:
                continue

            count += sum(
                1
                for building_id in available_buildings
                if row.get(building_id) not in (None, "", "nan", "NaN")
            )

    return count


def _parse_csv_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        timestamp = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)


def _cleaned_meter_csv_path(metric_type: str) -> Path:
    metric_name = Path(metric_type).name.strip().lower()
    if not metric_name:
        return METER_DATA_DIR / "__invalid__.csv"

    return METER_DATA_DIR / f"{metric_name}_cleaned.csv"


def _legacy_training_request(
    *,
    building_id: str,
    site_id: str | None,
    metric_type: str,
    model_task: ModelTask,
    data_source: TrainingDataSource,
) -> ModelTrainingRequest:
    end = datetime.now(timezone.utc)
    return ModelTrainingRequest(
        site_id=site_id or building_id,
        building_id=building_id,
        metrics=[metric_type],
        time_range_start=end - timedelta(days=30),
        time_range_end=end,
        model_task=model_task,
        data_source=data_source,
    )


def _algorithm_for_task(model_task: ModelTask) -> MLAlgorithm:
    return {
        ModelTask.Forecasting: MLAlgorithm.RandomForest,
        ModelTask.AnomalyDetection: MLAlgorithm.LightGBM,
        ModelTask.Prediction: MLAlgorithm.RandomForest,
    }[model_task]


@router.post("/rollback", response_model=ModelRollbackResponse)
async def rollback_model(
    payload: ModelRollbackRequest,
    current_user: UserResponse = Depends(get_current_ai_engineer_or_admin),
):
    """
    Promote the registered model version linked to an MLflow run ID.
    """
    client = _mlflow_client()
    model_version = _find_model_version_by_run_id(
        client,
        payload.mlflow_run_id,
        payload.model_name,
    )

    try:
        _promote_model_version(client, model_version)
    except MlflowException as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"MLflow registry update failed: {exc}",
        ) from exc

    run_id = model_version.run_id
    if run_id is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Model version has no associated run ID.",
        )
    return ModelRollbackResponse(
        message="Model version promoted to production.",
        model_name=model_version.name,
        version=str(model_version.version),
        run_id=run_id,
        promoted_by=current_user.email,
    )


@router.post("/demote", response_model=ModelRollbackResponse)
async def demote_model_from_production(
    payload: ModelRollbackRequest,
    current_user: UserResponse = Depends(get_current_ai_engineer_or_admin),
):
    """
    Move a registered model version out of production.
    """
    client = _mlflow_client()
    model_version = _find_model_version_by_run_id(
        client,
        payload.mlflow_run_id,
        payload.model_name,
    )

    try:
        _demote_model_version(client, model_version)
    except MlflowException as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"MLflow registry update failed: {exc}",
        ) from exc

    run_id = model_version.run_id
    if run_id is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Model version has no associated run ID.",
        )
    return ModelRollbackResponse(
        message="Model version moved out of production.",
        model_name=model_version.name,
        version=str(model_version.version),
        run_id=run_id,
        promoted_by=current_user.email,
    )


@router.get("/tasks/{task_id}")
async def get_task_status(
    task_id: str,
    current_user: UserResponse = Depends(get_current_user),
):
    """
    Check the status of a background Celery task (e.g., model training).
    """
    task_result = AsyncResult(task_id, app=celery_app)

    result_data = (
        str(task_result.result)
        if isinstance(task_result.result, Exception)
        else task_result.result
    )

    return {
        "task_id": task_id,
        "status": task_result.status,
        "result": result_data if task_result.ready() else None,
    }


@router.get("/logs/pipeline")
async def get_pipeline_logs(
    limit: int = Query(100, ge=1, le=1000, description="Maximum records to return"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    db: Session = Depends(get_db),
    current_user: UserResponse = Depends(get_current_ai_engineer_or_admin),
):
    """
    Retrieve history of AI training and inference pipeline executions.
    """
    query = db.query(AIPipelineLog).order_by(AIPipelineLog.created_at.desc())
    results = query.offset(offset).limit(limit).all()

    formatted_logs = [
        {
            "id": str(log.id),
            "type": log.type.name if hasattr(log.type, "name") else log.type,
            "model_task": (
                log.model_task.name
                if hasattr(log.model_task, "name")
                else log.model_task
            ),
            "status": log.status.name if hasattr(log.status, "name") else log.status,
            "mlflow_run_id": log.mlflow_run_id,
            "datasource_used": log.datasource_used,
            "execution_time_ms": log.execution_time_ms,
            "timestamp": log.created_at,
        }
        for log in results
    ]

    return {"limit": limit, "offset": offset, "logs": formatted_logs}
