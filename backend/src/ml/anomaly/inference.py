"""Rule-based anomaly checks and hourly inference runner."""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from src.ml.anomaly.types import (
    DEFAULT_METRIC_TYPE,
    FLATLINE,
    FLATLINE_MIN_RUN,
    LONG_MISSING_RUN,
    LONG_MISSING_RUN_MIN,
    LOOKBACK_HOURS,
    MISSING_READING,
    RuleFinding,
    SPIKE_EXTREME,
)

logger = logging.getLogger(__name__)

SPIKE_MULTIPLIER = 10.0


# ---------------------------------------------------------------------------
# Rule-based checks
# ---------------------------------------------------------------------------

def run_rule_based_checks(
    df: pd.DataFrame,
    mlflow_run_id: str | None,
    progress_cb: "Callable[[str], None] | None" = None,
) -> list[RuleFinding]:
    """
    Run deterministic data-quality checks over df.
    Returns plain rule findings (not yet committed).
    df must have columns: timestamp, building_id, site_id, metric_type_id,
    primaryspaceusage, consumption.
    """
    events: list[RuleFinding] = []
    buildings = list(df.groupby("building_id"))
    total_buildings = len(buildings)

    for i, (building_id, grp) in enumerate(buildings, start=1):
        if progress_cb and i % 200 == 0:
            progress_cb(f"Rule-based checks: {i}/{total_buildings} buildings processed.")
        grp = grp.sort_values("timestamp").copy()
        site_id = grp["site_id"].iloc[0] if "site_id" in grp.columns else None
        metric_type_id = grp["metric_type_id"].iloc[0] if "metric_type_id" in grp.columns else DEFAULT_METRIC_TYPE
        psu = grp["primaryspaceusage"].iloc[0] if "primaryspaceusage" in grp.columns else None

        consumption = grp["consumption"]
        is_nan = consumption.isna()

        # Missing readings
        for idx in grp.index[is_nan]:
            row = grp.loc[idx]
            events.append(RuleFinding(
                building_id=building_id,
                site_id=site_id or "",
                timestamp=pd.Timestamp(row["timestamp"]).to_pydatetime(),
                metric_type_id=metric_type_id,
                primary_space_usage=psu,
                actual_value=None,
                is_anomaly=True,
                direction=None,
                severity="Medium",
                source="rule_based",
                anomaly_type=MISSING_READING,
                reason="Meter reading is missing.",
                mlflow_run_id=mlflow_run_id,
            ))

        # Long missing run (3+ consecutive NaN hours) — vectorized.
        # One event per run (not one per row), fired at the 3rd missing hour.
        nan_run_id = (is_nan & ~is_nan.shift(fill_value=False)).cumsum()
        nan_grp_df = grp[is_nan].copy()
        nan_grp_df["_run"] = nan_run_id[is_nan].values
        for _, run_rows in nan_grp_df.groupby("_run"):
            if len(run_rows) >= LONG_MISSING_RUN_MIN:
                run_start_ts = run_rows["timestamp"].iloc[0]
                trigger_ts = run_rows["timestamp"].iloc[LONG_MISSING_RUN_MIN - 1]
                events.append(RuleFinding(
                    building_id=building_id,
                    site_id=site_id or "",
                    timestamp=pd.Timestamp(trigger_ts).to_pydatetime(),
                    metric_type_id=metric_type_id,
                    primary_space_usage=psu,
                    actual_value=None,
                    is_anomaly=True,
                    direction=None,
                    severity="High",
                    source="rule_based",
                    anomaly_type=LONG_MISSING_RUN,
                    reason=f"{LONG_MISSING_RUN_MIN}+ consecutive missing readings starting {run_start_ts}.",
                    mlflow_run_id=mlflow_run_id,
                ))

        # Flatline (std=0 over 3+ consecutive non-NaN hours) — vectorized.
        # Emit one event at the START of each flatline run (not one per row).
        clean = grp.dropna(subset=["consumption"]).reset_index(drop=True)
        if len(clean) >= FLATLINE_MIN_RUN:
            roll_std = clean["consumption"].rolling(FLATLINE_MIN_RUN, min_periods=FLATLINE_MIN_RUN).std()
            flatline_mask = roll_std == 0
            # Detect rising edge: first row of each flatline run
            flatline_starts = flatline_mask & (~flatline_mask.shift(1, fill_value=False))
            for i in clean.index[flatline_starts]:
                row = clean.iloc[i]
                events.append(RuleFinding(
                    building_id=building_id,
                    site_id=site_id or "",
                    timestamp=pd.Timestamp(row["timestamp"]).to_pydatetime(),
                    metric_type_id=metric_type_id,
                    primary_space_usage=psu,
                    actual_value=float(row["consumption"]),
                    is_anomaly=True,
                    direction=None,
                    severity="Medium",
                    source="rule_based",
                    anomaly_type=FLATLINE,
                    reason=f"Reading has not changed for {FLATLINE_MIN_RUN}+ consecutive hours.",
                    mlflow_run_id=mlflow_run_id,
                ))

        # Extreme spike (value > rolling 24h mean × SPIKE_MULTIPLIER)
        roll_mean = consumption.shift(1).rolling(24, min_periods=1).mean()
        spike_mask = consumption > (roll_mean * SPIKE_MULTIPLIER)
        for idx in grp.index[spike_mask & ~is_nan]:
            row = grp.loc[idx]
            events.append(RuleFinding(
                building_id=building_id,
                site_id=site_id or "",
                timestamp=pd.Timestamp(row["timestamp"]).to_pydatetime(),
                metric_type_id=metric_type_id,
                primary_space_usage=psu,
                actual_value=float(row["consumption"]),
                is_anomaly=True,
                direction="over",
                severity="Critical",
                source="rule_based",
                anomaly_type=SPIKE_EXTREME,
                reason=f"Reading is {SPIKE_MULTIPLIER}× above rolling 24h mean.",
                mlflow_run_id=mlflow_run_id,
            ))

    return events


def load_production_anomaly_model(client=None) -> tuple | None:
    """
    Find the Production version of dmp_energy_anomaly_detection in MLflow.
    Returns (model, resid_stats_df, feature_cols, cat_features, use_weather, metrics) or None.
    """
    from src.ml.anomaly.model_registry import MlflowModelRegistry

    return MlflowModelRegistry(client=client).load_production_model()


def run_hourly_inference(
    db: Session,
    target_hour: datetime,
    diagnostic_cb: Callable[[str], None] | None = None,
) -> int:
    """Score target_hour against the production model. Returns rows written."""
    from src.ml.anomaly.feature_engineering import build_feature_matrix
    from src.ml.anomaly.scoring import classify_severity, score_anomalies
    from src.ml.anomaly.store import AnomalyEventStore
    from src.ml.anomaly.telemetry_loaders import query_telemetry_window
    from src.ml.anomaly.weather_loaders import load_weather_for_range

    result = load_production_anomaly_model()
    if result is None:
        logger.info("No production anomaly model found; skipping inference.")
        return 0

    model, resid_stats, feature_cols, cat_features, use_weather, metrics = result

    # Fetch 168h history for lag warmup
    lookback_start = target_hour - timedelta(hours=LOOKBACK_HOURS)
    df = query_telemetry_window(db, lookback_start, target_hour, metrics or None)
    if df.empty:
        return 0

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

    scored = classify_severity(
        score_anomalies(
            model,
            resid_stats,
            target_df,
            feature_cols,
            diagnostic_cb=diagnostic_cb,
        )
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

    if not records:
        return 0

    AnomalyEventStore(db).upsert(records)

    logger.info("Hourly inference wrote %d rows for %s", len(records), target_hour)
    return len(records)
