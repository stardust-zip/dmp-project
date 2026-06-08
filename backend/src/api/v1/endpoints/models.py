from fastapi import APIRouter, Depends, HTTPException, Query, status
from celery.result import AsyncResult
from mlflow.exceptions import MlflowException
from mlflow.tracking import MlflowClient
from src.api.v1.deps import get_current_ai_engineer_or_admin, get_current_user
from src.core.config import settings
from sqlalchemy.orm import Session
from src.database import get_db
from src.models import AIPipelineLog
from src.schemas import (
    ModelTask,
    ModelRollbackRequest,
    ModelRollbackResponse,
    ModelVersionResponse,
    ModelVersionsResponse,
    UserResponse,
)
from src.tasks import celery_app, train_model_task

from mlflow import set_tracking_uri

router = APIRouter()
PRODUCTION_ALIAS = "production"
ACTIVE_TAG = "active"
STAGE_TAG = "stage"
MODEL_TASK_TAG = "model_task"


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
        models_data.append(
            {
                "name": rm.name,
                "description": rm.description,
                "creation_timestamp": rm.creation_timestamp,
                "last_updated_timestamp": rm.last_updated_timestamp,
                "tags": dict(getattr(rm, "tags", {}) or {}),
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


@router.post("/train")
async def trigger_training(
    building_id: str = "Panther_parking_Lorriane",
    metric_type: str = "electricity",
    model_task: ModelTask = Query(
        ModelTask.Forecasting,
        description="ML task to train. Currently only forecasting has an implemented trainer.",
    ),
    data_source: str = Query(
        "csv", description="Choose 'csv' for baseline or 'db' for live data"
    ),
    current_user: UserResponse = Depends(get_current_ai_engineer_or_admin),
):
    """
    Trigger training job for a supported model task via Celery.
    """
    if model_task != ModelTask.Forecasting:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=f"Training for model_task='{model_task.value}' is not implemented.",
        )

    task = train_model_task.delay(
        target_building_id=building_id,
        metric_type=metric_type,
        data_source=data_source,
        model_task=model_task.value,
    )

    return {
        "message": f"{model_task.value} training job queued using {data_source} data.",
        "task_id": task.id,
        "model_task": model_task.value,
        "triggered_by": current_user.email,
    }


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
                log.model_task.name if hasattr(log.model_task, "name") else log.model_task
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
