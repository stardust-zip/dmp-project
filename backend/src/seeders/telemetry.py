from __future__ import annotations

import logging
import time
from pathlib import Path

import pandas as pd
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session
from src import models

logger = logging.getLogger(__name__)

ALL_METRICS: tuple[str, ...] = (
    "electricity",
    "chilledwater",
    "steam",
    "hotwater",
    "gas",
    "water",
    "solar",
    "irrigation",
)

DEFAULT_CHUNK_SIZE = 10_000  # CSV rows per pandas chunk
DEFAULT_BATCH_SIZE = 10_000  # TelemetryData rows per DB batch insert

_SUCCESS_STATUS = "Success"


# ──────────────────────────────────────────────────────────────────────
# Device cache  —  {building_id: device_id}  pre-fetched once per metric
# ──────────────────────────────────────────────────────────────────────


def _build_device_map(db: Session, metric: str) -> dict[str, str]:
    prefix = f"meter_{metric}_"
    rows = (
        db.query(models.Device.id, models.Device.location_id)
        .filter(models.Device.id.startswith(prefix))
        .filter(models.Device.location_id.isnot(None))
        .all()
    )
    return {str(location_id): str(device_id) for device_id, location_id in rows}


# ──────────────────────────────────────────────────────────────────────
# Row builder  —  iterates a single building column into pending batch
# ──────────────────────────────────────────────────────────────────────


def _flush_pending(
    db: Session,
    pending: list[models.TelemetryData],
) -> int:
    """Upsert *pending* rows via ``INSERT … ON CONFLICT DO UPDATE``.

    Returns the number of rows flushed.
    """
    if not pending:
        return 0

    count = len(pending)
    stmt = pg_insert(models.TelemetryData).values(
        [
            {
                "timestamp": obj.timestamp,
                "device_id": obj.device_id,
                "metric_type_id": obj.metric_type_id,
                "value": obj.value,
                "ingestion_status": obj.ingestion_status,
            }
            for obj in pending
        ]
    )
    stmt = stmt.on_conflict_do_update(
        constraint="telemetry_data_pkey",
        set_={
            "value": stmt.excluded.value,
            "ingestion_status": stmt.excluded.ingestion_status,
        },
    )
    db.execute(stmt)
    db.commit()
    pending.clear()
    return count


def _scrape_column_into_batch(
    *,
    pending: list[models.TelemetryData],
    chunk: pd.DataFrame,
    building_id: str,
    device_id: str,
    metric: str,
    batch_size: int,
    db: Session,
    ts_series: pd.Series,
) -> int:
    """
    Extract all non-NaN (timestamp, value) pairs from a single building
    column and append ORM instances to *pending*.

    Flushes to DB whenever *pending* crosses *batch_size*.
    Returns the number of rows appended.
    """
    series = chunk.get(building_id)
    if series is None:
        return 0

    mask = series.notna()
    if not mask.any():
        return 0

    # Timestamps are already parsed by pd.to_datetime(…, utc=True)
    # at the chunk level.  Filter out any NaT rows.
    idx = mask[mask].index
    valid_idx = [i for i in idx if pd.notna(ts_series[i])]
    if not valid_idx:
        return 0

    # Build instance list in one list comprehension.
    # .to_pydatetime() is free — pd.Timestamp caches this internally.
    appended = 0
    for i in valid_idx:
        pending.append(
            models.TelemetryData(
                timestamp=ts_series[i].to_pydatetime(),
                device_id=device_id,
                metric_type_id=metric,
                value=float(series[i]),
                ingestion_status=_SUCCESS_STATUS,
            )
        )
        appended += 1
        if len(pending) >= batch_size:
            _flush_pending(db, pending)

    return appended


# ──────────────────────────────────────────────────────────────────────
# Single-metric seeder
# ──────────────────────────────────────────────────────────────────────


def seed_metric_telemetry(
    db: Session,
    meter_dir: str | Path,
    metric: str,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    batch_size: int = DEFAULT_BATCH_SIZE,
    limit: int | None = None,
) -> int:
    """
    Seed telemetry rows for a single metric.

    Returns the total number of rows inserted.
    """
    csv_path = Path(meter_dir) / f"{metric}_cleaned.csv"
    if not csv_path.exists():
        logger.warning("Meter CSV not found, skipping: %s", csv_path)
        return 0

    device_map = _build_device_map(db, metric)
    if not device_map:
        logger.warning("No devices registered for metric '%s'. Skipping.", metric)
        return 0

    # Only read columns that have a registered device (plus timestamp).
    # This dramatically reduces the memory footprint per chunk.
    valid_buildings = sorted(device_map.keys())

    total_inserted = 0
    chunk_index = 0
    started_at = time.monotonic()

    logger.info(
        "[%s] Starting seed — %d building columns, chunk_size=%d, batch_size=%d.",
        metric,
        len(valid_buildings),
        chunk_size,
        batch_size,
    )

    reader = pd.read_csv(
        csv_path,
        chunksize=chunk_size,
        nrows=limit,
        usecols=lambda col: col == "timestamp" or col in device_map,
        low_memory=False,
    )

    pending: list[models.TelemetryData] = []

    for chunk in reader:
        chunk_index += 1
        chunk_start = time.monotonic()
        chunk_total = 0

        # Parse the timestamp column once per chunk
        if "timestamp" not in chunk.columns:
            logger.warning(
                "[%s] Chunk %d: missing 'timestamp' column, skipping.",
                metric,
                chunk_index,
            )
            continue

        ts_series = pd.to_datetime(chunk["timestamp"], utc=True, errors="coerce")

        # Iterate over building columns (NOT melted rows)
        for building_id in valid_buildings:
            chunk_total += _scrape_column_into_batch(
                pending=pending,
                chunk=chunk,
                building_id=building_id,
                device_id=device_map[building_id],
                metric=metric,
                batch_size=batch_size,
                db=db,
                ts_series=ts_series,
            )

        elapsed = time.monotonic() - chunk_start
        total_inserted += chunk_total
        logger.info(
            "[%s] Chunk %3d: %7d rows | %5.1fs | cumulative: %d",
            metric,
            chunk_index,
            chunk_total,
            elapsed,
            total_inserted,
        )

    # ── Flush remaining ───────────────────────────────────────────
    if pending:
        total_inserted += _flush_pending(db, pending)

    total_elapsed = time.monotonic() - started_at
    rate = total_inserted / total_elapsed if total_elapsed > 0 else 0
    logger.info(
        "[%s] Finished — %d rows in %.1fs (%.0f rows/s).",
        metric,
        total_inserted,
        total_elapsed,
        rate,
    )

    return total_inserted


# ──────────────────────────────────────────────────────────────────────
# Public orchestrator
# ──────────────────────────────────────────────────────────────────────


def seed_telemetry_data(
    db: Session,
    meter_dir: str | Path = "/app/data/raw/data/meters/cleaned",
    *,
    metrics: tuple[str, ...] = ALL_METRICS,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    batch_size: int = DEFAULT_BATCH_SIZE,
    limit: int | None = None,
) -> dict[str, int]:
    """
    Seed telemetry rows for one or more metrics.

    Returns ``{metric: rows_inserted}``.
    """
    results: dict[str, int] = {}
    for metric in metrics:
        results[metric] = seed_metric_telemetry(
            db,
            meter_dir=meter_dir,
            metric=metric,
            chunk_size=chunk_size,
            batch_size=batch_size,
            limit=limit,
        )

    total = sum(results.values())
    logger.info(
        "Telemetry seeding completed — %d total rows across %d metrics.",
        total,
        len(metrics),
    )
    return results
