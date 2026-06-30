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
    LOOSE_FLATLINE_MIN_RUN,
    LOOSE_FLATLINE_USAGES,
    MISSING_READING,
    NEAR_ZERO_EPSILON,
    NEAR_ZERO_FLATLINE,
    NO_DATA_BUILDING,
    NO_DATA_MISSING_RATE,
    RuleFinding,
    SPIKE_EXTREME,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Rule-based checks
# ---------------------------------------------------------------------------

def _missing_run_severity(hours: int) -> str:
    if hours > 72:
        return "Critical"
    if hours > 24:
        return "High"
    if hours > 6:
        return "Medium"
    return "Low"


def _flatline_severity(hours: int, psu: str | None, value: float | None) -> str:
    near_zero = value is not None and abs(value) <= NEAR_ZERO_EPSILON
    if near_zero and psu == "Healthcare":
        return "Critical"
    if hours > 72:
        return "Critical"
    if hours > 24:
        return "High"
    if hours > 12:
        return "Medium"
    return "Low"


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

    # Compute per-building p99 and per-usage p99.9 for spike detection
    bld_p99: dict[str, float] = {}
    usage_vals: dict[str, list] = {}
    for building_id, grp in buildings:
        vals = grp["consumption"].dropna().values
        if len(vals) > 0:
            bld_p99[building_id] = float(np.percentile(vals, 99))
        psu = grp["primaryspaceusage"].iloc[0] if "primaryspaceusage" in grp.columns else None
        if psu:
            usage_vals.setdefault(psu, []).extend(vals.tolist())
    usage_p999: dict[str, float] = {
        psu: float(np.percentile(vals, 99.9))
        for psu, vals in usage_vals.items()
        if vals
    }
    SPIKE_BLD_MULTIPLIER = 5

    for i, (building_id, grp) in enumerate(buildings, start=1):
        if progress_cb and i % 200 == 0:
            progress_cb(f"Rule-based checks: {i}/{total_buildings} buildings processed.")
        grp = grp.sort_values("timestamp").copy()
        site_id = grp["site_id"].iloc[0] if "site_id" in grp.columns else None
        metric_type_id = grp["metric_type_id"].iloc[0] if "metric_type_id" in grp.columns else DEFAULT_METRIC_TYPE
        psu = grp["primaryspaceusage"].iloc[0] if "primaryspaceusage" in grp.columns else None

        consumption = grp["consumption"]
        is_nan = consumption.isna()
        total_rows = len(grp)
        missing_rate = float(is_nan.sum()) / total_rows if total_rows > 0 else 0.0

        # No-data building (>95% missing)
        if missing_rate > NO_DATA_MISSING_RATE:
            events.append(RuleFinding(
                building_id=building_id,
                site_id=site_id or "",
                timestamp=pd.Timestamp(grp["timestamp"].iloc[0]).to_pydatetime(),
                metric_type_id=metric_type_id,
                primary_space_usage=psu,
                actual_value=None,
                is_anomaly=True,
                direction=None,
                severity="Critical",
                source="rule_based",
                anomaly_type=NO_DATA_BUILDING,
                reason=f"Building has >{NO_DATA_MISSING_RATE:.0%} missing data ({missing_rate:.1%}).",
                mlflow_run_id=mlflow_run_id,
            ))
            continue  # skip further checks for this building

        # Group consecutive NaN hours into runs so each missing period is counted
        # once: isolated single hours emit missing_reading, while runs of >= 2 hours
        # are reported once as long_missing_run below (never both for the same gap).
        nan_run_id = (is_nan & ~is_nan.shift(fill_value=False)).cumsum()
        nan_grp_df = grp[is_nan].copy()
        nan_grp_df["_run"] = nan_run_id[is_nan].values

        # Missing readings — only isolated single NaNs (run length 1). The timestamp
        # is the only per-row value, so iterate the masked Series directly instead of
        # a per-row grp.loc[idx] lookup (which rebuilds a full Series each time).
        run_sizes = nan_grp_df.groupby("_run")["timestamp"].transform("size")
        for ts in nan_grp_df.loc[run_sizes == 1, "timestamp"]:
            events.append(RuleFinding(
                building_id=building_id,
                site_id=site_id or "",
                timestamp=pd.Timestamp(ts).to_pydatetime(),
                metric_type_id=metric_type_id,
                primary_space_usage=psu,
                actual_value=None,
                is_anomaly=True,
                direction=None,
                severity="Low",
                source="rule_based",
                anomaly_type=MISSING_READING,
                reason="Meter reading is missing.",
                mlflow_run_id=mlflow_run_id,
            ))

        # Long missing run (>=2 consecutive NaN hours) — one event per run
        for _, run_rows in nan_grp_df.groupby("_run"):
            run_len = len(run_rows)
            if run_len >= LONG_MISSING_RUN_MIN:
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
                    severity=_missing_run_severity(run_len),
                    source="rule_based",
                    anomaly_type=LONG_MISSING_RUN,
                    reason=f"{run_len}h consecutive missing readings starting {run_start_ts}.",
                    mlflow_run_id=mlflow_run_id,
                ))

        # Flatline / near-zero flatline — space-usage-aware threshold
        flatline_min = LOOSE_FLATLINE_MIN_RUN if psu in LOOSE_FLATLINE_USAGES else FLATLINE_MIN_RUN
        clean = grp.dropna(subset=["consumption"]).reset_index(drop=True)
        if len(clean) >= flatline_min:
            non_zero = clean[clean["consumption"] != 0].reset_index(drop=True)
            if len(non_zero) >= flatline_min:
                change = (non_zero["consumption"] != non_zero["consumption"].shift(1)).fillna(True)
                run_id_col = change.cumsum()
                fl_df = pd.DataFrame({
                    "ts": non_zero["timestamp"].values,
                    "val": non_zero["consumption"].values,
                    "run": run_id_col.values,
                })
                for _, run_rows in fl_df.groupby("run"):
                    run_len = len(run_rows)
                    if run_len < flatline_min:
                        continue
                    rv = float(run_rows["val"].iloc[0])
                    near_zero = abs(rv) <= NEAR_ZERO_EPSILON
                    a_type = NEAR_ZERO_FLATLINE if near_zero else FLATLINE
                    events.append(RuleFinding(
                        building_id=building_id,
                        site_id=site_id or "",
                        timestamp=pd.Timestamp(run_rows["ts"].iloc[0]).to_pydatetime(),
                        metric_type_id=metric_type_id,
                        primary_space_usage=psu,
                        actual_value=rv,
                        is_anomaly=True,
                        direction=None,
                        severity=_flatline_severity(run_len, psu, rv),
                        source="rule_based",
                        anomaly_type=a_type,
                        reason=f"{a_type.replace('_', ' ').title()} of {run_len}h (value={rv:.4f}).",
                        mlflow_run_id=mlflow_run_id,
                    ))

        # Spike: value > per-building p99 × 5 AND > per-usage p99.9
        bld_thresh = bld_p99.get(building_id, float("nan")) * SPIKE_BLD_MULTIPLIER
        use_thresh = usage_p999.get(psu or "", float("nan"))
        if not (np.isnan(bld_thresh) or np.isnan(use_thresh)):
            spike_mask = (consumption > bld_thresh) & (consumption > use_thresh) & ~is_nan
            spike_rows = grp.loc[spike_mask, ["timestamp", "consumption"]]
            for ts, raw_val in zip(
                spike_rows["timestamp"], spike_rows["consumption"], strict=True
            ):
                val = float(raw_val)
                events.append(RuleFinding(
                    building_id=building_id,
                    site_id=site_id or "",
                    timestamp=pd.Timestamp(ts).to_pydatetime(),
                    metric_type_id=metric_type_id,
                    primary_space_usage=psu,
                    actual_value=val,
                    is_anomaly=True,
                    direction="over",
                    severity="Critical",
                    source="rule_based",
                    anomaly_type=SPIKE_EXTREME,
                    reason=f"Spike {val:.2f} > bld_thresh {bld_thresh:.2f} & use_thresh {use_thresh:.2f}.",
                    mlflow_run_id=mlflow_run_id,
                ))

    return events


def _apply_quality_mask(df: pd.DataFrame, findings: list[RuleFinding]) -> pd.DataFrame:
    """Mask spike and near-zero flatline timestamps to NaN before feature engineering."""
    mask_types = {SPIKE_EXTREME, NEAR_ZERO_FLATLINE}
    bad = {
        (f.building_id, pd.Timestamp(f.timestamp).tz_localize("UTC") if pd.Timestamp(f.timestamp).tzinfo is None else pd.Timestamp(f.timestamp))
        for f in findings
        if f.anomaly_type in mask_types
    }
    if not bad:
        return df
    out = df.copy()
    ts_utc = pd.to_datetime(out["timestamp"], utc=True)
    mask = pd.Series(
        [(row["building_id"], ts_utc.iloc[i]) in bad for i, row in out.iterrows()],
        index=out.index,
    )
    out.loc[mask, "consumption"] = np.nan
    return out


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

    # Run rule-based checks for the target hour's data, then apply quality mask
    rule_findings = run_rule_based_checks(df, mlflow_run_id=None)
    df = _apply_quality_mask(df, rule_findings)
    if rule_findings:
        AnomalyEventStore(db).insert_findings(rule_findings)

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
