import os
import shutil
import tempfile
from datetime import datetime, timezone

import mlflow.artifacts
from celery.result import AsyncResult
from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from mlflow.exceptions import MlflowException
from mlflow.tracking import MlflowClient
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from src.api.v1.deps import get_current_ai_engineer_or_admin, get_current_user
from src.core.config import settings
from src.database import get_db
from src.ml.training import (
    algorithm_for_task,
    create_queued_pipeline_log,
    legacy_training_request,
    training_error_detail,
    validate_training_request,
)
from src.models import AIPipelineLog
from src.schemas import (
    ModelRollbackRequest,
    ModelRollbackResponse,
    ModelTask,
    ModelTrainingRequest,
    ModelTrainingResponse,
    ModelTrainingValidationResponse,
    ModelVersionResponse,
    ModelVersionsResponse,
    TrainingDataSource,
    UserResponse,
)
from src.tasks import (
    celery_app,
    mark_pipeline_log_external_failure,
    run_anomaly_backfill_task,
    train_model_task,
)
from starlette.background import BackgroundTask

from mlflow import set_tracking_uri

router = APIRouter()
PRODUCTION_ALIAS = "production"
ACTIVE_TAG = "active"
STAGE_TAG = "stage"
MODEL_TASK_TAG = "model_task"


class ModelDescriptionUpdate(BaseModel):
    description: str = Field(default="", max_length=2000)


def _mlflow_client() -> MlflowClient:
    set_tracking_uri(settings.MLFLOW_TRACKING_URI)
    return MlflowClient()


def _pipeline_log_status_value(log: AIPipelineLog) -> str:
    return log.status.name if hasattr(log.status, "name") else str(log.status)


def _sync_running_pipeline_log_with_celery(log: AIPipelineLog) -> bool:
    if _pipeline_log_status_value(log) not in {"Running", "running"}:
        return False
    if not log.celery_task_id:
        return False

    task_result = AsyncResult(log.celery_task_id, app=celery_app)
    task_status = str(task_result.status).upper()
    if task_status not in {"FAILURE", "REVOKED"}:
        return False

    result = task_result.result
    exception = (
        result
        if isinstance(result, BaseException)
        else RuntimeError(str(result) if result is not None else task_status)
    )
    return mark_pipeline_log_external_failure(
        log.celery_task_id,
        exception,
        task_state=task_status,
    )


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


@router.patch("/{model_name}/description")
async def update_model_description(
    model_name: str,
    payload: ModelDescriptionUpdate,
    current_user: UserResponse = Depends(get_current_ai_engineer_or_admin),
):
    """
    Update a registered model description in MLflow.
    """
    client = _mlflow_client()
    description = payload.description.strip()
    try:
        updated = client.update_registered_model(
            name=model_name,
            description=description,
        )
    except MlflowException as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"MLflow registry update failed: {exc}",
        ) from exc

    return {
        "name": getattr(updated, "name", model_name),
        "description": getattr(updated, "description", description),
        "updated_by": current_user.email,
    }


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


@router.get("/{model_name}/versions/{version}/download")
async def download_model(
    model_name: str,
    version: str,
    current_user: UserResponse = Depends(get_current_ai_engineer_or_admin),
):
    """
    Download a registered model version as a zip file containing all MLflow artifacts.

    The zip preserves the MLflow artifact directory structure (model files, conda
    environment, MLmodel metadata, and any custom artifacts like resid_stats.parquet).
    """
    client = _mlflow_client()

    try:
        model_version = client.get_model_version(model_name, version)
    except MlflowException as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model version not found: {exc}",
        ) from exc

    run_id = model_version.run_id
    if not run_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Model version has no associated run ID.",
        )

    artifacts_dir = tempfile.mkdtemp()
    try:
        # 1. Download run-specific artifacts (resid_stats.parquet, etc.)
        client.download_artifacts(run_id, "", artifacts_dir)

        # 2. Download the registered model files (model.pkl, MLmodel, conda.yaml, etc.)
        model_uri = f"models:/{model_name}/{version}"
        mlflow.artifacts.download_artifacts(
            artifact_uri=model_uri, dst_path=artifacts_dir
        )

        # 3. Zip everything — create the zip in a SEPARATE temp dir
        #    so there is zero risk of the zip self-archiving.
        zip_tmp = tempfile.mkdtemp()
        zip_path = os.path.join(zip_tmp, "model.zip")
        shutil.make_archive(
            base_name=zip_path.replace(".zip", ""),
            format="zip",
            root_dir=artifacts_dir,
        )

        def _cleanup():
            shutil.rmtree(artifacts_dir, ignore_errors=True)
            shutil.rmtree(zip_tmp, ignore_errors=True)

        return FileResponse(
            zip_path,
            media_type="application/zip",
            filename=f"{model_name}_v{version}.zip",
            background=BackgroundTask(_cleanup),
        )
    except Exception:
        shutil.rmtree(artifacts_dir, ignore_errors=True)
        raise


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
    request = payload or legacy_training_request(
        building_id=building_id,
        site_id=site_id,
        metric_type=metric_type,
        model_task=model_task,
        data_source=data_source,
    )
    validation = validate_training_request(request, db, enforce_data_availability=False)
    if not validation.valid:
        raise HTTPException(
            status_code=422,
            detail=training_error_detail(validation),
        )

    selected_algorithm = request.algorithm or algorithm_for_task(ModelTask(request.model_task))
    if (
        ModelTask(request.model_task) == ModelTask.Prediction
        and len(request.metrics) != 1
    ):
        raise HTTPException(
            status_code=422,
            detail="Prediction training requires exactly one metric per model.",
        )

    pipeline_log = create_queued_pipeline_log(db, request)
    task = train_model_task.delay(
        training_request=request.model_dump(mode="json", exclude_none=True),
        pipeline_log_id=str(pipeline_log.id),
    )
    pipeline_log.celery_task_id = task.id  # type: ignore
    db.commit()

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
    return validate_training_request(payload, db)


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


class AnomalyBackfillRequest(BaseModel):
    time_range_start: datetime
    time_range_end: datetime


@router.post("/anomaly/backfill")
async def trigger_anomaly_backfill(
    payload: AnomalyBackfillRequest,
    db: Session = Depends(get_db),
    current_user: UserResponse = Depends(get_current_ai_engineer_or_admin),
):
    """
    Queue a backfill inference job that scores rule-based and LGBm anomalies
    for every hour in the requested historical date range.
    """
    start = (
        payload.time_range_start.replace(tzinfo=timezone.utc)
        if payload.time_range_start.tzinfo is None
        else payload.time_range_start.astimezone(timezone.utc)
    )
    end = (
        payload.time_range_end.replace(tzinfo=timezone.utc)
        if payload.time_range_end.tzinfo is None
        else payload.time_range_end.astimezone(timezone.utc)
    )

    if end <= start:
        raise HTTPException(
            status_code=422, detail="time_range_end must be after time_range_start."
        )

    total_hours = int((end - start).total_seconds() // 3600) + 1
    if total_hours > 8760:
        raise HTTPException(
            status_code=422,
            detail="Backfill range cannot exceed 365 days (8 760 hours).",
        )

    pipeline_log = AIPipelineLog(
        type="Inference",
        model_task="anomaly_detection",
        datasource_used="csv",
        status="Running",
        execution_time_ms=0,
        mlflow_run_id="backfill",
        terminal_log="",
    )
    db.add(pipeline_log)
    db.commit()

    task = run_anomaly_backfill_task.delay(
        start_iso=start.isoformat(),
        end_iso=end.isoformat(),
        pipeline_log_id=str(pipeline_log.id),
    )
    pipeline_log.celery_task_id = task.id  # type: ignore
    db.commit()

    return {
        "message": f"Anomaly backfill queued for {total_hours} hours.",
        "task_id": task.id,
        "pipeline_log_id": str(pipeline_log.id),
        "time_range_start": start.isoformat(),
        "time_range_end": end.isoformat(),
        "triggered_by": current_user.email,
    }


@router.post("/logs/{log_id}/cancel")
async def cancel_pipeline_log(
    log_id: str,
    db: Session = Depends(get_db),
    current_user: UserResponse = Depends(get_current_ai_engineer_or_admin),
):
    """
    Cancel a running or queued training pipeline by revoking the Celery task.
    """
    from datetime import datetime, timezone
    from uuid import UUID

    try:
        log = db.get(AIPipelineLog, UUID(log_id))
    except ValueError:
        log = None

    if log is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Pipeline log not found."
        )

    log_status = log.status.name if hasattr(log.status, "name") else log.status
    if log_status not in ("Running", "running"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot cancel a pipeline with status '{log_status}'.",
        )

    if log.celery_task_id:
        celery_app.control.revoke(log.celery_task_id, terminate=True, signal="SIGTERM")

    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    line = f"[{ts}] Pipeline cancelled by {current_user.email}."
    log.terminal_log = f"{log.terminal_log}\n{line}" if log.terminal_log else line  # type: ignore
    log.status = "Cancelled"  # type: ignore
    db.commit()

    return {"id": log_id, "status": "Cancelled", "cancelled_by": current_user.email}


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
    if any(_sync_running_pipeline_log_with_celery(log) for log in results):
        db.expire_all()
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
            "celery_task_id": log.celery_task_id,
            "datasource_used": log.datasource_used,
            "execution_time_ms": log.execution_time_ms,
            "timestamp": log.created_at,
            "terminal_log": log.terminal_log,
        }
        for log in results
    ]

    return {"limit": limit, "offset": offset, "logs": formatted_logs}
