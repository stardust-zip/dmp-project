from pathlib import Path

from celery import Celery
from src.core.config import settings
from src.database import SessionLocal
from src.ml.data import DataLoader
from src.ml.dummy_randomforest import RandomForestTrainer
from src.models import AIPipelineLog
from src.schemas import ModelTask

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
    target_building_id: str,
    metric_type: str,
    data_source: str,
    model_task: str = ModelTask.Forecasting.value,
):
    """
    Orchestrates the ML pipeline: Data Loading -> Training -> DB Logging.
    """
    parsed_model_task = ModelTask(model_task)
    if parsed_model_task != ModelTask.Forecasting:
        raise NotImplementedError(
            f"Training for model_task='{parsed_model_task.value}' is not implemented."
        )

    mlflow.set_tracking_uri(settings.MLFLOW_TRACKING_URI)
    mlflow.set_experiment("dmp_energy_forecasting")
    data_path = _cleaned_meter_csv_path(metric_type)

    db = SessionLocal()
    pipeline_log = AIPipelineLog(
        type="Training",
        model_task=parsed_model_task.value,
        datasource_used=data_path.name,
        status="Running",
        execution_time_ms=0,
        mlflow_run_id="pending",
    )
    db.add(pipeline_log)
    db.commit()

    try:
        with mlflow.start_run() as run:
            mlflow.set_tags(
                {
                    "model_task": parsed_model_task.value,
                    "metric_type": metric_type,
                    "building_id": target_building_id,
                    "data_source": data_source,
                }
            )
            loader = DataLoader(str(data_path))
            X, y = loader.load_timeseries_target(target_column=target_building_id)

            model_name = f"dmp_{metric_type}_{target_building_id}"

            trainer = RandomForestTrainer(model_name=model_name, n_estimators=50)

            metrics = trainer.train_and_evaluate(X, y)

            pipeline_log.mlflow_run_id = run.info.run_id
            pipeline_log.execution_time_ms = metrics["execution_time_ms"]
            pipeline_log.status = "Success"  # type: ignore
            db.commit()

            return f"Training successful for {target_building_id}. Run ID: {run.info.run_id}"

    except Exception as e:
        pipeline_log.status = "Failed"  # type: ignore
        db.commit()
        raise self.retry(exc=e, countdown=60, max_retries=3)

    finally:
        db.close()
