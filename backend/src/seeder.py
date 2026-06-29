from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from sqlalchemy.orm import Session
from src.database import SessionLocal, init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("seeder")

DEFAULT_META_CSV = "/app/data/raw/data/metadata/metadata.csv"
DEFAULT_METER_DIR = "/app/data/raw/data/meters/cleaned"
DEFAULT_WEATHER_CSV = "/app/data/raw/data/weather/weather.csv"
DEFAULT_CHUNK_SIZE = 10_000
DEFAULT_BATCH_SIZE = 10_000
DEFAULT_DEV_LIMIT = 1_000

ALL_METRICS = (
    "electricity",
    "chilledwater",
    "steam",
    "hotwater",
    "gas",
    "water",
    "solar",
    "irrigation",
)


def _parse_metrics(raw: str | None) -> tuple[str, ...]:
    """
    Parse a comma-separated metric string like ``"electricity,water"``
    into a tuple of lowercase metric IDs.
    """
    if not raw:
        return ALL_METRICS

    parsed = tuple(m.strip().lower() for m in raw.split(",") if m.strip())
    if not parsed:
        return ALL_METRICS

    unknown = set(parsed).difference(ALL_METRICS)
    if unknown:
        logger.warning(
            "Ignoring unknown metric(s): %s. Valid metrics: %s",
            ", ".join(sorted(unknown)),
            ", ".join(ALL_METRICS),
        )
        parsed = tuple(m for m in parsed if m in ALL_METRICS)
        if not parsed:
            logger.error("No valid metrics remain after filtering. Aborting.")
            sys.exit(1)

    return parsed


def _validate_data_paths(meta_csv: str, meter_dir: str, weather_csv: str) -> None:
    """Warn if expected data paths don't exist, but don't abort."""
    if not Path(meta_csv).exists():
        logger.warning("Metadata CSV not found at: %s", meta_csv)
    if not Path(meter_dir).is_dir():
        logger.warning("Meter directory not found at: %s", meter_dir)
    if not Path(weather_csv).exists():
        logger.warning("Weather CSV not found at: %s", weather_csv)


# ──────────────────────────────────────────────────────────────────────
# Phase runners
# ──────────────────────────────────────────────────────────────────────


def _run_reference_phase(db: Session, meta_csv: str) -> None:
    from src.seeders.metadata import seed_reference_data

    logger.info("=" * 60)
    logger.info("PHASE 1/1: Reference data (metadata.csv → locations, devices)")
    logger.info("=" * 60)

    summary = seed_reference_data(db, csv_path=meta_csv)
    logger.info("Reference data summary: %s", summary)


def _run_telemetry_phase(
    db: Session,
    meter_dir: str,
    metrics: tuple[str, ...],
    chunk_size: int,
    batch_size: int,
    limit: int | None,
) -> None:
    from src.seeders.telemetry import seed_telemetry_data

    logger.info("=" * 60)
    logger.info("PHASE 1/1: Telemetry data — metrics: %s", ", ".join(metrics))
    logger.info(
        "  chunk_size=%d  batch_size=%d  limit=%s",
        chunk_size,
        batch_size,
        limit if limit is not None else "none (full)",
    )
    logger.info("=" * 60)

    results = seed_telemetry_data(
        db,
        meter_dir=meter_dir,
        metrics=metrics,
        chunk_size=chunk_size,
        batch_size=batch_size,
        limit=limit,
    )

    total = sum(results.values())
    logger.info(
        "Telemetry summary: %d total rows across %d metrics.", total, len(results)
    )


def _run_weather_phase(db: Session, weather_csv: str) -> None:
    from src.seeders.weather import seed_weather_data

    logger.info("=" * 60)
    logger.info("PHASE 1/1: Weather data → context_data")
    logger.info("=" * 60)

    summary = seed_weather_data(db, csv_path=weather_csv)
    logger.info("Weather summary: %s", summary)


# ──────────────────────────────────────────────────────────────────────
# Main entry point
# ──────────────────────────────────────────────────────────────────────


def run_seeder(
    *,
    phase: str = "all",
    metrics: tuple[str, ...] = ALL_METRICS,
    meta_csv: str = DEFAULT_META_CSV,
    meter_dir: str = DEFAULT_METER_DIR,
    weather_csv: str = DEFAULT_WEATHER_CSV,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    batch_size: int = DEFAULT_BATCH_SIZE,
    limit: int | None = DEFAULT_DEV_LIMIT,
) -> None:
    """Programmatic entry point for the seeder."""

    _validate_data_paths(meta_csv, meter_dir, weather_csv)

    init_db()
    db = SessionLocal()

    try:
        if phase in ("reference", "all"):
            _run_reference_phase(db, meta_csv)

        if phase in ("telemetry", "all"):
            _run_telemetry_phase(db, meter_dir, metrics, chunk_size, batch_size, limit)

        if phase in ("weather", "all"):
            _run_weather_phase(db, weather_csv)

        logger.info("Database seeding completed successfully.")

    except Exception:
        db.rollback()
        logger.exception("Seeding failed with an error.")
        raise
    finally:
        db.close()


# ──────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Seed the DMP database with Smart City data.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python -m src.seeder --phase reference\n"
            "  python -m src.seeder --phase telemetry --metrics electricity,water --full\n"
            "  python -m src.seeder --phase all --chunk-size 5000 --batch-size 10000\n"
        ),
    )

    parser.add_argument(
        "--phase",
        choices=["all", "reference", "telemetry", "weather"],
        default="all",
        help="Which data phase to seed (default: all).",
    )

    parser.add_argument(
        "--metrics",
        type=str,
        default=None,
        help=(
            "Comma-separated metric IDs to load (e.g. 'electricity,water'). "
            "Default: all 8 metrics."
        ),
    )

    parser.add_argument(
        "--data-dir",
        default="/app/data/raw",
        help="Root data directory containing data/ subfolder (default: /app/data/raw).",
    )

    parser.add_argument(
        "--meta-csv",
        default=None,
        help=(
            "Explicit path to metadata.csv. Overrides --data-dir for the metadata file."
        ),
    )

    parser.add_argument(
        "--meter-dir",
        default=None,
        help=(
            "Explicit directory containing cleaned meter CSVs. "
            "Overrides --data-dir for meter files."
        ),
    )
    parser.add_argument(
        "--weather-csv",
        default=None,
        help=(
            "Explicit path to weather.csv. Overrides --data-dir for the weather file."
        ),
    )

    parser.add_argument(
        "--chunk-size",
        type=int,
        default=DEFAULT_CHUNK_SIZE,
        help=f"CSV rows per pandas chunk (default: {DEFAULT_CHUNK_SIZE}).",
    )

    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"TelemetryData rows per DB batch insert (default: {DEFAULT_BATCH_SIZE}).",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_DEV_LIMIT,
        help=f"Max rows to seed per metric for fast testing (default: {DEFAULT_DEV_LIMIT}).",
    )

    parser.add_argument(
        "--full",
        action="store_true",
        help="Seed the entire dataset. Overrides --limit.",
    )

    args = parser.parse_args()

    # Resolve paths
    meta_csv = args.meta_csv or str(
        Path(args.data_dir) / "data" / "metadata" / "metadata.csv"
    )
    meter_dir = args.meter_dir or str(
        Path(args.data_dir) / "data" / "meters" / "cleaned"
    )
    weather_csv = args.weather_csv or str(
        Path(args.data_dir) / "data" / "weather" / "weather.csv"
    )

    final_limit: int | None = None if args.full else args.limit
    final_metrics = _parse_metrics(args.metrics)

    logger.info("Configuration:")
    logger.info("  phase      = %s", args.phase)
    logger.info("  metrics    = %s", ", ".join(final_metrics))
    logger.info("  meta_csv   = %s", meta_csv)
    logger.info("  meter_dir  = %s", meter_dir)
    logger.info("  weather_csv= %s", weather_csv)
    logger.info("  chunk_size = %d", args.chunk_size)
    logger.info("  batch_size = %d", args.batch_size)
    logger.info(
        "  limit      = %s", final_limit if final_limit is not None else "none (full)"
    )

    run_seeder(
        phase=args.phase,
        metrics=final_metrics,
        meta_csv=meta_csv,
        meter_dir=meter_dir,
        weather_csv=weather_csv,
        chunk_size=args.chunk_size,
        batch_size=args.batch_size,
        limit=final_limit,
    )
