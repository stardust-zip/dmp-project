from __future__ import annotations

import logging
import time
from pathlib import Path

import pandas as pd
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session
from src import models

logger = logging.getLogger(__name__)

DEFAULT_WEATHER_CSV = "/app/data/raw/data/weather/weather.csv"

# ──────────────────────────────────────────────────────────────────────
# Weather features  —  one context_type row per column
# ──────────────────────────────────────────────────────────────────────

WEATHER_CONTEXT_TYPES: dict[str, str] = {
    "airTemperature": "\u00b0C",
    "cloudCoverage": "oktas",
    "dewTemperature": "\u00b0C",
    "precipDepth1HR": "mm",
    "precipDepth6HR": "mm",
    "seaLvlPressure": "hPa",
    "windDirection": "deg",
    "windSpeed": "m/s",
}


def _seed_context_types(db: Session) -> None:
    """Upsert context_type entries for every weather feature."""
    existing_ids = {row[0] for row in db.query(models.ContextType.id).all()}

    new_count = 0
    updated_count = 0

    for ctx_id, unit in WEATHER_CONTEXT_TYPES.items():
        if ctx_id in existing_ids:
            (
                db.query(models.ContextType)
                .filter(models.ContextType.id == ctx_id)
                .update({"unit": unit}, synchronize_session=False)
            )
            updated_count += 1
        else:
            db.add(models.ContextType(id=ctx_id, unit=unit))
            new_count += 1

    if new_count or updated_count:
        db.flush()

    logger.info("ContextTypes: %d new, %d updated.", new_count, updated_count)


# ──────────────────────────────────────────────────────────────────────
# Weather CSV  →  context_data rows
# ──────────────────────────────────────────────────────────────────────


def _seed_context_rows(
    db: Session,
    csv_path: str | Path,
) -> int:
    """
    Read weather CSV, melt to long format, upsert into context_data.

    Returns the number of (new + updated) rows.
    """
    csv_path = Path(csv_path)
    if not csv_path.exists():
        logger.warning("Weather CSV not found: %s", csv_path)
        return 0

    logger.info("Reading weather CSV: %s", csv_path)
    df = pd.read_csv(csv_path)
    logger.info("Read %d rows × %d columns.", len(df), len(df.columns))

    # Melt: one row per (timestamp, site_id, context_type)
    feature_cols = [c for c in WEATHER_CONTEXT_TYPES if c in df.columns]
    if not feature_cols:
        logger.warning("No known weather feature columns found in CSV.")
        return 0

    melted = df.melt(
        id_vars=["timestamp", "site_id"],
        value_vars=feature_cols,
        var_name="context_type_id",
        value_name="value",
    )
    melted.dropna(subset=["value"], inplace=True)

    # Parse timestamps — existing code treats them as UTC
    melted["timestamp"] = pd.to_datetime(melted["timestamp"], utc=True)

    total = len(melted)
    logger.info("Melted to %d context_data rows. Upserting…", total)

    # Build dicts + upsert in batches of 10 000
    batch_size = 10_000
    inserted = 0

    for start in range(0, total, batch_size):
        end = min(start + batch_size, total)
        batch = melted.iloc[start:end]

        rows = [
            {
                "timestamp": batch["timestamp"].iloc[i].to_pydatetime(),
                "location_id": str(batch["site_id"].iloc[i]),
                "context_type_id": str(batch["context_type_id"].iloc[i]),
                "value": float(batch["value"].iloc[i]),
            }
            for i in range(len(batch))
        ]

        stmt = pg_insert(models.ContextData).values(rows)
        stmt = stmt.on_conflict_do_update(
            constraint="context_data_pkey",
            set_={"value": stmt.excluded.value},
        )
        db.execute(stmt)
        db.commit()
        inserted += len(rows)

    logger.info("Upserted %d context_data rows.", inserted)
    return inserted


# ──────────────────────────────────────────────────────────────────────
# Public orchestrator
# ──────────────────────────────────────────────────────────────────────


def seed_weather_data(
    db: Session,
    *,
    csv_path: str | Path = DEFAULT_WEATHER_CSV,
) -> dict[str, int]:
    """
    Seed weather context data from CSV.

    Safe to re-run — upserts context_type and context_data.

    Returns::

        {"context_types": 8, "context_rows": 2637048}
    """
    started_at = time.monotonic()

    _seed_context_types(db)
    rows = _seed_context_rows(db, csv_path)

    elapsed = time.monotonic() - started_at
    logger.info(
        "Weather seeding completed — %d context rows in %.1fs.",
        rows,
        elapsed,
    )
    return {"context_types": len(WEATHER_CONTEXT_TYPES), "context_rows": rows}
