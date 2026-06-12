"""Rule-based anomaly checks and hourly inference runner."""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

SPIKE_MULTIPLIER = 10.0


# ---------------------------------------------------------------------------
# Rule-based checks
# ---------------------------------------------------------------------------

def run_rule_based_checks(
    df: pd.DataFrame,
    mlflow_run_id: str | None,
    progress_cb: "Callable[[str], None] | None" = None,
) -> list:
    """
    Run deterministic data-quality checks over df.
    Returns list of AnomalyDetectedEvent instances (not yet committed).
    df must have columns: timestamp, building_id, site_id, metric_type_id,
    primaryspaceusage, consumption.
    """
    from src.models import AnomalyDetectedEvent

    events: list[AnomalyDetectedEvent] = []
    buildings = list(df.groupby("building_id"))
    total_buildings = len(buildings)

    for i, (building_id, grp) in enumerate(buildings, start=1):
        if progress_cb and i % 200 == 0:
            progress_cb(f"Rule-based checks: {i}/{total_buildings} buildings processed.")
        grp = grp.sort_values("timestamp").copy()
        site_id = grp["site_id"].iloc[0] if "site_id" in grp.columns else None
        metric_type_id = grp["metric_type_id"].iloc[0] if "metric_type_id" in grp.columns else "energy"
        psu = grp["primaryspaceusage"].iloc[0] if "primaryspaceusage" in grp.columns else None

        consumption = grp["consumption"]
        is_nan = consumption.isna()

        # Missing readings
        for idx in grp.index[is_nan]:
            row = grp.loc[idx]
            events.append(AnomalyDetectedEvent(
                building_id=building_id,
                site_id=site_id or "",
                timestamp=row["timestamp"],
                metric_type_id=metric_type_id,
                primary_space_usage=psu,
                actual_value=None,
                is_anomaly=True,
                direction=None,
                severity="Medium",
                source="rule_based",
                anomaly_type="missing_reading",
                reason="Meter reading is missing.",
                mlflow_run_id=mlflow_run_id,
            ))

        # Long missing run (3+ consecutive NaN hours) — vectorized.
        # One event per run (not one per row), fired at the 3rd missing hour.
        nan_run_id = (is_nan & ~is_nan.shift(fill_value=False)).cumsum()
        nan_grp_df = grp[is_nan].copy()
        nan_grp_df["_run"] = nan_run_id[is_nan].values
        for _, run_rows in nan_grp_df.groupby("_run"):
            if len(run_rows) >= 3:
                run_start_ts = run_rows["timestamp"].iloc[0]
                trigger_ts = run_rows["timestamp"].iloc[2]
                events.append(AnomalyDetectedEvent(
                    building_id=building_id,
                    site_id=site_id or "",
                    timestamp=trigger_ts,
                    metric_type_id=metric_type_id,
                    primary_space_usage=psu,
                    actual_value=None,
                    is_anomaly=True,
                    direction=None,
                    severity="High",
                    source="rule_based",
                    anomaly_type="long_missing_run",
                    reason=f"3+ consecutive missing readings starting {run_start_ts}.",
                    mlflow_run_id=mlflow_run_id,
                ))

        # Flatline (std=0 over 3+ consecutive non-NaN hours) — vectorized.
        # Emit one event at the START of each flatline run (not one per row).
        clean = grp.dropna(subset=["consumption"]).reset_index(drop=True)
        if len(clean) >= 3:
            roll_std = clean["consumption"].rolling(3, min_periods=3).std()
            flatline_mask = roll_std == 0
            # Detect rising edge: first row of each flatline run
            flatline_starts = flatline_mask & (~flatline_mask.shift(1, fill_value=False))
            for i in clean.index[flatline_starts]:
                row = clean.iloc[i]
                events.append(AnomalyDetectedEvent(
                    building_id=building_id,
                    site_id=site_id or "",
                    timestamp=row["timestamp"],
                    metric_type_id=metric_type_id,
                    primary_space_usage=psu,
                    actual_value=float(row["consumption"]),
                    is_anomaly=True,
                    direction=None,
                    severity="Medium",
                    source="rule_based",
                    anomaly_type="flatline",
                    reason="Reading has not changed for 3+ consecutive hours.",
                    mlflow_run_id=mlflow_run_id,
                ))

        # Extreme spike (value > rolling 24h mean × SPIKE_MULTIPLIER)
        roll_mean = consumption.shift(1).rolling(24, min_periods=1).mean()
        spike_mask = consumption > (roll_mean * SPIKE_MULTIPLIER)
        for idx in grp.index[spike_mask & ~is_nan]:
            row = grp.loc[idx]
            events.append(AnomalyDetectedEvent(
                building_id=building_id,
                site_id=site_id or "",
                timestamp=row["timestamp"],
                metric_type_id=metric_type_id,
                primary_space_usage=psu,
                actual_value=float(row["consumption"]),
                is_anomaly=True,
                direction="over",
                severity="Critical",
                source="rule_based",
                anomaly_type="spike_extreme_reading",
                reason=f"Reading is {SPIKE_MULTIPLIER}× above rolling 24h mean.",
                mlflow_run_id=mlflow_run_id,
            ))

    return events


# ---------------------------------------------------------------------------
# Inference runner
# ---------------------------------------------------------------------------

def load_production_anomaly_model(client) -> tuple | None:
    """
    Find the Production version of dmp_energy_anomaly_detection in MLflow.
    Returns (model, resid_stats_df, feature_cols, cat_features, use_weather) or None.
    """
    import tempfile

    import mlflow.lightgbm

    try:
        versions = client.get_latest_versions("dmp_energy_anomaly_detection", stages=["Production"])
    except Exception:
        return None

    if not versions:
        return None

    version = versions[0]
    run_id = version.run_id

    model = mlflow.lightgbm.load_model("models:/dmp_energy_anomaly_detection/Production")

    # Download resid_stats artifact
    with tempfile.TemporaryDirectory() as tmp:
        local_path = client.download_artifacts(run_id, "resid_stats.parquet", tmp)
        resid_stats = pd.read_parquet(local_path)

    # Read tags
    run = client.get_run(run_id)
    tags = run.data.tags
    feature_set = tags.get("feature_set", "")
    feature_cols = [f.strip() for f in feature_set.split(",") if f.strip()]
    use_weather = tags.get("weather_features", "false").lower() == "true"

    from src.ml.anomaly_pipeline import CAT_FEATURES
    cat_features = [c for c in CAT_FEATURES if c in feature_cols]

    return model, resid_stats, feature_cols, cat_features, use_weather


def run_hourly_inference(db: Session, target_hour: datetime) -> int:
    """Score target_hour against the production model. Returns rows written."""
    from mlflow.tracking import MlflowClient

    from src.ml.anomaly_pipeline import (
        build_feature_matrix,
        load_weather_for_range,
        score_anomalies,
    )
    from src.models import AnomalyDetectedEvent

    client = MlflowClient()
    result = load_production_anomaly_model(client)
    if result is None:
        logger.info("No production anomaly model found; skipping inference.")
        return 0

    model, resid_stats, feature_cols, cat_features, use_weather = result

    # Fetch 168h history for lag warmup
    lookback_start = target_hour - timedelta(hours=168)

    from src.models import Device, Location, TelemetryData
    rows = (
        db.query(
            TelemetryData.timestamp,
            TelemetryData.value.label("consumption"),
            TelemetryData.metric_type_id,
            Device.location_id.label("building_id"),
            Location.parent_id.label("site_id"),
        )
        .join(Device, TelemetryData.device_id == Device.id)
        .join(Location, Device.location_id == Location.id)
        .filter(
            TelemetryData.timestamp >= lookback_start,
            TelemetryData.timestamp <= target_hour,
        )
        .all()
    )

    if not rows:
        return 0

    df = pd.DataFrame(rows, columns=["timestamp", "consumption", "metric_type_id", "building_id", "site_id"])
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    # Fetch metadata
    loc_rows = (
        db.query(Location.id, Location.metadata_)
        .filter(Location.id.in_(df["building_id"].unique().tolist()))
        .all()
    )
    loc_meta = {loc_id: (meta or {}) for loc_id, meta in loc_rows}
    df["sqm"] = df["building_id"].map(lambda b: loc_meta.get(b, {}).get("sqm"))
    df["primaryspaceusage"] = df["building_id"].map(lambda b: loc_meta.get(b, {}).get("primaryspaceusage"))
    df["timezone"] = df["building_id"].map(lambda b: loc_meta.get(b, {}).get("timezone"))

    site_ids = df["site_id"].dropna().unique().tolist()
    weather_df, weather_feature_cols = pd.DataFrame(), []
    if use_weather:
        weather_df, weather_feature_cols = load_weather_for_range(
            db, site_ids,
            pd.Timestamp(lookback_start),
            pd.Timestamp(target_hour),
        )

    feature_df, _, _ = build_feature_matrix(df, use_weather, weather_df, weather_feature_cols)

    # Only score the target hour
    target_df = feature_df[feature_df["timestamp"] == pd.Timestamp(target_hour)].copy()
    if target_df.empty:
        return 0

    # Align feature columns (model may have been trained with different column order)
    missing = [c for c in feature_cols if c not in target_df.columns]
    for c in missing:
        target_df[c] = np.nan

    scored = score_anomalies(model, resid_stats, target_df, feature_cols)

    # Build ORM objects and upsert
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    records = []
    for _, row in scored.iterrows():
        records.append({
            "building_id": str(row["building_id"]),
            "site_id": str(row.get("site_id", "")),
            "timestamp": row["timestamp"],
            "metric_type_id": str(row.get("metric_type_id", "energy")),
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

    if not records:
        return 0

    stmt = pg_insert(AnomalyDetectedEvent.__table__).values(records)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_anomaly_detected_event",
        set_={
            "predicted_value": stmt.excluded.predicted_value,
            "residual": stmt.excluded.residual,
            "residual_z": stmt.excluded.residual_z,
            "anomaly_score": stmt.excluded.anomaly_score,
            "is_anomaly": stmt.excluded.is_anomaly,
            "direction": stmt.excluded.direction,
            "severity": stmt.excluded.severity,
        },
    )
    db.execute(stmt)
    db.commit()

    logger.info("Hourly inference wrote %d rows for %s", len(records), target_hour)
    return len(records)
