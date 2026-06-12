import logging
import tempfile
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import mlflow
import mlflow.lightgbm
import pandas as pd
from mlflow.tracking import MlflowClient
from sqlalchemy.orm import Session

from src.ml.anomaly_inference import run_rule_based_checks
from src.ml.anomaly_pipeline import (
    build_feature_matrix,
    compute_residual_stats,
    load_telemetry_for_training,
    load_weather_for_range,
    score_anomalies,
    train_lgbm,
)
from src.models import AIPipelineLog, AnomalyDetectedEvent
from src.schemas import ModelTrainingRequest

logger = logging.getLogger(__name__)


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
    train_end = start + total * 0.50
    test_start = end - total * 0.10

    # --- Weather auto-detection ---
    use_weather = (start.year >= 2016 and end.year <= 2017)
    if not use_weather:
        append_log("Weather features disabled: training range outside 2016–2017 weather data coverage.")

    # --- Load telemetry ---
    append_log("Loading telemetry...")
    df = load_telemetry_for_training(db, request)
    if df.empty:
        raise ValueError("No telemetry data found for the requested date range.")
    append_log(f"Loaded {len(df):,} rows, {df['building_id'].nunique()} buildings.")

    # --- Rule-based checks ---
    append_log("Running rule-based checks...")
    rule_events = run_rule_based_checks(df, mlflow_run_id=mlflow_run.info.run_id)
    if rule_events:
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        records = [
            {c.key: getattr(e, c.key) for c in AnomalyDetectedEvent.__table__.columns if c.key != "id"}
            for e in rule_events
        ]
        stmt = pg_insert(AnomalyDetectedEvent.__table__).values(records)
        stmt = stmt.on_conflict_do_nothing(constraint="uq_anomaly_detected_event")
        db.execute(stmt)
        db.commit()
    append_log(f"Rule-based checks complete: {len(rule_events)} events.")

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

    # --- Feature matrix ---
    append_log("Building feature matrix...")
    feature_df, feature_cols, cat_features = build_feature_matrix(df, use_weather, weather_df, weather_feature_cols)
    append_log(f"Feature matrix: {len(feature_df):,} rows × {len(feature_cols)} features.")

    # --- Train ---
    append_log("Training LightGBM (4-fold CV + final model)...")
    final_model, early_stop_model, val_df, train_metrics = train_lgbm(
        feature_df, feature_cols, cat_features, train_end, test_start
    )
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
    append_log("Computing residual calibration stats...")
    resid_stats = compute_residual_stats(early_stop_model, val_df, feature_cols)

    # --- MLflow logging ---
    append_log("Logging model to MLflow...")
    mlflow.log_params({
        "use_weather": use_weather,
        "n_features": len(feature_cols),
        "best_iteration": train_metrics["best_iteration"],
        "train_end": str(train_end.date()),
        "test_start": str(test_start.date()),
    })
    mlflow.log_metrics({
        "test_rmse": train_metrics["test_rmse"],
        "test_mae": train_metrics["test_mae"],
    })

    mlflow.lightgbm.log_model(
        final_model,
        artifact_path="model",
        registered_model_name="dmp_energy_anomaly_detection",
    )

    with tempfile.TemporaryDirectory() as tmp:
        stats_path = Path(tmp) / "resid_stats.parquet"
        resid_stats.to_parquet(stats_path, index=False)
        mlflow.log_artifact(str(stats_path))

    # Tag the registered version
    client = MlflowClient()
    versions = client.get_latest_versions("dmp_energy_anomaly_detection", stages=["None"])
    if versions:
        v = versions[-1]
        client.set_model_version_tag(v.name, v.version, "model_task", "anomaly_detection")
        client.set_model_version_tag(v.name, v.version, "weather_features", str(use_weather).lower())
        client.set_model_version_tag(v.name, v.version, "feature_set", ",".join(feature_cols))

    append_log("Model registered as dmp_energy_anomaly_detection.")

    # Anomaly rate on full training window (scored with final model)
    train_window = feature_df[
        (feature_df["timestamp"] >= start) & (feature_df["timestamp"] <= end)
    ].dropna(subset=["consumption"])
    anomaly_rate = 0.0
    if not train_window.empty:
        scored = score_anomalies(final_model, resid_stats, train_window, feature_cols)
        anomaly_rate = float(scored["is_anomaly"].mean())

    return {
        "rmse": train_metrics["test_rmse"],
        "mae": train_metrics["test_mae"],
        "anomaly_rate": anomaly_rate,
        "training_rows": len(feature_df),
        "n_buildings": feature_df["building_id"].nunique(),
        "n_rule_based_events": len(rule_events),
        "cv_folds": train_metrics.get("cv_folds", []),
    }
