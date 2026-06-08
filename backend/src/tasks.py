from pathlib import Path
from time import perf_counter

from celery import Celery
from src.core.config import settings
from src.database import SessionLocal
from src.models import AIPipelineLog
from src.schemas import (
    MLAlgorithm,
    ModelTask,
    ModelTrainingRequest,
    TrainingDataSource,
)

import mlflow

redis_url = settings.REDIS_URL
celery_app = Celery("dmp_tasks", broker=redis_url, backend=redis_url)
METER_DATA_DIR = Path("/app/data/building-data-genome-project-2/data/meters/cleaned")


def _cleaned_meter_csv_path(metric_type: str) -> Path:
    metric_name = Path(metric_type).name.strip().lower()
    if not metric_name:
        raise ValueError("metric_type is required")

    return METER_DATA_DIR / f"{metric_name}_cleaned.csv"


@celery_app.task(bind=True, name="train_model_task")
def train_model_task(
    self,
    training_request: dict | None = None,
    target_building_id: str | None = None,
    metric_type: str | None = None,
    data_source: str = TrainingDataSource.CSV.value,
    model_task: str = ModelTask.Forecasting.value,
):
    """
    Orchestrates the ML pipeline: Data Loading -> Training -> DB Logging.
    """
    request = _training_request_from_args(
        training_request=training_request,
        target_building_id=target_building_id,
        metric_type=metric_type,
        data_source=data_source,
        model_task=model_task,
    )

    mlflow.set_tracking_uri(settings.MLFLOW_TRACKING_URI)
    selected_algorithm = _algorithm_for_task(ModelTask(request.model_task))
    model_task_value = ModelTask(request.model_task).value
    mlflow.set_experiment(f"dmp_energy_{model_task_value}")

    db = SessionLocal()
    pipeline_log = AIPipelineLog(
        type="Training",
        model_task=model_task_value,
        datasource_used=_datasource_label(request),
        status="Running",
        execution_time_ms=0,
        mlflow_run_id="pending",
    )
    db.add(pipeline_log)
    db.commit()

    try:
        start = perf_counter()
        with mlflow.start_run() as run:
            mlflow.set_tags(
                {
                    "model_task": model_task_value,
                    "site_id": request.site_id,
                    "building_id": request.building_id or "",
                    "metrics": ",".join(request.metrics),
                    "data_source": TrainingDataSource(request.data_source).value,
                    "algorithm": selected_algorithm.value,
                }
            )
            mlflow.log_params(
                {
                    "time_range_start": request.time_range_start.isoformat(),
                    "time_range_end": request.time_range_end.isoformat(),
                }
            )
            metrics = _mock_training_metrics(request)
            mlflow.log_metrics(metrics)

            pipeline_log.mlflow_run_id = run.info.run_id
            pipeline_log.execution_time_ms = int((perf_counter() - start) * 1000)
            pipeline_log.status = "Success"  # type: ignore
            db.commit()

            return {
                "message": f"Mock {model_task_value} training completed.",
                "mlflow_run_id": run.info.run_id,
                "site_id": request.site_id,
                "building_id": request.building_id,
                "metrics": request.metrics,
                "algorithm": selected_algorithm.value,
                "scores": metrics,
            }

    except Exception as e:
        pipeline_log.status = "Failed"  # type: ignore
        db.commit()
        raise self.retry(exc=e, countdown=60, max_retries=3)

    finally:
        db.close()


def _training_request_from_args(
    *,
    training_request: dict | None,
    target_building_id: str | None,
    metric_type: str | None,
    data_source: str,
    model_task: str,
) -> ModelTrainingRequest:
    if training_request is not None:
        return ModelTrainingRequest(**training_request)

    from datetime import datetime, timedelta, timezone

    end = datetime.now(timezone.utc)
    return ModelTrainingRequest(
        site_id=target_building_id or "Panther_parking_Lorriane",
        building_id=target_building_id or "Panther_parking_Lorriane",
        metrics=[metric_type or "electricity"],
        time_range_start=end - timedelta(days=30),
        time_range_end=end,
        model_task=ModelTask(model_task),
        data_source=TrainingDataSource(data_source),
    )


def _datasource_label(request: ModelTrainingRequest) -> str:
    if TrainingDataSource(request.data_source) == TrainingDataSource.CSV:
        if request.csv_path:
            return request.csv_path
        return ",".join(
            _cleaned_meter_csv_path(metric).name for metric in request.metrics
        )
    return "database"


def _mock_training_metrics(request: ModelTrainingRequest) -> dict[str, float]:
    model_task = ModelTask(request.model_task)
    algorithm = _algorithm_for_task(model_task)
    task_scores = {
        ModelTask.Forecasting: {"mae": 4.2, "rmse": 6.8},
        ModelTask.AnomalyDetection: {"precision": 0.91, "recall": 0.87},
        ModelTask.Prediction: {"accuracy": 0.89, "f1": 0.86},
    }
    algorithm_boost = {
        MLAlgorithm.RandomForest: 0.02,
        MLAlgorithm.LinearRegression: -0.01,
        MLAlgorithm.LightGBM: 0.03,
    }[algorithm]

    scores = task_scores[model_task].copy()
    if "mae" in scores:
        return {key: max(value - algorithm_boost, 0.0) for key, value in scores.items()}
    return {key: min(value + algorithm_boost, 0.99) for key, value in scores.items()}


def _algorithm_for_task(model_task: ModelTask) -> MLAlgorithm:
    return {
        ModelTask.Forecasting: MLAlgorithm.RandomForest,
        ModelTask.AnomalyDetection: MLAlgorithm.LightGBM,
        ModelTask.Prediction: MLAlgorithm.LinearRegression,
    }[model_task]
