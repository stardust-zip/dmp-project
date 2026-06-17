from __future__ import annotations

import logging
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session
from src import models

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────
# Column sets (kept in sync with the metadata.csv schema)
# ──────────────────────────────────────────────────────────────────────

_METRIC_FLAG_COLUMNS: tuple[str, ...] = (
    "electricity",
    "hotwater",
    "chilledwater",
    "steam",
    "water",
    "irrigation",
    "solar",
    "gas",
)

_METADATA_VALUE_COLUMNS: tuple[str, ...] = (
    "building_id_kaggle",
    "site_id_kaggle",
    "sqm",
    "sqft",
    "lat",
    "lng",
    "timezone",
    "industry",
    "subindustry",
    "heatingtype",
    "yearbuilt",
    "date_opened",
    "numberoffloors",
    "occupants",
    "energystarscore",
    "eui",
    "site_eui",
    "source_eui",
    "leed_level",
    "rating",
    "primaryspaceusage",
    "sub_primaryspaceusage",
)


# ──────────────────────────────────────────────────────────────────────
# Normalised building record (pure data transfer object)
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class _BuildingRecord:
    building_id: str
    site_id: str
    location_type_id: str
    active_metrics: tuple[str, ...]
    metadata: dict[str, Any]


# ──────────────────────────────────────────────────────────────────────
# CSV → _BuildingRecord
# ──────────────────────────────────────────────────────────────────────


def _parse_metadata_csv(csv_path: str | Path) -> pd.DataFrame:
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"Metadata CSV not found: {csv_path}")

    df = pd.read_csv(csv_path)
    required = {"building_id", "site_id", "primaryspaceusage"}
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(
            f"Metadata CSV missing required column(s): {', '.join(sorted(missing))}"
        )
    return df


def _extract_active_metrics(row: pd.Series) -> tuple[str, ...]:
    """Return metric IDs whose column contains a truthy flag (``"Yes"``)."""
    return tuple(
        metric
        for metric in _METRIC_FLAG_COLUMNS
        if metric in row.index and str(row.get(metric, "")).strip().lower() == "yes"
    )


def _extract_metadata(row: pd.Series) -> dict[str, Any]:
    """Extract all available scalar metadata fields, dropping NaN values."""
    result: dict[str, Any] = {}
    for col in _METADATA_VALUE_COLUMNS:
        if col not in row.index:
            continue
        value = row[col]
        if pd.isna(value):
            continue
        # pandas/numpy scalars must be converted to native Python types
        # for JSONB storage — numpy.float64 is not isinstance(float)
        if isinstance(value, (pd.Timestamp,)):
            result[col] = str(value)
        elif hasattr(value, "item"):
            result[col] = value.item()
        else:
            result[col] = value
    return result


def _parse_building_records(csv_path: str | Path) -> tuple[_BuildingRecord, ...]:
    """Parse the full metadata CSV into an immutable tuple of building records."""
    df = _parse_metadata_csv(csv_path)

    records: list[_BuildingRecord] = []
    for _, row in df.iterrows():
        building_id = str(row["building_id"]).strip()
        site_id = str(row["site_id"]).strip()
        psu = row.get("primaryspaceusage")
        location_type_id = (
            str(psu).strip()
            if isinstance(psu, str) and psu.strip().lower() != "nan"
            else "Unknown"
        )

        records.append(
            _BuildingRecord(
                building_id=building_id,
                site_id=site_id,
                location_type_id=location_type_id,
                active_metrics=_extract_active_metrics(row),
                metadata=_extract_metadata(row),
            )
        )

    return tuple(records)


# ──────────────────────────────────────────────────────────────────────
# Seed: LocationType
# ──────────────────────────────────────────────────────────────────────


def _seed_location_types(db: Session, records: Collection[_BuildingRecord]) -> None:
    existing = {row[0] for row in db.query(models.LocationType.id).all()}

    unique_types = sorted({rec.location_type_id for rec in records})
    new_types: set[str] = set()
    for lt_id in unique_types:
        if lt_id not in existing and lt_id not in new_types:
            db.add(models.LocationType(id=lt_id, description=f"{lt_id} facility"))
            new_types.add(lt_id)

    # "site" is always needed for the site-level locations
    if "site" not in existing and "site" not in new_types:
        db.add(models.LocationType(id="site", description="Top-level site or campus"))

    if new_types:
        db.flush()


# ──────────────────────────────────────────────────────────────────────
# Seed: Location (sites + buildings)
# ──────────────────────────────────────────────────────────────────────


def _seed_sites(
    db: Session,
    records: Collection[_BuildingRecord],
) -> None:
    """Upsert top-level site locations — CSV data overwrites existing."""
    existing_ids = {row[0] for row in db.query(models.Location.id).all()}

    new_count = 0
    updated_count = 0
    seen: set[str] = set()

    for rec in records:
        if rec.site_id in seen:
            continue
        seen.add(rec.site_id)
        site_name = f"Site {rec.site_id}"

        if rec.site_id in existing_ids:
            (
                db.query(models.Location)
                .filter(models.Location.id == rec.site_id)
                .update(
                    {"name": site_name, "location_type_id": "site", "parent_id": None},
                    synchronize_session=False,
                )
            )
            updated_count += 1
        else:
            db.add(
                models.Location(
                    id=rec.site_id,
                    parent_id=None,
                    location_type_id="site",
                    name=site_name,
                    metadata_={},
                )
            )
            new_count += 1

    if new_count or updated_count:
        db.flush()

    logger.info("Sites: %d new, %d updated.", new_count, updated_count)


def _seed_buildings(
    db: Session,
    records: Collection[_BuildingRecord],
) -> None:
    """Upsert building locations — CSV metadata overwrites existing."""
    existing_ids = {row[0] for row in db.query(models.Location.id).all()}

    new_count = 0
    updated_count = 0

    for rec in records:
        if rec.building_id in existing_ids:
            (
                db.query(models.Location)
                .filter(models.Location.id == rec.building_id)
                .update(
                    {
                        "parent_id": rec.site_id,
                        "location_type_id": rec.location_type_id,
                        "name": f"Building {rec.building_id}",
                        "metadata_": rec.metadata,
                    },
                    synchronize_session=False,
                )
            )
            updated_count += 1
        else:
            db.add(
                models.Location(
                    id=rec.building_id,
                    parent_id=rec.site_id,
                    location_type_id=rec.location_type_id,
                    name=f"Building {rec.building_id}",
                    metadata_=rec.metadata,
                )
            )
            new_count += 1

    if new_count or updated_count:
        db.flush()

    logger.info(
        "Buildings: %d new, %d updated (total: %d).",
        new_count,
        updated_count,
        len(existing_ids) + new_count,
    )


# ──────────────────────────────────────────────────────────────────────
# Seed: DeviceType
# ──────────────────────────────────────────────────────────────────────


def _seed_device_type(db: Session) -> None:
    existing = (
        db.query(models.DeviceType)
        .filter(models.DeviceType.id == "virtual_meter")
        .one_or_none()
    )
    if existing is None:
        db.add(
            models.DeviceType(
                id="virtual_meter",
                description="Virtual meter aggregated from kaggle data.",
            )
        )
        db.flush()


# ──────────────────────────────────────────────────────────────────────
# Seed: Device (one per building × active metric)
# ──────────────────────────────────────────────────────────────────────


def _seed_devices(
    db: Session,
    records: Collection[_BuildingRecord],
) -> None:
    """
    Upsert one virtual meter device per (building, metric) pair where
    the metric is flagged as active in the metadata CSV.

    Existing devices have their status and location reset to CSV-derived values.
    """
    device_type_id = "virtual_meter"
    existing_ids = {row[0] for row in db.query(models.Device.id).all()}

    new_count = 0
    updated_count = 0

    for rec in records:
        for metric in rec.active_metrics:
            device_id = f"meter_{metric}_{rec.building_id}"
            if device_id in existing_ids:
                (
                    db.query(models.Device)
                    .filter(models.Device.id == device_id)
                    .update(
                        {
                            "location_id": rec.building_id,
                            "device_type_id": device_type_id,
                            "status": "Active",
                        },
                        synchronize_session=False,
                    )
                )
                updated_count += 1
            else:
                db.add(
                    models.Device(
                        id=device_id,
                        location_id=rec.building_id,
                        device_type_id=device_type_id,
                        status="Active",
                    )
                )
                new_count += 1

    if new_count or updated_count:
        db.flush()

    logger.info(
        "Devices: %d new, %d updated (total: %d).",
        new_count,
        updated_count,
        len(existing_ids) + new_count,
    )


# ──────────────────────────────────────────────────────────────────────
# Seed: MetricType (lookup)
# ──────────────────────────────────────────────────────────────────────


def _seed_metric_types(db: Session) -> None:
    metric_defs = {
        "electricity": ("kWh", "electricity consumption"),
        "solar": ("kWh", "solar consumption"),
        "steam": ("kg", "steam consumption"),
        "hotwater": ("m3", "hot water consumption"),
        "chilledwater": ("m3", "chilled water consumption"),
        "gas": ("m3", "gas consumption"),
        "water": ("m3", "water consumption"),
        "irrigation": ("m3", "irrigation consumption"),
    }

    existing_ids = {row[0] for row in db.query(models.MetricType.id).all()}

    new_count = 0
    updated_count = 0

    for metric_id, (unit, description) in metric_defs.items():
        if metric_id in existing_ids:
            (
                db.query(models.MetricType)
                .filter(models.MetricType.id == metric_id)
                .update(
                    {"unit": unit, "description": description},
                    synchronize_session=False,
                )
            )
            updated_count += 1
        else:
            db.add(
                models.MetricType(
                    id=metric_id,
                    unit=unit,
                    description=description,
                )
            )
            new_count += 1

    if new_count or updated_count:
        db.flush()

    logger.info("MetricTypes: %d new, %d updated.", new_count, updated_count)


# ──────────────────────────────────────────────────────────────────────
# Public orchestrator
# ──────────────────────────────────────────────────────────────────────


def seed_reference_data(
    db: Session,
    *,
    csv_path: str | Path = "/app/data/raw/data/metadata/metadata.csv",
) -> dict[str, int]:
    """
    Seed all reference data from metadata.csv.

    Safe to re-run — all functions use upsert semantics
    (CSV data overwrites existing DB rows).

    Returns a summary dict::

        {
            "location_types": 15,
            "buildings_and_sites": 1657,
            "devices": 4800,
        }
    """
    logger.info("Parsing metadata CSV: %s", csv_path)
    records = _parse_building_records(csv_path)
    logger.info("Parsed %d building records.", len(records))

    _seed_device_type(db)
    _seed_metric_types(db)
    _seed_location_types(db, records)
    _seed_sites(db, records)
    _seed_buildings(db, records)
    _seed_devices(db, records)

    db.commit()

    # Post-commit counts (idempotent: reflect total, not just new)
    location_count = db.query(models.Location).count()
    device_count = db.query(models.Device).count()
    location_type_count = db.query(models.LocationType).count()

    summary = {
        "location_types": location_type_count,
        "buildings_and_sites": location_count,
        "devices": device_count,
    }

    logger.info("Reference data seeding completed: %s", summary)
    return summary
