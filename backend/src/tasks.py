import gc
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter
from uuid import UUID

import mlflow.pyfunc
import numpy as np
import pandas as pd
from celery import Celery
from celery.signals import task_failure, task_revoked
from mlflow.tracking import MlflowClient
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, root_mean_squared_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from src.core.config import settings
from src.database import SessionLocal
from src.ml.training import algorithm_for_task, cleaned_meter_csv_path
from src.models import AIPipelineLog, Device, Location, TelemetryData
from src.schemas import (
    MLAlgorithm,
    ModelTask,
    ModelTrainingRequest,
    TrainingDataSource,
)

import mlflow

redis_url = settings.REDIS_URL
celery_app = Celery("dmp_tasks", broker=redis_url, backend=redis_url)
RAW_DATA_DIR = Path("/app/data/raw/data")
METADATA_CSV_PATH = RAW_DATA_DIR / "metadata" / "metadata.csv"
PREDICTION_FEATURE_COLUMNS = [
    "sqm",
    "hour",
    "day_of_week",
    "month",
    "closing_hour",
    "is_open",
    "primaryspaceusage",
    "metric_type",
]


class MockEnergyModel(mlflow.pyfunc.PythonModel):
    def __init__(self, default_score: float):
        self.default_score = default_score

    def predict(self, context: object, model_input: pd.DataFrame) -> list[float]:
        try:
            row_count = len(model_input)
        except TypeError:
            row_count = 1
        return [self.default_score] * row_count


def _terminal_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _append_terminal_log(db, pipeline_log: AIPipelineLog, message: str) -> None:
    line = f"[{_terminal_timestamp()}] {message}"
    pipeline_log.terminal_log = (
        f"{pipeline_log.terminal_log}\n{line}" if pipeline_log.terminal_log else line
    )
    db.commit()


def _pipeline_log_status_value(pipeline_log: AIPipelineLog) -> str:
    status = pipeline_log.status
    return status.name if hasattr(status, "name") else str(status)


def _external_task_failure_message(exception: object, task_state: str = "FAILURE") -> str:
    exception_name = type(exception).__name__
    exception_text = str(exception) or task_state
    message = (
        "Pipeline failed outside the task handler: "
        f"{exception_name}: {exception_text}"
    )
    if "SIGKILL" in exception_text or "signal 9" in exception_text:
        message += (
            " The worker process was killed by the OS or Docker, commonly due "
            "to memory pressure."
        )
    return message


def mark_pipeline_log_external_failure(
    celery_task_id: str | None,
    exception: object,
    *,
    task_state: str = "FAILURE",
) -> bool:
    if not celery_task_id:
        return False

    db = SessionLocal()
    try:
        pipeline_log = (
            db.query(AIPipelineLog)
            .filter(AIPipelineLog.celery_task_id == celery_task_id)
            .one_or_none()
        )
        if pipeline_log is None:
            return False

        if _pipeline_log_status_value(pipeline_log) in {"Success", "Failed", "Cancelled"}:
            return False

        message = _external_task_failure_message(exception, task_state)
        if pipeline_log.terminal_log and message in pipeline_log.terminal_log:
            return False

        pipeline_log.status = "Failed"  # type: ignore
        if pipeline_log.created_at:
            created_at = pipeline_log.created_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            pipeline_log.execution_time_ms = int(
                (datetime.now(timezone.utc) - created_at).total_seconds() * 1000
            )
        _append_terminal_log(db, pipeline_log, message)
        return True
    finally:
        db.close()


_MONITORED_TASK_NAMES = {"train_model_task", "run_anomaly_backfill_task"}


@task_failure.connect
def _mark_training_pipeline_failed_on_worker_failure(
    sender=None,
    task_id: str | None = None,
    exception: object | None = None,
    **_: object,
) -> None:
    task_name = getattr(sender, "name", sender)
    if task_name not in _MONITORED_TASK_NAMES:
        return
    mark_pipeline_log_external_failure(task_id, exception or "Task failed")


@task_revoked.connect
def _mark_training_pipeline_failed_on_revoke(
    sender=None,
    request=None,
    terminated: bool = False,
    signum: object | None = None,
    expired: bool = False,
    **_: object,
) -> None:
    task_name = getattr(sender, "name", sender)
    if task_name not in _MONITORED_TASK_NAMES or request is None:
        return
    reason = "revoked"
    if terminated:
        reason = f"terminated by signal {signum}"
    elif expired:
        reason = "expired before execution"
    mark_pipeline_log_external_failure(
        getattr(request, "id", None),
        RuntimeError(f"Celery task was {reason}."),
        task_state="REVOKED",
    )


@celery_app.task(bind=True, name="train_model_task")
def train_model_task(
    self,
    training_request: dict | None = None,
    target_building_id: str | None = None,
    metric_type: str | None = None,
    data_source: str = TrainingDataSource.CSV.value,
    model_task: str = ModelTask.Prediction.value,
    pipeline_log_id: str | None = None,
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
    selected_algorithm = algorithm_for_task(ModelTask(request.model_task))
    if getattr(request, "algorithm", None):
        selected_algorithm = MLAlgorithm(request.algorithm)
    model_task_value = ModelTask(request.model_task).value
    mlflow.set_experiment(f"dmp_energy_{model_task_value}")

    db = SessionLocal()
    pipeline_log = None
    if pipeline_log_id:
        try:
            pipeline_log = db.get(AIPipelineLog, UUID(pipeline_log_id))
        except ValueError:
            pipeline_log = None

    if pipeline_log is None:
        pipeline_log = AIPipelineLog(
            type="Training",
            model_task=model_task_value,
            datasource_used=_datasource_label(request),
            status="Running",
            execution_time_ms=0,
            mlflow_run_id="pending",
            terminal_log="",
        )
        db.add(pipeline_log)
        db.commit()
        _append_terminal_log(
            db,
            pipeline_log,
            (
                "Queued training pipeline "
                f"task={model_task_value} site={request.site_id} "
                f"building={request.building_id or '-'} metrics={','.join(request.metrics)} "
                f"source={TrainingDataSource(request.data_source).value}"
            ),
        )
    else:
        log_status = pipeline_log.status.name if hasattr(pipeline_log.status, "name") else pipeline_log.status
        if log_status == "Cancelled":
            db.close()
            return {"message": "Pipeline was cancelled; retry skipped."}

        pipeline_log.status = "Running"  # type: ignore
        _append_terminal_log(
            db, pipeline_log, "Worker picked up queued training pipeline."
        )

    try:
        start = perf_counter()

        with mlflow.start_run() as run:
            pipeline_log.mlflow_run_id = run.info.run_id  # type: ignore
            db.commit()
            _append_terminal_log(
                db,
                pipeline_log,
                f"Started MLflow run {run.info.run_id}.",
            )
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
            registered_model_name = _registered_model_name(request)
            _append_terminal_log(
                db,
                pipeline_log,
                f"Loading training data for registered model {registered_model_name}.",
            )
            if ModelTask(request.model_task) == ModelTask.Prediction:
                metrics = _train_prediction_model(
                    request=request,
                    db=db,
                    model_name=registered_model_name,
                )
                message_prefix = "Prediction"
            elif ModelTask(request.model_task) == ModelTask.AnomalyDetection:
                from src.ml.anomaly.detection import train_anomaly_detection_model

                anomaly_result = train_anomaly_detection_model(
                    request=request,
                    db=db,
                    mlflow_run=run,
                    pipeline_log=pipeline_log,
                    append_log=lambda msg: _append_terminal_log(db, pipeline_log, msg),
                )
                metrics = {
                    key: float(value)
                    for key, value in anomaly_result.items()
                    if isinstance(value, (int, float)) and not isinstance(value, bool)
                }
                message_prefix = "Anomaly detection"
            elif ModelTask(request.model_task) == ModelTask.Forecasting:
                from src.ml.forecasting.training import train_forecasting_model

                forecast_result = train_forecasting_model(
                    request=request,
                    db=db,
                    mlflow_run=run,
                    pipeline_log=pipeline_log,
                    append_log=lambda msg: _append_terminal_log(db, pipeline_log, msg),
                )
                metrics = {
                    key: float(value)
                    for key, value in forecast_result.items()
                    if isinstance(value, (int, float)) and not isinstance(value, bool)
                }
                message_prefix = "Forecasting"
            else:
                _append_terminal_log(
                    db,
                    pipeline_log,
                    f"Stopped: {model_task_value} training pipeline is not implemented yet.",
                )
                response = _not_implemented_training_response(
                    request, selected_algorithm
                )
                pipeline_log.status = "Failed"  # type: ignore
                pipeline_log.mlflow_run_id = "not_implemented"
                pipeline_log.execution_time_ms = int((perf_counter() - start) * 1000)
                db.commit()
                return response

            _append_terminal_log(
                db,
                pipeline_log,
                "Training completed. Logging metrics to MLflow: "
                + ", ".join(f"{key}={value:.4f}" for key, value in metrics.items()),
            )
            mlflow.log_metrics(metrics)
            _tag_registered_model_versions(
                request=request,
                model_name=registered_model_name,
                run_id=run.info.run_id,
            )
            _append_terminal_log(
                db,
                pipeline_log,
                f"Tagged registered model versions for run {run.info.run_id}.",
            )

            pipeline_log.mlflow_run_id = run.info.run_id
            pipeline_log.execution_time_ms = int((perf_counter() - start) * 1000)
            pipeline_log.status = "Success"  # type: ignore
            _append_terminal_log(
                db,
                pipeline_log,
                f"Pipeline finished successfully in {pipeline_log.execution_time_ms} ms.",
            )
            db.commit()

            return {
                "message": f"{message_prefix} training completed.",
                "mlflow_run_id": run.info.run_id,
                "site_id": request.site_id,
                "building_id": request.building_id,
                "metrics": request.metrics,
                "algorithm": selected_algorithm.value,
                # "model_name": registered_model_name,
                "scores": metrics,
            }

    except Exception as e:
        db.rollback()
        pipeline_log.status = "Failed"  # type: ignore
        pipeline_log.execution_time_ms = int((perf_counter() - start) * 1000)
        _append_terminal_log(
            db,
            pipeline_log,
            f"Pipeline failed: {type(e).__name__}: {e}",
        )
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
        return ModelTrainingRequest(**_training_request_payload(training_request))

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


def _training_request_payload(training_request: dict) -> dict:
    allowed_fields = set(ModelTrainingRequest.model_fields)
    return {
        key: value
        for key, value in training_request.items()
        if key in allowed_fields and value is not None
    }


def _datasource_label(request: ModelTrainingRequest) -> str:
    if TrainingDataSource(request.data_source) == TrainingDataSource.CSV:
        if request.csv_path:
            return request.csv_path
        return ",".join(
            cleaned_meter_csv_path(metric).name for metric in request.metrics
        )
    return "database"


def _registered_model_name(request: ModelTrainingRequest) -> str:
    task = ModelTask(request.model_task).value
    metric_segment = "_".join(request.metrics)
    return _safe_model_name(f"dmp_energy_{task}_{request.site_id}_{metric_segment}")


def _safe_model_name(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return normalized.strip("._-") or "dmp_energy_model"


def _log_mock_registered_model(
    *,
    request: ModelTrainingRequest,
    model_name: str,
    run_id: str,
    default_score: float,
) -> None:
    mlflow.pyfunc.log_model(
        artifact_path="model",
        python_model=MockEnergyModel(default_score=default_score),
        registered_model_name=model_name,
    )


def _tag_registered_model_versions(
    *,
    request: ModelTrainingRequest,
    model_name: str,
    run_id: str,
) -> None:
    client = MlflowClient()
    versions = client.search_model_versions(
        f"name = '{model_name}' and run_id = '{run_id}'"
    )
    for version in versions:
        version_number = str(version.version)
        client.set_model_version_tag(
            model_name,
            version_number,
            "model_task",
            ModelTask(request.model_task).value,
        )
        client.set_model_version_tag(
            model_name, version_number, "site_id", request.site_id
        )
        client.set_model_version_tag(
            model_name, version_number, "metrics", ",".join(request.metrics)
        )
        client.set_model_version_tag(
            model_name,
            version_number,
            "data_source",
            TrainingDataSource(request.data_source).value,
        )


def _train_prediction_model(
    *,
    request: ModelTrainingRequest,
    db,
    model_name: str,
) -> dict[str, float]:
    if len(request.metrics) != 1:
        raise ValueError("Prediction training requires exactly one metric per model")

    training_df = _load_prediction_training_frame(request, db)
    if len(training_df) < 24:
        raise ValueError("Prediction training requires at least 24 usable rows")

    training_df = training_df.sort_values("timestamp").reset_index(drop=True)
    X = training_df[PREDICTION_FEATURE_COLUMNS]
    y = training_df["meter_reading"]

    split_index = max(1, int(len(training_df) * 0.8))
    if split_index >= len(training_df):
        split_index = len(training_df) - 1

    X_train, X_test = X.iloc[:split_index], X.iloc[split_index:]
    y_train, y_test = y.iloc[:split_index], y.iloc[split_index:]

    model = _prediction_pipeline()
    model.fit(X_train, y_train)
    predictions = model.predict(X_test)

    metrics = {
        "mae": float(mean_absolute_error(y_test, predictions)),
        "rmse": float(root_mean_squared_error(y_test, predictions)),
        "training_rows": float(len(training_df)),
    }

    mlflow.sklearn.log_model(
        model,
        artifact_path="model",
        registered_model_name=model_name,
    )
    mlflow.log_param("n_estimators", 50)
    return metrics


def _prediction_pipeline() -> Pipeline:
    preprocessor = ColumnTransformer(
        transformers=[
            (
                "categorical",
                OneHotEncoder(handle_unknown="ignore"),
                ["primaryspaceusage", "metric_type"],
            ),
            (
                "numeric",
                "passthrough",
                ["sqm", "hour", "day_of_week", "month", "closing_hour", "is_open"],
            ),
        ]
    )
    return Pipeline(
        steps=[
            ("preprocessor", preprocessor),
            (
                "model",
                RandomForestRegressor(n_estimators=50, random_state=42),
            ),
        ]
    )


def _load_prediction_training_frame(request: ModelTrainingRequest, db) -> pd.DataFrame:
    source = TrainingDataSource(request.data_source)
    if source == TrainingDataSource.DB:
        return _load_prediction_training_frame_from_db(request, db)
    return _load_prediction_training_frame_from_csv(request)


def _load_prediction_training_frame_from_csv(
    request: ModelTrainingRequest,
) -> pd.DataFrame:
    metadata_df = _load_prediction_metadata()
    building_ids = _prediction_building_ids(request, metadata_df)
    if not building_ids:
        raise ValueError("No buildings matched the prediction training request")

    frames = []
    for metric in request.metrics:
        csv_path = (
            Path(request.csv_path)
            if request.csv_path
            else cleaned_meter_csv_path(metric)
        )
        if not csv_path.exists():
            raise FileNotFoundError(f"Meter data file not found: {csv_path}")

        meter_df = pd.read_csv(
            csv_path,
            usecols=lambda column: column == "timestamp" or column in building_ids,
        )
        if "timestamp" not in meter_df.columns:
            raise ValueError(f"Meter data file is missing timestamp column: {csv_path}")

        available_buildings = [
            building_id
            for building_id in building_ids
            if building_id in meter_df.columns
        ]
        if not available_buildings:
            continue

        meter_df["timestamp"] = pd.to_datetime(
            meter_df["timestamp"], errors="coerce", utc=True
        )
        meter_df = _filter_time_range(meter_df, request)
        if meter_df.empty:
            continue

        melted_df = meter_df.melt(
            id_vars=["timestamp"],
            value_vars=available_buildings,
            var_name="building_id",
            value_name="meter_reading",
        )
        melted_df["metric_type"] = metric
        frames.append(melted_df)

    if not frames:
        raise ValueError("No prediction training rows found in CSV data")

    return _finalize_prediction_training_frame(pd.concat(frames), metadata_df)


def _load_prediction_training_frame_from_db(
    request: ModelTrainingRequest,
    db,
) -> pd.DataFrame:
    metadata_df = _load_prediction_metadata(required=False)
    building_ids = _prediction_building_ids(request, metadata_df)
    if not building_ids:
        building_ids = [request.building_id or request.site_id]

    start = _to_utc(request.time_range_start)
    end = _to_utc(request.time_range_end)
    rows = (
        db.query(
            TelemetryData.timestamp,
            Device.location_id.label("building_id"),
            TelemetryData.metric_type_id.label("metric_type"),
            TelemetryData.value.label("meter_reading"),
            Location.location_type_id.label("primaryspaceusage"),
            Location.metadata_.label("metadata"),
        )
        .join(Device, Device.id == TelemetryData.device_id)
        .join(Location, Location.id == Device.location_id)
        .filter(Device.location_id.in_(building_ids))
        .filter(TelemetryData.metric_type_id.in_(request.metrics))
        .filter(TelemetryData.timestamp >= start)
        .filter(TelemetryData.timestamp <= end)
        .all()
    )
    if not rows:
        raise ValueError("No prediction training rows found in database")

    df = pd.DataFrame(
        [
            {
                "timestamp": row.timestamp,
                "building_id": row.building_id,
                "metric_type": row.metric_type,
                "meter_reading": row.meter_reading,
                "primaryspaceusage": row.primaryspaceusage,
                "sqm": (row.metadata or {}).get("sqm"),
            }
            for row in rows
        ]
    )
    return _finalize_prediction_training_frame(df, metadata_df)


def _load_prediction_metadata(*, required: bool = True) -> pd.DataFrame:
    if not METADATA_CSV_PATH.exists():
        if required:
            raise FileNotFoundError(f"Metadata file not found: {METADATA_CSV_PATH}")
        return pd.DataFrame(
            columns=["building_id", "site_id", "primaryspaceusage", "sqm"]
        )

    metadata_df = pd.read_csv(METADATA_CSV_PATH)
    required_columns = {"building_id", "primaryspaceusage", "sqm"}
    missing_columns = required_columns.difference(metadata_df.columns)
    if missing_columns:
        raise ValueError(
            "Metadata file is missing required column(s): "
            + ", ".join(sorted(missing_columns))
        )

    metadata_df = metadata_df.copy()
    metadata_df["building_id"] = metadata_df["building_id"].astype(str)
    if "site_id" in metadata_df.columns:
        metadata_df["site_id"] = metadata_df["site_id"].astype(str)
    return metadata_df


def _prediction_building_ids(
    request: ModelTrainingRequest,
    metadata_df: pd.DataFrame,
) -> list[str]:
    if request.building_id:
        return [request.building_id]

    if metadata_df.empty:
        return [request.site_id]

    if "site_id" in metadata_df.columns:
        site_buildings = metadata_df.loc[
            metadata_df["site_id"].astype(str) == request.site_id, "building_id"
        ]
        if not site_buildings.empty:
            return site_buildings.astype(str).tolist()

    if request.site_id in set(metadata_df["building_id"].astype(str)):
        return [request.site_id]

    return []


def _filter_time_range(
    df: pd.DataFrame,
    request: ModelTrainingRequest,
) -> pd.DataFrame:
    start = _to_utc(request.time_range_start)
    end = _to_utc(request.time_range_end)
    return df[(df["timestamp"] >= start) & (df["timestamp"] <= end)].copy()


def _finalize_prediction_training_frame(
    readings_df: pd.DataFrame,
    metadata_df: pd.DataFrame,
) -> pd.DataFrame:
    df = readings_df.copy()
    if not metadata_df.empty and (
        "primaryspaceusage" not in df.columns or "sqm" not in df.columns
    ):
        metadata_columns = ["building_id", "primaryspaceusage", "sqm"]
        df = pd.merge(df, metadata_df[metadata_columns], on="building_id", how="left")

    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    df["meter_reading"] = pd.to_numeric(df["meter_reading"], errors="coerce")
    df["sqm"] = pd.to_numeric(df["sqm"], errors="coerce")
    df["primaryspaceusage"] = df["primaryspaceusage"].fillna("Unknown").astype(str)
    df["metric_type"] = df["metric_type"].fillna("unknown").astype(str)

    df = df.replace([np.inf, -np.inf], np.nan)
    df = df.dropna(subset=["timestamp", "meter_reading", "sqm"])
    df["hour"] = df["timestamp"].dt.hour
    df["day_of_week"] = df["timestamp"].dt.dayofweek
    df["month"] = df["timestamp"].dt.month
    if "closing_hour" not in df.columns:
        df["closing_hour"] = 18
    df["closing_hour"] = pd.to_numeric(df["closing_hour"], errors="coerce").fillna(18)
    df["is_open"] = (df["hour"] < df["closing_hour"]).astype(int)
    return df.sort_values("timestamp").reset_index(drop=True)


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _not_implemented_training_response(
    request: ModelTrainingRequest,
    selected_algorithm: MLAlgorithm,
) -> dict[str, object]:
    model_task = ModelTask(request.model_task).value
    return {
        "message": f"{model_task} training pipeline is not implemented yet.",
        "implemented": False,
        "mlflow_run_id": None,
        "site_id": request.site_id,
        "building_id": request.building_id,
        "metrics": request.metrics,
        "algorithm": selected_algorithm.value,
        "scores": {},
    }


def _mock_training_metrics(request: ModelTrainingRequest) -> dict[str, float]:
    model_task = ModelTask(request.model_task)
    algorithm = algorithm_for_task(model_task)
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


def _utc_timestamp(value: datetime) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    return timestamp.tz_localize("UTC") if timestamp.tzinfo is None else timestamp.tz_convert("UTC")


def _load_anomaly_backfill_telemetry_from_csv(
    db,
    *,
    metrics: list[str],
    start: datetime,
    end: datetime,
) -> pd.DataFrame:
    """Load cleaned meter CSV rows with 168h lookback and DB location metadata."""
    from src.ml.anomaly.types import LOOKBACK_HOURS

    empty = pd.DataFrame(
        columns=[
            "timestamp",
            "consumption",
            "metric_type_id",
            "building_id",
            "site_id",
            "sqm",
            "primaryspaceusage",
            "timezone",
        ]
    )
    lookback_start = _utc_timestamp(start - timedelta(hours=LOOKBACK_HOURS))
    range_end = _utc_timestamp(end)

    frames = []
    missing_paths = []
    for metric in metrics:
        csv_path = cleaned_meter_csv_path(metric)
        if not csv_path.exists():
            missing_paths.append(str(csv_path))
            continue

        raw = pd.read_csv(csv_path)
        if "timestamp" not in raw.columns:
            raise ValueError(f"Meter data file is missing timestamp column: {csv_path}")

        raw["timestamp"] = pd.to_datetime(raw["timestamp"], utc=True, errors="coerce")
        raw = raw[
            (raw["timestamp"] >= lookback_start)
            & (raw["timestamp"] <= range_end)
        ]
        if raw.empty:
            continue

        building_cols = [column for column in raw.columns if column != "timestamp"]
        melted = raw.melt(
            id_vars=["timestamp"],
            value_vars=building_cols,
            var_name="building_id",
            value_name="consumption",
        )
        melted["building_id"] = melted["building_id"].astype(str)
        melted["consumption"] = pd.to_numeric(melted["consumption"], errors="coerce")
        melted["metric_type_id"] = metric
        frames.append(melted)

    if not frames:
        if missing_paths:
            raise FileNotFoundError(
                "No cleaned meter CSV files found for backfill metrics: "
                + ", ".join(missing_paths)
            )
        return empty

    df = pd.concat(frames, ignore_index=True)
    df.sort_values(["timestamp", "building_id"], inplace=True)
    df.reset_index(drop=True, inplace=True)

    loc_rows = (
        db.query(Location.id, Location.parent_id, Location.metadata_)
        .filter(Location.id.in_(df["building_id"].unique().tolist()))
        .all()
    )
    loc_meta = {
        str(loc_id): {
            "site_id": parent_id,
            "sqm": (meta or {}).get("sqm"),
            "primaryspaceusage": (meta or {}).get("primaryspaceusage"),
            "timezone": (meta or {}).get("timezone"),
        }
        for loc_id, parent_id, meta in loc_rows
    }

    df["site_id"] = df["building_id"].map(lambda b: loc_meta.get(b, {}).get("site_id"))
    df["sqm"] = df["building_id"].map(lambda b: loc_meta.get(b, {}).get("sqm"))
    df["primaryspaceusage"] = df["building_id"].map(
        lambda b: loc_meta.get(b, {}).get("primaryspaceusage")
    )
    df["timezone"] = df["building_id"].map(lambda b: loc_meta.get(b, {}).get("timezone"))
    return df


@celery_app.task(bind=True, name="run_anomaly_inference_task")
def run_anomaly_inference_task(self):
    from datetime import datetime, timezone

    from src.ml.anomaly.inference import run_hourly_inference

    db = SessionLocal()
    try:
        target_hour = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        count = run_hourly_inference(db, target_hour)
        return {"rows_written": count, "target_hour": target_hour.isoformat()}
    finally:
        db.close()


@celery_app.task(bind=True, name="run_anomaly_backfill_task")
def run_anomaly_backfill_task(
    self,
    start_iso: str,
    end_iso: str,
    pipeline_log_id: str | None = None,
):
    """
    Backfill rule-based and LGBm anomaly inference for a historical date range.
    Rule-based checks run once over the full range; LGBm inference runs hour by hour.
    """
    from datetime import datetime, timezone

    import pandas as pd
    from src.ml.anomaly.inference import (
        load_production_anomaly_model,
        run_rule_based_checks,
    )
    from src.ml.anomaly.feature_engineering import build_feature_matrix
    from src.ml.anomaly.scoring import classify_severity, score_anomalies
    from src.ml.anomaly.store import AnomalyEventStore
    from src.ml.anomaly.telemetry_loaders import downcast_telemetry_dtypes
    from src.ml.anomaly.types import DEFAULT_METRIC_TYPE, LOOKBACK_HOURS
    from src.ml.anomaly.weather_loaders import load_weather_for_range
    from src.models import Location

    start = datetime.fromisoformat(start_iso).replace(tzinfo=timezone.utc)
    end = datetime.fromisoformat(end_iso).replace(tzinfo=timezone.utc)

    db = SessionLocal()
    pipeline_log = None

    if pipeline_log_id:
        try:
            pipeline_log = db.get(AIPipelineLog, UUID(pipeline_log_id))
        except ValueError:
            pipeline_log = None

    if pipeline_log is None:
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
    else:
        pipeline_log.status = "Running"  # type: ignore
        db.commit()

    start_perf = perf_counter()

    try:
        _append_terminal_log(
            db, pipeline_log,
            f"Backfill started: {start_iso} → {end_iso}",
        )

        mlflow.set_tracking_uri(settings.MLFLOW_TRACKING_URI)
        model_result = load_production_anomaly_model()
        if model_result is None:
            raise ValueError("No production anomaly model found for backfill inference.")

        model, resid_stats, feature_cols, _cat_features, use_weather, metrics = model_result
        _append_terminal_log(
            db,
            pipeline_log,
            "Loading telemetry from cleaned CSV for metrics: " + ", ".join(metrics),
        )

        telemetry_df = _load_anomaly_backfill_telemetry_from_csv(
            db,
            metrics=metrics,
            start=start,
            end=end,
        )
        if telemetry_df.empty:
            raise ValueError("No cleaned CSV telemetry found for the requested backfill range.")

        target_start = _utc_timestamp(start)
        target_end = _utc_timestamp(end)
        range_df = telemetry_df[
            (telemetry_df["timestamp"] >= target_start)
            & (telemetry_df["timestamp"] <= target_end)
        ].copy()
        if range_df.empty:
            raise ValueError("No cleaned CSV telemetry found inside the requested backfill range.")

        _append_terminal_log(
            db,
            pipeline_log,
            (
                f"Loaded CSV telemetry: {len(range_df):,} target rows, "
                f"{range_df['building_id'].nunique()} buildings "
                f"({len(telemetry_df):,} rows including lag warmup)."
            ),
        )

        # --- Rule-based checks over full CSV-backed range ---
        _append_terminal_log(
            db, pipeline_log,
            f"Running rule-based checks: {len(range_df):,} rows, {range_df['building_id'].nunique()} buildings.",
        )
        rule_events = run_rule_based_checks(
            range_df,
            mlflow_run_id=None,
            progress_cb=lambda msg: _append_terminal_log(db, pipeline_log, msg),
        )

        existing_loc_ids = {
            str(row[0])
            for row in db.query(Location.id)
            .filter(Location.id.in_(sorted({finding.building_id for finding in rule_events})))
            .all()
        }
        persisted = [finding for finding in rule_events if finding.building_id in existing_loc_ids]
        skipped = len(rule_events) - len(persisted)

        if persisted:
            AnomalyEventStore(db).insert_findings(persisted)

        _append_terminal_log(
            db, pipeline_log,
            f"Rule-based complete: {len(rule_events)} events, "
            f"{len(persisted)} persisted, {skipped} skipped (unknown buildings).",
        )

        # --- LGBm inference over CSV-backed feature matrix ---
        total_hours = int((end - start).total_seconds() // 3600) + 1
        _append_terminal_log(
            db, pipeline_log,
            f"Starting LGBm inference for {total_hours} hours from CSV telemetry...",
        )

        logged_lgbm_diagnostic = False

        def append_lgbm_diagnostic_once(message: str) -> None:
            nonlocal logged_lgbm_diagnostic
            if logged_lgbm_diagnostic:
                return
            logged_lgbm_diagnostic = True
            _append_terminal_log(db, pipeline_log, message)

        site_ids = telemetry_df["site_id"].dropna().unique().tolist()
        weather_df, weather_feature_cols = pd.DataFrame(), []
        if use_weather:
            _append_terminal_log(
                db,
                pipeline_log,
                f"Loading weather features for {len(site_ids)} sites...",
            )
            weather_df, weather_feature_cols = load_weather_for_range(
                db,
                site_ids,
                target_start - pd.Timedelta(hours=LOOKBACK_HOURS),
                target_end,
            )
            _append_terminal_log(
                db,
                pipeline_log,
                f"Weather feature load complete: {weather_feature_cols or 'none'}.",
            )
        else:
            _append_terminal_log(db, pipeline_log, "Weather features disabled for this model.")

        _append_terminal_log(
            db,
            pipeline_log,
            f"Building feature matrix for {len(telemetry_df):,} CSV rows...",
        )
        downcast_telemetry_dtypes(telemetry_df)
        feature_df, _, _ = build_feature_matrix(
            telemetry_df,
            use_weather,
            weather_df,
            weather_feature_cols,
        )
        del telemetry_df, weather_df
        gc.collect()
        _append_terminal_log(
            db,
            pipeline_log,
            f"Feature matrix complete: {len(feature_df):,} rows, {len(feature_cols)} model features.",
        )
        score_df = feature_df[
            (feature_df["timestamp"] >= target_start)
            & (feature_df["timestamp"] <= target_end)
        ].dropna(subset=["consumption"]).copy()
        _append_terminal_log(
            db,
            pipeline_log,
            f"LGBm scoring frame prepared: {len(score_df):,} rows, {score_df['building_id'].nunique()} buildings.",
        )

        if score_df.empty:
            total_written = 0
            _append_terminal_log(db, pipeline_log, "No non-missing CSV rows available for LGBm scoring.")
        else:
            existing_loc_ids = {
                str(row[0])
                for row in db.query(Location.id)
                .filter(Location.id.in_(score_df["building_id"].astype(str).unique().tolist()))
                .all()
            }
            before_filter = len(score_df)
            score_df = score_df[score_df["building_id"].astype(str).isin(existing_loc_ids)].copy()
            skipped_lgbm = before_filter - len(score_df)

            score_chunk_size = 50_000
            scored_chunks = []
            for offset_idx in range(0, len(score_df), score_chunk_size):
                chunk = score_df.iloc[offset_idx: offset_idx + score_chunk_size].copy()
                _append_terminal_log(
                    db,
                    pipeline_log,
                    (
                        f"LGBm scoring progress: "
                        f"{min(offset_idx + len(chunk), len(score_df)):,}/{len(score_df):,} rows..."
                    ),
                )
                scored_chunks.append(
                    classify_severity(
                        score_anomalies(
                            model,
                            resid_stats,
                            chunk,
                            feature_cols,
                            diagnostic_cb=append_lgbm_diagnostic_once,
                        )
                    )
                )
            scored = pd.concat(scored_chunks, ignore_index=True)
            _append_terminal_log(
                db,
                pipeline_log,
                f"LGBm scoring complete: {len(scored):,} scored rows.",
            )

            records = []
            for _, row in scored.iterrows():
                records.append({
                    "building_id": str(row["building_id"]),
                    "site_id": str(row.get("site_id", "")),
                    "timestamp": row["timestamp"],
                    "metric_type_id": str(row.get("metric_type_id", DEFAULT_METRIC_TYPE)),
                    "primary_space_usage": row.get("primaryspaceusage"),
                    "actual_value": float(row["consumption"]) if pd.notna(row.get("consumption")) else None,
                    "predicted_value": float(row["predicted_value"]) if pd.notna(row.get("predicted_value")) else None,
                    "residual": float(row["residual"]) if pd.notna(row.get("residual")) else None,
                    "residual_z": float(row["residual_z"]) if pd.notna(row.get("residual_z")) else None,
                    "anomaly_score": float(row["anomaly_score"]) if pd.notna(row.get("anomaly_score")) else None,
                    "is_anomaly": bool(row["is_anomaly"]),
                    "direction": str(row["direction"]) if pd.notna(row.get("direction")) else None,
                    "severity": str(row["severity"]),
                    "source": "lgbm",
                    "mlflow_run_id": None,
                })

            store = AnomalyEventStore(db)
            chunk_size = 50_000
            for offset_idx in range(0, len(records), chunk_size):
                chunk = records[offset_idx: offset_idx + chunk_size]
                store.upsert(chunk, commit=False)
                if offset_idx == 0 or (offset_idx + len(chunk)) % 5_000 == 0 or offset_idx + len(chunk) == len(records):
                    _append_terminal_log(
                        db,
                        pipeline_log,
                        (
                            f"LGBm persistence progress: "
                            f"{offset_idx + len(chunk):,}/{len(records):,} rows written..."
                        ),
                    )
            db.commit()
            total_written = len(records)
            if skipped_lgbm:
                _append_terminal_log(
                    db,
                    pipeline_log,
                    f"LGBm skipped {skipped_lgbm:,} rows for buildings missing from location metadata.",
                )

        _append_terminal_log(
            db, pipeline_log,
            f"LGBm inference complete: {total_hours} hours, {total_written} rows written.",
        )

        pipeline_log.execution_time_ms = int((perf_counter() - start_perf) * 1000)
        pipeline_log.status = "Success"  # type: ignore
        _append_terminal_log(
            db, pipeline_log,
            f"Backfill finished in {pipeline_log.execution_time_ms} ms.",
        )
        db.commit()

        return {
            "message": "Anomaly backfill inference complete.",
            "hours_processed": total_hours,
            "lgbm_events_written": total_written,
        }

    except Exception as e:
        db.rollback()
        if pipeline_log is not None:
            pipeline_log.status = "Failed"  # type: ignore
            pipeline_log.execution_time_ms = int((perf_counter() - start_perf) * 1000)
            _append_terminal_log(db, pipeline_log, f"Backfill failed: {type(e).__name__}: {e}")
            db.commit()
        raise

    finally:
        db.close()


celery_app.conf.beat_schedule = {
    **getattr(celery_app.conf, "beat_schedule", {}),
    "anomaly-inference-hourly": {
        "task": "run_anomaly_inference_task",
        "schedule": 3600.0,
    },
}
