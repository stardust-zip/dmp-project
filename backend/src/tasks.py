from celery import Celery
from src.core.config import settings
from src.database import SessionLocal
from src.ml.core import RandomForestTrainer
from src.ml.data import DataLoader
from src.models import AIPipelineLog

import mlflow

redis_url = settings.REDIS_URL
celery_app = Celery("dmp_tasks", broker=redis_url, backend=redis_url)


@celery_app.task(bind=True, name="train_model_task")
def train_model_task(self, target_building_id: str):
    """
    Orchestrates the ML pipeline: Data Loading -> Training -> DB Logging.
    """
    mlflow.set_tracking_uri(settings.MLFLOW_TRACKING_URI)
    mlflow.set_experiment("dmp_energy_forecasting")

    db = SessionLocal()
    pipeline_log = AIPipelineLog(
        type="Training",
        datasource_used="electricity_cleaned.csv",
        status="Running",
        execution_time_ms=0,
        mlflow_run_id="pending",
    )
    db.add(pipeline_log)
    db.commit()

    try:
        with mlflow.start_run() as run:
            data_path = "/app/data/building-data-genome-project-2/data/meters/cleaned/electricity_cleaned.csv"
            loader = DataLoader(data_path)
            X, y = loader.load_timeseries_target(target_column=target_building_id)

            trainer = RandomForestTrainer(n_estimators=50)

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
