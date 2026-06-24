import gc
import logging
from collections.abc import Callable, Sequence
from datetime import timedelta

import pandas as pd
from sqlalchemy.orm import Session

from src.ml.anomaly.feature_engineering import build_feature_matrix
from src.ml.anomaly.inference import run_rule_based_checks
from src.ml.anomaly.model_registry import MlflowModelRegistry
from src.ml.anomaly.scoring import classify_severity, score_anomalies
from src.ml.anomaly.store import AnomalyEventStore
from src.ml.anomaly.telemetry_loaders import downcast_telemetry_dtypes, load_telemetry_for_training
from src.ml.anomaly.training import (
    CHUNK_TRAINING_THRESHOLD_DAYS,
    DEFAULT_CHUNK_MONTHS,
    compute_residual_stats,
    train_lgbm,
    train_lgbm_chunked,
)
from src.ml.anomaly.types import RuleFinding, WEATHER_COVERAGE_END_YEAR, WEATHER_COVERAGE_START_YEAR
from src.ml.anomaly.weather_loaders import load_weather_for_range
from src.models import AIPipelineLog
from src.schemas import ModelTrainingRequest

logger = logging.getLogger(__name__)


def _existing_location_ids_for_findings(
    findings: Sequence[RuleFinding],
    db: Session,
) -> set[str]:
    from src.models import Location

    building_ids = sorted({finding.building_id for finding in findings})
    if not building_ids:
        return set()

    rows = db.query(Location.id).filter(Location.id.in_(building_ids)).all()
    existing_ids: set[str] = set()
    for row in rows:
        if isinstance(row, tuple):
            existing_ids.add(str(row[0]))
        elif hasattr(row, "id"):
            existing_ids.add(str(row.id))
        else:
            existing_ids.add(str(row[0]))
    return existing_ids


def _filter_findings_with_existing_locations(
    findings: Sequence[RuleFinding],
    db: Session,
    append_log: Callable[[str], None],
) -> list[RuleFinding]:
    existing_ids = _existing_location_ids_for_findings(findings, db)
    filtered = [finding for finding in findings if finding.building_id in existing_ids]
    skipped = len(findings) - len(filtered)
    if skipped:
        missing_buildings = {
            finding.building_id for finding in findings if finding.building_id not in existing_ids
        }
        append_log(
            f"Skipped {skipped:,} rule-based events for "
            f"{len(missing_buildings):,} buildings missing from location metadata."
        )
    return filtered


def _make_chunk_source(db: Session, request: ModelTrainingRequest):
    def _load(start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
        chunk_request = request.model_copy(
            update={"time_range_start": start, "time_range_end": end}
        )
        return load_telemetry_for_training(db, chunk_request)

    return _load


def train_anomaly_detection_model(
    request: ModelTrainingRequest,
    db: Session,
    *,
    mlflow_run,
    pipeline_log: AIPipelineLog,
    append_log: Callable[[str], None],
) -> dict[str, object]:
    start = pd.Timestamp(request.time_range_start)
    end = pd.Timestamp(request.time_range_end)
    total = end - start
    train_end = start + total * 0.80
    test_start = end - total * 0.10

    append_log(
        f"Time splits — Train: {start.date()} → {train_end.date()} | "
        f"Val: {train_end.date()} → {test_start.date()} | "
        f"Test: {test_start.date()} → {end.date()} "
        f"(total {total.days} days)."
    )

    # --- Weather auto-detection ---
    use_weather = (
        start.year >= WEATHER_COVERAGE_START_YEAR
        and end.year <= WEATHER_COVERAGE_END_YEAR
    )
    if not use_weather:
        append_log("Weather features disabled: training range outside 2016–2017 weather data coverage.")

    # --- Load telemetry ---
    append_log("Loading telemetry...")
    df = load_telemetry_for_training(db, request)
    if df.empty:
        raise ValueError("No telemetry data found for the requested date range.")
    downcast_telemetry_dtypes(df)
    append_log(f"Loaded {len(df):,} rows, {df['building_id'].nunique()} buildings.")

    # --- Rule-based checks ---
    n_buildings = df["building_id"].nunique()
    append_log(f"Running rule-based checks across {n_buildings} buildings...")
    rule_events = run_rule_based_checks(df, mlflow_run_id=mlflow_run.info.run_id, progress_cb=append_log)
    persisted_rule_events = _filter_findings_with_existing_locations(rule_events, db, append_log)
    if persisted_rule_events:
        append_log(f"Persisting {len(persisted_rule_events):,} rule-based events to DB...")
        AnomalyEventStore(db).insert_findings(persisted_rule_events, progress_cb=append_log)
    append_log(
        f"Rule-based checks complete: {len(rule_events)} events, "
        f"{len(persisted_rule_events)} persisted."
    )

    # --- Weather loading ---
    weather_df, weather_feature_cols = pd.DataFrame(), []
    if use_weather:
        append_log("Loading weather features...")
        site_ids = df["site_id"].dropna().unique().tolist()
        weather_df, weather_feature_cols = load_weather_for_range(db, site_ids, start, end + timedelta(hours=1))
        if weather_df.empty:
            use_weather = False
            append_log("No weather data available; continuing without weather features.")
        else:
            append_log(f"Weather loaded: {weather_feature_cols}")

    # --- Feature matrix & training ---
    use_chunked = (end - start).days > CHUNK_TRAINING_THRESHOLD_DAYS

    if use_chunked:
        append_log(
            f"Training range is {(end - start).days} days — using chunked continual learning "
            f"({DEFAULT_CHUNK_MONTHS}-month segments)."
        )
        del df
        gc.collect()
        result = train_lgbm_chunked(
            _make_chunk_source(db, request),
            start,
            end,
            train_end,
            test_start,
            use_weather,
            weather_df,
            weather_feature_cols,
            chunk_months=DEFAULT_CHUNK_MONTHS,
            append_log=append_log,
        )
        del weather_df
        gc.collect()
    else:
        append_log("Building feature matrix...")
        feature_df, feature_cols, cat_features = build_feature_matrix(df, use_weather, weather_df, weather_feature_cols)
        del df, weather_df
        gc.collect()
        append_log(f"Feature matrix: {len(feature_df):,} rows × {len(feature_cols)} features.")

        append_log("Training LightGBM...")
        result = train_lgbm(
            feature_df, feature_cols, cat_features, train_end, test_start, append_log
        )

    final_model = result.final_model
    early_stop_model = result.early_stop_model
    val_df = result.val_df
    train_metrics = result.metrics
    feature_cols = result.feature_cols
    feature_df = result.feature_df

    for fold in train_metrics.get("cv_folds", []):
        append_log(
            f"  Fold {fold['fold']}: RMSE={fold['val_rmse']:.3f} MAE={fold['val_mae']:.3f} "
            f"best_iter={fold['best_iteration']}"
        )
    append_log(
        f"Final model — Test RMSE={train_metrics['test_rmse']:.3f} "
        f"MAE={train_metrics['test_mae']:.3f} trees={train_metrics['best_iteration']}"
    )

    # --- Residual calibration ---
    resid_stats = compute_residual_stats(early_stop_model, val_df, feature_cols, append_log)

    append_log("Logging model to MLflow...")
    registry = MlflowModelRegistry()
    registry.log_model(final_model, feature_cols, train_metrics, request, use_weather=use_weather)
    registry.log_artifact("resid_stats.parquet", resid_stats)

    append_log("Model registered as dmp_energy_anomaly_detection.")

    # Anomaly rate on full training window (skipped for chunked path — feature_df not retained)
    anomaly_rate = 0.0
    if feature_df is not None:
        train_window = feature_df[
            (feature_df["timestamp"] >= start) & (feature_df["timestamp"] <= end)
        ].dropna(subset=["consumption"])
        if not train_window.empty:
            append_log(f"Computing anomaly rate on {len(train_window):,} training rows...")
            scored = classify_severity(
                score_anomalies(final_model, resid_stats, train_window, feature_cols)
            )
            anomaly_rate = float(scored["is_anomaly"].mean())
            append_log(f"Anomaly rate: {anomaly_rate:.4f} ({scored['is_anomaly'].sum():,} flagged).")
    else:
        append_log("Anomaly rate skipped (chunked path — full feature_df not retained).")

    return {
        "rmse": train_metrics["test_rmse"],
        "mae": train_metrics["test_mae"],
        "anomaly_rate": anomaly_rate,
        "training_rows": len(feature_df) if feature_df is not None else 0,
        "n_buildings": feature_df["building_id"].nunique() if feature_df is not None else n_buildings,
        "n_rule_based_events": len(rule_events),
        "cv_folds": train_metrics.get("cv_folds", []),
    }
