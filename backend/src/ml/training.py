import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.models import AIPipelineLog, Device, Location, MetricType, TelemetryData
from src.schemas import (
    MLAlgorithm,
    ModelTask,
    ModelTrainingRequest,
    ModelTrainingValidationMetric,
    ModelTrainingValidationResponse,
    TrainingDataSource,
)

MIN_TRAINING_ROWS_PER_METRIC = 24
METER_DATA_DIR = Path("/app/data/raw/data/meters/cleaned")


def create_queued_pipeline_log(
    db: Session,
    request: ModelTrainingRequest,
) -> AIPipelineLog:
    model_task_value = ModelTask(request.model_task).value
    log = AIPipelineLog(
        type="Training",
        model_task=model_task_value,
        datasource_used=pipeline_datasource_label(request),
        status="Running",
        execution_time_ms=0,
        mlflow_run_id="pending",
        terminal_log=(
            f"[{_terminal_timestamp()}] Queued training pipeline "
            f"task={model_task_value} site={request.site_id or 'all'} "
            f"building={request.building_id or '-'} metrics={','.join(request.metrics)} "
            f"source={TrainingDataSource(request.data_source).value}"
        ),
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


def pipeline_datasource_label(request: ModelTrainingRequest) -> str:
    if TrainingDataSource(request.data_source) == TrainingDataSource.CSV:
        if request.csv_path:
            return request.csv_path
        return ",".join(
            cleaned_meter_csv_path(metric).name for metric in request.metrics
        )
    return "database"


def legacy_training_request(
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


def algorithm_for_task(model_task: ModelTask) -> MLAlgorithm:
    return {
        ModelTask.Forecasting: MLAlgorithm.XGBoost,
        ModelTask.AnomalyDetection: MLAlgorithm.LightGBM,
        ModelTask.Prediction: MLAlgorithm.RandomForest,
    }[model_task]


def validate_training_request(
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

    site = _get_location_ref(db, request.site_id) if request.site_id else None
    building = (
        _get_location_ref(db, request.building_id) if request.building_id else None
    )
    if request.site_id and site is None:
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
    elif not request.site_id:
        all_rows = _safe_all(db.query(Location.id).order_by(Location.id))
        target_building_ids = [row[0] for row in all_rows]

    is_anomaly = ModelTask(request.model_task) == ModelTask.AnomalyDetection
    known_metrics = (
        set(request.metrics)
        if is_anomaly
        else {
            row[0]
            for row in db.query(MetricType.id)
            .filter(MetricType.id.in_(request.metrics))
            .all()
        }
    )
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


def training_error_detail(
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


def cleaned_meter_csv_path(metric_type: str) -> Path:
    metric_name = Path(metric_type).name.strip().lower()
    if not metric_name:
        return METER_DATA_DIR / "__invalid__.csv"

    return METER_DATA_DIR / f"{metric_name}_cleaned.csv"


def _terminal_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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
    csv_path = Path(explicit_csv_path) if explicit_csv_path else cleaned_meter_csv_path(metric)
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
