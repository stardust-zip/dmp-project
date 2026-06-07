from fastapi import APIRouter, Depends, HTTPException, status
from mlflow import set_tracking_uri
from mlflow.exceptions import MlflowException
from mlflow.tracking import MlflowClient
from src.api.v1.deps import get_current_admin, get_current_user
from src.core.config import settings
from src.schemas import (
    ModelRollbackRequest,
    ModelRollbackResponse,
    ModelVersionResponse,
    ModelVersionsResponse,
    UserResponse,
)
from src.tasks import train_model_task

router = APIRouter()
PRODUCTION_ALIAS = "production"
ACTIVE_TAG = "active"
STAGE_TAG = "stage"


def _mlflow_client() -> MlflowClient:
    set_tracking_uri(settings.MLFLOW_TRACKING_URI)
    return MlflowClient()


def _model_version_response(client: MlflowClient, model_version) -> ModelVersionResponse:
    run = client.get_run(model_version.run_id)
    return ModelVersionResponse(
        name=model_version.name,
        version=str(model_version.version),
        run_id=model_version.run_id,
        metrics=dict(run.data.metrics),
        tags=dict(getattr(model_version, "tags", {}) or {}),
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
        client.set_model_version_tag(model_name, str(sibling.version), ACTIVE_TAG, "false")

    client.set_model_version_tag(model_name, version, ACTIVE_TAG, "true")
    client.set_model_version_tag(model_name, version, STAGE_TAG, "production")
    _set_optional_production_alias(client, model_name, version)


@router.get("/")
async def list_models(current_user: UserResponse = Depends(get_current_user)):
    """
    (Placeholder)
    Listing AI models (forecasting, anomaly detection).
    TODO: Implement
    """
    return {"models": ["forecasting_v1", "anomaly_detection_v1"]}


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
    current_admin: UserResponse = Depends(get_current_admin),
):
    """
    Trigger training job for the forecasting model via Celery.
    """
    task = train_model_task.delay(  # type: ignore
        target_building_id=building_id,
        metric_type=metric_type,
    )

    return {
        "message": "Training job queued successfully.",
        "task_id": task.id,
        "triggered_by": current_admin.email,
    }


@router.post("/rollback", response_model=ModelRollbackResponse)
async def rollback_model(
    payload: ModelRollbackRequest,
    current_admin: UserResponse = Depends(get_current_admin),
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

    return ModelRollbackResponse(
        message="Model version promoted to production.",
        model_name=model_version.name,
        version=str(model_version.version),
        run_id=model_version.run_id,
        promoted_by=current_admin.email,
    )
